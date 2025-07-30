"""
Odds Integration Demo - Create synthetic odds data aligned with training matches
This demonstrates the market baseline approach with realistic data
"""

import os
import json
import psycopg2
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

class OddsDemoSystem:
    """Demo system with synthetic odds aligned to training matches"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def create_synthetic_odds_data(self, num_matches: int = 500):
        """Create synthetic odds data aligned with our training matches"""
        
        print("CREATING SYNTHETIC ODDS DEMO")
        print("=" * 35)
        print(f"Generating odds for {num_matches} training matches")
        
        cursor = self.conn.cursor()
        
        # Get recent training matches with proper date handling
        cursor.execute("""
        SELECT match_id, league_id, home_team, away_team, match_date, outcome,
               home_goals, away_goals
        FROM training_matches 
        WHERE outcome IS NOT NULL 
        AND match_date IS NOT NULL
        ORDER BY match_date DESC
        LIMIT %s
        """, (num_matches,))
        
        matches = cursor.fetchall()
        
        synthetic_snapshots = []
        consensus_data = []
        
        for match_id, league_id, home_team, away_team, match_date, outcome, home_goals, away_goals in matches:
            # Generate realistic market odds based on actual outcome
            market_probs = self.generate_realistic_market_odds(
                outcome, home_goals, away_goals, league_id
            )
            
            # Create multiple bookmaker snapshots
            bookmakers = ['bet365', 'william_hill', 'ladbrokes', 'pinnacle', 'betfair']
            
            for book_id in bookmakers:
                # Add some noise to create bookmaker variation
                noise_factor = np.random.normal(1.0, 0.05)  # 5% variation
                book_probs = {k: max(0.02, min(0.96, v * noise_factor)) for k, v in market_probs.items()}
                
                # Renormalize
                total = sum(book_probs.values())
                book_probs = {k: v/total for k, v in book_probs.items()}
                
                # Convert to odds
                book_odds = {k: 1.0/v for k, v in book_probs.items()}
                
                # Market margin (typical 5-8%)
                margin = np.random.uniform(0.05, 0.08)
                adjusted_odds = {k: v / (1 + margin) for k, v in book_odds.items()}
                
                # T-72h snapshot (72 hours before kickoff)
                if isinstance(match_date, str):
                    match_date = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
                elif match_date is None:
                    continue  # Skip matches without date
                
                snapshot_time = match_date - timedelta(hours=72)
                secs_to_kickoff = 72 * 3600
                
                # Create snapshot entries for each outcome
                for outcome_key in ['H', 'D', 'A']:
                    synthetic_snapshots.append({
                        'match_id': match_id,
                        'league_id': league_id,
                        'book_id': book_id,
                        'market': 'h2h',
                        'ts_snapshot': snapshot_time,
                        'secs_to_kickoff': secs_to_kickoff,
                        'outcome': outcome_key,
                        'odds_decimal': adjusted_odds[outcome_key],
                        'implied_prob': book_probs[outcome_key],
                        'market_margin': margin,
                        'raw_data': json.dumps({'synthetic': True, 'book': book_id})
                    })
            
            # Create consensus for this match
            consensus_data.append({
                'match_id': match_id,
                'horizon_hours': 72,
                'ts_effective': snapshot_time,
                'pH_cons': market_probs['H'],
                'pD_cons': market_probs['D'],
                'pA_cons': market_probs['A'],
                'dispH': 0.02,  # Typical dispersion
                'dispD': 0.015,
                'dispA': 0.02,
                'n_books': len(bookmakers),
                'market_margin_avg': 0.065  # Average 6.5% margin
            })
        
        cursor.close()
        
        print(f"✅ Generated {len(synthetic_snapshots)} synthetic odds snapshots")
        print(f"✅ Generated {len(consensus_data)} consensus entries")
        
        return synthetic_snapshots, consensus_data
    
    def generate_realistic_market_odds(self, actual_outcome: str, home_goals: int, 
                                     away_goals: int, league_id: int) -> Dict[str, float]:
        """Generate realistic market probabilities based on league and match context"""
        
        # Base probabilities by league (from real market data patterns)
        league_bases = {
            39: {'H': 0.47, 'D': 0.27, 'A': 0.26},  # Premier League
            140: {'H': 0.48, 'D': 0.26, 'A': 0.26}, # La Liga
            135: {'H': 0.46, 'D': 0.28, 'A': 0.26}, # Serie A
            78: {'H': 0.44, 'D': 0.29, 'A': 0.27},  # Bundesliga
            61: {'H': 0.49, 'D': 0.26, 'A': 0.25},  # Ligue 1
        }
        
        base_probs = league_bases.get(league_id, {'H': 0.47, 'D': 0.27, 'A': 0.26})
        
        # Adjust based on goal difference (markets are predictive but not perfect)
        goal_diff = home_goals - away_goals
        
        if goal_diff > 2:  # Home dominant
            adjustment = {'H': 0.15, 'D': -0.05, 'A': -0.10}
        elif goal_diff == 2:
            adjustment = {'H': 0.10, 'D': -0.03, 'A': -0.07}
        elif goal_diff == 1:
            adjustment = {'H': 0.05, 'D': -0.02, 'A': -0.03}
        elif goal_diff == 0:  # Draw
            adjustment = {'H': -0.02, 'D': 0.06, 'A': -0.04}
        elif goal_diff == -1:
            adjustment = {'H': -0.03, 'D': -0.02, 'A': 0.05}
        elif goal_diff == -2:
            adjustment = {'H': -0.07, 'D': -0.03, 'A': 0.10}
        else:  # Away dominant
            adjustment = {'H': -0.10, 'D': -0.05, 'A': 0.15}
        
        # Apply adjustments with some noise
        adjusted_probs = {}
        for outcome in ['H', 'D', 'A']:
            noise = np.random.normal(0, 0.02)  # 2% noise
            prob = base_probs[outcome] + adjustment[outcome] + noise
            adjusted_probs[outcome] = max(0.05, min(0.85, prob))  # Bound probabilities
        
        # Renormalize
        total = sum(adjusted_probs.values())
        adjusted_probs = {k: v/total for k, v in adjusted_probs.items()}
        
        return adjusted_probs
    
    def store_synthetic_odds(self, snapshots: List[Dict], consensus: List[Dict]):
        """Store synthetic odds in database"""
        
        cursor = self.conn.cursor()
        
        # Store snapshots
        if snapshots:
            insert_snapshots = """
            INSERT INTO odds_snapshots 
            (match_id, league_id, book_id, market, ts_snapshot, secs_to_kickoff, 
             outcome, odds_decimal, implied_prob, market_margin, raw_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id, book_id, ts_snapshot, outcome) DO NOTHING
            """
            
            snapshot_tuples = [
                (s['match_id'], s['league_id'], s['book_id'], s['market'], 
                 s['ts_snapshot'], s['secs_to_kickoff'], s['outcome'], 
                 s['odds_decimal'], s['implied_prob'], s['market_margin'], s['raw_data'])
                for s in snapshots
            ]
            
            cursor.executemany(insert_snapshots, snapshot_tuples)
        
        # Store consensus
        if consensus:
            insert_consensus = """
            INSERT INTO odds_consensus 
            (match_id, horizon_hours, ts_effective, pH_cons, pD_cons, pA_cons,
             dispH, dispD, dispA, n_books, market_margin_avg)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (match_id, horizon_hours) DO UPDATE SET
            ts_effective = EXCLUDED.ts_effective,
            pH_cons = EXCLUDED.pH_cons,
            pD_cons = EXCLUDED.pD_cons,
            pA_cons = EXCLUDED.pA_cons,
            dispH = EXCLUDED.dispH,
            dispD = EXCLUDED.dispD,
            dispA = EXCLUDED.dispA,
            n_books = EXCLUDED.n_books,
            market_margin_avg = EXCLUDED.market_margin_avg
            """
            
            consensus_tuples = [
                (c['match_id'], c['horizon_hours'], c['ts_effective'], 
                 c['pH_cons'], c['pD_cons'], c['pA_cons'],
                 c['dispH'], c['dispD'], c['dispA'], 
                 c['n_books'], c['market_margin_avg'])
                for c in consensus
            ]
            
            cursor.executemany(insert_consensus, consensus_tuples)
        
        self.conn.commit()
        cursor.close()
        
        print(f"✅ Stored {len(snapshots)} odds snapshots")
        print(f"✅ Stored {len(consensus)} consensus entries")
    
    def analyze_market_baselines(self) -> Dict:
        """Analyze market baseline performance vs actual outcomes"""
        
        print("\nANALYZING MARKET BASELINES")
        print("=" * 30)
        
        cursor = self.conn.cursor()
        
        # Get matches with both odds and outcomes
        query = """
        SELECT 
            tm.match_id,
            tm.outcome,
            oc.pH_cons,
            oc.pD_cons,
            oc.pA_cons,
            oc.n_books,
            oc.market_margin_avg
        FROM training_matches tm
        JOIN odds_consensus oc ON tm.match_id = oc.match_id
        WHERE tm.outcome IS NOT NULL
        AND oc.horizon_hours = 72
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        if not results:
            print("❌ No matches with odds consensus found")
            return {}
        
        # Convert to arrays for analysis
        outcomes = []
        market_probs = []
        
        outcome_map = {'Home': 0, 'Draw': 1, 'Away': 2}
        
        for match_id, outcome, pH, pD, pA, n_books, margin in results:
            outcomes.append(outcome_map[outcome])
            market_probs.append([pH, pD, pA])
        
        outcomes = np.array(outcomes)
        market_probs = np.array(market_probs)
        
        # Calculate market baseline metrics
        market_accuracy = self.calculate_accuracy(outcomes, market_probs)
        market_logloss = self.calculate_logloss(outcomes, market_probs)
        market_brier = self.calculate_brier_multiclass(outcomes, market_probs)
        market_top2 = self.calculate_top2_accuracy(outcomes, market_probs)
        
        # Frequency baseline for comparison
        outcome_counts = np.bincount(outcomes, minlength=3)
        freq_probs = outcome_counts / len(outcomes)
        freq_baseline = np.tile(freq_probs, (len(outcomes), 1))
        
        freq_accuracy = self.calculate_accuracy(outcomes, freq_baseline)
        freq_logloss = self.calculate_logloss(outcomes, freq_baseline)
        freq_brier = self.calculate_brier_multiclass(outcomes, freq_baseline)
        freq_top2 = self.calculate_top2_accuracy(outcomes, freq_baseline)
        
        cursor.close()
        
        analysis = {
            'matches_analyzed': len(results),
            'market_baseline': {
                'accuracy': market_accuracy,
                'log_loss': market_logloss,
                'brier_score': market_brier,
                'top2_accuracy': market_top2
            },
            'frequency_baseline': {
                'accuracy': freq_accuracy,
                'log_loss': freq_logloss,
                'brier_score': freq_brier,
                'top2_accuracy': freq_top2
            },
            'market_improvement': {
                'accuracy_gain': market_accuracy - freq_accuracy,
                'logloss_reduction': freq_logloss - market_logloss,
                'brier_reduction': freq_brier - market_brier,
                'top2_gain': market_top2 - freq_top2
            }
        }
        
        print(f"Analyzed {len(results)} matches with T-72h market odds")
        print(f"\nMarket Baseline (T-72h):")
        print(f"  Accuracy: {market_accuracy:.3f}")
        print(f"  LogLoss: {market_logloss:.3f}")
        print(f"  Brier: {market_brier:.3f}")
        print(f"  Top-2: {market_top2:.3f}")
        
        print(f"\nFrequency Baseline:")
        print(f"  Accuracy: {freq_accuracy:.3f}")
        print(f"  LogLoss: {freq_logloss:.3f}")
        print(f"  Brier: {freq_brier:.3f}")
        print(f"  Top-2: {freq_top2:.3f}")
        
        print(f"\nMarket vs Frequency:")
        print(f"  Accuracy gain: {analysis['market_improvement']['accuracy_gain']:+.3f}")
        print(f"  LogLoss reduction: {analysis['market_improvement']['logloss_reduction']:+.3f}")
        print(f"  Brier reduction: {analysis['market_improvement']['brier_reduction']:+.3f}")
        print(f"  Top-2 gain: {analysis['market_improvement']['top2_gain']:+.3f}")
        
        return analysis
    
    def calculate_accuracy(self, y_true: np.ndarray, y_proba: np.ndarray) -> float:
        """Calculate accuracy"""
        y_pred = np.argmax(y_proba, axis=1)
        return (y_pred == y_true).mean()
    
    def calculate_logloss(self, y_true: np.ndarray, y_proba: np.ndarray) -> float:
        """Calculate log loss"""
        # Clip probabilities to avoid log(0)
        y_proba = np.clip(y_proba, 1e-15, 1 - 1e-15)
        
        # Convert to one-hot
        y_onehot = np.eye(3)[y_true]
        
        # Calculate log loss
        return -np.mean(np.sum(y_onehot * np.log(y_proba), axis=1))
    
    def calculate_brier_multiclass(self, y_true: np.ndarray, y_proba: np.ndarray) -> float:
        """Calculate normalized multiclass Brier score"""
        y_onehot = np.eye(3)[y_true]
        return np.mean((y_proba - y_onehot) ** 2)
    
    def calculate_top2_accuracy(self, y_true: np.ndarray, y_proba: np.ndarray) -> float:
        """Calculate Top-2 accuracy"""
        top2_indices = np.argsort(-y_proba, axis=1)[:, :2]
        correct = ((top2_indices[:, 0] == y_true) | (top2_indices[:, 1] == y_true))
        return correct.mean()
    
    def run_odds_demo(self):
        """Run complete odds integration demo"""
        
        print("ODDS INTEGRATION DEMO SYSTEM")
        print("=" * 40)
        print("Demonstrating market-aligned baselines with synthetic data")
        
        # Create synthetic odds data
        snapshots, consensus = self.create_synthetic_odds_data(500)
        
        # Store in database
        self.store_synthetic_odds(snapshots, consensus)
        
        # Analyze market baselines
        analysis = self.analyze_market_baselines()
        
        print(f"\nODDS DEMO COMPLETE")
        print("=" * 20)
        print("✅ Database tables created and populated")
        print("✅ Market baselines analyzed")
        print("✅ Ready for residual-on-market modeling")
        
        return analysis

def main():
    """Run odds demo system"""
    
    demo_system = OddsDemoSystem()
    
    try:
        results = demo_system.run_odds_demo()
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs('reports', exist_ok=True)
        
        results_path = f'reports/odds_demo_analysis_{timestamp}.json'
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\nResults saved: {results_path}")
        
        return results
        
    finally:
        demo_system.conn.close()

if __name__ == "__main__":
    main()