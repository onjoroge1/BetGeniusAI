"""
Comprehensive QA/QC Test Suite for Market API Cascade Flow
Tests: V1 Consensus -> V3 Sharp -> V0 Form prediction cascade
"""

import requests
import json
import time
import sys
from datetime import datetime, timezone

BASE_URL = "http://localhost:8000"
AUTH = {"Authorization": "Bearer betgenius_secure_key_2024"}
TIMEOUT = 90
FULL_TIMEOUT = 120

PASS = 0
FAIL = 0
WARN = 0
results = []

def record(test_name, passed, detail="", warning=False):
    global PASS, FAIL, WARN
    if warning:
        WARN += 1
        status = "WARN"
    elif passed:
        PASS += 1
        status = "PASS"
    else:
        FAIL += 1
        status = "FAIL"
    results.append((status, test_name, detail))
    print(f"  [{status}] {test_name}" + (f" -- {detail}" if detail else ""))


def test_market_lite_basic():
    print("\n" + "="*70)
    print("TEST GROUP 1: /market?mode=lite Basic Response")
    print("="*70)

    r = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)
    record("HTTP 200 response", r.status_code == 200, f"got {r.status_code}")

    data = r.json()
    record("Response has 'matches' key", "matches" in data)
    record("Response has 'total_count' key", "total_count" in data)
    record("Response has 'mode' key", "mode" in data)
    record("Mode is 'lite'", data.get("mode") == "lite", f"got '{data.get('mode')}'")

    matches = data.get("matches", [])
    total = data.get("total_count", 0)
    record("total_count matches len(matches)", total == len(matches), f"total={total}, len={len(matches)}")
    record("At least 1 match returned", total > 0, f"got {total}")

    return data


def test_cascade_sources(data):
    print("\n" + "="*70)
    print("TEST GROUP 2: Cascade Source Distribution")
    print("="*70)

    matches = data.get("matches", [])
    sources = {}
    qualities = {}
    no_prediction = 0

    for m in matches:
        pred = m.get("prediction", {})
        if not pred:
            no_prediction += 1
            continue
        src = pred.get("source", "unknown")
        qual = pred.get("data_quality", "unknown")
        sources[src] = sources.get(src, 0) + 1
        qualities[qual] = qualities.get(qual, 0) + 1

    print(f"  Source breakdown: {json.dumps(sources, indent=2)}")
    print(f"  Quality breakdown: {json.dumps(qualities, indent=2)}")

    record("Zero matches without predictions", no_prediction == 0, f"{no_prediction} without prediction")

    has_consensus = "v1_consensus" in sources
    has_v0 = "v0_form" in sources
    record("V1 consensus predictions present", has_consensus, f"{sources.get('v1_consensus', 0)} matches")
    record("V0 form predictions present", has_v0, f"{sources.get('v0_form', 0)} matches")

    valid_sources = {"v1_consensus", "v3_fallback", "v3_sharp_fallback", "v0_form"}
    all_valid = all(s in valid_sources for s in sources.keys())
    record("All sources are valid cascade types", all_valid, f"sources: {list(sources.keys())}")

    valid_qualities = {"full", "limited", "form_only"}
    all_valid_q = all(q in valid_qualities for q in qualities.keys())
    record("All data_quality labels are valid", all_valid_q, f"qualities: {list(qualities.keys())}")

    if has_consensus:
        record("'full' quality present for consensus", "full" in qualities)
    if has_v0:
        record("'form_only' quality present for V0", "form_only" in qualities)

    return sources


def test_prediction_integrity_lite(data):
    print("\n" + "="*70)
    print("TEST GROUP 3: Lite Mode Prediction Data Integrity")
    print("="*70)

    matches = data.get("matches", [])
    missing_fields = []
    confidence_issues = []
    pick_issues = []

    for m in matches:
        mid = m.get("match_id")
        pred = m.get("prediction", {})
        if not pred:
            missing_fields.append(f"{mid}: no prediction")
            continue

        if "pick" not in pred:
            missing_fields.append(f"{mid}: missing 'pick'")
        else:
            pick = pred["pick"]
            if pick not in ("home", "draw", "away"):
                pick_issues.append(f"{mid}: pick='{pick}'")

        conf = pred.get("confidence")
        if conf is None:
            missing_fields.append(f"{mid}: missing 'confidence'")
        elif conf < 0 or conf > 1:
            confidence_issues.append(f"{mid}: confidence={conf}")

        if "source" not in pred:
            missing_fields.append(f"{mid}: missing 'source'")
        if "data_quality" not in pred:
            missing_fields.append(f"{mid}: missing 'data_quality'")

    record("All predictions have pick/confidence/source/data_quality",
           len(missing_fields) == 0,
           f"{len(missing_fields)} issues: {missing_fields[:3]}" if missing_fields else f"all {len(matches)} valid")
    record("All picks are home/draw/away", len(pick_issues) == 0,
           f"{len(pick_issues)} issues: {pick_issues[:3]}" if pick_issues else "")
    record("All confidence values in [0, 1]", len(confidence_issues) == 0,
           f"{len(confidence_issues)} issues" if confidence_issues else "")


