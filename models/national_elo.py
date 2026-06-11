"""
National-Team ELO — World Football Elo methodology for WC 2026.

International football is the one place ELO genuinely shines: the official
"World Football Elo Ratings" predict national-team matches better than most
models because the signal (relative team strength) is stable and the data is
clean. Unlike club V3 (which just echoed the betting line), this is a real,
non-market signal.

Methodology (eloratings.net standard):
  expected_home = 1 / (1 + 10^((elo_away - (elo_home + HFA)) / 400))
  new_elo = elo + K * G * (actual - expected)
where:
  HFA  = home-field advantage (0 at neutral venues — most tournament matches)
  K    = base weight scaled by tournament importance
  G    = margin-of-victory multiplier (bigger wins move ELO more)

Tournament K-weights (importance):
  FIFA World Cup            : 60
  Continental (Euro/Copa/AFCON): 50
  WC Qualifiers / Nations Lg: 40
  Friendlies               : 20

Usage:
  from models.national_elo import NationalEloModel
  m = NationalEloModel()
  history = m.build_from_history()      # populates national_team_elo, returns per-match pre-game ELOs
  p = m.predict_proba(home_id, away_id, neutral=True)   # {'home':..,'draw':..,'away':..}
"""

import os
import math
import logging
from typing import Dict, List, Optional
from datetime import datetime

import psycopg2

logger = logging.getLogger(__name__)

INITIAL_ELO = 1500.0
HOME_ADVANTAGE = 100.0  # ELO points; applied only at non-neutral venues

# Tournament importance → base K factor
TOURNAMENT_K = {
    1:  60,   # FIFA World Cup
    4:  50,   # UEFA Euro
    6:  50,   # AFCON
    9:  50,   # Copa America
    5:  40,   # Nations League
    10: 20,   # Friendlies
}
DEFAULT_QUALIFIER_K = 40  # leagues 29-34 (WC qualifiers, all confederations)


def _k_factor(tournament_id: Optional[int]) -> float:
    if tournament_id in TOURNAMENT_K:
        return TOURNAMENT_K[tournament_id]
    if tournament_id in (29, 30, 31, 32, 33, 34):
        return DEFAULT_QUALIFIER_K
    return 30.0  # unknown


def _mov_multiplier(goal_diff: int) -> float:
    """Margin-of-victory multiplier (eloratings.net): dampens blowouts log-style."""
    gd = abs(goal_diff)
    if gd <= 1:
        return 1.0
    if gd == 2:
        return 1.5
    return (11.0 + gd) / 8.0  # 3→1.75, 4→1.875, ...


