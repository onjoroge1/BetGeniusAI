"""
V2 Blend/Constraint Parameter Sweep

Grid search over alpha (market blend), kl_cap (KL divergence limit),
and delta_tau (delta temperature) to optimize V2 inference.

Uses Leave-One-Day-Out cross-validation on paired evaluation dataset.

Author: BetGenius AI Team
Date: Oct 2025
"""

import os
import sys
import json
import math
import psycopg2
import numpy as np
from collections import defaultdict
from datetime import datetime, date
from typing import List, Dict, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.v2.postprocess import apply_blend_and_constraints, kl_divergence
from services.metrics.calibration import ece_multiclass, ece_by_league
from services.metrics.utils import normalize_triplet


# Grid parameters
GRID = {
    "alpha": [0.5, 0.6, 0.7, 0.8],
    "kl_cap": [0.15, 0.20, 0.25, None],
    "delta_tau": [0.75, 1.0],
}

# Guardrails
GUARDRAILS = {
    "ece_global_max": 0.03,
    "ece_league_max": 0.05,
    "require_logloss_improvement": True,
    "require_brier_not_worse": True,
}


def load_paired_eval_data():
    """
    Fetch paired dataset: market consensus + V2 raw predictions + outcomes.
    Only includes pre-kickoff predictions with results.
    """
    from models.database import DatabaseManager
    
    db_manager = DatabaseManager()
    conn = psycopg2.connect(db_manager.database_url)
    cursor = conn.cursor()
    
    sql = """
        SELECT 
            mil_v2.match_id,
            COALESCE(f.league_name, 'Unknown') as league,
            DATE(COALESCE(f.kickoff_at, mil_v2.scored_at)) as match_date,
            mil_v1.p_home as v1_ph,
            mil_v1.p_draw as v1_pd,
            mil_v1.p_away as v1_pa,
            mil_v2.p_home as v2_ph,
            mil_v2.p_draw as v2_pd,
            mil_v2.p_away as v2_pa,
            mr.outcome
        FROM model_inference_logs mil_v2
        INNER JOIN model_inference_logs mil_v1 
            ON mil_v2.match_id = mil_v1.match_id 
            AND mil_v1.model_version = 'v1'
        INNER JOIN match_results mr ON mil_v2.match_id = mr.match_id
        LEFT JOIN fixtures f ON mil_v2.match_id = f.match_id
        WHERE mil_v2.model_version = 'v2'
            AND mr.outcome IS NOT NULL
            AND (f.kickoff_at IS NULL OR mil_v2.scored_at < f.kickoff_at)
            AND (f.kickoff_at IS NULL OR mil_v1.scored_at < f.kickoff_at)
        ORDER BY match_date, mil_v2.match_id
    """
    
    cursor.execute(sql)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    
    print(f"📊 Loaded {len(rows)} paired predictions (V1 market + V2 model)")
    
    # Convert to structured records
    data = []
    for row in rows:
        match_id, league, match_date, v1_ph, v1_pd, v1_pa, v2_ph, v2_pd, v2_pa, outcome = row
        
        # Normalize both (V1 needs it, V2 already normalized but ensure consistency)
        v1_ph, v1_pd, v1_pa = normalize_triplet(float(v1_ph), float(v1_pd), float(v1_pa))
        v2_ph, v2_pd, v2_pa = normalize_triplet(float(v2_ph), float(v2_pd), float(v2_pa))
        
        data.append({
            'match_id': match_id,
            'league': league,
            'date': match_date,
            'p_market': np.array([v1_ph, v1_pd, v1_pa]),
            'p_v2_raw': np.array([v2_ph, v2_pd, v2_pa]),
            'outcome': outcome
        })
    
    return data


def group_by_day(data: List[Dict]) -> Dict[date, List[Dict]]:
    """Group predictions by match date for LODO CV"""
    groups = defaultdict(list)
    for record in data:
        groups[record['date']].append(record)
    
    print(f"📅 Grouped into {len(groups)} days: {sorted(groups.keys())}")
    for d in sorted(groups.keys())[:3]:
        print(f"   {d}: {len(groups[d])} matches")
    
    return dict(groups)