def test_odds_cascade_correlation(data):
    print("\n" + "="*70)
    print("TEST GROUP 4: Odds <-> Cascade Source Correlation")
    print("="*70)

    matches = data.get("matches", [])
    odds_with_v0 = []
    no_odds_with_consensus = []
    correct_mapping = 0

    for m in matches:
        mid = m.get("match_id")
        books = m.get("bookmakers", [])
        pred = m.get("prediction", {})
        source = pred.get("source", "")

        has_odds = len(books) > 0

        if has_odds and source == "v0_form":
            odds_with_v0.append(mid)
        elif not has_odds and source == "v1_consensus":
            no_odds_with_consensus.append(mid)
        else:
            correct_mapping += 1

    record("Matches WITH odds don't use V0 form", len(odds_with_v0) == 0,
           f"{len(odds_with_v0)} matches have odds but use V0: {odds_with_v0[:5]}" if odds_with_v0 else "")

    record("Matches WITHOUT odds don't use V1 consensus", len(no_odds_with_consensus) == 0,
           f"{len(no_odds_with_consensus)} matches lack odds but use consensus: {no_odds_with_consensus[:5]}" if no_odds_with_consensus else "")

    total = len(matches)
    pct = (correct_mapping / total * 100) if total else 0
    record(f"Cascade mapping correctness", pct >= 95, f"{correct_mapping}/{total} ({pct:.0f}%)")


def test_match_structure(data):
    print("\n" + "="*70)
    print("TEST GROUP 5: Match Response Structure")
    print("="*70)

    matches = data.get("matches", [])
    required_keys = ["match_id", "home", "away", "league", "status"]
    kickoff_keys = ["kickoff_at", "kickoff_utc"]
    team_keys = ["name"]
    issues = []

    for m in matches:
        mid = m.get("match_id", "?")
        for k in required_keys:
            if k not in m:
                issues.append(f"{mid}: missing '{k}'")

        has_kickoff = any(k in m for k in kickoff_keys)
        if not has_kickoff:
            issues.append(f"{mid}: missing kickoff time field")

        for team_key in ["home", "away"]:
            team = m.get(team_key, {})
            if isinstance(team, dict):
                for tk in team_keys:
                    if tk not in team:
                        issues.append(f"{mid}: {team_key} missing '{tk}'")
            else:
                issues.append(f"{mid}: {team_key} is not a dict")

    record("All matches have required fields", len(issues) == 0,
           f"{len(issues)} issues: {issues[:5]}" if issues else f"all {len(matches)} valid")


def test_v0_form_quality(data):
    print("\n" + "="*70)
    print("TEST GROUP 6: V0 Form Prediction Quality")
    print("="*70)

    matches = data.get("matches", [])
    v0_matches = [m for m in matches if m.get("prediction", {}).get("source") == "v0_form"]

    if not v0_matches:
        record("V0 matches exist for quality check", False, "no V0 predictions found")
        return

    record(f"V0 matches found for quality check", True, f"{len(v0_matches)} matches")

    conf_sane = 0
    for m in v0_matches:
        pred = m.get("prediction", {})
        conf = pred.get("confidence", 0)
        if 0.30 < conf < 0.95:
            conf_sane += 1

    record("V0 confidence values are in reasonable range (0.30-0.95)",
           conf_sane == len(v0_matches),
           f"{conf_sane}/{len(v0_matches)} reasonable")

    confidences = [m["prediction"].get("confidence", 0) for m in v0_matches]
    all_different = len(set(confidences)) > 1 if len(v0_matches) > 1 else True
    record("V0 predictions are not all identical", all_different,
           f"{len(set(confidences))} unique confidence values" if all_different else "IDENTICAL predictions -- possible bug")

    picks = [m["prediction"].get("pick") for m in v0_matches]
    pick_dist = {p: picks.count(p) for p in set(picks)}
    has_variety = len(pick_dist) >= 2 if len(v0_matches) >= 3 else True
    record("V0 picks have variety (not all same outcome)", has_variety,
           f"distribution: {pick_dist}")

    no_books = all(len(m.get("bookmakers", [])) == 0 for m in v0_matches)
    record("V0 matches correctly have no bookmaker data", no_books)

    quality_correct = all(m.get("prediction", {}).get("data_quality") == "form_only" for m in v0_matches)
    record("V0 matches all labeled as 'form_only' quality", quality_correct)


