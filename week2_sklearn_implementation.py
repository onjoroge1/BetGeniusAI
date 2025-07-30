"""
Week 2 Sklearn Implementation
Book-aware residual training using sklearn models
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
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import log_loss, brier_score_loss

class Week2SklearnImplementation:
    """Week 2 implementation using sklearn models"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def load_consensus_data(self) -> pd.DataFrame:
        """Load weighted consensus data"""
        
        consensus_dir = 'consensus/weighted'
        if os.path.exists(consensus_dir):
            consensus_files = [f for f in os.listdir(consensus_dir) if f.startswith('weighted_consensus_t72_') and f.endswith('.csv')]
            if consensus_files:
                latest_file = sorted(consensus_files)[-1]
                consensus_path = os.path.join(consensus_dir, latest_file)
                
                print(f"Loading consensus data from {consensus_path}")
                df = pd.read_csv(consensus_path)
                return df
        
        print("Creating basic consensus from historical data...")
        return self.create_basic_consensus()
    
    def create_basic_consensus(self) -> pd.DataFrame:
        """Create basic consensus from historical odds"""
        
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
                        prob_h = 1.0 / odds_h
                        prob_d = 1.0 / odds_d
                        prob_a = 1.0 / odds_a
                        
                        total = prob_h + prob_d + prob_a
                        if total > 0:
                            valid_probs.append([prob_h/total, prob_d/total, prob_a/total])
            
            if valid_probs:
                consensus = np.mean(valid_probs, axis=0)
                
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
                    'avg_overround': 1.0,
                    'disagree_js': np.std(valid_probs, axis=0).mean() if len(valid_probs) > 1 else 0.0
                })
        
        return pd.DataFrame(consensus_data)
    
    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build comprehensive features"""
        
        print("Building enhanced features...")
        
        # Ensure required columns exist
        required_cols = ['pH_cons_w', 'pD_cons_w', 'pA_cons_w']
        for col in required_cols:
            if col not in df.columns:
                df[col] = 1/3  # Default uniform probability
        
        # Fill missing dispersion columns
        for col in ['dispH', 'dispD', 'dispA']:
            if col not in df.columns:
                df[col] = 0.0
        
        if 'n_books' not in df.columns:
            df['n_books'] = 3.0
        
        if 'avg_overround' not in df.columns:
            df['avg_overround'] = 1.0
        
        if 'disagree_js' not in df.columns:
            df['disagree_js'] = 0.0
        
        # Convert consensus probabilities to logits
        df['logit_cons_h'] = np.log(np.clip(df['pH_cons_w'], 0.02, 0.98) / np.clip(1 - df['pH_cons_w'], 0.02, 0.98))
        df['logit_cons_d'] = np.log(np.clip(df['pD_cons_w'], 0.02, 0.98) / np.clip(1 - df['pD_cons_w'], 0.02, 0.98))
        df['logit_cons_a'] = np.log(np.clip(df['pA_cons_w'], 0.02, 0.98) / np.clip(1 - df['pA_cons_w'], 0.02, 0.98))
        
        # Market intelligence features
        df['total_dispersion'] = df['dispH'] + df['dispD'] + df['dispA']
        df['max_dispersion'] = np.maximum.reduce([df['dispH'], df['dispD'], df['dispA']])
        df['market_confidence'] = 1.0 / (1.0 + df['total_dispersion'])
        df['book_coverage_pct'] = df['n_books'] / 8.0
        
        # League features
        league_mapping = {'E0': 1, 'SP1': 1, 'I1': 1, 'D1': 1, 'F1': 1}
        df['league_tier'] = df['league'].map(league_mapping).fillna(2)
        
        # Temporal features
        df['match_date_dt'] = pd.to_datetime(df['match_date'])
        df['month'] = df['match_date_dt'].dt.month
        df['is_weekend'] = (df['match_date_dt'].dt.weekday >= 5).astype(int)
        
        # Season phase
        season_phase_map = {8: 0, 9: 0, 10: 0, 11: 1, 12: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2}
        df['season_phase'] = df['month'].map(season_phase_map).fillna(1)
        
        # Interaction features
        df['dispersion_x_books'] = df['total_dispersion'] * df['n_books']
        df['confidence_x_tier'] = df['market_confidence'] * df['league_tier']
        df['overround_deviation'] = df['avg_overround'] - 1.0
        
        return df
    
    def prepare_training_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
        """Prepare training data"""
        
        print("Preparing training data...")
        
        # Select features
        feature_columns = [
            'logit_cons_h', 'logit_cons_d', 'logit_cons_a',
            'dispH', 'dispD', 'dispA',
            'total_dispersion', 'max_dispersion', 'market_confidence',
            'n_books', 'book_coverage_pct', 'avg_overround', 'overround_deviation',
            'league_tier', 'is_weekend', 'season_phase',
            'dispersion_x_books', 'confidence_x_tier', 'disagree_js'
        ]
        
        available_features = [col for col in feature_columns if col in df.columns]
        print(f"Using {len(available_features)} features")
        
        X = df[available_features].copy()
        X = X.fillna(0.0)
        
        consensus_probs = df[['pH_cons_w', 'pD_cons_w', 'pA_cons_w']].copy()
        y = df['result'].copy()
        
        return X, consensus_probs, y
    
    def train_residual_model(self, X: pd.DataFrame, consensus_probs: pd.DataFrame, y: pd.Series) -> Dict:
        """Train residual model using sklearn"""
        
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
        
        # Calculate residual targets
        consensus_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        consensus_logits = np.log(consensus_clipped / (1 - consensus_clipped))
        
        true_clipped = np.clip(y_onehot, 1e-15, 1 - 1e-15)
        true_logits = np.log(true_clipped / (1 - true_clipped))
        
        residual_targets = true_logits - consensus_logits
        
        # Cross-validation
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
                # Use Random Forest for residual prediction
                model = RandomForestRegressor(
                    n_estimators=100,
                    max_depth=10,
                    min_samples_split=20,
                    min_samples_leaf=10,
                    random_state=42 + fold,
                    n_jobs=-1
                )
                
                model.fit(X_train_scaled, residuals_train[:, outcome_idx])
                fold_models[outcome_name] = (model, scaler)
            
            if fold == 0:
                trained_models = fold_models.copy()
            
            # Generate predictions
            fold_residual_preds = np.zeros((len(val_idx), 3))
            
            for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
                model, _ = fold_models[outcome_name]
                fold_residual_preds[:, outcome_idx] = model.predict(X_val_scaled)
            
            # Combine with consensus
            consensus_val_clipped = np.clip(consensus_val.values, 1e-15, 1 - 1e-15)
            consensus_logits_val = np.log(consensus_val_clipped / (1 - consensus_val_clipped))
            
            final_logits = consensus_logits_val + fold_residual_preds
            
            # Convert to probabilities
            exp_logits = np.exp(final_logits)
            final_probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
            
            # Store predictions
            oof_residuals[val_idx] = fold_residual_preds
            oof_final_probs[val_idx] = final_probs
            
            # Calculate performance
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
        
        # Overall performance
        oof_final_probs_clipped = np.clip(oof_final_probs, 1e-15, 1 - 1e-15)
        consensus_full_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        
        oof_final_ll = -np.mean(np.sum(y_onehot * np.log(oof_final_probs_clipped), axis=1))
        oof_consensus_ll = -np.mean(np.sum(y_onehot * np.log(consensus_full_clipped), axis=1))
        oof_improvement = oof_consensus_ll - oof_final_ll
        
        oof_final_brier = np.mean(np.sum((oof_final_probs - y_onehot) ** 2, axis=1))
        oof_consensus_brier = np.mean(np.sum((consensus_probs.values - y_onehot) ** 2, axis=1))
        oof_brier_improvement = oof_consensus_brier - oof_final_brier
        
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
        
        # Convert and calculate residuals
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
            
            model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                min_samples_split=20,
                min_samples_leaf=10,
                random_state=42,
                n_jobs=-1
            )
            
            model.fit(X_scaled, residual_targets[:, outcome_idx])
            final_models[outcome_name] = model
            
            # Feature importance
            feature_importance[outcome_name] = dict(zip(X.columns, model.feature_importances_))
        
        return {
            'models': final_models,
            'scaler': scaler,
            'feature_importance': feature_importance,
            'feature_names': X.columns.tolist()
        }
    
    def generate_verification_report(self, results: Dict) -> Dict:
        """Generate verification report for Week 2"""
        
        cv_results = results['cv_results']
        
        # Week 2 targets
        week2_logloss_target = 0.015
        week2_brier_target = 0.005
        
        verification = {
            'logloss_improvement': cv_results['oof_logloss_improvement'],
            'brier_improvement': cv_results['oof_brier_improvement'],
            'accuracy': cv_results['oof_accuracy'],
            'targets': {
                'logloss_target': week2_logloss_target,
                'logloss_achieved': cv_results['oof_logloss_improvement'] >= week2_logloss_target,
                'brier_target': week2_brier_target,
                'brier_achieved': cv_results['oof_brier_improvement'] >= week2_brier_target
            },
            'fold_consistency': {
                'positive_folds': sum(1 for fold in cv_results['fold_performances'] if fold['improvement'] > 0),
                'total_folds': len(cv_results['fold_performances']),
                'mean_improvement': np.mean([fold['improvement'] for fold in cv_results['fold_performances']]),
                'std_improvement': np.std([fold['improvement'] for fold in cv_results['fold_performances']])
            }
        }
        
        return verification
    
    def run_week2_sklearn(self) -> Dict:
        """Run complete Week 2 sklearn implementation"""
        
        print("WEEK 2 SKLEARN IMPLEMENTATION")
        print("=" * 50)
        
        try:
            # Load and prepare data
            df = self.load_consensus_data()
            print(f"Loaded {len(df)} matches")
            
            df_enhanced = self.build_features(df)
            X, consensus_probs, y = self.prepare_training_data(df_enhanced)
            
            # Train models
            cv_results = self.train_residual_model(X, consensus_probs, y)
            final_model_data = self.train_final_model(X, consensus_probs, y)
            
            # Generate verification
            verification = self.generate_verification_report({'cv_results': cv_results})
            
            # Save results
            os.makedirs('models/week2_sklearn', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            model_path = f'models/week2_sklearn/week2_sklearn_model_{timestamp}.joblib'
            joblib.dump(final_model_data, model_path)
            
            results_path = f'models/week2_sklearn/week2_sklearn_results_{timestamp}.json'
            with open(results_path, 'w') as f:
                json.dump({
                    'cv_results': cv_results,
                    'verification': verification
                }, f, indent=2, default=str)
            
            # Compile results
            results = {
                'timestamp': datetime.now().isoformat(),
                'cv_results': cv_results,
                'final_model_data': final_model_data,
                'verification': verification,
                'model_path': model_path,
                'results_path': results_path,
                'dataset_info': {
                    'total_matches': len(df),
                    'feature_count': X.shape[1],
                    'leagues': df['league'].nunique(),
                    'date_range': f"{df['match_date'].min()} to {df['match_date'].max()}"
                }
            }
            
            self.print_week2_summary(results)
            
            return results
            
        finally:
            self.conn.close()
    
    def print_week2_summary(self, results: Dict):
        """Print comprehensive Week 2 summary"""
        
        print("\n" + "=" * 60)
        print("WEEK 2 SKLEARN IMPLEMENTATION COMPLETE")
        print("=" * 60)
        
        cv_results = results['cv_results']
        verification = results['verification']
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
        
        print(f"\n🎯 WEEK 2 TARGET ASSESSMENT:")
        targets = verification['targets']
        print(f"   • LogLoss Target: {targets['logloss_target']:.4f}")
        print(f"   • LogLoss Achieved: {'✅ Yes' if targets['logloss_achieved'] else '❌ No'} ({cv_results['oof_logloss_improvement']:.4f})")
        print(f"   • Brier Target: {targets['brier_target']:.4f}")
        print(f"   • Brier Achieved: {'✅ Yes' if targets['brier_achieved'] else '❌ No'} ({cv_results['oof_brier_improvement']:.4f})")
        
        consistency = verification['fold_consistency']
        print(f"\n📈 FOLD CONSISTENCY:")
        print(f"   • Positive Folds: {consistency['positive_folds']}/{consistency['total_folds']}")
        print(f"   • Mean Improvement: {consistency['mean_improvement']:.4f}")
        print(f"   • Std Improvement: {consistency['std_improvement']:.4f}")
        
        current_baseline = 0.8157
        if cv_results['oof_logloss_improvement'] > 0:
            expected_production = current_baseline - cv_results['oof_logloss_improvement']
            print(f"\n🚀 PRODUCTION PROJECTION:")
            print(f"   • Current Baseline: {current_baseline:.4f}")
            print(f"   • Expected Production: {expected_production:.4f}")
            
            if expected_production <= 0.80:
                print(f"   ✅ WEEK 2 TARGET ACHIEVED: {expected_production:.4f} ≤ 0.80")
            else:
                print(f"   📊 Progress toward 0.79-0.80 target: {expected_production:.4f}")
        
        print(f"\n📄 Files saved:")
        print(f"   • Model: {results['model_path']}")
        print(f"   • Results: {results['results_path']}")

def main():
    """Run Week 2 sklearn implementation"""
    
    implementer = Week2SklearnImplementation()
    results = implementer.run_week2_sklearn()
    
    return results

if __name__ == "__main__":
    main()