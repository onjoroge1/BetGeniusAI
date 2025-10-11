#!/usr/bin/env python3
"""
V2 Daily Health Check
Run this script daily to verify V2 model is making realistic predictions

Usage:
    python scripts/v2_health_check.py [--days 1]
"""

import os
import sys
import psycopg2
from datetime import datetime
import argparse

DATABASE_URL = os.environ.get('DATABASE_URL')

def check_v2_confidence(conn, days=1):
    """Check if V2 average confidence is realistic (<80%)"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                ROUND(AVG(GREATEST(p_home, p_draw, p_away))::numeric, 4) AS avg_top_prob,
                COUNT(*) AS n_predictions
            FROM model_inference_logs
            WHERE model_version = 'v2' 
                AND scored_at > NOW() - INTERVAL '%s days'
        """, (days,))
        
        row = cur.fetchone()
        if not row or row[1] == 0:
            return None, "No V2 predictions in last {} days".format(days)
        
        avg_conf, n = row
        status = "✅ OK" if avg_conf < 0.80 else "⚠️ TOO HIGH"
        return avg_conf, f"{status} ({n} predictions)"

def check_v2_divergence(conn, days=1):
    """Check if V2 L1 divergence from market is in target range (0.10-0.30)"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                ROUND(AVG(
                    ABS(mil.p_home - mf.prob_home) +
                    ABS(mil.p_draw - mf.prob_draw) +
                    ABS(mil.p_away - mf.prob_away)
                )::numeric, 4) AS mean_L1_diff,
                COUNT(*) AS n_predictions
            FROM model_inference_logs mil
            JOIN match_features mf ON mil.match_id = mf.match_id
            WHERE mil.model_version = 'v2'
                AND mil.scored_at > NOW() - INTERVAL '%s days'
        """, (days,))
        
        row = cur.fetchone()
        if not row or row[1] == 0:
            return None, "No V2 predictions with features"
        
        l1, n = row
        if l1 < 0.10:
            status = "⚠️ TOO CONSERVATIVE"
        elif l1 > 0.30:
            status = "⚠️ TOO AGGRESSIVE"
        else:
            status = "✅ IN RANGE"
        
        return l1, f"{status} ({n} predictions)"

def check_guardrails(conn, days=1):
    """Check how often guardrails are triggered"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 
                COUNT(*) FILTER (WHERE reason_code LIKE '%%KL_CAPPED%%') AS kl_capped,
                COUNT(*) FILTER (WHERE reason_code LIKE '%%MAX_PROB_CAPPED%%') AS max_prob_capped,
                COUNT(*) FILTER (WHERE reason_code LIKE '%%DELTA_CLIPPED%%') AS delta_clipped,
                COUNT(*) AS total
            FROM model_inference_logs
            WHERE model_version = 'v2'
                AND scored_at > NOW() - INTERVAL '%s days'
        """, (days,))
        
        row = cur.fetchone()
        if not row or row[3] == 0:
            return None, "No V2 predictions"
        
        kl, maxp, delta, total = row
        kl_pct = 100.0 * kl / total
        maxp_pct = 100.0 * maxp / total
        delta_pct = 100.0 * delta / total
        
        return {
            'kl_cap_pct': kl_pct,
            'max_prob_pct': maxp_pct,
            'delta_clip_pct': delta_pct,
            'total': total
        }, f"KL: {kl_pct:.1f}%, MaxP: {maxp_pct:.1f}%, Delta: {delta_pct:.1f}%"

def check_shadow_enabled(conn):
    """Check if shadow mode is enabled"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT config_value 
            FROM model_config 
            WHERE config_key = 'ENABLE_SHADOW_V2'
        """)
        row = cur.fetchone()
        return row[0] if row else None

def check_model_manifest():
    """Check if V2 manifest exists and is recent"""
    import json
    from pathlib import Path
    
    manifest_path = Path('models/v2/manifest.json')
    if not manifest_path.exists():
        return None, "❌ No manifest found"
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    version = manifest.get('version', 'unknown')
    trained_at = manifest.get('trained_at', 'unknown')
    architecture = manifest.get('architecture', 'unknown')
    
    return manifest, f"✅ {version} ({architecture}) trained {trained_at[:10]}"

def main():
    parser = argparse.ArgumentParser(description='V2 Daily Health Check')
    parser.add_argument('--days', type=int, default=1, help='Number of days to check (default: 1)')
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"V2 HEALTH CHECK - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Check manifest
    manifest, msg = check_model_manifest()
    print(f"\n📦 Model Manifest: {msg}")
    if manifest:
        hyperparams = manifest.get('hyperparameters', {})
        print(f"   Hyperparams: tau={hyperparams.get('delta_tau')}, "
              f"alpha={hyperparams.get('blend_alpha')}, "
              f"C={hyperparams.get('C')}")
    
    with psycopg2.connect(DATABASE_URL) as conn:
        # Check shadow mode
        shadow_enabled = check_shadow_enabled(conn)
        print(f"\n🔄 Shadow Mode: {'✅ ENABLED' if shadow_enabled == 'true' else '❌ DISABLED'}")
        
        if shadow_enabled != 'true':
            print("\n⚠️  WARNING: Shadow mode is disabled! V2 not running.")
            return
        
        # Check confidence
        conf, msg = check_v2_confidence(conn, args.days)
        print(f"\n📊 Avg Confidence (last {args.days}d): {conf or 'N/A'}")
        print(f"   {msg}")
        print(f"   Target: <0.80 (realistic)")
        
        # Check divergence
        l1, msg = check_v2_divergence(conn, args.days)
        print(f"\n📏 L1 Divergence (last {args.days}d): {l1 or 'N/A'}")
        print(f"   {msg}")
        print(f"   Target: 0.10-0.30 (meaningful adjustments)")
        
        # Check guardrails
        guards, msg = check_guardrails(conn, args.days)
        print(f"\n🛡️  Guardrails (last {args.days}d): {msg}")
        if guards:
            print(f"   Target: <30% activation rate")
        
        # Overall status
        print("\n" + "=" * 70)
        
        issues = []
        if conf and conf >= 0.80:
            issues.append("High confidence")
        if l1 and (l1 < 0.10 or l1 > 0.30):
            issues.append("L1 out of range")
        if guards and (guards['kl_cap_pct'] > 30 or guards['max_prob_pct'] > 30):
            issues.append("Guardrails triggering too often")
        
        if not issues:
            print("✅ V2 HEALTH: ALL CHECKS PASSED")
        else:
            print(f"⚠️  V2 HEALTH: ISSUES DETECTED - {', '.join(issues)}")
        
        print("=" * 70)
        
        # Return exit code
        sys.exit(1 if issues else 0)

if __name__ == '__main__':
    main()
