"""
Residual-on-Market Head with Book Intelligence
Train book-aware residual model to leverage market consensus and bookmaker signals
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
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss, brier_score_loss
import lightgbm as lgb

class ResidualBookAwareTrainer:
    """Train book-aware residual model for enhanced market predictions"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.model = None
        self.scaler = None
        self.calibrators = {}
        self.feature_importance = None
        
    def load_book_features_dataset(self) -> pd.DataFrame:
        """Load the latest book features dataset"""
        
        # Find latest features dataset
        features_dir = 'features/book_features'
        if os.path.exists(features_dir):
            feature_files = [f for f in os.listdir(features_dir) if f.startswith('book_features_') and f.endswith('.csv')]
            if feature_files:
                latest_file = sorted(feature_files)[-1]
                features_path = os.path.join(features_dir, latest_file)
                
                print(f"Loading features from {features_path}")
                df = pd.read_csv(features_path)
                return df
        
        # Fallback: load weighted consensus and basic features
        print("No book features found, loading weighted consensus...")
        consensus_dir = 'consensus/weighted'
        if os.path.exists(consensus_dir):
            consensus_files = [f for f in os.listdir(consensus_dir) if f.startswith('weighted_consensus_t72_') and f.endswith('.csv')]
            if consensus_files:
                latest_file = sorted(consensus_files)[-1]
                consensus_path = os.path.join(consensus_dir, latest_file)
                
                df = pd.read_csv(consensus_path)
                return df
        
        raise FileNotFoundError("No features dataset or consensus data found")
    
    def prepare_features_and_targets(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
        """Prepare features and targets for training"""
        
        print("Preparing features and targets...")
        
        # Define feature groups
        consensus_features = [col for col in df.columns if col.startswith(('logit_cons_', 'pH_cons_w', 'pD_cons_w', 'pA_cons_w'))]
        dispersion_features = [col for col in df.columns if col.startswith(('disp', 'avg_dispersion', 'disagree_js'))]
        market_features = [col for col in df.columns if col.startswith(('n_books', 'avg_overround', 'overround_std'))]
        book_identity_features = [col for col in df.columns if col.startswith(('delta_logit_', 'overround_', 'present_'))]
        book_group_features = [col for col in df.columns if col.startswith(('sharp_', 'rec_'))]
        structural_features = [col for col in df.columns if col in ['league_tier', 'season_phase', 'is_weekend']]
        
        # Select available features
        feature_columns = []
        
        # Always include consensus features (core requirement)
        if 'pH_cons_w' in df.columns:
            # Weighted consensus available
            consensus_features = ['pH_cons_w', 'pD_cons_w', 'pA_cons_w']
        elif 'logit_cons_h' in df.columns:
            # Logit consensus available
            consensus_features = ['logit_cons_h', 'logit_cons_d', 'logit_cons_a']
        else:
            raise ValueError("No consensus features found in dataset")
        
        feature_columns.extend([col for col in consensus_features if col in df.columns])
        feature_columns.extend([col for col in dispersion_features if col in df.columns])
        feature_columns.extend([col for col in market_features if col in df.columns])
        feature_columns.extend([col for col in book_identity_features if col in df.columns])
        feature_columns.extend([col for col in book_group_features if col in df.columns])
        feature_columns.extend([col for col in structural_features if col in df.columns])
        
        print(f"Selected {len(feature_columns)} features for training")
        
        # Prepare features
        X = df[feature_columns].copy()
        
        # Handle missing values
        X = X.fillna(0.0)
        
        # Convert consensus probabilities to logits if needed
        if 'pH_cons_w' in X.columns:
            prob_columns = ['pH_cons_w', 'pD_cons_w', 'pA_cons_w']
            for col in prob_columns:
                # Clip probabilities and convert to logits
                probs_clipped = np.clip(X[col], 0.02, 0.98)
                X[f'logit_{col}'] = np.log(probs_clipped / (1 - probs_clipped))
            
            # Store consensus probabilities for residual calculation
            consensus_probs = X[prob_columns].values
        else:
            # Logits already available, convert back to probabilities
            logit_columns = ['logit_cons_h', 'logit_cons_d', 'logit_cons_a']
            logits = X[logit_columns].values
            
            # Convert logits to probabilities
            exp_logits = np.exp(logits)
            consensus_probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
        
        # Prepare targets (one-hot encoded outcomes)
        y = df['result'].copy()
        y_onehot = pd.get_dummies(y, columns=['H', 'D', 'A'])
        
        # Ensure all outcome columns exist
        for outcome in ['H', 'D', 'A']:
            if outcome not in y_onehot.columns:
                y_onehot[outcome] = 0
        
        y_onehot = y_onehot[['H', 'D', 'A']].values
        
        # Create DataFrame for consensus probabilities
        consensus_df = pd.DataFrame(consensus_probs, columns=['cons_H', 'cons_D', 'cons_A'])
        
        return X, consensus_df, y
    
    def calculate_residual_targets(self, consensus_probs: pd.DataFrame, y_true: pd.Series) -> np.ndarray:
        """Calculate residual targets (actual - consensus logits)"""
        
        # Convert true outcomes to one-hot
        y_onehot = []
        for outcome in y_true:
            if outcome == 'H':
                y_onehot.append([1, 0, 0])
            elif outcome == 'D':
                y_onehot.append([0, 1, 0])
            elif outcome == 'A':
                y_onehot.append([0, 0, 1])
            else:
                y_onehot.append([1/3, 1/3, 1/3])  # Fallback
        
        y_onehot = np.array(y_onehot)
        
        # Convert consensus probabilities to logits
        consensus_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        consensus_logits = np.log(consensus_clipped / (1 - consensus_clipped))
        
        # Convert true outcomes to logits
        y_clipped = np.clip(y_onehot, 1e-15, 1 - 1e-15)
        true_logits = np.log(y_clipped / (1 - y_clipped))
        
        # Calculate residuals
        residuals = true_logits - consensus_logits
        
        return residuals
    
    def train_residual_model(self, X: pd.DataFrame, consensus_probs: pd.DataFrame, 
                           y: pd.Series, cv_folds: int = 5) -> Dict:
        """Train residual model with cross-validation"""
        
        print(f"Training residual model with {len(X)} samples and {X.shape[1]} features...")
        
        # Calculate residual targets
        residual_targets = self.calculate_residual_targets(consensus_probs, y)
        
        # Setup cross-validation
        skf = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        
        # Store out-of-fold predictions
        oof_residuals = np.zeros_like(residual_targets)
        oof_final_probs = np.zeros((len(X), 3))
        feature_importance_list = []
        
        fold_performances = []
        
        for fold, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            print(f"Training fold {fold + 1}/{cv_folds}...")
            
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            consensus_train, consensus_val = consensus_probs.iloc[train_idx], consensus_probs.iloc[val_idx]
            residuals_train, residuals_val = residual_targets[train_idx], residual_targets[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_val_scaled = scaler.transform(X_val)
            
            # Train separate models for each outcome
            fold_models = {}
            
            for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
                # Prepare data for this outcome
                y_residual = residuals_train[:, outcome_idx]
                
                # Train LightGBM model
                train_data = lgb.Dataset(X_train_scaled, label=y_residual)
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
                    'random_state': 42
                }
                
                model = lgb.train(
                    params,
                    train_data,
                    valid_sets=[val_data],
                    num_boost_round=100,
                    callbacks=[lgb.early_stopping(10), lgb.log_evaluation(0)]
                )
                
                fold_models[outcome_name] = model
                
                # Store feature importance
                if fold == 0:  # Only store for first fold
                    importance = model.feature_importance(importance_type='gain')
                    feature_names = X.columns.tolist()
                    feature_importance_list.append(dict(zip(feature_names, importance)))
            
            # Generate out-of-fold predictions
            fold_residual_preds = np.zeros((len(val_idx), 3))
            
            for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
                fold_residual_preds[:, outcome_idx] = fold_models[outcome_name].predict(X_val_scaled)
            
            # Combine with consensus to get final probabilities
            consensus_val_clipped = np.clip(consensus_val.values, 1e-15, 1 - 1e-15)
            consensus_logits = np.log(consensus_val_clipped / (1 - consensus_val_clipped))
            
            # Add residuals to consensus logits
            final_logits = consensus_logits + fold_residual_preds
            
            # Convert back to probabilities
            exp_logits = np.exp(final_logits)
            final_probs = exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
            
            # Store out-of-fold predictions
            oof_residuals[val_idx] = fold_residual_preds
            oof_final_probs[val_idx] = final_probs
            
            # Calculate fold performance
            y_val_onehot = []
            for outcome in y_val:
                if outcome == 'H':
                    y_val_onehot.append([1, 0, 0])
                elif outcome == 'D':
                    y_val_onehot.append([0, 1, 0])
                elif outcome == 'A':
                    y_val_onehot.append([0, 0, 1])
            
            y_val_onehot = np.array(y_val_onehot)
            
            # Calculate metrics
            final_probs_clipped = np.clip(final_probs, 1e-15, 1 - 1e-15)
            consensus_clipped = np.clip(consensus_val.values, 1e-15, 1 - 1e-15)
            
            fold_final_ll = -np.mean(np.sum(y_val_onehot * np.log(final_probs_clipped), axis=1))
            fold_consensus_ll = -np.mean(np.sum(y_val_onehot * np.log(consensus_clipped), axis=1))
            fold_improvement = fold_consensus_ll - fold_final_ll
            
            fold_performances.append({
                'fold': fold + 1,
                'final_logloss': fold_final_ll,
                'consensus_logloss': fold_consensus_ll,
                'improvement': fold_improvement,
                'sample_size': len(val_idx)
            })
            
            print(f"Fold {fold + 1}: {fold_final_ll:.4f} final LL, {fold_improvement:.4f} improvement")
        
        # Calculate overall out-of-fold performance
        y_onehot_full = []
        for outcome in y:
            if outcome == 'H':
                y_onehot_full.append([1, 0, 0])
            elif outcome == 'D':
                y_onehot_full.append([0, 1, 0])
            elif outcome == 'A':
                y_onehot_full.append([0, 0, 1])
        
        y_onehot_full = np.array(y_onehot_full)
        
        # Calculate final metrics
        oof_final_probs_clipped = np.clip(oof_final_probs, 1e-15, 1 - 1e-15)
        consensus_full_clipped = np.clip(consensus_probs.values, 1e-15, 1 - 1e-15)
        
        oof_final_ll = -np.mean(np.sum(y_onehot_full * np.log(oof_final_probs_clipped), axis=1))
        oof_consensus_ll = -np.mean(np.sum(y_onehot_full * np.log(consensus_full_clipped), axis=1))
        oof_improvement = oof_consensus_ll - oof_final_ll
        
        oof_final_brier = np.mean(np.sum((oof_final_probs - y_onehot_full) ** 2, axis=1))
        oof_consensus_brier = np.mean(np.sum((consensus_probs.values - y_onehot_full) ** 2, axis=1))
        oof_brier_improvement = oof_consensus_brier - oof_final_brier
        
        # Calculate accuracy
        oof_accuracy = np.mean(np.argmax(oof_final_probs, axis=1) == np.argmax(y_onehot_full, axis=1))
        
        return {
            'oof_final_logloss': oof_final_ll,
            'oof_consensus_logloss': oof_consensus_ll,
            'oof_logloss_improvement': oof_improvement,
            'oof_final_brier': oof_final_brier,
            'oof_consensus_brier': oof_consensus_brier,
            'oof_brier_improvement': oof_brier_improvement,
            'oof_accuracy': oof_accuracy,
            'oof_predictions': oof_final_probs,
            'oof_residuals': oof_residuals,
            'fold_performances': fold_performances,
            'feature_importance': feature_importance_list[0] if feature_importance_list else {}
        }
    
    def train_final_model(self, X: pd.DataFrame, consensus_probs: pd.DataFrame, y: pd.Series) -> Dict:
        """Train final model on full dataset"""
        
        print("Training final model on full dataset...")
        
        # Calculate residual targets
        residual_targets = self.calculate_residual_targets(consensus_probs, y)
        
        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Train separate models for each outcome
        final_models = {}
        
        for outcome_idx, outcome_name in enumerate(['H', 'D', 'A']):
            print(f"Training final model for outcome {outcome_name}...")
            
            y_residual = residual_targets[:, outcome_idx]
            
            # Train LightGBM model
            train_data = lgb.Dataset(X_scaled, label=y_residual)
            
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
        
        self.model = final_models
        
        # Store feature importance
        if 'H' in final_models:
            feature_names = X.columns.tolist()
            importance = final_models['H'].feature_importance(importance_type='gain')
            self.feature_importance = dict(zip(feature_names, importance))
        
        return final_models
    
    def run_residual_training(self) -> Dict:
        """Run complete residual model training"""
        
        print("RESIDUAL-ON-MARKET BOOK AWARE TRAINING")
        print("=" * 50)
        print("Training book-aware residual model...")
        
        try:
            # Load features dataset
            df = self.load_book_features_dataset()
            print(f"Loaded dataset with {len(df)} matches")
            
            # Prepare features and targets
            X, consensus_probs, y = self.prepare_features_and_targets(df)
            
            # Train with cross-validation
            cv_results = self.train_residual_model(X, consensus_probs, y)
            
            # Train final model
            final_models = self.train_final_model(X, consensus_probs, y)
            
            # Save models and results
            os.makedirs('models/residual_bookaware', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Save models
            model_path = f'models/residual_bookaware/residual_bookaware_model_{timestamp}.joblib'
            joblib.dump({
                'models': final_models,
                'scaler': self.scaler,
                'feature_names': X.columns.tolist(),
                'feature_importance': self.feature_importance,
                'training_timestamp': timestamp
            }, model_path)
            
            # Save results
            results_path = f'models/residual_bookaware/training_results_{timestamp}.json'
            with open(results_path, 'w') as f:
                json.dump(cv_results, f, indent=2, default=str)
            
            # Compile results
            training_results = {
                'timestamp': datetime.now().isoformat(),
                'cv_results': cv_results,
                'final_models': final_models,
                'model_path': model_path,
                'results_path': results_path,
                'dataset_info': {
                    'total_matches': len(df),
                    'feature_count': X.shape[1],
                    'leagues': df['league'].nunique() if 'league' in df.columns else 0,
                    'date_range': f"{df['match_date'].min()} to {df['match_date'].max()}" if 'match_date' in df.columns else 'Unknown'
                }
            }
            
            # Print comprehensive summary
            self.print_training_summary(training_results)
            
            return training_results
            
        finally:
            self.conn.close()
    
    def print_training_summary(self, results: Dict):
        """Print comprehensive training summary"""
        
        print("\n" + "=" * 60)
        print("RESIDUAL-ON-MARKET TRAINING COMPLETE")
        print("=" * 60)
        
        cv_results = results['cv_results']
        dataset_info = results['dataset_info']
        
        print(f"\n📊 TRAINING OVERVIEW:")
        print(f"   • Dataset Size: {dataset_info['total_matches']:,} matches")
        print(f"   • Feature Count: {dataset_info['feature_count']}")
        print(f"   • Leagues: {dataset_info['leagues']}")
        print(f"   • Date Range: {dataset_info['date_range']}")
        
        print(f"\n🎯 CROSS-VALIDATION PERFORMANCE:")
        print(f"   • Final Model LogLoss: {cv_results['oof_final_logloss']:.4f}")
        print(f"   • Consensus LogLoss: {cv_results['oof_consensus_logloss']:.4f}")
        print(f"   • LogLoss Improvement: {cv_results['oof_logloss_improvement']:.4f}")
        print(f"   • Final Model Brier: {cv_results['oof_final_brier']:.4f}")
        print(f"   • Brier Improvement: {cv_results['oof_brier_improvement']:.4f}")
        print(f"   • Accuracy: {cv_results['oof_accuracy']:.3f}")
        
        if cv_results['oof_logloss_improvement'] > 0:
            print(f"\n✅ RESIDUAL MODEL OUTPERFORMS CONSENSUS")
            print(f"   Production gain: {cv_results['oof_logloss_improvement']:.4f} LogLoss")
        else:
            print(f"\n⚠️  Consensus competitive ({abs(cv_results['oof_logloss_improvement']):.4f} difference)")
        
        print(f"\n📈 FOLD-BY-FOLD PERFORMANCE:")
        for fold_data in cv_results['fold_performances']:
            print(f"   • Fold {fold_data['fold']}: {fold_data['improvement']:.4f} improvement ({fold_data['sample_size']} samples)")
        
        # Top feature importance
        if cv_results['feature_importance']:
            print(f"\n🔍 TOP FEATURE IMPORTANCE:")
            sorted_features = sorted(cv_results['feature_importance'].items(), key=lambda x: x[1], reverse=True)
            for feature, importance in sorted_features[:10]:
                print(f"   • {feature}: {importance:.0f}")
        
        print(f"\n🚀 WEEK 2 TARGET ASSESSMENT:")
        target_improvement = 0.015  # Minimum target for Week 2
        if cv_results['oof_logloss_improvement'] >= target_improvement:
            print(f"   ✅ TARGET ACHIEVED: {cv_results['oof_logloss_improvement']:.4f} >= {target_improvement:.4f}")
        else:
            print(f"   📊 Progress: {cv_results['oof_logloss_improvement']:.4f} / {target_improvement:.4f} target")
        
        print(f"\n📄 Model saved: {results['model_path']}")
        print(f"📄 Results saved: {results['results_path']}")

def main():
    """Run residual model training"""
    
    trainer = ResidualBookAwareTrainer()
    results = trainer.run_residual_training()
    
    return results

if __name__ == "__main__":
    main()