def test_consensus_quality(data):
    print("\n" + "="*70)
    print("TEST GROUP 7: V1 Consensus Prediction Quality")
    print("="*70)

    matches = data.get("matches", [])
    v1_matches = [m for m in matches if m.get("prediction", {}).get("source") == "v1_consensus"]

    if not v1_matches:
        record("V1 matches exist for quality check", False, "no V1 predictions found")
        return

    record(f"V1 matches found for quality check", True, f"{len(v1_matches)} matches")

    all_have_books = sum(1 for m in v1_matches if len(m.get("bookmakers", [])) > 0)
    record("All V1 consensus matches have bookmaker data",
           all_have_books == len(v1_matches),
           f"{all_have_books}/{len(v1_matches)}")

    confidences = [m["prediction"].get("confidence", 0) for m in v1_matches]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0
    min_conf = min(confidences) if confidences else 0
    max_conf = max(confidences) if confidences else 0
    record("Confidence range is reasonable",
           0.3 <= min_conf and max_conf <= 0.95,
           f"min={min_conf:.3f}, max={max_conf:.3f}, avg={avg_conf:.3f}")

    quality_correct = all(m.get("prediction", {}).get("data_quality") == "full" for m in v1_matches)
    record("V1 matches all labeled as 'full' quality", quality_correct)