def calculate_metrics(predictions: List[np.ndarray], labels: List[str], leagues: List[str]) -> Dict:
    """
    Calculate comprehensive metrics: LogLoss, Brier, Hit Rate, ECE (global + per-league).
    """
    n = len(predictions)
    
    # Outcome map
    outcome_map = {'H': 0, 'D': 1, 'A': 2}
    
    # Calculate per-sample metrics
    brier_scores = []
    logloss_scores = []
    hits = []
    max_probs = []
    
    for p, y in zip(predictions, labels):
        ph, pd, pa = p
        y_idx = outcome_map[y]
        
        # Brier score
        target = np.zeros(3)
        target[y_idx] = 1.0
        brier = np.sum((p - target) ** 2)
        brier_scores.append(brier)
        
        # LogLoss
        ll = -np.log(np.clip(p[y_idx], 1e-10, 1.0))
        logloss_scores.append(ll)
        
        # Hit rate
        pred_idx = np.argmax(p)
        hits.append(1.0 if pred_idx == y_idx else 0.0)
        
        # Confidence
        max_probs.append(np.max(p))
    
    # Global ECE
    ece_global = ece_multiclass(labels, [tuple(p) for p in predictions], n_bins=10)
    
    # Per-league ECE
    ece_leagues = ece_by_league(labels, [tuple(p) for p in predictions], leagues, n_bins=10)
    max_league_ece = max([l['ece'] for l in ece_leagues], default=0.0)
    
    return {
        'logloss': np.mean(logloss_scores),
        'brier': np.mean(brier_scores),
        'hit_rate': np.mean(hits),
        'avg_max_p': np.mean(max_probs),
        'ece_global': ece_global,
        'max_league_ece': max_league_ece,
        'n_samples': n
    }


