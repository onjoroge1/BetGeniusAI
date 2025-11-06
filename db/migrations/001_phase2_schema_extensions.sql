-- Phase 2 Schema Extensions for BetGenius AI
-- Player intelligence, referee tracking, weather, and contextual features

-- ============================================================================
-- PLAYERS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS players (
    player_id BIGSERIAL PRIMARY KEY,
    api_football_id BIGINT UNIQUE,
    name TEXT NOT NULL,
    date_of_birth DATE,
    nationality TEXT,
    primary_position TEXT,
    preferred_foot TEXT CHECK (preferred_foot IN ('Left', 'Right', 'Both')),
    height_cm INT,
    weight_kg INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_players_api_football_id ON players(api_football_id);
CREATE INDEX IF NOT EXISTS idx_players_name ON players(name);

COMMENT ON TABLE players IS 'Player master data for lineup intelligence';
COMMENT ON COLUMN players.api_football_id IS 'External API player identifier';
COMMENT ON COLUMN players.primary_position IS 'GK, CB, FB, DM, CM, AM, W, or ST';

-- ============================================================================
-- PLAYER AVAILABILITY TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS player_availability (
    match_id BIGINT NOT NULL,
    player_id BIGINT NOT NULL,
    team_id BIGINT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('started', 'bench', 'out', 'unknown')),
    reason TEXT,  -- 'injury', 'suspension', 'tactical', 'rest', 'fitness'
    minutes_played INT CHECK (minutes_played >= 0 AND minutes_played <= 120),
    position_played TEXT,
    rating DECIMAL(3, 1),  -- Match rating 0.0-10.0
    goals INT DEFAULT 0,
    assists INT DEFAULT 0,
    yellow_cards INT DEFAULT 0,
    red_cards INT DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (match_id, player_id),
    FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_avail_match ON player_availability(match_id);
CREATE INDEX IF NOT EXISTS idx_player_avail_player ON player_availability(player_id);
CREATE INDEX IF NOT EXISTS idx_player_avail_team ON player_availability(team_id);
CREATE INDEX IF NOT EXISTS idx_player_avail_status ON player_availability(status);

COMMENT ON TABLE player_availability IS 'Player lineup and availability data per match';
COMMENT ON COLUMN player_availability.status IS 'Player status: started, bench, out, unknown';
COMMENT ON COLUMN player_availability.reason IS 'Why player is out or on bench';

-- ============================================================================
-- REFEREES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS referees (
    ref_id BIGSERIAL PRIMARY KEY,
    api_football_id BIGINT UNIQUE,
    name TEXT NOT NULL,
    nationality TEXT,
    
    -- Calculated metrics (updated from historical data)
    card_rate DECIMAL(4, 2),  -- Average cards per match
    yellow_card_rate DECIMAL(4, 2),
    red_card_rate DECIMAL(4, 2),
    penalty_rate DECIMAL(4, 2),  -- Penalties awarded per match
    home_bias_index DECIMAL(5, 3),  -- -1 (away bias) to +1 (home bias)
    matches_refereed INT DEFAULT 0,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_referees_api_football_id ON referees(api_football_id);
CREATE INDEX IF NOT EXISTS idx_referees_name ON referees(name);

COMMENT ON TABLE referees IS 'Referee master data with historical metrics';
COMMENT ON COLUMN referees.home_bias_index IS 'Calculated from historical decisions, 0 = neutral';

-- ============================================================================
-- MATCH REFEREE ASSIGNMENT
-- ============================================================================
CREATE TABLE IF NOT EXISTS match_referees (
    match_id BIGINT PRIMARY KEY,
    ref_id BIGINT NOT NULL,
    FOREIGN KEY (ref_id) REFERENCES referees(ref_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_match_referees_ref ON match_referees(ref_id);

-- ============================================================================
-- WEATHER TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS match_weather (
    match_id BIGINT PRIMARY KEY,
    temperature_celsius DECIMAL(5, 2),
    humidity_pct DECIMAL(5, 2),
    precipitation_mm DECIMAL(6, 2),
    wind_speed_kmh DECIMAL(6, 2),
    wind_direction TEXT,  -- 'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'
    conditions TEXT,  -- 'clear', 'cloudy', 'rain', 'snow', 'fog'
    visibility_km DECIMAL(6, 2),
    pressure_hpa DECIMAL(7, 2),
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source TEXT  -- API source
);

CREATE INDEX IF NOT EXISTS idx_weather_conditions ON match_weather(conditions);

COMMENT ON TABLE match_weather IS 'Weather conditions at kickoff time';
COMMENT ON COLUMN match_weather.conditions IS 'General weather category';

-- ============================================================================
-- MATCH CONTEXT TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS match_context (
    match_id BIGINT PRIMARY KEY,
    
    -- Rest and schedule features
    rest_days_home DECIMAL(6, 2),
    rest_days_away DECIMAL(6, 2),
    
    -- Travel features
    travel_distance_home_km DECIMAL(8, 2),
    travel_distance_away_km DECIMAL(8, 2),
    
    -- Schedule congestion (matches in time windows)
    schedule_congestion_home_7d INT,  -- Matches in last 7 days
    schedule_congestion_away_7d INT,
    schedule_congestion_home_14d INT,  -- Matches in last 14 days
    schedule_congestion_away_14d INT,
    
    -- Upcoming schedule
    next_match_days_home DECIMAL(6, 2),  -- Days until next match
    next_match_days_away DECIMAL(6, 2),
    
    -- Match importance
    fixture_difficulty_rating DECIMAL(4, 2),  -- 0-10 scale
    derby_flag BOOLEAN DEFAULT FALSE,
    cup_match BOOLEAN DEFAULT FALSE,
    season_stage DECIMAL(4, 3),  -- 0.0 (start) to 1.0 (end)
    
    -- Venue factors
    venue_altitude_m INT,
    venue_capacity INT,
    attendance_expected INT,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_context_derby ON match_context(derby_flag);
CREATE INDEX IF NOT EXISTS idx_match_context_cup ON match_context(cup_match);

COMMENT ON TABLE match_context IS 'Contextual features: schedule, travel, venue, importance';
COMMENT ON COLUMN match_context.fixture_difficulty_rating IS 'How difficult is this fixture (opponent quality, schedule, etc.)';
COMMENT ON COLUMN match_context.derby_flag IS 'Local rivalry match';

-- ============================================================================
-- DATA LINEAGE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS data_lineage (
    entity_type TEXT NOT NULL,  -- 'match', 'players', 'availability', 'weather', 'odds', 'referee'
    entity_id TEXT NOT NULL,
    source TEXT NOT NULL,  -- 'api-football', 'odds-api', 'weather-api', 'manual'
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetch_duration_ms INT,
    record_count INT,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    extra JSONB,  -- Flexible metadata
    PRIMARY KEY (entity_type, entity_id, source, fetched_at)
);

CREATE INDEX IF NOT EXISTS idx_lineage_entity ON data_lineage(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_lineage_source ON data_lineage(source);
CREATE INDEX IF NOT EXISTS idx_lineage_fetched ON data_lineage(fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_lineage_success ON data_lineage(success);

COMMENT ON TABLE data_lineage IS 'Track data provenance and collection history';
COMMENT ON COLUMN data_lineage.entity_type IS 'Type of data collected';
COMMENT ON COLUMN data_lineage.source IS 'Data source identifier';

-- ============================================================================
-- TEAM VENUE INFORMATION (extending teams)
-- ============================================================================
CREATE TABLE IF NOT EXISTS team_venues (
    team_id BIGINT PRIMARY KEY,
    venue_name TEXT,
    city TEXT,
    latitude DECIMAL(9, 6),
    longitude DECIMAL(9, 6),
    altitude_m INT,
    capacity INT,
    surface TEXT,  -- 'grass', 'artificial', 'hybrid'
    pitch_length_m INT,
    pitch_width_m INT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_team_venues_city ON team_venues(city);

COMMENT ON TABLE team_venues IS 'Home venue details for each team';
COMMENT ON COLUMN team_venues.altitude_m IS 'Stadium altitude (affects play at high altitude)';

-- ============================================================================
-- PLAYER STATISTICS (per-90 aggregates)
-- ============================================================================
CREATE TABLE IF NOT EXISTS player_stats_per90 (
    player_id BIGINT NOT NULL,
    season TEXT NOT NULL,  -- e.g., '2024-2025'
    league_id BIGINT,
    
    -- Playing time
    matches_played INT DEFAULT 0,
    minutes_played INT DEFAULT 0,
    
    -- Offensive stats
    goals DECIMAL(4, 2),  -- Per 90 minutes
    assists DECIMAL(4, 2),
    shots DECIMAL(4, 2),
    shots_on_target DECIMAL(4, 2),
    key_passes DECIMAL(4, 2),
    dribbles_attempted DECIMAL(4, 2),
    dribbles_successful DECIMAL(4, 2),
    
    -- Defensive stats
    tackles DECIMAL(4, 2),
    interceptions DECIMAL(4, 2),
    clearances DECIMAL(4, 2),
    blocks DECIMAL(4, 2),
    
    -- Discipline
    fouls_committed DECIMAL(4, 2),
    fouls_drawn DECIMAL(4, 2),
    yellow_cards DECIMAL(4, 2),
    red_cards DECIMAL(4, 2),
    
    -- Goalkeeper specific
    saves DECIMAL(4, 2),
    goals_conceded DECIMAL(4, 2),
    clean_sheets_pct DECIMAL(5, 2),
    
    -- Advanced metrics
    xg DECIMAL(4, 2),  -- Expected goals
    xa DECIMAL(4, 2),  -- Expected assists
    
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (player_id, season),
    FOREIGN KEY (player_id) REFERENCES players(player_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_stats_season ON player_stats_per90(season);
CREATE INDEX IF NOT EXISTS idx_player_stats_league ON player_stats_per90(league_id);

COMMENT ON TABLE player_stats_per90 IS 'Aggregated player statistics per 90 minutes';
COMMENT ON COLUMN player_stats_per90.goals IS 'Goals per 90 minutes played';

-- ============================================================================
-- VIEWS FOR ANALYTICS
-- ============================================================================

-- View: Team strength with lineup
CREATE OR REPLACE VIEW v_team_lineup_strength AS
SELECT 
    pa.match_id,
    pa.team_id,
    COUNT(DISTINCT CASE WHEN pa.status = 'started' THEN pa.player_id END) as starters_count,
    AVG(CASE WHEN pa.status = 'started' THEN ps.xg END) as avg_xg_per90,
    AVG(CASE WHEN pa.status = 'started' THEN ps.xa END) as avg_xa_per90,
    AVG(CASE WHEN pa.status = 'started' THEN pa.rating END) as avg_player_rating,
    SUM(CASE WHEN pa.status = 'out' AND pa.reason IN ('injury', 'suspension') THEN 1 ELSE 0 END) as key_absences
FROM player_availability pa
LEFT JOIN player_stats_per90 ps ON pa.player_id = ps.player_id
GROUP BY pa.match_id, pa.team_id;

COMMENT ON VIEW v_team_lineup_strength IS 'Team quality metrics based on available lineup';

-- View: Referee impact summary
CREATE OR REPLACE VIEW v_referee_summary AS
SELECT 
    r.ref_id,
    r.name,
    r.matches_refereed,
    r.card_rate,
    r.home_bias_index,
    COUNT(mr.match_id) as recent_matches,
    AVG(CASE WHEN EXISTS (
        SELECT 1 FROM match_context mc 
        WHERE mc.match_id = mr.match_id AND mc.derby_flag = TRUE
    ) THEN 1 ELSE 0 END) as derby_frequency
FROM referees r
LEFT JOIN match_referees mr ON r.ref_id = mr.ref_id
GROUP BY r.ref_id, r.name, r.matches_refereed, r.card_rate, r.home_bias_index;

COMMENT ON VIEW v_referee_summary IS 'Referee statistics and assignment patterns';

-- ============================================================================
-- FUNCTIONS FOR FEATURE CALCULATION
-- ============================================================================

-- Calculate team rest days
CREATE OR REPLACE FUNCTION calculate_rest_days(
    p_team_id BIGINT,
    p_match_date TIMESTAMPTZ
) RETURNS DECIMAL AS $$
DECLARE
    v_last_match_date TIMESTAMPTZ;
    v_rest_days DECIMAL;
BEGIN
    SELECT match_date INTO v_last_match_date
    FROM training_matches
    WHERE (home_team_id = p_team_id OR away_team_id = p_team_id)
      AND match_date < p_match_date
    ORDER BY match_date DESC
    LIMIT 1;
    
    IF v_last_match_date IS NULL THEN
        RETURN 7.0;  -- Default to 1 week
    END IF;
    
    v_rest_days := EXTRACT(EPOCH FROM (p_match_date - v_last_match_date)) / 86400.0;
    RETURN v_rest_days;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION calculate_rest_days IS 'Calculate days since team last played';

-- Calculate schedule congestion
CREATE OR REPLACE FUNCTION calculate_congestion(
    p_team_id BIGINT,
    p_match_date TIMESTAMPTZ,
    p_days INT DEFAULT 7
) RETURNS INT AS $$
DECLARE
    v_match_count INT;
BEGIN
    SELECT COUNT(*) INTO v_match_count
    FROM training_matches
    WHERE (home_team_id = p_team_id OR away_team_id = p_team_id)
      AND match_date BETWEEN (p_match_date - (p_days || ' days')::INTERVAL) AND p_match_date
      AND match_date < p_match_date;
    
    RETURN v_match_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION calculate_congestion IS 'Count matches in recent time window';

-- ============================================================================
-- SAMPLE DATA QUERIES (for testing)
-- ============================================================================

-- Query: Matches with full contextual data
-- SELECT 
--     tm.match_id,
--     tm.home_team,
--     tm.away_team,
--     mc.rest_days_home,
--     mc.rest_days_away,
--     mc.derby_flag,
--     r.name as referee,
--     r.card_rate,
--     mw.temperature_celsius,
--     mw.conditions as weather
-- FROM training_matches tm
-- LEFT JOIN match_context mc ON tm.match_id = mc.match_id
-- LEFT JOIN match_referees mr ON tm.match_id = mr.match_id
-- LEFT JOIN referees r ON mr.ref_id = r.ref_id
-- LEFT JOIN match_weather mw ON tm.match_id = mw.match_id
-- WHERE tm.match_date >= NOW() - INTERVAL '30 days'
-- ORDER BY tm.match_date DESC;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
