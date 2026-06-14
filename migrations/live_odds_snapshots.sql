-- In-play odds store (Snapbet Live Edge, Layer 2 unblock)
-- ============================================================================
-- The missing piece that gates the whole edge/CLV/spec-validation product:
-- live prices. Fed by models/live_odds_collector.py from API-Football
-- /odds/live (one global call returns ALL in-play fixtures — cheap).
-- One row per (match, market, selection, line) per snapshot tick.

CREATE TABLE IF NOT EXISTS live_odds_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    match_id      BIGINT NOT NULL,            -- our fixtures.match_id
    league_id     INTEGER,
    ts_snapshot   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    minute        INTEGER,                    -- match elapsed at capture
    market_id     INTEGER NOT NULL,           -- API-Football market id (59=FT result, 25/36=totals, 69=BTTS)
    market_name   TEXT,
    selection     TEXT NOT NULL,              -- 'Home'/'Draw'/'Away' | 'Over'/'Under' | 'Yes'/'No'
    line          NUMERIC(6,2),               -- handicap/total line (NULL for 1X2/BTTS)
    odds_decimal  NUMERIC(8,3) NOT NULL,
    implied_prob  NUMERIC(6,4),               -- 1/odds (raw, vig-in)
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_live_odds_match ON live_odds_snapshots(match_id, ts_snapshot DESC);
CREATE INDEX IF NOT EXISTS idx_live_odds_market ON live_odds_snapshots(match_id, market_id, ts_snapshot DESC);
-- latest snapshot per match/market/selection/line is the working set
CREATE INDEX IF NOT EXISTS idx_live_odds_latest
    ON live_odds_snapshots(match_id, market_id, selection, line, ts_snapshot DESC);
