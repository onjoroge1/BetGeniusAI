-- World Cup 2026 Preparation - Database Tables Migration
-- Run with: psql $DATABASE_URL -f migrations/world_cup_2026_tables.sql

-- 1. International Matches - Historical Tournament Data
CREATE TABLE IF NOT EXISTS international_matches (
    id SERIAL PRIMARY KEY,
    api_football_fixture_id BIGINT UNIQUE,
    tournament_id INTEGER,
    tournament_name VARCHAR(100),
    tournament_stage VARCHAR(50),
    season INTEGER,
    match_date TIMESTAMPTZ,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_team_name VARCHAR(100),
    away_team_name VARCHAR(100),
    home_goals INTEGER,
    away_goals INTEGER,
    home_goals_ht INTEGER,
    away_goals_ht INTEGER,
    outcome CHAR(1),
    extra_time BOOLEAN DEFAULT FALSE,
    penalty_shootout BOOLEAN DEFAULT FALSE,
    penalty_home INTEGER,
    penalty_away INTEGER,
    venue VARCHAR(200),
    city VARCHAR(100),
    country VARCHAR(100),
    neutral_venue BOOLEAN DEFAULT TRUE,
    attendance INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. National Team Squads - Player Call-ups
CREATE TABLE IF NOT EXISTS national_team_squads (
    id SERIAL PRIMARY KEY,
    team_id INTEGER,
    team_name VARCHAR(100),
    player_id BIGINT,
    player_name VARCHAR(200),
    tournament_id INTEGER,
    tournament_name VARCHAR(100),
    season INTEGER,
    squad_announced_date DATE,
    position VARCHAR(50),
    club_team VARCHAR(100),
    caps_at_announcement INTEGER,
    goals_at_announcement INTEGER,
    is_withdrawn BOOLEAN DEFAULT FALSE,
    withdrawal_reason VARCHAR(200),
    is_late_callup BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Player International Stats - Career National Team Stats
CREATE TABLE IF NOT EXISTS player_international_stats (
    id SERIAL PRIMARY KEY,
    player_id BIGINT,
    player_name VARCHAR(200),
    team_id INTEGER,
    team_name VARCHAR(100),
    total_caps INTEGER DEFAULT 0,
    total_goals INTEGER DEFAULT 0,
    total_assists INTEGER DEFAULT 0,
    tournament_caps INTEGER DEFAULT 0,
    tournament_goals INTEGER DEFAULT 0,
    debut_date DATE,
    last_match_date DATE,
    minutes_last_12_months INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(player_id, team_id)
);

-- 4. National Team ELO - International ELO Ratings
CREATE TABLE IF NOT EXISTS national_team_elo (
    id SERIAL PRIMARY KEY,
    team_id INTEGER UNIQUE,
    team_name VARCHAR(100),
    elo_rating NUMERIC(8,2) DEFAULT 1500,
    elo_rank INTEGER,
    matches_played INTEGER DEFAULT 0,
    last_match_date DATE,
    peak_elo NUMERIC(8,2),
    peak_date DATE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Tournament Features - WC-Specific Context
CREATE TABLE IF NOT EXISTS tournament_features (
    id SERIAL PRIMARY KEY,
    match_id BIGINT,
    fixture_id BIGINT,
    stage VARCHAR(50),
    group_letter CHAR(1),
    matchday INTEGER,
    is_must_win_home BOOLEAN,
    is_must_win_away BOOLEAN,
    is_dead_rubber BOOLEAN,
    home_manager_tenure_days INTEGER,
    away_manager_tenure_days INTEGER,
    home_squad_new_pct NUMERIC(5,2),
    away_squad_new_pct NUMERIC(5,2),
    home_avg_caps NUMERIC(6,2),
    away_avg_caps NUMERIC(6,2),
    home_tournament_appearances INTEGER,
    away_tournament_appearances INTEGER,
    home_wc_wins INTEGER,
    away_wc_wins INTEGER,
    home_club_dispersion_index NUMERIC(5,2),
    away_club_dispersion_index NUMERIC(5,2),
    home_rest_days INTEGER,
    away_rest_days INTEGER,
    home_travel_km NUMERIC(10,2),
    away_travel_km NUMERIC(10,2),
    temperature_celsius NUMERIC(4,1),
    humidity_pct NUMERIC(4,1),
    altitude_meters INTEGER,
    kickoff_local_time TIME,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Penalty Shootout History - Psychology Features
CREATE TABLE IF NOT EXISTS penalty_shootout_history (
    id SERIAL PRIMARY KEY,
    team_id INTEGER,
    team_name VARCHAR(100),
    opponent_id INTEGER,
    opponent_name VARCHAR(100),
    tournament_id INTEGER,
    tournament_name VARCHAR(100),
    match_date DATE,
    stage VARCHAR(50),
    result CHAR(1),
    penalties_scored INTEGER,
    penalties_missed INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_intl_matches_tournament ON international_matches(tournament_id, season);
CREATE INDEX IF NOT EXISTS idx_intl_matches_teams ON international_matches(home_team_id, away_team_id);
CREATE INDEX IF NOT EXISTS idx_intl_matches_date ON international_matches(match_date);
CREATE INDEX IF NOT EXISTS idx_intl_matches_stage ON international_matches(tournament_stage);

CREATE INDEX IF NOT EXISTS idx_squad_team ON national_team_squads(team_id, tournament_id);
CREATE INDEX IF NOT EXISTS idx_squad_player ON national_team_squads(player_id);

CREATE INDEX IF NOT EXISTS idx_player_intl_team ON player_international_stats(team_id);
CREATE INDEX IF NOT EXISTS idx_player_intl_player ON player_international_stats(player_id);

CREATE INDEX IF NOT EXISTS idx_elo_rating ON national_team_elo(elo_rating DESC);

CREATE INDEX IF NOT EXISTS idx_tournament_features_match ON tournament_features(match_id);
CREATE INDEX IF NOT EXISTS idx_tournament_features_fixture ON tournament_features(fixture_id);

CREATE INDEX IF NOT EXISTS idx_penalty_team ON penalty_shootout_history(team_id);

-- Add unique constraint to league_map if needed
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'league_map_league_id_key'
    ) THEN
        ALTER TABLE league_map ADD CONSTRAINT league_map_league_id_key UNIQUE (league_id);
    END IF;
END $$;

-- Seed international leagues to league_map
INSERT INTO league_map (league_id, league_name, theodds_sport_key)
VALUES 
    (1, 'FIFA World Cup', 'soccer_fifa_world_cup'),
    (4, 'UEFA Euro', 'soccer_uefa_european_championship'),
    (5, 'UEFA Nations League', 'soccer_uefa_nations_league'),
    (6, 'Africa Cup of Nations', 'soccer_africa_cup_of_nations'),
    (9, 'Copa America', 'soccer_copa_america'),
    (10, 'International Friendlies', 'soccer_international_friendlies'),
    (29, 'WC Qualifiers - CAF', 'soccer_wc_qualification_caf'),
    (30, 'WC Qualifiers - AFC', 'soccer_wc_qualification_afc'),
    (31, 'WC Qualifiers - CONCACAF', 'soccer_wc_qualification_concacaf'),
    (32, 'WC Qualifiers - UEFA', 'soccer_wc_qualification_uefa'),
    (34, 'WC Qualifiers - CONMEBOL', 'soccer_wc_qualification_conmebol')
ON CONFLICT (league_id) DO UPDATE SET 
    league_name = EXCLUDED.league_name,
    theodds_sport_key = EXCLUDED.theodds_sport_key;
