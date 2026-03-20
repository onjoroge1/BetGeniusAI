-- Idempotent migration: register basketball_ncaab as an active sport.
-- Run this once in any environment (local, staging, production) to enable
-- NCAA Basketball data collection. Safe to run multiple times (ON CONFLICT).

INSERT INTO sports (sport_key, sport_name, api_source, is_active, created_at)
VALUES (
    'basketball_ncaab',
    'Basketball (NCAA)',
    'the-odds-api',
    true,
    NOW()
)
ON CONFLICT (sport_key) DO UPDATE SET
    sport_name = EXCLUDED.sport_name,
    api_source  = EXCLUDED.api_source,
    is_active   = true;
