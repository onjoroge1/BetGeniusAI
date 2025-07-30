"""
Training Matches ML Evaluator - Using real 1,893 training_matches data
Establish proper baselines and test enhanced features
"""

import os
import json
import numpy as np
import pandas as pd
import psycopg2
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
import warnings
warnings.filterwarnings('ignore')

class TrainingMatchesEvaluator:
    """Comprehensive evaluation using real training_matches data"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.results = {}
        
    def load_training_data(self) -> pd.DataFrame:
        """Load and process training_matches data"""
        
        print("LOADING TRAINING MATCHES DATA")
        print("=" * 40)
        
        query = """
        SELECT 
            id,
            match_id,
            league_id,
            season,
            home_team,
            away_team,
            match_date,
            outcome,
            home_goals,
            away_goals,
            features,
            collection_phase,
            region
        FROM training_matches 
        WHERE outcome IS NOT NULL 
        AND features IS NOT NULL
        ORDER BY match_date
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        print(f"Loaded {len(df)} matches with complete data")
        print(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
        print(f"Leagues: {df['league_id'].nunique()}")
        print(f"Outcomes: {df['outcome'].value_counts().to_dict()}")
        
        return df
    
    def extract_features_from_jsonb(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract features from JSONB column and create feature matrix"""
        
        print(f"\nEXTRACTING FEATURES FROM JSONB")
        print("=" * 40)
        
        # Extract all unique feature keys
        all_features = set()
        for features_dict in df['features']:
            if isinstance(features_dict, dict):
                all_features.update(features_dict.keys())
        
        print(f"Found {len(all_features)} unique features:")
        
        # Create feature matrix
        feature_matrix = []
        feature_names = sorted(list(all_features))
        
        for _, row in df.iterrows():
            features_dict = row['features']
            feature_row = []
            
            for feature_name in feature_names:
                if isinstance(features_dict, dict) and feature_name in features_dict:
                    value = features_dict[feature_name]
                    
                    # Convert to numeric
                    if isinstance(value, (int, float)):
                        feature_row.append(float(value))
                    elif isinstance(value, bool):
                        feature_row.append(float(value))
                    elif isinstance(value, str):
                        try:
                            feature_row.append(float(value))
                        except:
                            feature_row.append(0.0)  # Default for non-numeric strings
                    else:
                        feature_row.append(0.0)
                else:
                    feature_row.append(0.0)  # Missing feature
            
            feature_matrix.append(feature_row)
        
        # Create feature DataFrame
        feature_df = pd.DataFrame(feature_matrix, columns=feature_names)
        
        # Add basic derived features
        if 'home_goals' in df.columns and 'away_goals' in df.columns:
            feature_df['goal_difference'] = df['home_goals'] - df['away_goals']
            feature_df['total_goals'] = df['home_goals'] + df['away_goals']
        
        # Add league context features
        feature_df['league_id'] = df['league_id']
        feature_df['season'] = df['season']
        
        print(f"Created feature matrix: {feature_df.shape}")
        print(f"Feature completeness: {(feature_df != 0).sum().sum() / (feature_df.shape[0] * feature_df.shape[1]) * 100:.1f}%")
        
        # Show key features
        print(f"\nKey features available:")
        key_features = [col for col in feature_names if any(term in col.lower() for term in 
                       ['competitiveness', 'advantage', 'importance', 'expectancy', 'quality'])][:10]
        for feature in key_features:
            print(f"  {feature}: mean={feature_df[feature].mean():.3f}, std={feature_df[feature].std():.3f}")
        
        return feature_df, feature_names
    
    def calculate_baselines(self, y_true: np.ndarray) -> Dict:
        """Calculate baseline performance metrics"""
        
        print(f"\nCALCULATING BASELINES")
        print("=" * 40)
        
        # Get outcome distribution
        unique, counts = np.unique(y_true, return_counts=True)
        outcome_dist = dict(zip(unique, counts))
        total = len(y_true)
        
        print(f"Outcome distribution: {outcome_dist}")
        
        baselines = {}
        
        # 1. Uniform baseline (33.33% each outcome)
        uniform_probs = np.full((len(y_true), 3), 1/3)
        uniform_preds = np.full(len(y_true), 1)  # Always predict draw (middle class)
        
        baselines['uniform'] = {
            'accuracy': accuracy_score(y_true, uniform_preds),
            'log_loss': log_loss(y_true, uniform_probs),
            'brier_score': self._multiclass_brier_score(y_true, uniform_probs),
            'description': 'Uniform 33.33% probability for each outcome'
        }
        
        # 2. Frequency baseline (predict based on historical frequencies)
        freq_probs = np.zeros((len(y_true), 3))
        class_probs = [outcome_dist.get(i, 0) / total for i in range(3)]
        
        for i in range(len(y_true)):
            freq_probs[i] = class_probs
        
        freq_preds = np.full(len(y_true), np.argmax(class_probs))
        
        baselines['frequency'] = {
            'accuracy': accuracy_score(y_true, freq_preds),
            'log_loss': log_loss(y_true, freq_probs),
            'brier_score': self._multiclass_brier_score(y_true, freq_probs),
            'description': f'Historical frequencies: {[f"{p:.1%}" for p in class_probs]}'
        }
        
        # 3. Random baseline (random predictions)
        np.random.seed(42)
        random_preds = np.random.choice(3, len(y_true))
        random_probs = np.random.dirichlet([1, 1, 1], len(y_true))
        
        baselines['random'] = {
            'accuracy': accuracy_score(y_true, random_preds),
            'log_loss': log_loss(y_true, random_probs),
            'brier_score': self._multiclass_brier_score(y_true, random_probs),
            'description': 'Random predictions with Dirichlet probabilities'
        }
        
        print(f"\nBaseline Results:")
        for name, metrics in baselines.items():
            print(f"{name.upper():10} | Accuracy: {metrics['accuracy']:.3f} | LogLoss: {metrics['log_loss']:.4f} | Brier: {metrics['brier_score']:.4f}")
        
        return baselines
    
    def _multiclass_brier_score(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Calculate multiclass Brier score"""
        y_true_binary = np.zeros((len(y_true), y_prob.shape[1]))
        for i, label in enumerate(y_true):
            y_true_binary[i, label] = 1
        
        return np.mean(np.sum((y_prob - y_true_binary) ** 2, axis=1))
    
    def train_enhanced_models(self, X: pd.DataFrame, y: np.ndarray, baselines: Dict, feature_names: List[str]) -> Dict:
        """Train and evaluate enhanced models"""
        
        print(f"\nTRAINING ENHANCED MODELS")
        print("=" * 40)
        
        # Time-aware split (last 20% as test set)
        split_idx = int(0.8 * len(X))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        print(f"Training set: {len(X_train)} matches")
        print(f"Test set: {len(X_test)} matches")
        
        models = {}
        
        # 1. Random Forest with comprehensive features
        print(f"\nTraining Random Forest...")
        
        # Select most informative features (remove constant/near-constant ones)
        feature_variance = X_train.var()
        informative_features = feature_variance[feature_variance > 0.001].index.tolist()
        print(f"Using {len(informative_features)} informative features")
        
        X_train_selected = X_train[informative_features]
        X_test_selected = X_test[informative_features]
        
        rf = RandomForestClassifier(
            n_estimators=200,
            max_depth=10,
            min_samples_split=10,
            min_samples_leaf=5,
            random_state=42,
            class_weight='balanced'
        )
        
        rf.fit(X_train_selected, y_train)
        
        # Get calibrated probabilities
        rf_calibrated = CalibratedClassifierCV(rf, method='isotonic', cv=3)
        rf_calibrated.fit(X_train_selected, y_train)
        
        rf_probs = rf_calibrated.predict_proba(X_test_selected)
        rf_preds = rf.predict(X_test_selected)
        
        models['random_forest'] = {
            'accuracy': accuracy_score(y_test, rf_preds),
            'log_loss': log_loss(y_test, rf_probs),
            'brier_score': self._multiclass_brier_score(y_test, rf_probs),
            'model': rf_calibrated,
            'features_used': informative_features,
            'description': f'Random Forest with {len(informative_features)} features + isotonic calibration'
        }
        
        # 2. Logistic Regression with feature scaling
        print(f"Training Logistic Regression...")
        
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train_selected)
        X_test_scaled = scaler.transform(X_test_selected)
        
        lr = LogisticRegression(
            max_iter=1000,
            random_state=42,
            class_weight='balanced',
            multi_class='multinomial',
            solver='lbfgs'
        )
        
        lr.fit(X_train_scaled, y_train)
        
        lr_probs = lr.predict_proba(X_test_scaled)
        lr_preds = lr.predict(X_test_scaled)
        
        models['logistic_regression'] = {
            'accuracy': accuracy_score(y_test, lr_preds),
            'log_loss': log_loss(y_test, lr_probs),
            'brier_score': self._multiclass_brier_score(y_test, lr_probs),
            'model': lr,
            'scaler': scaler,
            'features_used': informative_features,
            'description': f'Logistic Regression with scaling and {len(informative_features)} features'
        }
        
        # 3. Feature importance analysis
        feature_importance = pd.DataFrame({
            'feature': informative_features,
            'importance': rf.feature_importances_
        }).sort_values('importance', ascending=False)
        
        print(f"\nTop 10 Most Important Features:")
        for _, row in feature_importance.head(10).iterrows():
            print(f"  {row['feature']}: {row['importance']:.4f}")
        
        models['feature_importance'] = feature_importance
        
        return models, y_test
    
    def compare_against_baselines(self, models: Dict, baselines: Dict, y_test: np.ndarray) -> Dict:
        """Compare model performance against baselines"""
        
        print(f"\nMODEL VS BASELINE COMPARISON")
        print("=" * 50)
        
        comparison = {}
        
        print(f"{'Model':<20} | {'Accuracy':<8} | {'LogLoss':<8} | {'Brier':<8} | {'vs Uniform':<10} | {'vs Freq':<10}")
        print("-" * 80)
        
        # Baselines first
        for baseline_name, baseline_metrics in baselines.items():
            print(f"{baseline_name.upper():<20} | {baseline_metrics['accuracy']:.3f}   | {baseline_metrics['log_loss']:.4f} | {baseline_metrics['brier_score']:.4f} | {'BASELINE':<10} | {'BASELINE':<10}")
        
        print("-" * 80)
        
        # Models
        for model_name, model_metrics in models.items():
            if model_name == 'feature_importance':
                continue
                
            accuracy = model_metrics['accuracy']
            log_loss_val = model_metrics['log_loss']
            brier_score = model_metrics['brier_score']
            
            # Calculate improvements
            uniform_acc_improvement = (accuracy - baselines['uniform']['accuracy']) / baselines['uniform']['accuracy'] * 100
            freq_acc_improvement = (accuracy - baselines['frequency']['accuracy']) / baselines['frequency']['accuracy'] * 100
            
            uniform_logloss_improvement = (baselines['uniform']['log_loss'] - log_loss_val) / baselines['uniform']['log_loss'] * 100
            freq_logloss_improvement = (baselines['frequency']['log_loss'] - log_loss_val) / baselines['frequency']['log_loss'] * 100
            
            comparison[model_name] = {
                'accuracy': accuracy,
                'log_loss': log_loss_val,
                'brier_score': brier_score,
                'uniform_acc_improvement': uniform_acc_improvement,
                'freq_acc_improvement': freq_acc_improvement,
                'uniform_logloss_improvement': uniform_logloss_improvement,
                'freq_logloss_improvement': freq_logloss_improvement
            }
            
            print(f"{model_name.upper():<20} | {accuracy:.3f}   | {log_loss_val:.4f} | {brier_score:.4f} | {uniform_acc_improvement:+5.1f}%     | {freq_acc_improvement:+5.1f}%")
        
        return comparison
    
    def save_comprehensive_results(self, df: pd.DataFrame, feature_names: List[str], 
                                  baselines: Dict, models: Dict, comparison: Dict) -> str:
        """Save comprehensive evaluation results"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        results = {
            'timestamp': timestamp,
            'dataset_info': {
                'total_matches': len(df),
                'date_range': f"{df['match_date'].min()} to {df['match_date'].max()}",
                'leagues': df['league_id'].nunique(),
                'outcome_distribution': df['outcome'].value_counts().to_dict(),
                'features_extracted': len(feature_names)
            },
            'baselines': baselines,
            'models': {k: v for k, v in models.items() if k != 'feature_importance'},
            'comparison': comparison,
            'feature_importance': models.get('feature_importance', pd.DataFrame()).head(20).to_dict('records') if 'feature_importance' in models else []
        }
        
        # Save JSON results
        os.makedirs('reports', exist_ok=True)
        json_path = f'reports/training_matches_evaluation_{timestamp}.json'
        
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        # Save markdown report
        md_path = f'reports/training_matches_evaluation_{timestamp}.md'
        
        report = f"""# Training Matches ML Evaluation Report
*Generated: {timestamp}*

## Dataset Overview
- **Total Matches**: {len(df):,}
- **Date Range**: {df['match_date'].min()} to {df['match_date'].max()}
- **Leagues**: {df['league_id'].nunique()}
- **Features Extracted**: {len(feature_names)}

## Outcome Distribution
{df['outcome'].value_counts().to_dict()}

## Baseline Performance

| Baseline | Accuracy | LogLoss | Brier Score | Description |
|----------|----------|---------|-------------|-------------|
"""
        
        for name, metrics in baselines.items():
            report += f"| {name.title()} | {metrics['accuracy']:.3f} | {metrics['log_loss']:.4f} | {metrics['brier_score']:.4f} | {metrics['description']} |\n"
        
        report += f"""
## Model Performance

| Model | Accuracy | LogLoss | Brier Score | vs Uniform | vs Frequency |
|-------|----------|---------|-------------|------------|--------------|
"""
        
        for model_name, metrics in comparison.items():
            report += f"| {model_name.replace('_', ' ').title()} | {metrics['accuracy']:.3f} | {metrics['log_loss']:.4f} | {metrics['brier_score']:.4f} | {metrics['uniform_acc_improvement']:+.1f}% | {metrics['freq_acc_improvement']:+.1f}% |\n"
        
        if 'feature_importance' in models:
            report += f"""
## Top 10 Feature Importance

| Rank | Feature | Importance |
|------|---------|------------|
"""
            for i, (_, row) in enumerate(models['feature_importance'].head(10).iterrows(), 1):
                report += f"| {i} | {row['feature']} | {row['importance']:.4f} |\n"
        
        with open(md_path, 'w') as f:
            f.write(report)
        
        return json_path, md_path

def main():
    """Run comprehensive training matches evaluation"""
    
    evaluator = TrainingMatchesEvaluator()
    
    try:
        # Load data
        df = evaluator.load_training_data()
        
        if len(df) == 0:
            print("No training data found!")
            return
        
        # Extract features
        feature_df, feature_names = evaluator.extract_features_from_jsonb(df)
        
        # Prepare target variable (convert outcome to numeric)
        outcome_mapping = {'Home': 0, 'Draw': 1, 'Away': 2}  # Home, Draw, Away
        y = df['outcome'].map(outcome_mapping).values
        
        # Check for any unmapped outcomes
        unmapped = df[df['outcome'].isin(outcome_mapping.keys()) == False]['outcome'].unique()
        if len(unmapped) > 0:
            print(f"Warning: Unmapped outcomes found: {unmapped}")
        
        # Remove any NaN values
        valid_indices = ~pd.isna(y)
        df = df[valid_indices].reset_index(drop=True)
        feature_df = feature_df[valid_indices].reset_index(drop=True)
        y = y[valid_indices]
        
        print(f"Final dataset: {len(y)} matches with valid outcomes")
        
        # Calculate baselines
        baselines = evaluator.calculate_baselines(y)
        
        # Train enhanced models
        models, y_test = evaluator.train_enhanced_models(feature_df, y, baselines, feature_names)
        
        # Compare against baselines
        comparison = evaluator.compare_against_baselines(models, baselines, y_test)
        
        # Save results
        json_path, md_path = evaluator.save_comprehensive_results(df, feature_names, baselines, models, comparison)
        
        print(f"\n" + "="*60)
        print("EVALUATION COMPLETE")
        print("="*60)
        print(f"Results saved:")
        print(f"  JSON: {json_path}")
        print(f"  Report: {md_path}")
        
        # Key findings
        best_model = max(comparison.keys(), key=lambda x: comparison[x]['accuracy'])
        best_accuracy = comparison[best_model]['accuracy']
        best_improvement = comparison[best_model]['uniform_acc_improvement']
        
        print(f"\nKEY FINDINGS:")
        print(f"  Best Model: {best_model.replace('_', ' ').title()}")
        print(f"  Best Accuracy: {best_accuracy:.1%}")
        print(f"  Improvement vs Uniform: {best_improvement:+.1f}%")
        print(f"  Features Used: {len(models[best_model]['features_used'])}")
        
        if best_accuracy > 0.45:
            print(f"  ✅ EXCELLENT: Achieved target >45% accuracy!")
        elif best_accuracy > 0.40:
            print(f"  ✅ GOOD: Above 40% threshold")
        else:
            print(f"  ⚠️  NEEDS IMPROVEMENT: Below 40% threshold")
            
    finally:
        evaluator.conn.close()

if __name__ == "__main__":
    main()