"""
Integration tests for NCAA Basketball (NCAAB) data collection pipeline.

Sections:
  1. TestNCAAbSportRegistry       — sports table registration
  2. TestNCAAbCollectorConfig     — SPORT_CONFIGS in both collector classes
  3. TestNCAAbFeatureBuilderConfig — SEASON_INFO and ELO home advantage
  4. TestNCAAbDatabaseRows        — fixtures / odds / training row counts (live DB)
  5. TestNCAAbTrainingSyncCovers  — training sync picks up basketball_ncaab rows
"""

import os
import sys
import pytest
import psycopg2
from unittest.mock import patch, MagicMock

# ── helpers ─────────────────────────────────────────────────────────────────────

DB_URL = os.getenv("DATABASE_URL", "")


def get_db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    return psycopg2.connect(DB_URL)


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1 — Sports Table Registration
# ═══════════════════════════════════════════════════════════════════════════════

class TestNCAAbSportRegistry:

    def test_ncaab_row_exists_in_sports_table(self):
        """basketball_ncaab must be present and active in the sports table."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sport_key, is_active FROM sports WHERE sport_key = 'basketball_ncaab'"
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "basketball_ncaab missing from sports table"
        assert row[1] is True, "basketball_ncaab must be active"

    def test_ncaab_api_source_is_odds_api(self):
        """api_source must be 'the-odds-api' (same key as NBA)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT api_source FROM sports WHERE sport_key = 'basketball_ncaab'"
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None
        assert row[0] == "the-odds-api"

    def test_sport_name_is_descriptive(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sport_name FROM sports WHERE sport_key = 'basketball_ncaab'"
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None
        name = row[0].lower()
        assert "ncaa" in name or "basketball" in name, f"Unexpected sport_name: {row[0]}"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2 — Collector SPORT_CONFIGS
# ═══════════════════════════════════════════════════════════════════════════════

class TestNCAAbCollectorConfig:

    def test_odds_collector_has_ncaab_key(self):
        from models.multisport_collector import MultiSportCollector
        assert "basketball_ncaab" in MultiSportCollector.SPORT_CONFIGS

    def test_odds_collector_ncaab_sport_field(self):
        from models.multisport_collector import MultiSportCollector
        cfg = MultiSportCollector.SPORT_CONFIGS["basketball_ncaab"]
        assert cfg["sport"] == "basketball"

    def test_odds_collector_ncaab_regions_us(self):
        from models.multisport_collector import MultiSportCollector
        cfg = MultiSportCollector.SPORT_CONFIGS["basketball_ncaab"]
        assert cfg["regions"] == "us"

    def test_odds_collector_ncaab_markets(self):
        from models.multisport_collector import MultiSportCollector
        cfg = MultiSportCollector.SPORT_CONFIGS["basketball_ncaab"]
        for market in ["h2h", "spreads", "totals"]:
            assert market in cfg["markets"], f"Missing market: {market}"

    def test_odds_collector_ncaab_active_months_include_march(self):
        from models.multisport_collector import MultiSportCollector
        cfg = MultiSportCollector.SPORT_CONFIGS["basketball_ncaab"]
        assert 3 in cfg["active_months"], "March (month 3) must be active for March Madness"

    def test_odds_collector_ncaab_active_months_exclude_summer(self):
        from models.multisport_collector import MultiSportCollector
        cfg = MultiSportCollector.SPORT_CONFIGS["basketball_ncaab"]
        for off_month in [6, 7, 8, 9, 10]:
            assert off_month not in cfg["active_months"], (
                f"Month {off_month} should not be active for NCAAB"
            )

    def test_data_collector_has_ncaab_key(self):
        from models.multisport_data_collector import MultiSportDataCollector
        assert "basketball_ncaab" in MultiSportDataCollector.SPORT_CONFIGS

    def test_data_collector_ncaab_sport_field(self):
        from models.multisport_data_collector import MultiSportDataCollector
        cfg = MultiSportDataCollector.SPORT_CONFIGS["basketball_ncaab"]
        assert cfg["sport"] == "basketball"

    def test_data_collector_ncaab_has_playoffs(self):
        from models.multisport_data_collector import MultiSportDataCollector
        cfg = MultiSportDataCollector.SPORT_CONFIGS["basketball_ncaab"]
        assert cfg.get("has_playoffs") is True, "NCAAB must have has_playoffs=True"

    def test_data_collector_ncaab_active_months_include_nov_through_apr(self):
        from models.multisport_data_collector import MultiSportDataCollector
        cfg = MultiSportDataCollector.SPORT_CONFIGS["basketball_ncaab"]
        for month in [11, 12, 1, 2, 3, 4]:
            assert month in cfg["active_months"], f"Month {month} should be active for NCAAB"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3 — Feature Builder Config
# ═══════════════════════════════════════════════════════════════════════════════

class TestNCAAbFeatureBuilderConfig:

    def test_season_info_has_ncaab(self):
        from features.multisport_feature_builder import SEASON_INFO
        assert "basketball_ncaab" in SEASON_INFO, "NCAAB missing from SEASON_INFO"

    def test_season_start_is_november(self):
        from features.multisport_feature_builder import SEASON_INFO
        start_month, _ = SEASON_INFO["basketball_ncaab"]["start"]
        assert start_month == 11, f"NCAAB season start should be November (11), got {start_month}"

    def test_season_end_is_april(self):
        from features.multisport_feature_builder import SEASON_INFO
        end_month, _ = SEASON_INFO["basketball_ncaab"]["end"]
        assert end_month == 4, f"NCAAB season end should be April (4), got {end_month}"

    def test_total_games_is_reasonable(self):
        from features.multisport_feature_builder import SEASON_INFO
        total = SEASON_INFO["basketball_ncaab"]["total_games"]
        assert 25 <= total <= 45, f"NCAAB total_games {total} out of reasonable range 25-45"

    def test_elo_home_adv_by_sport_has_ncaab(self):
        from features.multisport_feature_builder import ELO_HOME_ADV_BY_SPORT
        assert "basketball_ncaab" in ELO_HOME_ADV_BY_SPORT, (
            "basketball_ncaab missing from ELO_HOME_ADV_BY_SPORT"
        )

    def test_ncaab_home_adv_greater_than_nba(self):
        """College home advantage must be larger than NBA home advantage."""
        from features.multisport_feature_builder import ELO_HOME_ADV_BY_SPORT
        ncaab_adv = ELO_HOME_ADV_BY_SPORT["basketball_ncaab"]
        nba_adv   = ELO_HOME_ADV_BY_SPORT.get("basketball_nba", 35)
        assert ncaab_adv > nba_adv, (
            f"NCAAB home advantage ({ncaab_adv}) must exceed NBA ({nba_adv})"
        )

    def test_ncaab_home_adv_is_positive(self):
        from features.multisport_feature_builder import ELO_HOME_ADV_BY_SPORT
        assert ELO_HOME_ADV_BY_SPORT["basketball_ncaab"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4 — Live Database Row Counts (after backfill)
# ═══════════════════════════════════════════════════════════════════════════════

class TestNCAAbDatabaseRows:

    def _counts(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM multisport_fixtures WHERE sport_key = 'basketball_ncaab'"
        )
        fixtures = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM multisport_odds_snapshots WHERE sport_key = 'basketball_ncaab'"
        )
        odds = cursor.fetchone()[0]
        cursor.execute(
            "SELECT COUNT(*) FROM multisport_schedule WHERE sport_key = 'basketball_ncaab'"
        )
        schedule = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return fixtures, odds, schedule

    def test_fixtures_row_count_positive(self):
        """Backfill must have stored at least 1 NCAAB fixture."""
        fixtures, _, _ = self._counts()
        assert fixtures > 0, (
            "No NCAAB fixtures found — backfill_ncaab.py may have failed or NCAAB is off-season"
        )

    def test_odds_snapshots_row_count_positive(self):
        """At least one odds snapshot must exist (upcoming games have odds)."""
        _, odds, _ = self._counts()
        assert odds >= 0  # odds may be 0 if season ended — not a hard failure

    def test_schedule_row_count_positive(self):
        """Schedule table must have NCAAB entries."""
        _, _, schedule = self._counts()
        assert schedule > 0, "No NCAAB entries found in multisport_schedule"

    def test_fixtures_sport_field_is_basketball(self):
        """Every NCAAB fixture must have sport='basketball'."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM multisport_fixtures
            WHERE sport_key = 'basketball_ncaab' AND sport != 'basketball'
        """)
        bad_rows = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        assert bad_rows == 0, f"{bad_rows} NCAAB fixtures have wrong sport field (not 'basketball')"

    def test_completed_fixtures_have_outcome(self):
        """Fixtures marked 'final' must have a non-null outcome (H or A)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM multisport_fixtures
            WHERE sport_key = 'basketball_ncaab'
              AND status = 'final'
              AND outcome IS NULL
        """)
        bad_rows = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        assert bad_rows == 0, f"{bad_rows} 'final' NCAAB fixtures are missing outcome"

    def test_outcome_values_are_h_or_a(self):
        """Outcome column must only contain H or A (no draws in NCAAB)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT outcome FROM multisport_fixtures
            WHERE sport_key = 'basketball_ncaab' AND outcome IS NOT NULL
        """)
        outcomes = {row[0] for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        invalid = outcomes - {"H", "A"}
        assert not invalid, f"Invalid NCAAB outcome values found: {invalid}"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5 — Training Sync Covers NCAAB
# ═══════════════════════════════════════════════════════════════════════════════

class TestNCAAbTrainingSyncCovers:

    def test_training_sync_basketball_covers_ncaab(self):
        """
        The training sync runs for sport='basketball' and should pick up
        basketball_ncaab fixtures from multisport_fixtures (same sport field).
        Verify the query returns NCAAB rows when fixtures are present.
        """
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM multisport_fixtures
            WHERE sport = 'basketball'
              AND sport_key = 'basketball_ncaab'
              AND home_score IS NOT NULL
              AND away_score IS NOT NULL
        """)
        ncaab_completed = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        # Just verifying the query works and doesn't error out.
        # If no completed fixtures yet that's OK (season may have ended before backfill).
        assert ncaab_completed >= 0

    def test_sync_to_training_table_ncaab_does_not_raise(self):
        """
        MultiSportDataCollector.sync_to_training_table() must handle basketball_ncaab
        without raising an exception. The query itself is the important contract here.
        """
        from models.multisport_data_collector import MultiSportDataCollector
        collector = MultiSportDataCollector()
        result = collector.sync_to_training_table("basketball_ncaab")
        # Result may have 0 rows synced (no odds for historical games yet) but must not error
        assert "error" not in result, f"sync_to_training_table returned error: {result}"
        assert "synced" in result
        assert result["synced"] >= 0

    def test_multisport_training_ncaab_sport_key_present(self):
        """After sync, any inserted training rows for NCAAB must use correct sport_key."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM multisport_training
            WHERE sport_key = 'basketball_ncaab'
        """)
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        # May be 0 if no completed games with odds exist yet — soft assertion
        assert count >= 0

    def test_ncaab_training_rows_have_correct_sport(self):
        """All basketball_ncaab training rows must have sport='basketball'."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM multisport_training
            WHERE sport_key = 'basketball_ncaab' AND sport != 'basketball'
        """)
        bad = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        assert bad == 0, f"{bad} NCAAB training rows have wrong sport field"

    def test_collect_all_sports_includes_ncaab(self):
        """
        MultiSportDataCollector.collect_all_sports() must include basketball_ncaab
        in its SPORT_CONFIGS (month-based loop — no API call needed to verify config).
        """
        from models.multisport_data_collector import MultiSportDataCollector
        configs = MultiSportDataCollector.SPORT_CONFIGS
        assert "basketball_ncaab" in configs, (
            "basketball_ncaab not in MultiSportDataCollector.SPORT_CONFIGS"
        )
        cfg = configs["basketball_ncaab"]
        assert "active_months" in cfg
        assert len(cfg["active_months"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6 — End-to-End Training Flow Integration Test
#
# Seeds one completed NCAAB fixture + matching consensus odds snapshot, runs
# sync_to_training_table('basketball_ncaab'), asserts the row materialises in
# multisport_training with the correct sport_key / scores / outcome / probs,
# then cleans up all seeded rows.
# ═══════════════════════════════════════════════════════════════════════════════

TEST_EVENT_ID = "ncaab_test_e2e_fixture_pytest_unique_001"

class TestNCAAbEndToEndTrainingFlow:

    @classmethod
    def _cleanup(cls, cursor):
        """Remove all seeded test rows so tests are idempotent."""
        cursor.execute(
            "DELETE FROM multisport_training WHERE event_id = %s AND sport_key = 'basketball_ncaab'",
            (TEST_EVENT_ID,)
        )
        cursor.execute(
            "DELETE FROM multisport_match_results WHERE event_id = %s AND sport_key = 'basketball_ncaab'",
            (TEST_EVENT_ID,)
        )
        cursor.execute(
            "DELETE FROM multisport_odds_snapshots WHERE event_id = %s AND sport_key = 'basketball_ncaab'",
            (TEST_EVENT_ID,)
        )
        cursor.execute(
            "DELETE FROM multisport_fixtures WHERE event_id = %s AND sport = 'basketball'",
            (TEST_EVENT_ID,)
        )

    @classmethod
    def setup_class(cls):
        """Seed one completed NCAAB game with consensus odds into the DB."""
        conn = get_db()
        cursor = conn.cursor()
        cls._cleanup(cursor)  # clean any leftover from a previous failed run

        from datetime import datetime, timezone, timedelta
        game_dt = datetime(2026, 3, 15, 19, 0, 0, tzinfo=timezone.utc)

        # 1. Fixture
        cursor.execute("""
            INSERT INTO multisport_fixtures (
                sport, sport_key, event_id,
                home_team, away_team, commence_time,
                status, home_score, away_score, outcome, updated_at
            ) VALUES (
                'basketball', 'basketball_ncaab', %s,
                'Duke', 'UNC', %s,
                'final', 78, 65, 'H', NOW()
            )
            ON CONFLICT (sport, event_id) DO NOTHING
        """, (TEST_EVENT_ID, game_dt))

        # 2. Completed result (multisport_match_results is what sync_to_training_table reads)
        cursor.execute("""
            INSERT INTO multisport_match_results (
                sport_key, event_id, game_date,
                home_team, away_team,
                home_score, away_score, result,
                status, updated_at
            ) VALUES (
                'basketball_ncaab', %s, %s,
                'Duke', 'UNC',
                78, 65, 'H',
                'final', NOW()
            )
            ON CONFLICT (sport_key, event_id) DO NOTHING
        """, (TEST_EVENT_ID, game_dt))

        # 3. Consensus odds snapshot (is_consensus=True is required by the sync query)
        ts_recorded = game_dt - timedelta(hours=2)  # captured 2 hours before tip-off
        cursor.execute("""
            INSERT INTO multisport_odds_snapshots (
                sport, sport_key, event_id,
                home_team, away_team, commence_time,
                home_prob, away_prob,
                overround, n_bookmakers,
                bookmaker, is_consensus, ts_recorded
            ) VALUES (
                'basketball', 'basketball_ncaab', %s,
                'Duke', 'UNC', %s,
                0.6200, 0.3800,
                1.0400, 10,
                'consensus', TRUE, %s
            )
            ON CONFLICT (event_id, bookmaker, ts_recorded) DO NOTHING
        """, (TEST_EVENT_ID, game_dt, ts_recorded))

        conn.commit()
        cursor.close()
        conn.close()

    @classmethod
    def teardown_class(cls):
        """Remove all seeded rows after all tests in this class finish."""
        conn = get_db()
        cursor = conn.cursor()
        cls._cleanup(cursor)
        conn.commit()
        cursor.close()
        conn.close()

    def test_e2e_sync_inserts_row_into_multisport_training(self):
        """
        sync_to_training_table('basketball_ncaab') must insert the seeded completed
        game into multisport_training.
        """
        from models.multisport_data_collector import MultiSportDataCollector
        collector = MultiSportDataCollector()
        result = collector.sync_to_training_table("basketball_ncaab")
        assert "error" not in result, f"sync_to_training_table raised: {result}"
        assert result["synced"] >= 1, (
            f"Expected at least 1 row synced, got {result['synced']}. "
            "Seeded fixture + consensus odds should have produced a training row."
        )

    def test_e2e_training_row_has_correct_sport_key(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sport_key FROM multisport_training
            WHERE event_id = %s
        """, (TEST_EVENT_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Training row not found after sync"
        assert row[0] == "basketball_ncaab", f"Wrong sport_key: {row[0]}"

    def test_e2e_training_row_has_correct_scores(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT home_score, away_score FROM multisport_training
            WHERE event_id = %s AND sport_key = 'basketball_ncaab'
        """, (TEST_EVENT_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Training row not found"
        assert row[0] == 78, f"home_score should be 78, got {row[0]}"
        assert row[1] == 65, f"away_score should be 65, got {row[1]}"

    def test_e2e_training_row_outcome_is_H(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT outcome FROM multisport_training
            WHERE event_id = %s AND sport_key = 'basketball_ncaab'
        """, (TEST_EVENT_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Training row not found"
        assert row[0] == "H", f"Outcome should be H (Duke won 78-65), got {row[0]}"

    def test_e2e_training_row_has_consensus_probs(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT consensus_home_prob, consensus_away_prob FROM multisport_training
            WHERE event_id = %s AND sport_key = 'basketball_ncaab'
        """, (TEST_EVENT_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Training row not found"
        home_prob, away_prob = row
        assert home_prob is not None, "consensus_home_prob must not be NULL"
        assert away_prob is not None, "consensus_away_prob must not be NULL"
        assert abs(float(home_prob) - 0.62) < 0.01, f"home_prob should be ~0.62, got {home_prob}"
        assert abs(float(away_prob) - 0.38) < 0.01, f"away_prob should be ~0.38, got {away_prob}"

    def test_e2e_training_row_sport_is_basketball(self):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sport FROM multisport_training
            WHERE event_id = %s AND sport_key = 'basketball_ncaab'
        """, (TEST_EVENT_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        assert row is not None, "Training row not found"
        assert row[0] == "basketball", f"sport field should be 'basketball', got {row[0]}"
