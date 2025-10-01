-- Team matching cache for API-Football fixture resolution
-- Idempotent migration - safe to run multiple times

-- Canonical team names & aliases for fuzzy matching
CREATE TABLE IF NOT EXISTS team_alias (
  team_canonical TEXT PRIMARY KEY,
  aliases TEXT[] NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- API-Football teams reference (per league+season cache)
CREATE TABLE IF NOT EXISTS apif_teams_ref (
  league_id INT NOT NULL,
  season INT NOT NULL,
  team_id INT NOT NULL,
  team_name TEXT NOT NULL,
  team_canonical TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (league_id, season, team_id)
);

CREATE INDEX IF NOT EXISTS idx_apif_teams_canonical 
ON apif_teams_ref(league_id, season, team_canonical);

-- Fixture mapping state for backfill observability
CREATE TABLE IF NOT EXISTS fixture_map_state (
  match_id BIGINT PRIMARY KEY,
  status TEXT NOT NULL,  -- 'matched' | 'ambiguous_top2' | 'no_candidates' | 'error'
  candidate_count INT DEFAULT 0,
  chosen_fixture_id INT,
  top_score DECIMAL(4,3),
  margin_vs_second DECIMAL(4,3),
  diagnostic_msg TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fixture_map_status 
ON fixture_map_state(status);

-- Seed common team aliases for major clubs
INSERT INTO team_alias (team_canonical, aliases) VALUES
  ('parissaintgermain', ARRAY['psg', 'paris sg', 'paris saint germain', 'paris saint-germain']),
  ('atleticomadrid', ARRAY['atletico', 'atlético madrid', 'atleti']),
  ('manchesterunited', ARRAY['man utd', 'man united', 'manchester utd', 'mufc']),
  ('manchestercity', ARRAY['man city', 'manchester city', 'mcfc']),
  ('tottenhamhotspur', ARRAY['spurs', 'tottenham', 'thfc']),
  ('wolverhamptonwanderers', ARRAY['wolves', 'wolverhampton']),
  ('brightonandhovealbion', ARRAY['brighton', 'brighton & hove albion']),
  ('westhamunited', ARRAY['west ham', 'whu']),
  ('newcastleunited', ARRAY['newcastle', 'nufc']),
  ('bayernmunich', ARRAY['bayern', 'fc bayern', 'bayern münchen', 'bayern munchen']),
  ('borussiadortmund', ARRAY['dortmund', 'bvb']),
  ('bayerleverkusen', ARRAY['leverkusen', 'bayer 04']),
  ('borussiamonchengladbach', ARRAY['gladbach', 'monchengladbach', 'mönchengladbach']),
  ('internazionale', ARRAY['inter', 'inter milan', 'fc internazionale']),
  ('acmilan', ARRAY['milan', 'ac milan']),
  ('asroma', ARRAY['roma', 'as roma']),
  ('realmadrid', ARRAY['real', 'real madrid cf']),
  ('fcbarcelona', ARRAY['barcelona', 'barça', 'barca', 'fcb']),
  ('atleticobilbao', ARRAY['athletic', 'athletic bilbao', 'athletic club']),
  ('realbetibalompie', ARRAY['betis', 'real betis']),
  ('olympiquemarseille', ARRAY['marseille', 'om']),
  ('olympiquelyonnais', ARRAY['lyon', 'ol']),
  ('parisfc', ARRAY['paris fc', 'pfc'])
ON CONFLICT (team_canonical) DO NOTHING;
