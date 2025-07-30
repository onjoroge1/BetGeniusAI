"""
Fast Week 2 Implementation
Streamlined book-aware residual training using existing consensus data
"""

import os
import pandas as pd
import numpy as np
import psycopg2
from datetime import datetime
import json
import joblib
from typing import Dict, List, Tuple
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, brier_score_loss
import lightgbm as lgb

class FastWeek2Implementation:
    """Fast implementation of Week 2 book-aware enhancements"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def load_consensus_data(self) -> pd.DataFrame:
        """Load weighted consensus data"""
        
        # Find latest consensus data
        consensus_dir = 'consensus/weighted'
        if os.path.exists(consensus_dir):
            consensus_files = [f for f in os.listdir(consensus_dir) if f.startswith('weighted_consensus_t72_') and f.endswith('.csv')]
            if consensus_files:
                latest_file = sorted(consensus_files)[-1]
                consensus_path = os.path.join(consensus_dir, latest_file)
                
                print(f"Loading consensus data from {consensus_path}")
                df = pd.read_csv(consensus_path)
                return df
        
        # Fallback: create consensus from historical data
        print("Creating consensus from historical data...")
        return self.create_consensus_from_historical()
    
    def create_consensus_from_historical(self) -> pd.DataFrame:
        """Create weighted consensus from historical odds data"""
        
        query = """
        SELECT 
            id, match_date, league, home_team, away_team, result,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            wh_h, wh_d, wh_a
        FROM historical_odds
        WHERE result IS NOT NULL
        AND match_date >= '2020-01-01'
        AND b365_h IS NOT NULL
        ORDER BY match_date DESC
        LIMIT 2000
        """
        
        df = pd.read_sql(query, self.conn)
        
        # Build simple consensus
        consensus_data = []
        bookmakers = ['b365', 'bw', 'wh']
        
        for _, row in df.iterrows():
            valid_probs = []
            
            for bm in bookmakers:
                odds_h = row.get(f"{bm}_h")
                odds_d = row.get(f"{bm}_d")
                odds_a = row.get(f"{bm}_a")
                
                if pd.notna(odds_h) and pd.notna(odds_d) and pd.notna(odds_a):
                    if odds_h > 1 and odds_d > 1 and odds_a > 1:
                        # Convert to probabilities
                        prob_h = 1.0 / odds_h
                        prob_d = 1.0 / odds_d
                        prob_a = 1.0 / odds_a
                        
                        total = prob_h + prob_d + prob_a
                        if total > 0:
                            valid_probs.append([prob_h/total, prob_d/total, prob_a/total])
            
            if valid_probs:
                consensus = np.mean(valid_probs, axis=0)
                
                # Calculate dispersion
                disp_h = np.std([p[0] for p in valid_probs]) if len(valid_probs) > 1 else 0.0
                disp_d = np.std([p[1] for p in valid_probs]) if len(valid_probs) > 1 else 0.0
                disp_a = np.std([p[2] for p in valid_probs]) if len(valid_probs) > 1 else 0.0
                
                consensus_data.append({
                    'match_id': row['id'],
                    'match_date': row['match_date'],
                    'league': row['league'],
                    'home_team': row['home_team'],
                    'away_team': row['away_team'],
                    'result': row['result'],
                    'pH_cons_w': consensus[0],
                    'pD_cons_w': consensus[1],
                    'pA_cons_w': consensus[2],
                    'dispH': disp_h,
                    'dispD': disp_d,
                    'dispA': disp_a,
                    'n_books': len(valid_probs),
                    'avg_overround': np.mean([sum(p) for p in valid_probs]) if valid_probs else 1.0
                })
        
        return pd.DataFrame(consensus_data)
    
    def build_enhanced_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build enhanced features for residual training"""
        
        print("Building enhanced features...")
        
        # Convert consensus probabilities to logits
        df['logit_cons_h'] = np.log(np.clip(df['pH_cons_w'], 0.02, 0.98) / np.clip(1 - df['pH_cons_w'], 0.02, 0.98))
        df['logit_cons_d'] = np.log(np.clip(df['pD_cons_w'], 0.02, 0.98) / np.clip(1 - df['pD_cons_w'], 0.02, 0.98))
        df['logit_cons_a'] = np.log(np.clip(df['pA_cons_w'], 0.02, 0.98) / np.clip(1 - df['pA_cons_w'], 0.02, 0.98))
        
        # Market intelligence features
        df['total_dispersion'] = df['dispH'] + df['dispD'] + df['dispA']
        df['max_dispersion'] = np.maximum.reduce([df['dispH'], df['dispD'], df['dispA']])
        df['market_confidence'] = 1.0 / (1.0 + df['total_dispersion'])
        df['book_coverage_pct'] = df['n_books'] / 8.0  # Max 8 bookmakers
        
        # League intelligence
        league_mapping = {'E0': 1, 'SP1': 1, 'I1': 1, 'D1': 1, 'F1': 1}
        df['league_tier'] = df['league'].map(league_mapping).fillna(2)
        
        # Temporal features
        df['match_date_dt'] = pd.to_datetime(df['match_date'])
        df['month'] = df['match_date_dt'].dt.month
        df['is_weekend'] = (df['match_date_dt'].dt.weekday >= 5).astype(int)
        
        # Season phase
        season_phase_map = {8: 'early', 9: 'early', 10: 'early',
                           11: 'mid', 12: 'mid', 1: 'mid', 2: 'mid',
                           3: 'late', 4: 'late', 5: 'late'}
        df['season_phase'] = df['month'].map(season_phase_map).fillna('mid')
        df['season_phase_early'] = (df['season_phase'] == 'early').astype(int)
        df['season_phase_late'] = (df['season_phase'] == 'late').astype(int)
        
        # Interaction features
        df['dispersion_x_books'] = df['total_dispersion'] * df['n_books']
        df['confidence_x_tier'] = df['market_confidence'] * df['league_tier']
        
        return df
    
    def prepare_training_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
        """Prepare training data for residual model"""
        
        print("Preparing training data...")
        
        # Select features for training
        feature_columns = [
            'logit_cons_h', 'logit_cons_d', 'logit_cons_a',
            'dispH', 'dispD', 'dispA',
            'total_dispersion', 'max_dispersion', 'market_confidence',
            'n_books', 'book_coverage_pct', 'avg_overround',
            'league_tier', 'is_weekend',
            'season_phase_early', 'season_phase_late',
            'dispersion_x_books', 'confidence_x_tier'
        ]
        
        # Ensure all columns exist
        available_features = [col for col in feature_columns if col in df.columns]
        print(f"Using {len(available_features)} features: {available_features}")
        
        X = df[available_features].copy()
        X = X.fillna(0.0)
        
        # Consensus probabilities
        consensus_probs = df[['pH_cons_w', 'pD_cons_w', 'pA_cons_w']].copy()
        
        # Target variable
        y = df['result'].copy()
        
        return X, consensus_probs, y
    
    def train_residual_model(self, X: pd.DataFrame, consensus_probs: pd.DataFrame, y: pd.Series) -> Dict:
        """Train residual model with cross-validation"""
        
        print(f"Training residual model with {len(X)} samples and {X.shape[1]} features...")
        
        # Convert targets to one-hot
        y_onehot = []
        for outcome in y:
            if outcome == 'H':
                y_onehot.append([1, 0, 0])
            elif outcome == 'D':
                y_onehot.append([0, 1, 0])
            elif outcome == 'A':
                y_onehot.append([0, 0, 1])
            else:
                y_onehot.append([1/3, 1/3, 1/3])
        
        y_onehot = np.array(y_onehot)
        
        # Calculate residual targets (log odds residuals)
        consensus_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        consensus_logits = np.log(consensus_clipped / (1 - consensus_clipped))
        
        true_clipped = np.clip(y_onehot, 1e-15, 1 - 1e-15)
        true_logits = np.log(true_clipped / (1 - true_clipped))
        
        residual_targets = true_logits - consensus_logits
        
        # Cross-validation setup
        skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        
        oof_residuals = np.zeros_like(residual_targets)
        oof_final_probs = np.zeros((len(X), 3))
        
        fold_performances = []
        trained_models = []
        
        for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            print(f"Training fold {fold + 1}/5...")
            
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            residuals_train, residuals_val = residual_targets[train_idx], residual_targets[val_idx]
            consensus_train, consensus_val = consensus_probs.iloc[train_idx], consensus_probs.iloc[val_idx]
            y_val_onehot = y_onehot[val_idx]
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_val_scaled = scaler.transform(X_val)
            
            # Train models for each outcome
            fold_models = {}
            
            for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
                # Train LightGBM for this outcome
                train_data = lgb.Dataset(X_train_scaled, label=residuals_train[:, outcome_idx])
                val_data = lgb.Dataset(X_val_scaled, label=residuals_val[:, outcome_idx], reference=train_data)
                
                params = {
                    'objective': 'regression',
                    'metric': 'rmse',
                    'boosting_type': 'gbdt',
                    'num_leaves': 31,
                    'learning_rate': 0.1,
                    'feature_fraction': 0.8,
                    'bagging_fraction': 0.8,
                    'bagging_freq': 5,
                    'verbose': -1,
                    'random_state': 42 + fold
                }
                
                model = lgb.train(
                    params,
                    train_data,
                    valid_sets=[val_data],
                    num_boost_round=100,
                    callbacks=[lgb.early_stopping(10), lgb.log_evaluation(0)]
                )
                
                fold_models[outcome_name] = model
            
            # Store models from first fold for final training
            if fold == 0:
                trained_models = fold_models.copy()
            
            # Generate predictions
            fold_residual_preds = np.zeros((len(val_idx), 3))
            
            for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
                fold_residual_preds[:, outcome_idx] = fold_models[outcome_name].predict(X_val_scaled)
            
            # Combine with consensus to get final probabilities
            consensus_val_clipped = np.clip(consensus_val.values, 1e-15, 1 - 1e-15)
            consensus_logits_val = np.log(consensus_val_clipped / (1 - consensus_val_clipped))
            
            final_logits = consensus_logits_val + fold_residual_preds
            
            # Convert to probabilities
            exp_logits = np.exp(final_logits)
            final_probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
            
            # Store predictions
            oof_residuals[val_idx] = fold_residual_preds
            oof_final_probs[val_idx] = final_probs
            
            # Calculate fold performance
            final_probs_clipped = np.clip(final_probs, 1e-15, 1 - 1e-15)
            consensus_val_clipped_eval = np.clip(consensus_val.values, 1e-15, 1 - 1e-15)
            
            fold_final_ll = -np.mean(np.sum(y_val_onehot * np.log(final_probs_clipped), axis=1))
            fold_consensus_ll = -np.mean(np.sum(y_val_onehot * np.log(consensus_val_clipped_eval), axis=1))
            fold_improvement = fold_consensus_ll - fold_final_ll
            
            fold_performances.append({
                'fold': fold + 1,
                'final_logloss': fold_final_ll,
                'consensus_logloss': fold_consensus_ll,
                'improvement': fold_improvement,
                'sample_size': len(val_idx)
            })
            
            print(f"Fold {fold + 1}: {fold_final_ll:.4f} final LL, improvement: {fold_improvement:.4f}")
        
        # Calculate overall performance
        oof_final_probs_clipped = np.clip(oof_final_probs, 1e-15, 1 - 1e-15)
        consensus_full_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        
        oof_final_ll = -np.mean(np.sum(y_onehot * np.log(oof_final_probs_clipped), axis=1))
        oof_consensus_ll = -np.mean(np.sum(y_onehot * np.log(consensus_full_clipped), axis=1))
        oof_improvement = oof_consensus_ll - oof_final_ll
        
        oof_final_brier = np.mean(np.sum((oof_final_probs - y_onehot) ** 2, axis=1))
        oof_consensus_brier = np.mean(np.sum((consensus_probs.values - y_onehot) ** 2, axis=1))
        oof_brier_improvement = oof_consensus_brier - oof_final_brier
        
        # Calculate accuracy
        oof_accuracy = np.mean(np.argmax(oof_final_probs, axis=1) == np.argmax(y_onehot, axis=1))
        
        return {
            'oof_final_logloss': oof_final_ll,
            'oof_consensus_logloss': oof_consensus_ll,
            'oof_logloss_improvement': oof_improvement,
            'oof_final_brier': oof_final_brier,
            'oof_consensus_brier': oof_consensus_brier,
            'oof_brier_improvement': oof_brier_improvement,
            'oof_accuracy': oof_accuracy,
            'fold_performances': fold_performances,
            'trained_models': trained_models,
            'feature_names': X.columns.tolist()
        }
    
    def train_final_model(self, X: pd.DataFrame, consensus_probs: pd.DataFrame, y: pd.Series) -> Dict:
        """Train final model on full dataset"""
        
        print("Training final model on full dataset...")
        
        # Convert targets and calculate residuals
        y_onehot = []
        for outcome in y:
            if outcome == 'H':
                y_onehot.append([1, 0, 0])
            elif outcome == 'D':
                y_onehot.append([0, 1, 0])
            elif outcome == 'A':
                y_onehot.append([0, 0, 1])
            else:
                y_onehot.append([1/3, 1/3, 1/3])
        
        y_onehot = np.array(y_onehot)
        
        consensus_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        consensus_logits = np.log(consensus_clipped / (1 - consensus_clipped))
        
        true_clipped = np.clip(y_onehot, 1e-15, 1 - 1e-15)
        true_logits = np.log(true_clipped / (1 - true_clipped))
        
        residual_targets = true_logits - consensus_logits
        
        # Scale features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Train final models
        final_models = {}
        feature_importance = {}
        
        for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
            print(f"Training final model for outcome {outcome_name}...")
            
            train_data = lgb.Dataset(X_scaled, label=residual_targets[:, outcome_idx])
            
            params = {
                'objective': 'regression',
                'metric': 'rmse',
                'boosting_type': 'gbdt',
                'num_leaves': 31,
                'learning_rate': 0.1,
                'feature_fraction': 0.8,
                'bagging_fraction': 0.8,
                'bagging_freq': 5,
                'verbose': -1,
                'random_state': 42
            }
            
            model = lgb.train(
                params,
                train_data,
                num_boost_round=100,
                callbacks=[lgb.log_evaluation(0)]
            )
            
            final_models[outcome_name] = model
            
            # Store feature importance
            importance = model.feature_importance(importance_type='gain')
            feature_importance[outcome_name] = dict(zip(X.columns, importance))
        
        return {
            'models': final_models,
            'scaler': scaler,
            'feature_importance': feature_importance,
            'feature_names': X.columns.tolist()
        }
    
    def run_fast_week2(self) -> Dict:
        """Run fast Week 2 implementation"""
        
        print("FAST WEEK 2 BOOK-AWARE IMPLEMENTATION")
        print("=" * 50)
        
        try:
            # Load consensus data
            df = self.load_consensus_data()
            print(f"Loaded {len(df)} matches with consensus data")
            
            # Build enhanced features
            df_enhanced = self.build_enhanced_features(df)
            
            # Prepare training data
            X, consensus_probs, y = self.prepare_training_data(df_enhanced)
            
            # Train with cross-validation
            cv_results = self.train_residual_model(X, consensus_probs, y)
            
            # Train final model
            final_model_data = self.train_final_model(X, consensus_probs, y)
            
            # Save models and results
            os.makedirs('models/fast_week2', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Save model
            model_path = f'models/fast_week2/fast_week2_model_{timestamp}.joblib'
            joblib.dump(final_model_data, model_path)
            
            # Save results
            results_path = f'models/fast_week2/fast_week2_results_{timestamp}.json'
            with open(results_path, 'w') as f:
                json.dump(cv_results, f, indent=2, default=str)
            
            # Compile final results
            results = {
                'timestamp': datetime.now().isoformat(),
                'cv_results': cv_results,
                'final_model_data': final_model_data,
                'model_path': model_path,
                'results_path': results_path,
                'dataset_info': {
                    'total_matches': len(df),
                    'feature_count': X.shape[1],
                    'leagues': df['league'].nunique() if 'league' in df.columns else 0,
                    'date_range': f"{df['match_date'].min()} to {df['match_date'].max()}" if 'match_date' in df.columns else 'Unknown'
                }
            }
            
            # Print summary
            self.print_week2_summary(results)
            
            return results
            
        finally:
            self.conn.close()
    
    def print_week2_summary(self, results: Dict):
        """Print comprehensive Week 2 summary"""
        
        print("\n" + "=" * 60)
        print("FAST WEEK 2 IMPLEMENTATION COMPLETE")
        print("=" * 60)
        
        cv_results = results['cv_results']
        dataset_info = results['dataset_info']
        
        print(f"\n📊 IMPLEMENTATION OVERVIEW:")
        print(f"   • Dataset Size: {dataset_info['total_matches']:,} matches")
        print(f"   • Feature Count: {dataset_info['feature_count']}")
        print(f"   • Leagues: {dataset_info['leagues']}")
        print(f"   • Date Range: {dataset_info['date_range']}")
        
        print(f"\n🎯 RESIDUAL MODEL PERFORMANCE:")
        print(f"   • Final Model LogLoss: {cv_results['oof_final_logloss']:.4f}")
        print(f"   • Consensus LogLoss: {cv_results['oof_consensus_logloss']:.4f}")
        print(f"   • LogLoss Improvement: {cv_results['oof_logloss_improvement']:.4f}")
        print(f"   • Final Model Brier: {cv_results['oof_final_brier']:.4f}")
        print(f"   • Brier Improvement: {cv_results['oof_brier_improvement']:.4f}")
        print(f"   • Accuracy: {cv_results['oof_accuracy']:.3f}")
        
        # Target assessment
        week2_target = 0.015
        current_baseline = 0.8157  # From previous results
        
        if cv_results['oof_logloss_improvement'] > 0:
            print(f"\n✅ RESIDUAL MODEL OUTPERFORMS CONSENSUS")
            expected_production = current_baseline - cv_results['oof_logloss_improvement']
            print(f"   Expected Production LogLoss: {expected_production:.4f}")
            
            if cv_results['oof_logloss_improvement'] >= week2_target:
                print(f"   🎯 WEEK 2 TARGET ACHIEVED: {cv_results['oof_logloss_improvement']:.4f} >= {week2_target:.4f}")
            else:
                print(f"   📊 Week 2 Progress: {cv_results['oof_logloss_improvement']:.4f} / {week2_target:.4f}")
        else:
            print(f"\n⚠️  Consensus still competitive ({abs(cv_results['oof_logloss_improvement']):.4f} difference)")
        
        print(f"\n📈 FOLD-BY-FOLD CONSISTENCY:")
        improvements = [fold['improvement'] for fold in cv_results['fold_performances']]
        print(f"   • Mean Improvement: {np.mean(improvements):.4f}")
        print(f"   • Std Improvement: {np.std(improvements):.4f}")
        print(f"   • Positive Folds: {sum(1 for imp in improvements if imp > 0)}/5")
        
        print(f"\n🔍 TOP FEATURES:")
        if 'feature_names' in cv_results:
            feature_names = cv_results['feature_names']
            print(f"   • Core Features: {len([f for f in feature_names if 'logit_cons' in f])} consensus logits")
            print(f"   • Dispersion Features: {len([f for f in feature_names if 'disp' in f])} dispersion metrics")
            print(f"   • Market Features: {len([f for f in feature_names if any(x in f for x in ['n_books', 'overround', 'confidence'])])} market intelligence")
        
        print(f"\n🚀 WEEK 2 STATUS:")
        if cv_results['oof_logloss_improvement'] >= week2_target:
            print(f"   ✅ TARGET ACHIEVED - Ready for verification bundle")
            print(f"   📈 Expected gain: {cv_results['oof_logloss_improvement']:.4f} LogLoss")
        else:
            print(f"   📊 Solid foundation - {cv_results['oof_logloss_improvement']:.4f} improvement demonstrated")
            print(f"   🔧 Consider additional book features or calibration tuning")
        
        print(f"\n📄 Files saved:")
        print(f"   • Model: {results['model_path']}")
        print(f"   • Results: {results['results_path']}")

def main():
    """Run fast Week 2 implementation"""
    
    implementer = FastWeek2Implementation()
    results = implementer.run_fast_week2()
    
    return results

if __name__ == "__main__":
    main()