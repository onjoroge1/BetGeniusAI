-- Live Edge persistent snapshot store (Snapbet Live Edge, Phase 0)
-- ============================================================================
-- WHY: live_match_stats is the live cache, but stale_cleanup DELETES it ~4h
-- after a match ends. That destroys the exact training goldmine the in-game
-- model needs. This table is the PERMANENT append-only record — the live
-- collector (or a snapshot writer) inserts here every cycle and rows are NEVER
-- purged by stale_cleanup. One row per (match, minute) decision point.
--
-- Targets (target_more_goal / target_next_goal / target_result_holds) are
-- backfilled after full time from match_events — see features/live_feature_builder.py.

CREATE TABLE IF NOT EXISTS live_match_snapshots (
    id                  BIGSERIAL PRIMARY KEY,
    match_id            BIGINT NOT NULL,
    league_id           INTEGER,
    sport_key           TEXT DEFAULT 'soccer',
    snapshot_ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    match_minute        INTEGER NOT NULL,
    period              TEXT,
    -- score state
    home_score          INTEGER, away_score INTEGER,
    -- cumulative live stats (mirror of live_match_stats at this instant)
    home_shots          INTEGER, away_shots INTEGER,
    home_sot            INTEGER, away_sot INTEGER,
    home_corners        INTEGER, away_corners INTEGER,
    home_red            INTEGER, away_red INTEGER,
    home_possession     NUMERIC(5,2),
    -- pre-match anchor captured once (so training rows are self-contained)
    prematch_home_prob  NUMERIC(6,4),
    prematch_draw_prob  NUMERIC(6,4),
    prematch_away_prob  NUMERIC(6,4),
    -- live odds (NULL until in-play odds collection ships — Phase 3 blocker)
    live_over05_odds        NUMERIC(8,3),
    live_next_goal_home_odds NUMERIC(8,3),
    live_next_goal_away_odds NUMERIC(8,3),
    live_no_goal_odds        NUMERIC(8,3),
    -- labels (backfilled at FT)
    target_more_goal     SMALLINT,
    target_next_goal     TEXT,
    target_result_holds  SMALLINT,
    final_home_goals     INTEGER,
    final_away_goals     INTEGER,
    created_at           TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (match_id, match_minute)
);

CREATE INDEX IF NOT EXISTS idx_live_snap_match ON live_match_snapshots(match_id, match_minute);
CREATE INDEX IF NOT EXISTS idx_live_snap_unlabeled
    ON live_match_snapshots(match_id) WHERE target_more_goal IS NULL;
CREATE INDEX IF NOT EXISTS idx_live_snap_window
    ON live_match_snapshots(sport_key, match_minute) WHERE match_minute >= 55;
