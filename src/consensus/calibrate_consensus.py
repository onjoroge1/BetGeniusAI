"""
Per-league, per-bucket calibration for consensus forecasts
Isotonic regression calibration to ensure well-calibrated probabilities
"""

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, brier_score_loss
import psycopg2
import os
import joblib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
import warnings
warnings.filterwarnings('ignore')

class ConsensusCalibrator:
    """Calibrate consensus probabilities per league and time bucket"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        self.time_buckets = ['24h', '6h', '1h', 'close']
        self.calibrators = {}  # {league_id: {bucket: {outcome: calibrator}}}
        
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def load_consensus_training_data(self, start_date: str = None, 
                                   end_date: str = None) -> pd.DataFrame:
        """Load consensus predictions with match outcomes for training"""
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        conn = self.get_db_connection()
        
        query = """
        SELECT 
            cp.match_id,
            cp.time_bucket,
            cp.consensus_h,
            cp.consensus_d, 
            cp.consensus_a,
            cp.dispersion_h,
            cp.dispersion_d,
            cp.dispersion_a,
            cp.n_books,
            m.league_id,
            m.match_date_utc,
            m.outcome,
            m.home_goals,
            m.away_goals
        FROM consensus_predictions cp
        JOIN matches m ON cp.match_id = m.match_id
        WHERE m.match_date_utc >= %s
          AND m.match_date_utc <= %s
          AND m.outcome IS NOT NULL
          AND m.league_id IN (39, 140, 135, 78, 61)
        ORDER BY m.match_date_utc ASC
        """
        
        df = pd.read_sql_query(query, conn, params=[start_date, end_date])
        conn.close()
        
        print(f"Loaded {len(df)} consensus predictions with outcomes")
        return df
    
    def create_outcome_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """Convert outcomes to binary labels for each outcome"""
        
        df = df.copy()
        
        # Create binary outcome columns
        df['outcome_h'] = (df['outcome'] == 'H').astype(int)
        df['outcome_d'] = (df['outcome'] == 'D').astype(int)
        df['outcome_a'] = (df['outcome'] == 'A').astype(int)
        
        return df
    
    def train_calibrator_for_league_bucket(self, df: pd.DataFrame, 
                                         league_id: int, time_bucket: str) -> Dict:
        """Train calibrators for specific league and time bucket"""
        
        league_name = self.euro_leagues.get(league_id, f"League_{league_id}")
        
        # Filter data
        league_bucket_data = df[
            (df['league_id'] == league_id) & 
            (df['time_bucket'] == time_bucket)
        ].copy()
        
        if len(league_bucket_data) < 30:
            print(f"   Insufficient data for {league_name} {time_bucket}: {len(league_bucket_data)} samples")
            return None
        
        print(f"   Training {league_name} {time_bucket}: {len(league_bucket_data)} samples")
        
        # Sort by date for time-aware validation
        league_bucket_data = league_bucket_data.sort_values('match_date_utc')
        
        calibrators = {}
        results = {}
        
        # Train calibrator for each outcome
        for outcome in ['h', 'd', 'a']:
            prob_col = f'consensus_{outcome}'
            outcome_col = f'outcome_{outcome}'
            
            # Get probabilities and binary outcomes
            X = league_bucket_data[prob_col].values
            y = league_bucket_data[outcome_col].values
            
            # Check if we have both classes
            if len(np.unique(y)) < 2:
                print(f"     Skipping {outcome}: only one class present")
                calibrators[outcome] = None
                continue
            
            # Use time series split for validation
            tscv = TimeSeriesSplit(n_splits=3)
            
            # Collect out-of-fold predictions for evaluation
            oof_probs_raw = np.zeros(len(X))
            oof_probs_cal = np.zeros(len(X))
            
            for train_idx, val_idx in tscv.split(X):
                X_train, X_val = X[train_idx], X[val_idx]
                y_train, y_val = y[train_idx], y[val_idx]
                
                # Train isotonic regression
                calibrator = IsotonicRegression(out_of_bounds='clip')
                calibrator.fit(X_train, y_train)
                
                # Predict on validation fold
                cal_probs = calibrator.predict(X_val)
                oof_probs_raw[val_idx] = X_val
                oof_probs_cal[val_idx] = cal_probs
            
            # Train final calibrator on all data
            final_calibrator = IsotonicRegression(out_of_bounds='clip')
            final_calibrator.fit(X, y)
            calibrators[outcome] = final_calibrator
            
            # Evaluate calibration improvement
            try:
                brier_raw = brier_score_loss(y, oof_probs_raw)
                brier_cal = brier_score_loss(y, oof_probs_cal)
                
                results[outcome] = {
                    'brier_raw': brier_raw,
                    'brier_calibrated': brier_cal,
                    'improvement': brier_raw - brier_cal,
                    'samples': len(X)
                }
                
                print(f"     {outcome.upper()}: Brier {brier_raw:.4f} → {brier_cal:.4f} "
                      f"(Δ{brier_raw - brier_cal:+.4f})")
                      
            except Exception as e:
                print(f"     {outcome.upper()}: Evaluation failed: {e}")
                results[outcome] = {'error': str(e)}
        
        return {
            'calibrators': calibrators,
            'results': results,
            'league_id': league_id,
            'time_bucket': time_bucket,
            'n_samples': len(league_bucket_data)
        }
    
    def apply_calibration(self, probs_h: np.ndarray, probs_d: np.ndarray, probs_a: np.ndarray,
                         league_id: int, time_bucket: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Apply trained calibrators to new predictions"""
        
        # Get calibrators for this league/bucket
        league_calibrators = self.calibrators.get(league_id, {})
        bucket_calibrators = league_calibrators.get(time_bucket, {})
        
        # Apply calibration if available
        cal_h = probs_h.copy()
        cal_d = probs_d.copy()
        cal_a = probs_a.copy()
        
        if 'h' in bucket_calibrators and bucket_calibrators['h'] is not None:
            cal_h = bucket_calibrators['h'].predict(probs_h)
        
        if 'd' in bucket_calibrators and bucket_calibrators['d'] is not None:
            cal_d = bucket_calibrators['d'].predict(probs_d)
            
        if 'a' in bucket_calibrators and bucket_calibrators['a'] is not None:
            cal_a = bucket_calibrators['a'].predict(probs_a)
        
        # Renormalize to ensure sum = 1
        total = cal_h + cal_d + cal_a
        cal_h = cal_h / total
        cal_d = cal_d / total
        cal_a = cal_a / total
        
        return cal_h, cal_d, cal_a
    
    def train_all_calibrators(self, buckets: List[str] = None, 
                            leagues: List[int] = None) -> Dict:
        """Train calibrators for all league/bucket combinations"""
        
        if buckets is None:
            buckets = self.time_buckets
        if leagues is None:
            leagues = list(self.euro_leagues.keys())
        
        print("🔧 Training consensus calibrators...")
        print(f"Buckets: {buckets}")
        print(f"Leagues: {[self.euro_leagues[l] for l in leagues]}")
        
        # Load training data
        training_data = self.load_consensus_training_data()
        training_data = self.create_outcome_labels(training_data)
        
        if len(training_data) == 0:
            print("❌ No training data available")
            return {}
        
        # Initialize calibrator storage
        self.calibrators = {}
        training_results = {}
        
        # Train for each league/bucket combination
        for league_id in leagues:
            self.calibrators[league_id] = {}
            training_results[league_id] = {}
            
            for bucket in buckets:
                print(f"\n🎯 Training {self.euro_leagues[league_id]} - {bucket}")
                
                result = self.train_calibrator_for_league_bucket(
                    training_data, league_id, bucket
                )
                
                if result is not None:
                    self.calibrators[league_id][bucket] = result['calibrators']
                    training_results[league_id][bucket] = result['results']
                else:
                    self.calibrators[league_id][bucket] = {}
                    training_results[league_id][bucket] = {'error': 'Insufficient data'}
        
        return training_results
    
    def evaluate_calibrated_consensus(self, test_data: pd.DataFrame = None) -> Dict:
        """Evaluate calibrated consensus vs raw consensus"""
        
        if test_data is None:
            # Use recent data for evaluation
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
            test_data = self.load_consensus_training_data(start_date, end_date)
            test_data = self.create_outcome_labels(test_data)
        
        if len(test_data) == 0:
            return {'error': 'No test data available'}
        
        results = {}
        
        for bucket in self.time_buckets:
            bucket_data = test_data[test_data['time_bucket'] == bucket]
            
            if len(bucket_data) == 0:
                continue
            
            bucket_results = {}
            
            for league_id in self.euro_leagues.keys():
                league_data = bucket_data[bucket_data['league_id'] == league_id]
                
                if len(league_data) < 10:
                    continue
                
                # Get raw and calibrated probabilities
                raw_probs = league_data[['consensus_h', 'consensus_d', 'consensus_a']].values
                
                cal_h, cal_d, cal_a = self.apply_calibration(
                    league_data['consensus_h'].values,
                    league_data['consensus_d'].values,
                    league_data['consensus_a'].values,
                    league_id, bucket
                )
                
                cal_probs = np.column_stack([cal_h, cal_d, cal_a])
                
                # Convert outcomes to numeric labels
                label_map = {'H': 0, 'D': 1, 'A': 2}
                y_true = np.array([label_map[outcome] for outcome in league_data['outcome']])
                
                # Calculate metrics
                try:
                    raw_logloss = log_loss(y_true, raw_probs)
                    cal_logloss = log_loss(y_true, cal_probs)
                    
                    bucket_results[league_id] = {
                        'raw_logloss': raw_logloss,
                        'calibrated_logloss': cal_logloss,
                        'improvement': raw_logloss - cal_logloss,
                        'n_samples': len(league_data)
                    }
                    
                except Exception as e:
                    bucket_results[league_id] = {'error': str(e)}
            
            results[bucket] = bucket_results
        
        return results
    
    def save_calibrators(self, version: str = None):
        """Save trained calibrators to disk"""
        
        if version is None:
            version = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Create calibrators directory
        os.makedirs('models/consensus/calibrators', exist_ok=True)
        
        # Save calibrators
        calibrator_path = f'models/consensus/calibrators/consensus_calibrators_v{version}.joblib'
        
        artifacts = {
            'calibrators': self.calibrators,
            'euro_leagues': self.euro_leagues,
            'time_buckets': self.time_buckets,
            'version': version,
            'created_at': datetime.now().isoformat()
        }
        
        joblib.dump(artifacts, calibrator_path)
        
        # Save metadata
        metadata_path = f'models/consensus/calibrators/metadata_v{version}.json'
        metadata = {
            'version': version,
            'calibrator_path': calibrator_path,
            'leagues': list(self.euro_leagues.keys()),
            'buckets': self.time_buckets,
            'created_at': datetime.now().isoformat()
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"✅ Calibrators saved: {calibrator_path}")
        return calibrator_path
    
    def load_calibrators(self, version: str = 'latest'):
        """Load trained calibrators from disk"""
        
        if version == 'latest':
            # Find latest version
            import glob
            calibrator_files = glob.glob('models/consensus/calibrators/consensus_calibrators_v*.joblib')
            if not calibrator_files:
                raise FileNotFoundError("No calibrators found")
            calibrator_path = sorted(calibrator_files)[-1]
        else:
            calibrator_path = f'models/consensus/calibrators/consensus_calibrators_v{version}.joblib'
        
        artifacts = joblib.load(calibrator_path)
        self.calibrators = artifacts['calibrators']
        
        print(f"✅ Calibrators loaded: {calibrator_path}")
        return calibrator_path