def test_full_mode():
    """Full mode returns structured data under 'models' key, not 'prediction'"""
    print("\n" + "="*70)
    print("TEST GROUP 8: /market Full Mode (Single Match)")
    print("="*70)

    lite_r = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)
    lite_data = lite_r.json()
    matches = lite_data.get("matches", [])

    v1_match = next((m for m in matches if m.get("prediction", {}).get("source") == "v1_consensus"), None)
    v0_match = next((m for m in matches if m.get("prediction", {}).get("source") == "v0_form"), None)

    if v1_match:
        mid = v1_match["match_id"]
        r = requests.get(f"{BASE_URL}/market?match_id={mid}&mode=full", headers=AUTH, timeout=FULL_TIMEOUT)
        record(f"Full mode returns 200 for V1 match {mid}", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            fdata = r.json()
            fmatches = fdata.get("matches", [])
            if fmatches:
                fm = fmatches[0]

                models = fm.get("models", {})
                v1_data = models.get("v1_consensus", {})
                odds = fm.get("odds", {})
                books = odds.get("books", [])

                record("Full mode V1 match has models.v1_consensus", v1_data is not None and len(v1_data) > 0,
                       f"keys: {list(v1_data.keys()) if v1_data else 'None'}")
                record("Full mode V1 match has odds.books", len(books) > 0, f"{len(books)} bookmakers")

                if v1_data:
                    source = v1_data.get("source", "")
                    record("Full mode V1 source is v1_consensus",
                           source == "v1_consensus",
                           f"got '{source}'")
                    probs = v1_data.get("probs", {})
                    if probs:
                        total_p = sum(probs.values())
                        record("Full mode V1 probs sum to ~1.0",
                               abs(total_p - 1.0) < 0.05,
                               f"sum={total_p:.4f}")
                        record("Full mode V1 probs have home/draw/away keys",
                               all(k in probs for k in ("home", "draw", "away")),
                               f"keys: {list(probs.keys())}")
            else:
                record("Full mode returns match data", False, "empty matches array")
    else:
        record("V1 match available for full-mode test", False, warning=True)

    if v0_match:
        mid = v0_match["match_id"]
        r = requests.get(f"{BASE_URL}/market?match_id={mid}&mode=full", headers=AUTH, timeout=FULL_TIMEOUT)
        record(f"Full mode returns 200 for V0 match {mid}", r.status_code == 200, f"got {r.status_code}")
        if r.status_code == 200:
            fdata = r.json()
            fmatches = fdata.get("matches", [])
            if fmatches:
                fm = fmatches[0]
                models = fm.get("models", {})
                v1_data = models.get("v1_consensus", {})

                record("Full mode V0 match has models.v1_consensus", v1_data is not None and len(v1_data) > 0,
                       f"keys: {list(v1_data.keys()) if v1_data else 'None'}")

                if v1_data:
                    source = v1_data.get("source", "")
                    record("Full mode V0 match uses form/cascade source",
                           source in ("v0_form", "v3_sharp_fallback"),
                           f"got '{source}'")
                    probs = v1_data.get("probs", {})
                    if probs:
                        record("Full mode V0 match has normalized keys",
                               "home" in probs and "draw" in probs and "away" in probs,
                               f"keys: {list(probs.keys())}")
                        quality = v1_data.get("data_quality", "")
                        record("Full mode V0 quality is form_only", quality == "form_only",
                               f"got '{quality}'")
            else:
                record("Full mode returns V0 match data", False, "empty matches array")
    else:
        record("V0 match available for full-mode test", False, warning=True)


def test_league_filter():
    print("\n" + "="*70)
    print("TEST GROUP 9: League Filtering with Cascade")
    print("="*70)

    r = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)
    data = r.json()
    matches = data.get("matches", [])

    leagues = set()
    for m in matches:
        lid = m.get("league", {}).get("id") if isinstance(m.get("league"), dict) else m.get("league_id")
        if lid:
            leagues.add(lid)

    if not leagues:
        record("League IDs available for filtering", False, "no league IDs found")
        return

    test_league = list(leagues)[0]
    r2 = requests.get(f"{BASE_URL}/market?status=upcoming&league_id={test_league}&mode=lite", headers=AUTH, timeout=TIMEOUT)
    record(f"League filter returns 200", r2.status_code == 200, f"league_id={test_league}")

    if r2.status_code == 200:
        fdata = r2.json()
        fmatches = fdata.get("matches", [])
        record(f"League filter returns matches", len(fmatches) > 0, f"{len(fmatches)} matches")

        all_correct_league = True
        for m in fmatches:
            lid = m.get("league", {}).get("id") if isinstance(m.get("league"), dict) else m.get("league_id")
            if lid != test_league:
                all_correct_league = False
                break
        record("All filtered matches belong to correct league", all_correct_league)

        for m in fmatches:
            pred = m.get("prediction", {})
            if not pred or not pred.get("source"):
                record("Filtered matches have predictions", False, f"match {m.get('match_id')} missing prediction")
                return
        record("All filtered matches have cascade predictions", True)


def test_error_handling():
    print("\n" + "="*70)
    print("TEST GROUP 10: Error Handling & Edge Cases")
    print("="*70)

    r = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", timeout=TIMEOUT)
    record("Unauthenticated request handled", r.status_code in (401, 403, 200),
           f"status={r.status_code}")

    r2 = requests.get(f"{BASE_URL}/market?match_id=999999999&mode=lite", headers=AUTH, timeout=TIMEOUT)
    record("Non-existent match handled gracefully", r2.status_code in (200, 404),
           f"status={r2.status_code}")
    if r2.status_code == 200:
        d = r2.json()
        record("Non-existent match returns empty/zero", d.get("total_count", -1) == 0,
               f"total_count={d.get('total_count')}")

    r3 = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite&limit=3", headers=AUTH, timeout=TIMEOUT)
    record("Limit parameter works", r3.status_code == 200)
    if r3.status_code == 200:
        d = r3.json()
        record("Limit caps results", len(d.get("matches", [])) <= 3,
               f"got {len(d.get('matches', []))} matches")


def test_response_time():
    print("\n" + "="*70)
    print("TEST GROUP 11: Performance / Response Time")
    print("="*70)

    requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)

    start = time.time()
    r = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)
    lite_time = time.time() - start
    record(f"Lite mode responds under 15s", lite_time < 15, f"{lite_time:.2f}s")
    record(f"Lite mode responds under 5s (ideal)", lite_time < 5, f"{lite_time:.2f}s",
           warning=(lite_time >= 5))


