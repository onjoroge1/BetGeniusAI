"""
Data-integrity tests: the DB is in the expected post-cleanup, post-seed state.
Covers the synthetic-odds removal, WC data collection, and fixture seeding.
"""
import pytest
from conftest import requires_db


@requires_db
class TestSyntheticOddsRemoved:
    """The 3 hardcoded template vectors must be gone from odds_consensus."""
    SYN = (
        "(ABS(ph_cons-0.650)<0.001 AND ABS(pd_cons-0.250)<0.001 AND ABS(pa_cons-0.100)<0.001) "
        "OR (ABS(ph_cons-0.100)<0.001 AND ABS(pd_cons-0.250)<0.001 AND ABS(pa_cons-0.650)<0.001) "
        "OR (ABS(ph_cons-0.300)<0.001 AND ABS(pd_cons-0.400)<0.001 AND ABS(pa_cons-0.300)<0.001)"
    )

    def test_no_synthetic_rows_contaminate_training(self, db):
        """
        The contamination vector that matters: synthetic template rows that JOIN
        to a trainable match (fixtures with a result, or training_matches). These
        are what poisoned V3. Orphan synthetic rows (match_id in no real table)
        can't reach the model and are tolerated — production keeps regenerating
        them until the disabled fix_odds_consensus_backfill ships, so asserting
        zero-anywhere would be flaky and is not the real risk.
        """
        cur = db.cursor()
        cur.execute(f"""
            SELECT COUNT(*) FROM odds_consensus oc
            WHERE ({self.SYN})
              AND (EXISTS (SELECT 1 FROM training_matches tm WHERE tm.match_id = oc.match_id)
                   OR EXISTS (SELECT 1 FROM fixtures f
                              WHERE f.match_id = oc.match_id AND f.status = 'finished'))
        """)
        assert cur.fetchone()[0] == 0, "synthetic rows joined to trainable matches — training contamination risk"

    def test_synthetic_orphans_surfaced(self, db):
        """Diagnostic (never fails): report orphan synthetic rows so the team
        knows the production disable hasn't deployed yet."""
        cur = db.cursor()
        cur.execute(f"SELECT COUNT(*) FROM odds_consensus WHERE {self.SYN}")
        total = cur.fetchone()[0]
        if total:
            print(f"\n  [info] {total} synthetic template rows present (orphans tolerated; "
                  f"deploy the fix_odds_consensus_backfill disable to stop regeneration)")

    def test_real_rows_remain(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM odds_consensus WHERE ph_cons IS NOT NULL")
        assert cur.fetchone()[0] > 0


@requires_db
class TestNationalElo:
    def test_populated(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM national_team_elo")
        assert cur.fetchone()[0] >= 100

    def test_ratings_reasonable(self, db):
        cur = db.cursor()
        cur.execute("SELECT MIN(elo_rating), MAX(elo_rating) FROM national_team_elo")
        lo, hi = cur.fetchone()
        assert 800 <= float(lo) <= 1500
        assert 1700 <= float(hi) <= 2300

    def test_elite_teams_ranked_high(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT team_name FROM national_team_elo
            ORDER BY elo_rating DESC LIMIT 20
        """)
        top20 = {r[0] for r in cur.fetchall()}
        # at least a few of the genuine elite should appear in the top 20
        elite = {"Spain", "France", "England", "Argentina", "Germany", "Netherlands", "Brazil"}
        assert len(top20 & elite) >= 3, f"expected elite teams in top 20, got {top20}"


@requires_db
class TestWCSquads:
    def test_squads_collected(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT team_id) FROM national_team_squads")
        players, teams = cur.fetchone()
        assert teams >= 40, "expected ~48 national squads"
        assert players >= 1000


@requires_db
class TestWCFixtures:
    def test_fixtures_seeded(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM fixtures WHERE league_id=1 AND season=2026")
        assert cur.fetchone()[0] >= 48, "expected the WC group-stage fixtures"

    def test_fixtures_have_team_ids(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM fixtures
            WHERE league_id=1 AND season=2026
              AND (home_team_id IS NULL OR away_team_id IS NULL)
        """)
        assert cur.fetchone()[0] == 0, "WC fixtures missing team ids → ELO routing breaks"

    def test_fixture_teams_have_elo(self, db):
        # every seeded fixture's teams should have ELO ratings (so routing succeeds)
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM fixtures f
            WHERE f.league_id=1 AND f.season=2026
              AND (f.home_team_id NOT IN (SELECT team_id FROM national_team_elo)
                   OR f.away_team_id NOT IN (SELECT team_id FROM national_team_elo))
        """)
        missing = cur.fetchone()[0]
        # allow a small number (a brand-new nation with no match history)
        assert missing <= 4, f"{missing} WC fixtures have teams without ELO"


@requires_db
class TestInternationalMatches:
    def test_history_present(self, db):
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM international_matches WHERE home_goals IS NOT NULL")
        assert cur.fetchone()[0] >= 3000

    def test_has_world_cup_and_qualifiers(self, db):
        cur = db.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT tournament_name) FROM international_matches
            WHERE tournament_name ILIKE '%world cup%'
        """)
        assert cur.fetchone()[0] >= 1