def main():
    """Train and evaluate consensus calibrators"""
    
    calibrator = ConsensusCalibrator()
    
    # Train calibrators
    training_results = calibrator.train_all_calibrators()
    
    # Evaluate performance
    print("\n📊 Evaluating calibrated consensus...")
    eval_results = calibrator.evaluate_calibrated_consensus()
    
    # Save calibrators
    calibrator_path = calibrator.save_calibrators()
    
    # Generate report
    print("\n" + "="*60)
    print("CONSENSUS CALIBRATION REPORT")
    print("="*60)
    
    for bucket, bucket_results in eval_results.items():
        if not bucket_results:
            continue
            
        print(f"\n{bucket.upper()} BUCKET:")
        print("-" * 30)
        
        for league_id, metrics in bucket_results.items():
            if 'error' in metrics:
                continue
                
            league_name = calibrator.euro_leagues[league_id]
            improvement = metrics['improvement']
            status = "✅ IMPROVED" if improvement > 0 else "⚠️  DEGRADED"
            
            print(f"{league_name}: {metrics['raw_logloss']:.4f} → "
                  f"{metrics['calibrated_logloss']:.4f} "
                  f"(Δ{improvement:+.4f}) {status}")
    
    print(f"\n✅ Consensus calibration complete!")
    print(f"📊 Artifacts: {calibrator_path}")
    
    return training_results, eval_results

if __name__ == "__main__":
    main()