def test_data_consistency():
    print("\n" + "="*70)
    print("TEST GROUP 12: Data Consistency Across Calls")
    print("="*70)

    r1 = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)
    r2 = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)

    d1 = r1.json()
    d2 = r2.json()

    record("Consistent total_count across calls",
           d1.get("total_count") == d2.get("total_count"),
           f"call1={d1.get('total_count')}, call2={d2.get('total_count')}")

    ids1 = sorted([m["match_id"] for m in d1.get("matches", [])])
    ids2 = sorted([m["match_id"] for m in d2.get("matches", [])])
    record("Same match IDs across calls", ids1 == ids2,
           f"call1={len(ids1)} ids, call2={len(ids2)} ids")

    sources1 = {m["match_id"]: m.get("prediction", {}).get("source") for m in d1.get("matches", [])}
    sources2 = {m["match_id"]: m.get("prediction", {}).get("source") for m in d2.get("matches", [])}
    mismatches = [mid for mid in sources1 if sources1.get(mid) != sources2.get(mid)]
    record("Consistent prediction sources across calls", len(mismatches) == 0,
           f"{len(mismatches)} mismatches" if mismatches else "")


def test_status_values():
    print("\n" + "="*70)
    print("TEST GROUP 13: Match Status Consistency")
    print("="*70)

    r = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite", headers=AUTH, timeout=TIMEOUT)
    data = r.json()
    matches = data.get("matches", [])

    statuses = set()
    for m in matches:
        statuses.add(m.get("status", "UNKNOWN"))

    record("Upcoming filter returns only UPCOMING status",
           statuses <= {"UPCOMING"},
           f"statuses found: {statuses}")

    r2 = requests.get(f"{BASE_URL}/market?status=all&mode=lite", headers=AUTH, timeout=TIMEOUT)
    if r2.status_code == 200:
        d2 = r2.json()
        all_count = d2.get("total_count", 0)
        upcoming_count = data.get("total_count", 0)
        record("'all' status returns >= 'upcoming' count",
               all_count >= upcoming_count,
               f"all={all_count}, upcoming={upcoming_count}")

        all_matches = d2.get("matches", [])
        all_have_pred = sum(1 for m in all_matches if m.get("prediction"))
        total_all = len(all_matches)
        pct = (all_have_pred / total_all * 100) if total_all else 0
        record("All-status matches have predictions (>90%)",
               pct >= 90,
               f"{all_have_pred}/{total_all} ({pct:.0f}%)")
    else:
        record("'all' status endpoint works", False, f"status={r2.status_code}")


if __name__ == "__main__":
    print("=" * 70)
    print("  BetGenius AI -- Market API Cascade QA/QC Test Suite")
    print(f"  Run at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)

    try:
        print("\n  Warming up server...")
        for attempt in range(3):
            try:
                wr = requests.get(f"{BASE_URL}/market?status=upcoming&mode=lite&limit=1", headers=AUTH, timeout=TIMEOUT)
                if wr.status_code == 200:
                    print(f"  Server ready (attempt {attempt+1})")
                    break
            except Exception:
                if attempt < 2:
                    print(f"  Server not ready, retrying in 10s... (attempt {attempt+1})")
                    time.sleep(10)
                else:
                    print("  Server did not respond after 3 attempts")
                    sys.exit(1)

        data = test_market_lite_basic()
        test_cascade_sources(data)
        test_prediction_integrity_lite(data)
        test_odds_cascade_correlation(data)
        test_match_structure(data)
        test_v0_form_quality(data)
        test_consensus_quality(data)
        test_full_mode()
        test_league_filter()
        test_error_handling()
        test_response_time()
        test_data_consistency()
        test_status_values()
    except requests.exceptions.ConnectionError:
        print("\n  FATAL: Cannot connect to server at localhost:8000")
        sys.exit(1)
    except Exception as e:
        print(f"\n  FATAL: Unexpected error: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  PASSED:   {PASS}")
    print(f"  WARNINGS: {WARN}")
    print(f"  FAILED:   {FAIL}")
    print(f"  TOTAL:    {PASS + WARN + FAIL}")
    print("=" * 70)

    if FAIL > 0:
        print("\n  FAILED TESTS:")
        for status, name, detail in results:
            if status == "FAIL":
                print(f"    {name}: {detail}")

    if WARN > 0:
        print("\n  WARNINGS:")
        for status, name, detail in results:
            if status == "WARN":
                print(f"    {name}: {detail}")

    print()
    sys.exit(1 if FAIL > 0 else 0)
