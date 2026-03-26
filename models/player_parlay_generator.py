"""
Player Parlay Generator V3 (Rewrite)

Fixes applied:
- Poisson-based baseline probabilities (not goals_per_game * 0.8)
- Sampling-based parlay assembly (not combinations())
- Diversity constraints: max 1 leg per match, max 1 per team
- Daily leg reuse caps via player_leg_usage table
- Honest risk tiers (no fake edge/confidence)
- Generation caps: max 20 parlays per run
"""

import os
import math
import random
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from collections import defaultdict
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

LEAGUE_AVG_GOAL_RATE = 0.07
SHRINKAGE_GAMES = 25
MAX_PARLAYS_PER_RUN = 20
MAX_LEG_REUSE_PER_DAY = 5
MAX_PARLAYS_PER_MATCH_PER_DAY = 10
MIN_PROB = 0.05
MAX_PROB = 0.25


class PlayerParlayGenerator:
    DEFAULT_BET = 100.0
    MARKET_MARGIN = 0.06

    def __init__(self):
        self.engine = create_engine(
            os.environ.get('DATABASE_URL'),
            pool_pre_ping=True,
            pool_recycle=300
        )
        self.Session = sessionmaker(bind=self.engine)
        self._ensure_tables()

    def _ensure_tables(self):
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_parlays (
                    id SERIAL PRIMARY KEY,
                    parlay_hash VARCHAR(32) UNIQUE NOT NULL,
                    generated_at TIMESTAMPTZ DEFAULT NOW(),
                    leg_count INTEGER NOT NULL,
                    match_ids INTEGER[] NOT NULL,
                    combined_odds NUMERIC(10,2),
                    raw_prob_pct NUMERIC(8,3),
                    adjusted_prob_pct NUMERIC(8,3),
                    edge_pct NUMERIC(8,2),
                    confidence_tier VARCHAR(20),
                    payout_100 NUMERIC(12,2),
                    status VARCHAR(20) DEFAULT 'pending',
                    result VARCHAR(20),
                    settled_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    has_market_odds BOOLEAN DEFAULT FALSE,
                    ev_pct NUMERIC(8,3),
                    calibrated_prob_pct NUMERIC(8,3)
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_parlay_legs (
                    id SERIAL PRIMARY KEY,
                    parlay_id INTEGER REFERENCES player_parlays(id) ON DELETE CASCADE,
                    leg_index INTEGER NOT NULL,
                    match_id INTEGER NOT NULL,
                    home_team VARCHAR(100),
                    away_team VARCHAR(100),
                    league_name VARCHAR(100),
                    kickoff_at TIMESTAMPTZ,
                    player_id INTEGER NOT NULL,
                    player_name VARCHAR(100),
                    team_name VARCHAR(100),
                    model_prob NUMERIC(6,4),
                    market_prob NUMERIC(6,4),
                    decimal_odds NUMERIC(8,2),
                    edge_pct NUMERIC(8,2),
                    result VARCHAR(20),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    calibrated_prob NUMERIC(6,4),
                    real_market_odds NUMERIC(8,2),
                    ev NUMERIC(6,4),
                    has_market_odds BOOLEAN DEFAULT FALSE
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS player_leg_usage (
                    id SERIAL PRIMARY KEY,
                    window_key DATE NOT NULL DEFAULT CURRENT_DATE,
                    match_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (window_key, match_id, player_id)
                )
            """))

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_player_parlays_expires 
                ON player_parlays(expires_at) WHERE status = 'pending'
            """))
            conn.commit()
            logger.info("PlayerParlayGenerator: Tables ensured")

    def _ml_scorer_prob(self, player_id: int, league_id: int = None,
                        is_home: bool = False) -> Optional[float]:
        """Get ML-based scoring probability if model available."""
        # Check batch cache first (populated by _batch_ml_predictions)
        if hasattr(self, '_ml_cache') and self._ml_cache:
            return self._ml_cache.get(player_id)

        # Fallback to individual prediction
        if not hasattr(self, '_ml_service'):
            try:
                from models.player_props_service import PlayerPropsService
                self._ml_service = PlayerPropsService()
                if not self._ml_service.ml_scored_models:
                    self._ml_service = None
            except Exception:
                self._ml_service = None

        if not self._ml_service:
            return None

        try:
            result = self._ml_service._ml_predict(
                player_id, league_id=league_id, is_home=is_home
            )
            if result:
                return result["scored_probability"]
        except Exception:
            pass
        return None

    def _batch_ml_predictions(self, fixtures: List[Dict]) -> Dict[int, float]:
        """Batch-compute ML probabilities for all players in upcoming fixtures.
        Returns {player_id: scored_probability}. Much faster than per-player calls."""
        cache = {}

        try:
            import pickle
            import numpy as np
            from pathlib import Path

            model_dir = Path("artifacts/models/player_soccer")
            scored_path = model_dir / "scored_lgbm_ensemble.pkl"
            cal_path = model_dir / "scored_calibrator.pkl"

            if not scored_path.exists():
                return cache

            with open(scored_path, "rb") as f:
                models = pickle.load(f)
            with open(cal_path, "rb") as f:
                calibrator = pickle.load(f)

            POSITION_MAP = {"Attacker": 3, "Forward": 3, "F": 3,
                            "Midfielder": 2, "M": 2, "Defender": 1, "D": 1,
                            "Goalkeeper": 0, "G": 0}

            # Collect all team IDs from fixtures
            all_team_ids = set()
            fixture_league = {}  # team_id -> league_id
            fixture_home = {}    # team_id -> is_home
            for fix in fixtures:
                htid = fix.get("home_team_id")
                atid = fix.get("away_team_id")
                lid = fix.get("league_id")
                if htid:
                    all_team_ids.add(htid)
                    fixture_league[htid] = lid
                    fixture_home[htid] = True
                if atid:
                    all_team_ids.add(atid)
                    fixture_league[atid] = lid
                    fixture_home[atid] = False

            if not all_team_ids:
                return cache

            # Batch query: get player stats for all teams at once
            with self.engine.connect() as conn:
                tid_list = list(all_team_ids)
                placeholders = ",".join([str(t) for t in tid_list])

                result = conn.execute(text(f"""
                    SELECT pgs.player_id, pu.position, pgs.team_id,
                           COUNT(*) as games,
                           SUM((pgs.stats->>'goals')::int) as total_goals,
                           SUM((pgs.stats->>'assists')::int) as total_assists,
                           AVG((pgs.stats->>'shots')::float) as avg_shots,
                           AVG(pgs.rating) as avg_rating,
                           AVG(pgs.minutes_played) as avg_minutes
                    FROM player_game_stats pgs
                    JOIN players_unified pu ON pgs.player_id = pu.player_id AND pu.sport_key = 'soccer'
                    WHERE pgs.sport_key = 'soccer'
                      AND pgs.minutes_played >= 15
                      AND pgs.team_id IN ({placeholders})
                      AND pu.position IS NOT NULL
                      AND pu.position NOT IN ('Goalkeeper', 'G')
                    GROUP BY pgs.player_id, pu.position, pgs.team_id
                    HAVING COUNT(*) >= 3
                """))

                rows = result.fetchall()

            if not rows:
                return cache

            # Build feature matrix for all players at once
            feature_rows = []
            player_ids = []

            for row in rows:
                pid, position, team_id, games, goals, assists, avg_shots, avg_rating, avg_minutes = row
                goals = goals or 0
                assists = assists or 0
                avg_shots = avg_shots or 0
                avg_rating = avg_rating or 6.5
                avg_minutes = avg_minutes or 60

                total_mins = avg_minutes * games
                goals_per_90 = (goals / max(total_mins, 1)) * 90
                shots_per_90 = (avg_shots * games / max(total_mins, 1)) * 90
                pos_enc = POSITION_MAP.get(position, 1)
                lid = fixture_league.get(team_id, 0)
                is_home = 1 if fixture_home.get(team_id, False) else 0

                # Approximate form features from aggregates (not rolling, but good enough for batch)
                goals_last_3 = min(goals, 3)  # rough approximation
                goals_last_5 = min(goals, 5)

                features = [
                    goals_last_3, goals_last_5, min(assists, 2), min(assists, 3),
                    avg_shots, avg_shots, avg_rating, avg_minutes,
                    goals, assists, games, goals_per_90, shots_per_90,
                    is_home, 1, avg_minutes, 7,  # rest days default
                    1.2, 0.25,  # opponent defaults
                    pos_enc, 1,  # age bucket default
                    lid or 0, 2.6, 0.07, 0.09,  # league defaults
                ]
                feature_rows.append(features)
                player_ids.append(pid)

            if not feature_rows:
                return cache

            X = np.array(feature_rows, dtype=np.float32)

            # Batch predict
            preds = np.mean([m.predict(X) for m in models], axis=0)

            # Calibrate
            cal_preds = calibrator.predict(preds)

            for pid, prob in zip(player_ids, cal_preds):
                cache[pid] = round(float(max(0.01, min(0.50, prob))), 4)

            logger.info(f"Batch ML predictions: {len(cache)} players computed")

        except Exception as e:
            logger.warning(f"Batch ML prediction failed: {e}")

        return cache

    def _poisson_prob(self, goals: int, games_played: int) -> float:
        """
        Compute P(goals >= 1) using Poisson with Bayesian shrinkage.
        lambda = (player_goal_rate * shrinkage_weight + league_avg * (1 - shrinkage_weight))
        P(X >= 1) = 1 - exp(-lambda_adjusted)
        """
        games_equiv = max(games_played, 1.0)
        raw_rate = goals / games_equiv

        shrinkage_weight = min(games_equiv / (games_equiv + SHRINKAGE_GAMES), 0.85)
        shrunk_rate = raw_rate * shrinkage_weight + LEAGUE_AVG_GOAL_RATE * (1 - shrinkage_weight)

        shrunk_rate = max(0.03, min(0.29, shrunk_rate))

        prob = 1.0 - math.exp(-shrunk_rate)

        return max(MIN_PROB, min(MAX_PROB, prob))

    def _get_upcoming_fixtures(self, hours_ahead: int = 72) -> List[Dict]:
        with self.engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT 
                    f.match_id,
                    f.home_team,
                    f.away_team,
                    f.league_name,
                    f.kickoff_at,
                    f.home_team_id,
                    f.away_team_id
                FROM fixtures f
                WHERE f.kickoff_at > NOW()
                  AND f.kickoff_at < NOW() + INTERVAL '{hours_ahead} hours'
                  AND f.status IN ('NS', 'scheduled', 'TBD')
                  AND f.home_team_id IS NOT NULL
                  AND f.away_team_id IS NOT NULL
                ORDER BY f.kickoff_at
                LIMIT 50
            """))
            return [dict(row._mapping) for row in result.fetchall()]

    def _get_players_for_match(self, match_id: int, home_team_id: int, away_team_id: int) -> List[Dict]:
        """Get candidate players: wider pool than just top scorers."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                WITH fixture_teams AS (
                    SELECT api_football_team_id FROM teams WHERE team_id = :home_id AND api_football_team_id IS NOT NULL
                    UNION
                    SELECT api_football_team_id FROM teams WHERE team_id = :away_id AND api_football_team_id IS NOT NULL
                )
                SELECT 
                    p.player_id,
                    p.player_name,
                    p.position,
                    pss.team_id,
                    pss.team_name,
                    COALESCE((pss.stats->>'goals')::int, 0) as season_goals,
                    COALESCE(pss.games_played, 0) as games_played,
                    COALESCE((pss.stats->>'minutes')::int, 0) as minutes_played,
                    COALESCE((pss.stats->>'shots_on_target')::int, 0) as shots_on_target
                FROM players_unified p
                JOIN player_season_stats pss ON p.player_id = pss.player_id 
                    AND pss.sport_key = 'soccer' AND pss.season = 2024
                WHERE pss.team_id IN (SELECT api_football_team_id FROM fixture_teams)
                  AND p.position IN ('Attacker', 'Midfielder')
                  AND COALESCE(pss.games_played, 0) >= 3
                ORDER BY COALESCE((pss.stats->>'goals')::int, 0) DESC
                LIMIT 12
            """), {
                'home_id': home_team_id,
                'away_id': away_team_id,
            })
            return [dict(row._mapping) for row in result.fetchall()]

    def _get_leg_usage_today(self) -> Dict:
        """Get current leg usage for today to enforce caps."""
        usage = {}
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT match_id, player_id, use_count
                FROM player_leg_usage
                WHERE window_key = CURRENT_DATE
            """)).fetchall()
            for r in rows:
                usage[(r.match_id, r.player_id)] = r.use_count
        return usage

    def _get_match_parlay_count_today(self) -> Dict:
        """Get how many parlays each match is already in today."""
        counts = defaultdict(int)
        with self.engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT match_id, COUNT(DISTINCT parlay_id) as cnt
                FROM player_parlay_legs
                WHERE created_at::date = CURRENT_DATE
                GROUP BY match_id
            """)).fetchall()
            for r in rows:
                counts[r.match_id] = r.cnt
        return counts

    def _increment_leg_usage(self, legs: List[Dict]):
        """Track leg usage in player_leg_usage table."""
        with self.engine.connect() as conn:
            for leg in legs:
                conn.execute(text("""
                    INSERT INTO player_leg_usage (window_key, match_id, player_id, use_count)
                    VALUES (CURRENT_DATE, :match_id, :player_id, 1)
                    ON CONFLICT (window_key, match_id, player_id)
                    DO UPDATE SET use_count = player_leg_usage.use_count + 1
                """), {'match_id': leg['match_id'], 'player_id': leg['player_id']})
            conn.commit()

    def _get_real_odds_for_matches(self, match_ids: List[int]) -> Dict:
        """Fetch real bookmaker scorer odds for given matches."""
        real_odds = {}
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT 
                        match_id,
                        player_name,
                        player_id,
                        AVG(decimal_odds) AS avg_odds,
                        MAX(decimal_odds) AS best_odds,
                        AVG(implied_prob) AS avg_implied,
                        COUNT(DISTINCT bookmaker) AS n_books
                    FROM soccer_scorer_odds
                    WHERE match_id = ANY(:mids)
                      AND collected_at > NOW() - INTERVAL '12 hours'
                    GROUP BY match_id, player_name, player_id
                    HAVING COUNT(DISTINCT bookmaker) >= 1
                """), {'mids': match_ids})

                for row in result.fetchall():
                    key = (row.match_id, row.player_id) if row.player_id else None
                    name_key = (row.match_id, row.player_name.lower().strip())
                    entry = {
                        'avg_odds': float(row.avg_odds),
                        'best_odds': float(row.best_odds),
                        'avg_implied': float(row.avg_implied),
                        'n_books': row.n_books,
                        'has_market_odds': True,
                    }
                    if key:
                        real_odds[key] = entry
                    real_odds[name_key] = entry
        except Exception as e:
            logger.debug(f"Real odds lookup failed (non-fatal): {e}")
        return real_odds

    def _generate_candidate_legs(self, fixtures: List[Dict]) -> List[Dict]:
        """Generate candidate legs with Poisson probabilities, enriched with real odds when available."""
        all_legs = []
        match_ids = [f['match_id'] for f in fixtures]
        real_odds_map = self._get_real_odds_for_matches(match_ids)
        odds_enriched = 0

        for fixture in fixtures:
            players = self._get_players_for_match(
                fixture['match_id'],
                fixture['home_team_id'],
                fixture['away_team_id']
            )

            for player in players:
                # Try ML model first (batch cache), fall back to Poisson
                ml_prob = self._ml_scorer_prob(
                    player.get('player_id'),
                    league_id=fixture.get('league_id'),
                    is_home=(player.get('team_id') == fixture.get('home_team_id'))
                )
                if ml_prob is not None:
                    prob = ml_prob
                    prob_source = "ml_lightgbm"
                else:
                    prob = self._poisson_prob(
                        player.get('season_goals', 0),
                        player.get('games_played', 0)
                    )
                    prob_source = "poisson"

                if prob < MIN_PROB:
                    continue

                has_market_odds = False
                market_odds_data = None
                key_by_id = (fixture['match_id'], player['player_id'])
                key_by_name = (fixture['match_id'], player['player_name'].lower().strip())

                if key_by_id in real_odds_map:
                    market_odds_data = real_odds_map[key_by_id]
                elif key_by_name in real_odds_map:
                    market_odds_data = real_odds_map[key_by_name]

                if market_odds_data:
                    decimal_odds = market_odds_data['best_odds']
                    implied_prob = market_odds_data['avg_implied']
                    has_market_odds = True
                    odds_enriched += 1
                    edge = prob - implied_prob
                    ev = prob * (decimal_odds - 1) - (1 - prob)
                else:
                    fair_odds = 1.0 / prob
                    decimal_odds = fair_odds * (1 + self.MARKET_MARGIN)
                    implied_prob = 1.0 / decimal_odds
                    edge = 0.0
                    ev = 0.0

                all_legs.append({
                    'match_id': fixture['match_id'],
                    'home_team': fixture['home_team'],
                    'away_team': fixture['away_team'],
                    'league_name': fixture['league_name'],
                    'kickoff_at': fixture['kickoff_at'],
                    'player_id': player['player_id'],
                    'player_name': player['player_name'],
                    'team_name': player.get('team_name', 'Unknown'),
                    'team_id': player.get('team_id'),
                    'model_prob': round(prob, 4),
                    'decimal_odds': round(decimal_odds, 2),
                    'implied_prob': round(implied_prob, 4),
                    'edge': round(edge, 4),
                    'ev': round(ev, 4),
                    'has_market_odds': has_market_odds,
                    'season_goals': player.get('season_goals', 0),
                    'games_played': player.get('games_played', 0),
                    'prob_method': prob_source,
                })

        if odds_enriched > 0:
            positive_ev_legs = [l for l in all_legs if l.get('has_market_odds') and l.get('ev', 0) > 0]
            negative_ev_removed = odds_enriched - len(positive_ev_legs)
            all_legs = [l for l in all_legs if not l.get('has_market_odds') or l.get('ev', 0) > 0]
            logger.info(
                f"PlayerParlay: {odds_enriched} legs with real odds, "
                f"{len(positive_ev_legs)} positive EV, {negative_ev_removed} negative EV removed"
            )

        return all_legs

    def _sample_parlay(self, legs: List[Dict], k: int, leg_usage: Dict, match_parlay_counts: Dict) -> Optional[List[Dict]]:
        """
        Sample k legs with diversity constraints:
        - Max 1 leg per match
        - Max 1 leg per team
        - Respect daily leg reuse caps
        - Respect per-match parlay caps
        """
        eligible = []
        for leg in legs:
            key = (leg['match_id'], leg['player_id'])
            if leg_usage.get(key, 0) >= MAX_LEG_REUSE_PER_DAY:
                continue
            if match_parlay_counts.get(leg['match_id'], 0) >= MAX_PARLAYS_PER_MATCH_PER_DAY:
                continue
            eligible.append(leg)

        if len(eligible) < k:
            return None

        weights = [
            leg['model_prob'] * (1.5 if leg.get('has_market_odds') else 1.0)
            for leg in eligible
        ]
        total_w = sum(weights)
        if total_w == 0:
            return None
        weights = [w / total_w for w in weights]

        max_attempts = 50
        for _ in range(max_attempts):
            try:
                sampled_indices = []
                used_matches = set()
                used_teams = set()
                remaining_indices = list(range(len(eligible)))
                remaining_weights = weights[:]

                for _pick in range(k):
                    if not remaining_indices:
                        break

                    total_rw = sum(remaining_weights)
                    if total_rw <= 0:
                        break
                    norm_weights = [w / total_rw for w in remaining_weights]

                    idx = random.choices(remaining_indices, weights=norm_weights, k=1)[0]
                    leg = eligible[idx]

                    if leg['match_id'] in used_matches:
                        remaining_idx = remaining_indices.index(idx)
                        remaining_indices.pop(remaining_idx)
                        remaining_weights.pop(remaining_idx)
                        continue

                    team_id = leg.get('team_id')
                    if team_id and team_id in used_teams:
                        remaining_idx = remaining_indices.index(idx)
                        remaining_indices.pop(remaining_idx)
                        remaining_weights.pop(remaining_idx)
                        continue

                    sampled_indices.append(idx)
                    used_matches.add(leg['match_id'])
                    if team_id:
                        used_teams.add(team_id)

                    remaining_idx = remaining_indices.index(idx)
                    remaining_indices.pop(remaining_idx)
                    remaining_weights.pop(remaining_idx)

                if len(sampled_indices) == k:
                    return [eligible[i] for i in sampled_indices]
            except Exception:
                continue

        return None

    def _compute_risk_tier(self, legs: List[Dict]) -> str:
        """
        Honest risk tier based on probability bands + parlay size.
        No fake edge. Just probability reality.
        """
        avg_prob = sum(l['model_prob'] for l in legs) / len(legs)
        k = len(legs)

        if k == 2 and avg_prob >= 0.18:
            return 'low_risk'
        elif k == 2 and avg_prob >= 0.12:
            return 'medium_risk'
        elif k == 3 and avg_prob >= 0.15:
            return 'medium_risk'
        else:
            return 'high_risk'

    def _build_parlay(self, legs: List[Dict]) -> Dict:
        match_ids = list(set(leg['match_id'] for leg in legs))

        combined_odds = 1.0
        combined_prob = 1.0
        has_any_market_odds = False
        total_ev = 0.0

        for leg in legs:
            combined_odds *= leg['decimal_odds']
            combined_prob *= leg['model_prob']
            if leg.get('has_market_odds'):
                has_any_market_odds = True
            total_ev += leg.get('ev', 0)

        risk_tier = self._compute_risk_tier(legs)

        leg_ids = sorted([f"{l['player_id']}_{l['match_id']}" for l in legs])
        parlay_hash = hashlib.md5('|'.join(leg_ids).encode()).hexdigest()[:16]

        max_kickoff = max(leg['kickoff_at'] for leg in legs)
        expires_at = max_kickoff + timedelta(hours=3)

        edge_pct = round(total_ev / len(legs) * 100, 2) if has_any_market_odds else 0

        return {
            'parlay_hash': parlay_hash,
            'leg_count': len(legs),
            'match_ids': match_ids,
            'legs': legs,
            'combined_odds': round(combined_odds, 2),
            'combined_prob_pct': round(combined_prob * 100, 4),
            'risk_tier': risk_tier,
            'payout_100': round(self.DEFAULT_BET * combined_odds, 2),
            'expires_at': expires_at,
            'has_market_odds': has_any_market_odds,
            'edge_pct': edge_pct,
            'avg_ev': round(total_ev / len(legs), 4) if legs else 0,
        }

    def _save_parlay(self, parlay: Dict) -> bool:
        session = self.Session()
        try:
            result = session.execute(text("""
                INSERT INTO player_parlays 
                (parlay_hash, leg_count, match_ids, combined_odds, raw_prob_pct, 
                 adjusted_prob_pct, edge_pct, confidence_tier, payout_100, expires_at,
                 has_market_odds, ev_pct, calibrated_prob_pct)
                VALUES (:parlay_hash, :leg_count, :match_ids, :combined_odds, :raw_prob_pct,
                        :adjusted_prob_pct, :edge_pct, :confidence_tier, :payout_100, :expires_at,
                        FALSE, 0, :calibrated_prob_pct)
                ON CONFLICT (parlay_hash) DO NOTHING
                RETURNING id
            """), {
                'parlay_hash': parlay['parlay_hash'],
                'leg_count': parlay['leg_count'],
                'match_ids': parlay['match_ids'],
                'combined_odds': parlay['combined_odds'],
                'raw_prob_pct': parlay['combined_prob_pct'],
                'adjusted_prob_pct': parlay['combined_prob_pct'],
                'edge_pct': parlay.get('edge_pct', 0),
                'confidence_tier': parlay['risk_tier'],
                'payout_100': parlay['payout_100'],
                'expires_at': parlay['expires_at'],
                'calibrated_prob_pct': parlay['combined_prob_pct']
            })

            row = result.fetchone()
            if not row:
                session.rollback()
                return False

            parlay_id = row[0]

            for idx, leg in enumerate(parlay['legs']):
                session.execute(text("""
                    INSERT INTO player_parlay_legs
                    (parlay_id, leg_index, match_id, home_team, away_team, 
                     league_name, kickoff_at, player_id, player_name, team_name,
                     model_prob, market_prob, decimal_odds, edge_pct,
                     calibrated_prob, has_market_odds)
                    VALUES (:parlay_id, :leg_index, :match_id, :home_team, :away_team,
                            :league_name, :kickoff_at, :player_id, :player_name, :team_name,
                            :model_prob, :market_prob, :decimal_odds, 0,
                            :model_prob, FALSE)
                """), {
                    'parlay_id': parlay_id,
                    'leg_index': idx,
                    'match_id': leg['match_id'],
                    'home_team': leg['home_team'],
                    'away_team': leg['away_team'],
                    'league_name': leg['league_name'],
                    'kickoff_at': leg['kickoff_at'],
                    'player_id': leg['player_id'],
                    'player_name': leg['player_name'],
                    'team_name': leg['team_name'],
                    'model_prob': leg['model_prob'],
                    'market_prob': leg.get('implied_prob', 1.0 / leg['decimal_odds'] if leg['decimal_odds'] > 0 else 0),
                    'decimal_odds': leg['decimal_odds'],
                })

            session.commit()
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Failed to save player parlay: {e}")
            return False
        finally:
            session.close()

    def generate_all_player_parlays(self, hours_ahead: int = 72) -> Dict:
        """
        Generate player parlays using sampling (not combinations).
        Caps: max 20 parlays per run, diversity constraints, leg reuse tracking.
        """
        logger.info(f"PlayerParlay: Starting generation for {hours_ahead}h ahead")

        fixtures = self._get_upcoming_fixtures(hours_ahead)
        logger.info(f"PlayerParlay: Found {len(fixtures)} fixtures")

        if len(fixtures) < 2:
            return {
                'status': 'insufficient_fixtures',
                'fixtures_found': len(fixtures),
                'parlays_generated': 0
            }

        fixtures = fixtures[:20]

        # Batch-compute ML probabilities for all players (fast vectorized approach)
        self._ml_cache = self._batch_ml_predictions(fixtures)
        self._used_ml = len(self._ml_cache) > 0

        all_legs = self._generate_candidate_legs(fixtures)

        # Clear cache after use
        self._ml_cache = {}
        logger.info(f"PlayerParlay: {len(all_legs)} candidate legs from {len(fixtures)} fixtures")

        if len(all_legs) < 2:
            return {
                'status': 'insufficient_players',
                'fixtures_found': len(fixtures),
                'legs_found': len(all_legs),
                'parlays_generated': 0
            }

        leg_usage = self._get_leg_usage_today()
        match_parlay_counts = self._get_match_parlay_count_today()

        parlays_generated = 0
        by_risk = {'low_risk': 0, 'medium_risk': 0, 'high_risk': 0}
        seen_hashes = set()
        prob_values = []

        per_k_counts = {2: 0, 3: 0}
        for k in [2, 3]:
            target = MAX_PARLAYS_PER_RUN // 2 if k == 2 else MAX_PARLAYS_PER_RUN // 4
            attempts = 0
            max_attempts = target * 10

            while parlays_generated < MAX_PARLAYS_PER_RUN and per_k_counts[k] < target and attempts < max_attempts:
                attempts += 1

                sampled = self._sample_parlay(all_legs, k, leg_usage, match_parlay_counts)
                if not sampled:
                    break

                parlay = self._build_parlay(sampled)

                if parlay['parlay_hash'] in seen_hashes:
                    continue
                seen_hashes.add(parlay['parlay_hash'])

                saved = self._save_parlay(parlay)
                if saved:
                    self._increment_leg_usage(sampled)
                    for leg in sampled:
                        key = (leg['match_id'], leg['player_id'])
                        leg_usage[key] = leg_usage.get(key, 0) + 1
                        match_parlay_counts[leg['match_id']] = match_parlay_counts.get(leg['match_id'], 0) + 1

                    parlays_generated += 1
                    per_k_counts[k] += 1
                    by_risk[parlay['risk_tier']] = by_risk.get(parlay['risk_tier'], 0) + 1
                    prob_values.append(parlay['combined_prob_pct'])

                if parlays_generated >= MAX_PARLAYS_PER_RUN:
                    break

        avg_prob = sum(prob_values) / len(prob_values) if prob_values else 0

        logger.info(f"PlayerParlay: Generated {parlays_generated} parlays (avg prob {avg_prob:.2f}%)")

        return {
            'status': 'success',
            'version': 'v3_rewrite',
            'fixtures_found': len(fixtures),
            'candidate_legs': len(all_legs),
            'parlays_generated': parlays_generated,
            'by_risk_tier': by_risk,
            'avg_combined_prob_pct': round(avg_prob, 3),
            'prob_method': 'ml_lightgbm_batch' if getattr(self, '_used_ml', False) else 'poisson_shrinkage'
        }

    def get_best_parlays(self, limit: int = 10, min_edge: float = -50, leg_count: int = None) -> List[Dict]:
        with self.engine.connect() as conn:
            leg_filter = f"AND pp.leg_count = {leg_count}" if leg_count else ""

            result = conn.execute(text(f"""
                SELECT 
                    pp.id,
                    pp.parlay_hash,
                    pp.leg_count,
                    pp.match_ids,
                    pp.combined_odds,
                    pp.raw_prob_pct,
                    pp.edge_pct,
                    pp.confidence_tier,
                    pp.payout_100,
                    pp.expires_at,
                    pp.calibrated_prob_pct
                FROM player_parlays pp
                WHERE pp.expires_at > NOW()
                  AND pp.status = 'pending'
                  {leg_filter}
                ORDER BY pp.raw_prob_pct DESC
                LIMIT :limit
            """), {'limit': limit})

            parlays = []
            for row in result.fetchall():
                parlay_data = dict(row._mapping)

                legs_result = conn.execute(text("""
                    SELECT 
                        player_name, team_name, model_prob, decimal_odds, edge_pct,
                        home_team, away_team, league_name, kickoff_at
                    FROM player_parlay_legs
                    WHERE parlay_id = :parlay_id
                    ORDER BY leg_index
                """), {'parlay_id': parlay_data['id']})

                parlay_data['legs'] = [dict(leg._mapping) for leg in legs_result.fetchall()]
                parlays.append(parlay_data)

            return parlays