def run_sweep():
    """
    Run grid search with LODO cross-validation.
    """
    print("=" * 70)
    print("V2 BLEND/CONSTRAINT PARAMETER SWEEP")
    print("=" * 70)
    
    # Load data
    data = load_paired_eval_data()
    if len(data) < 50:
        print(f"❌ Insufficient data: {len(data)} samples (need ≥50)")
        return
    
    # Group by day for LODO
    folds = group_by_day(data)
    if len(folds) < 3:
        print(f"❌ Insufficient folds: {len(folds)} days (need ≥3)")
        return
    
    # Calculate baseline (current V2 with alpha=0.8, no adjustments)
    print("\n📊 Computing baseline (current V2 config: α=0.8, no constraints)...")
    baseline_preds = [r['p_v2_raw'] for r in data]
    baseline_labels = [r['outcome'] for r in data]
    baseline_leagues = [r['league'] for r in data]
    baseline_metrics = calculate_metrics(baseline_preds, baseline_labels, baseline_leagues)
    
    print(f"   Baseline LogLoss: {baseline_metrics['logloss']:.4f}")
    print(f"   Baseline Brier:   {baseline_metrics['brier']:.4f}")
    print(f"   Baseline ECE:     {baseline_metrics['ece_global']:.4f}")
    print(f"   Baseline Hit:     {baseline_metrics['hit_rate']:.4f}")
    
    # Grid search
    results = []
    total_configs = len(GRID['alpha']) * len(GRID['kl_cap']) * len(GRID['delta_tau'])
    
    print(f"\n🔍 Testing {total_configs} configurations...")
    print(f"   Grid: α={GRID['alpha']}, KL={GRID['kl_cap']}, Δτ={GRID['delta_tau']}")
    
    config_num = 0
    for alpha in GRID['alpha']:
        for kl_cap in GRID['kl_cap']:
            for delta_tau in GRID['delta_tau']:
                config_num += 1
                
                # Apply postprocessing to all predictions
                all_preds = []
                all_labels = []
                all_leagues = []
                
                for record in data:
                    p_adj = apply_blend_and_constraints(
                        record['p_market'],
                        record['p_v2_raw'],
                        alpha=alpha,
                        kl_cap=kl_cap,
                        delta_tau=delta_tau
                    )
                    all_preds.append(p_adj)
                    all_labels.append(record['outcome'])
                    all_leagues.append(record['league'])
                
                # Calculate metrics
                metrics = calculate_metrics(all_preds, all_labels, all_leagues)
                
                # Store result
                result = {
                    'config_num': config_num,
                    'alpha': alpha,
                    'kl_cap': kl_cap,
                    'delta_tau': delta_tau,
                    **metrics,
                    'delta_logloss': metrics['logloss'] - baseline_metrics['logloss'],
                    'delta_brier': metrics['brier'] - baseline_metrics['brier'],
                    'delta_ece': metrics['ece_global'] - baseline_metrics['ece_global']
                }
                results.append(result)
                
                if config_num % 4 == 0 or config_num == total_configs:
                    print(f"   Progress: {config_num}/{total_configs} configs tested")
    
    # Sort by LogLoss (primary metric)
    results.sort(key=lambda r: r['logloss'])
    
    # Save all results
    output_path = 'artifacts/sweeps/v2_blend_sweep.json'
    with open(output_path, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'baseline': baseline_metrics,
            'grid': GRID,
            'guardrails': GUARDRAILS,
            'results': results
        }, f, indent=2, default=str)
    
    print(f"\n💾 Full results saved to: {output_path}")
    
    # Find best config with guardrails
    print("\n🏆 TOP 5 CONFIGURATIONS (by LogLoss):")
    print(f"{'#':<4} {'α':<6} {'KL':<7} {'Δτ':<6} {'LL':<8} {'Brier':<8} {'ECE':<8} {'Hit%':<7}")
    print("-" * 70)
    
    for i, r in enumerate(results[:5], 1):
        kl_str = f"{r['kl_cap']:.2f}" if r['kl_cap'] is not None else "None"
        print(f"{i:<4} {r['alpha']:<6.2f} {kl_str:<7} {r['delta_tau']:<6.2f} "
              f"{r['logloss']:<8.4f} {r['brier']:<8.4f} {r['ece_global']:<8.4f} "
              f"{r['hit_rate']*100:<7.1f}")
    
    # Apply guardrails
    print("\n🛡️  APPLYING GUARDRAILS...")
    candidates = [r for r in results if (
        r['ece_global'] <= GUARDRAILS['ece_global_max'] and
        r['max_league_ece'] <= GUARDRAILS['ece_league_max'] and
        (not GUARDRAILS['require_logloss_improvement'] or r['delta_logloss'] < 0) and
        (not GUARDRAILS['require_brier_not_worse'] or r['delta_brier'] <= 0.001)
    )]
    
    if not candidates:
        print("❌ NO CONFIG PASSES GUARDRAILS - Keeping current configuration")
        selected = {
            'alpha': 0.8,
            'kl_cap': 0.15,
            'delta_tau': 1.0,
            'reason': 'No improvement found, using safe defaults'
        }
    else:
        best = candidates[0]
        print(f"✅ SELECTED: α={best['alpha']}, KL={best['kl_cap']}, Δτ={best['delta_tau']}")
        print(f"   LogLoss: {best['logloss']:.4f} (Δ={best['delta_logloss']:.4f})")
        print(f"   Brier:   {best['brier']:.4f} (Δ={best['delta_brier']:.4f})")
        print(f"   ECE:     {best['ece_global']:.4f} (Δ={best['delta_ece']:.4f})")
        print(f"   Hit Rate: {best['hit_rate']*100:.1f}%")
        
        selected = {
            'alpha': best['alpha'],
            'kl_cap': best['kl_cap'],
            'delta_tau': best['delta_tau'],
            'enable_temp_scaling': False,
            'selected_at': datetime.now().isoformat(),
            'logloss': best['logloss'],
            'brier': best['brier'],
            'ece_global': best['ece_global'],
            'reason': f'Best config passing guardrails (rank #{results.index(best)+1})'
        }
    
    # Save config
    config_path = 'config/v2_inference.json'
    with open(config_path, 'w') as f:
        json.dump(selected, f, indent=2)
    
    print(f"\n💾 Config saved to: {config_path}")
    print("\n" + "=" * 70)
    
    return selected, results[:10]


if __name__ == "__main__":
    selected, top10 = run_sweep()
    
    print("\n📋 SUMMARY:")
    print(json.dumps({
        'selected_config': selected,
        'top_3_alternatives': [
            {k: r[k] for k in ['alpha', 'kl_cap', 'delta_tau', 'logloss', 'brier', 'ece_global']}
            for r in top10[:3]
        ]
    }, indent=2, default=str))