class NationalEloModel:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL")
        self.elos: Dict[int, float] = {}        # team_id -> rating
        self.names: Dict[int, str] = {}         # team_id -> name

    # ── ELO math ──────────────────────────────────────────────────────────────
    @staticmethod
    def expected(elo_home: float, elo_away: float, neutral: bool) -> float:
        hfa = 0.0 if neutral else HOME_ADVANTAGE
        return 1.0 / (1.0 + 10 ** ((elo_away - (elo_home + hfa)) / 400.0))

    def _get(self, team_id: int) -> float:
        return self.elos.get(team_id, INITIAL_ELO)

    # ── Build ratings from full match history ─────────────────────────────────
    def build_from_history(self, persist: bool = True) -> List[Dict]:
        """
        Process all completed international matches chronologically, updating ELO.
        Returns a per-match list of PRE-game ELOs (leak-safe features for training).
        Optionally persists final ratings to national_team_elo.
        """
        self._matches_played: Dict[int, int] = {}
        self._last_match: Dict[int, datetime] = {}
        self._peak: Dict[int, float] = {}
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT home_team_id, home_team_name, away_team_id, away_team_name,
                   home_goals, away_goals, tournament_id, tournament_stage,
                   match_date, neutral_venue
            FROM international_matches
            WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL
              AND home_team_id IS NOT NULL AND away_team_id IS NOT NULL
            ORDER BY match_date ASC, id ASC
        """)
        rows = cur.fetchall()
        logger.info(f"🌍 Building national ELO from {len(rows):,} completed matches…")

        history: List[Dict] = []
        for (h_id, h_name, a_id, a_name, hg, ag, tid, stage, mdate, neutral) in rows:
            self.names[h_id] = h_name
            self.names[a_id] = a_name
            eh, ea = self._get(h_id), self._get(a_id)

            # Record PRE-game state (leak-safe for training)
            neutral_b = bool(neutral)
            exp_h = self.expected(eh, ea, neutral_b)
            history.append({
                "home_id": h_id, "away_id": a_id,
                "home_elo_pre": eh, "away_elo_pre": ea,
                "elo_diff": (eh + (0 if neutral_b else HOME_ADVANTAGE)) - ea,
                "expected_home": exp_h,
                "neutral": int(neutral_b),
                "is_knockout": int(stage in ("final", "sf", "qf", "r16", "r32", "3rd_place")),
                "tournament_id": tid,
                "outcome": "H" if hg > ag else ("A" if ag > hg else "D"),
                "match_date": mdate,
            })

            # Update ELO
            actual_h = 1.0 if hg > ag else (0.0 if ag > hg else 0.5)
            k = _k_factor(tid) * _mov_multiplier(hg - ag)
            delta = k * (actual_h - exp_h)
            self.elos[h_id] = eh + delta
            self.elos[a_id] = ea - delta

            # Track metadata for persistence
            for tid_, new_elo in ((h_id, self.elos[h_id]), (a_id, self.elos[a_id])):
                self._matches_played[tid_] = self._matches_played.get(tid_, 0) + 1
                self._last_match[tid_] = mdate
                self._peak[tid_] = max(self._peak.get(tid_, INITIAL_ELO), new_elo)

        cur.close()
        if persist:
            self._persist(conn)
        conn.close()
        logger.info(f"✅ ELO built for {len(self.elos)} national teams")
        return history

    def _persist(self, conn):
        cur = conn.cursor()
        # Compute ranks (1 = highest ELO)
        ranked = sorted(self.elos.items(), key=lambda kv: kv[1], reverse=True)
        rank_of = {tid: i + 1 for i, (tid, _) in enumerate(ranked)}
        for tid, rating in self.elos.items():
            cur.execute("""
                INSERT INTO national_team_elo
                  (team_id, team_name, elo_rating, elo_rank, matches_played,
                   last_match_date, peak_elo, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (team_id) DO UPDATE
                  SET elo_rating = EXCLUDED.elo_rating,
                      team_name = EXCLUDED.team_name,
                      elo_rank = EXCLUDED.elo_rank,
                      matches_played = EXCLUDED.matches_played,
                      last_match_date = EXCLUDED.last_match_date,
                      peak_elo = GREATEST(national_team_elo.peak_elo, EXCLUDED.peak_elo),
                      updated_at = NOW()
            """, (tid, self.names.get(tid, "Unknown"), round(rating, 2),
                  rank_of[tid], self._matches_played.get(tid, 0),
                  self._last_match.get(tid), round(self._peak.get(tid, rating), 2)))
        conn.commit()
        cur.close()
        logger.info(f"💾 Persisted {len(self.elos)} ratings to national_team_elo")

    # ── Inference: ELO-only baseline probabilities ────────────────────────────
    def predict_proba(self, home_id: int, away_id: int, neutral: bool = True) -> Dict[str, float]:
        """
        Convert ELO difference to H/D/A probabilities.
        Draw probability peaks for evenly-matched teams (empirical intl draw rate ~22%).
        This is the ELO BASELINE — the trained WC model calibrates on top of it.
        """
        eh, ea = self._get(home_id), self._get(away_id)
        exp_h = self.expected(eh, ea, neutral)  # expected score in [0,1]
        # Map expected score to win/draw/loss. Draw mass largest at exp_h=0.5.
        # p_draw = d_max * (1 - 2*|exp_h - 0.5|) keeps draws plausible for close games.
        d_max = 0.30
        p_draw = d_max * (1.0 - 2.0 * abs(exp_h - 0.5))
        p_draw = max(0.08, p_draw)
        # Split remaining mass by expected score
        remaining = 1.0 - p_draw
        p_home = remaining * exp_h
        p_away = remaining * (1.0 - exp_h)
        return {"home": round(p_home, 4), "draw": round(p_draw, 4), "away": round(p_away, 4)}

    def load_ratings(self):
        """Load persisted ratings from DB (for inference without rebuilding)."""
        conn = psycopg2.connect(self.db_url)
        cur = conn.cursor()
        cur.execute("SELECT team_id, team_name, elo_rating FROM national_team_elo")
        for tid, name, rating in cur.fetchall():
            self.elos[tid] = float(rating)
            self.names[tid] = name
        cur.close()
        conn.close()
        return self


if __name__ == "__main__":
    import re
    from pathlib import Path
    REPO = Path(__file__).parent.parent
    for ef in [".env.local", ".env"]:
        p = REPO / ef
        if p.exists():
            for line in p.read_text().splitlines():
                m = re.match(r"^([^#=\s][^=]*)=(.*)$", line)
                if m and not os.environ.get(m.group(1).strip()):
                    os.environ[m.group(1).strip()] = m.group(2).strip()
            break
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    model = NationalEloModel()
    model.build_from_history()
    # Show top 20 ranked teams
    ranked = sorted(model.elos.items(), key=lambda kv: kv[1], reverse=True)[:20]
    print("\nTop 20 national teams by ELO:")
    for i, (tid, rating) in enumerate(ranked, 1):
        print(f"  {i:2d}. {model.names.get(tid, tid):<24} {rating:.0f}")
