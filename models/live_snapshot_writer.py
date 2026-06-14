"""
Live snapshot persistence + labeling (Snapbet Live Edge #2 — the data foundation).

live_match_stats is the 4h-purged cache; this copies each new live snapshot into
the PERMANENT live_match_snapshots store and, at full time, backfills the targets
from match_events. Without this, no labeled training data ever accumulates and the
Poisson prior can never be replaced by a calibrated model.

Two pure cores (unit-testable, no I/O):
  - next_goal_after(goal_events, minute): first goal's team after `minute`
  - label_snapshot(goal_minutes_teams, minute, score_at, final_score): the 3 targets

Thin DB wrappers:
  - persist_open_snapshots(): copy un-persisted live_match_stats rows → live_match_snapshots
  - backfill_labels(): for finished matches, fill target_* from match_events + final score
"""

import os
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Pure label logic ──────────────────────────────────────────────────────────

def next_goal_after(goals: List[Tuple[int, str]], minute: int) -> Optional[str]:
    """
    goals: chronological [(goal_minute, team)] where team is 'home'/'away'.
    Returns the team of the first goal strictly after `minute`, else None.
    """
    after = [(gm, t) for gm, t in goals if gm > minute]
    if not after:
        return None
    after.sort(key=lambda x: x[0])
    return after[0][1]


def label_snapshot(goals: List[Tuple[int, str]], minute: int,
                   score_at: Tuple[int, int], final_score: Tuple[int, int]) -> Dict:
    """
    Compute the 3 training targets for a snapshot at `minute`.
      target_more_goal    : 1 if any goal after `minute`
      target_next_goal    : 'home'/'away'/'none'
      target_result_holds : 1 if the outcome at `minute` == final outcome
    """
    nxt = next_goal_after(goals, minute)
    h0, a0 = score_at
    hf, af = final_score
    state_now = "H" if h0 > a0 else ("A" if a0 > h0 else "D")
    state_ft = "H" if hf > af else ("A" if af > hf else "D")
    return {
        "target_more_goal": 1 if nxt is not None else 0,
        "target_next_goal": nxt if nxt is not None else "none",
        "target_result_holds": 1 if state_now == state_ft else 0,
    }


# ── DB wrappers ───────────────────────────────────────────────────────────────

def _conn():
    import psycopg2
    return psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=15)


def persist_open_snapshots() -> int:
    """
    Copy live_match_stats rows that aren't yet in live_match_snapshots (one per
    match+minute). Runs every cycle while matches are live. Labels stay NULL until
    backfill_labels() runs at FT. Returns rows inserted.
    """
    inserted = 0
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO live_match_snapshots (
                        match_id, league_id, snapshot_ts, match_minute, period,
                        home_score, away_score, home_shots, away_shots,
                        home_sot, away_sot, home_corners, away_corners,
                        home_red, away_red, home_possession, home_xg, away_xg,
                        prematch_home_prob, prematch_draw_prob, prematch_away_prob)
                    SELECT lms.match_id, f.league_id, lms.timestamp, lms.minute, lms.period,
                           lms.home_score, lms.away_score, lms.home_shots_total, lms.away_shots_total,
                           lms.home_shots_on_target, lms.away_shots_on_target,
                           lms.home_corners, lms.away_corners,
                           lms.home_red_cards, lms.away_red_cards, lms.home_possession, lms.home_xg, lms.away_xg,
                           oc.ph_cons, oc.pd_cons, oc.pa_cons
                    FROM live_match_stats lms
                    JOIN fixtures f ON f.match_id = lms.match_id
                    LEFT JOIN LATERAL (
                        SELECT ph_cons, pd_cons, pa_cons FROM odds_consensus o
                        WHERE o.match_id = lms.match_id AND o.ph_cons IS NOT NULL
                        ORDER BY o.ts_effective DESC LIMIT 1
                    ) oc ON true
                    WHERE lms.minute IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM live_match_snapshots s
                          WHERE s.match_id = lms.match_id AND s.match_minute = lms.minute)
                    ON CONFLICT (match_id, match_minute) DO NOTHING
                """)
                inserted = cur.rowcount
                conn.commit()
    except Exception as e:
        logger.warning(f"persist_open_snapshots failed: {e}")
    if inserted:
        logger.info(f"🗄️ Persisted {inserted} live snapshots")
    return inserted


def backfill_labels(max_matches: int = 50) -> int:
    """
    For finished matches with unlabeled snapshots, compute targets from
    match_events + final score and write them. Returns matches labeled.
    """
    labeled = 0
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT DISTINCT s.match_id
                    FROM live_match_snapshots s
                    JOIN fixtures f ON f.match_id = s.match_id
                    WHERE s.target_more_goal IS NULL
                      AND f.status IN ('finished','FT','completed','AET','PEN')
                    LIMIT %s
                """, (max_matches,))
                match_ids = [r[0] for r in cur.fetchall()]
                for mid in match_ids:
                    # goal events (team side from score deltas or 'team' field)
                    cur.execute("""
                        SELECT minute, event_type, score_home, score_away
                        FROM match_events
                        WHERE match_id = %s AND event_type ILIKE '%%goal%%'
                        ORDER BY minute ASC
                    """, (mid,))
                    evs = cur.fetchall()
                    goals = []
                    prev_h = prev_a = 0
                    for minute, etype, sh, sa in evs:
                        sh, sa = sh or prev_h, sa or prev_a
                        if sh > prev_h:
                            goals.append((minute, "home"))
                        elif sa > prev_a:
                            goals.append((minute, "away"))
                        prev_h, prev_a = sh, sa
                    # final score from fixtures/matches
                    cur.execute("""
                        SELECT m.home_goals, m.away_goals FROM matches m WHERE m.match_id = %s
                    """, (mid,))
                    fr = cur.fetchone()
                    if not fr or fr[0] is None:
                        continue
                    final = (int(fr[0]), int(fr[1]))
                    # label each snapshot
                    cur.execute("""
                        SELECT match_minute, home_score, away_score
                        FROM live_match_snapshots WHERE match_id = %s AND target_more_goal IS NULL
                    """, (mid,))
                    for minute, hs, as_ in cur.fetchall():
                        lab = label_snapshot(goals, minute, (hs or 0, as_ or 0), final)
                        cur.execute("""
                            UPDATE live_match_snapshots
                            SET target_more_goal = %s, target_next_goal = %s,
                                target_result_holds = %s,
                                final_home_goals = %s, final_away_goals = %s
                            WHERE match_id = %s AND match_minute = %s
                        """, (lab["target_more_goal"], lab["target_next_goal"],
                              lab["target_result_holds"], final[0], final[1], mid, minute))
                    labeled += 1
                conn.commit()
    except Exception as e:
        logger.warning(f"backfill_labels failed: {e}")
    if labeled:
        logger.info(f"🏷️ Labeled snapshots for {labeled} finished matches")
    return labeled


def run_snapshot_cycle() -> Dict:
    """One scheduler tick: persist open snapshots, then backfill any finished matches."""
    return {"persisted": persist_open_snapshots(), "labeled": backfill_labels()}
