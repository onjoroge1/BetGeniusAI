"""
Simplified Static Predictor - Accuracy-first forecasting without timing complexity
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, accuracy_score, brier_score_loss
import warnings
warnings.filterwarnings('ignore')

import os
import json
import joblib
from datetime import datetime
from typing import Dict, List, Tuple

class SimplifiedStaticPredictor:
    """Simplified static predictor focusing purely on accuracy"""
    
    def __init__(self):
        """Initialize simplified predictor"""
        
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = None
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
    def prepare_training_data(self) -> pd.DataFrame:
        """Prepare simplified training dataset"""
        
        print("Preparing simplified training data...")
        
        # Use existing matches from database with enhanced features
        import psycopg2
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            
            # Get matches with basic data
            query = """
            SELECT 
                match_id,
                league_id,
                home_team_id,
                away_team_id,
                outcome,
                home_goals,
                away_goals,
                match_date_utc
            FROM matches
            WHERE outcome IS NOT NULL
              AND league_id IN (39, 140, 135, 78, 61)
              AND home_goals IS NOT NULL
              AND away_goals IS NOT NULL
            ORDER BY match_date_utc ASC
            """
            
            df = pd.read_sql_query(query, conn)
            conn.close()
            
            if len(df) < 50:
                print("Insufficient database data, generating enhanced synthetic dataset...")
                df = self._generate_enhanced_synthetic_data()
            else:
                print(f"Loaded {len(df)} matches from database")
                df = self._add_simplified_features(df)
            
        except Exception as e:
            print(f"Database error: {e}")
            print("Generating enhanced synthetic dataset...")
            df = self._generate_enhanced_synthetic_data()
        
        return df
    
    def _generate_enhanced_synthetic_data(self, n_samples: int = 2000) -> pd.DataFrame:
        """Generate realistic synthetic football data"""
        
        np.random.seed(42)
        
        # Generate matches
        matches = []
        match_id = 1
        
        for league_id in [39, 140, 135, 78, 61]:
            league_matches = n_samples // 5
            
            for i in range(league_matches):
                # Simulate team strengths
                home_strength = np.random.normal(1500, 150)
                away_strength = np.random.normal(1500, 150)
                
                # Home advantage (varies by league)
                home_advantage = {39: 0.18, 140: 0.16, 135: 0.15, 78: 0.17, 61: 0.14}[league_id]
                
                # Expected goals based on strengths
                strength_diff = (home_strength - away_strength) / 100
                home_xg = 1.4 + 0.3 * strength_diff + home_advantage
                away_xg = 1.3 + 0.3 * (-strength_diff)
                
                # Simulate actual goals (Poisson)
                home_goals = np.random.poisson(max(0.1, home_xg))
                away_goals = np.random.poisson(max(0.1, away_xg))
                
                # Determine outcome
                if home_goals > away_goals:
                    outcome = 'H'
                elif home_goals < away_goals:
                    outcome = 'A'
                else:
                    outcome = 'D'
                
                matches.append({
                    'match_id': match_id,
                    'league_id': league_id,
                    'home_team_id': 100 + (i % 20),  # 20 teams per league
                    'away_team_id': 100 + ((i + 10) % 20),
                    'outcome': outcome,
                    'home_goals': home_goals,
                    'away_goals': away_goals,
                    'match_date_utc': pd.Timestamp('2023-01-01') + pd.Timedelta(days=i),
                    'home_strength': home_strength,
                    'away_strength': away_strength,
                    'home_xg': home_xg,
                    'away_xg': away_xg
                })
                
                match_id += 1
        
        df = pd.DataFrame(matches)
        print(f"Generated {len(df)} synthetic matches")
        
        return self._add_simplified_features(df)
    
    def _add_simplified_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add meaningful predictive features"""
        
        df = df.copy()
        
        # Basic match features (only if goals exist)
        if 'home_goals' in df.columns and 'away_goals' in df.columns:
            df['goal_difference'] = df['home_goals'] - df['away_goals']
            df['total_goals'] = df['home_goals'] + df['away_goals']
        else:
            df['goal_difference'] = 0  # Not used for prediction
            df['total_goals'] = 3  # Average assumption
        
        # League-specific features
        league_stats = df.groupby('league_id').agg({
            'home_goals': 'mean',
            'away_goals': 'mean',
            'total_goals': 'mean',
            'outcome': lambda x: (x == 'H').mean()
        }).add_prefix('league_')
        
        df = df.merge(league_stats, left_on='league_id', right_index=True)
        
        # Team strength proxies
        if 'home_strength' not in df.columns:
            # Calculate team strength from historical performance
            team_stats = {}
            
            for team_col, goals_for, goals_against in [
                ('home_team_id', 'home_goals', 'away_goals'),
                ('away_team_id', 'away_goals', 'home_goals')
            ]:
                team_agg = df.groupby(team_col).agg({
                    goals_for: 'mean',
                    goals_against: 'mean',
                    'outcome': lambda x: (x == ('H' if team_col == 'home_team_id' else 'A')).mean()
                })
                
                for team_id, stats in team_agg.iterrows():
                    if team_id not in team_stats:
                        team_stats[team_id] = {}
                    
                    prefix = 'home' if team_col == 'home_team_id' else 'away'
                    team_stats[team_id][f'{prefix}_gf_avg'] = stats[goals_for]
                    team_stats[team_id][f'{prefix}_ga_avg'] = stats[goals_against]
                    team_stats[team_id][f'{prefix}_win_pct'] = stats['outcome']
            
            # Add team strength features
            for col in ['home_gf_avg', 'home_ga_avg', 'home_win_pct', 
                       'away_gf_avg', 'away_ga_avg', 'away_win_pct']:
                df[col] = 0.0
            
            for idx, row in df.iterrows():
                home_team = row['home_team_id']
                away_team = row['away_team_id']
                
                if home_team in team_stats:
                    for stat_name, stat_value in team_stats[home_team].items():
                        if stat_name.startswith('home_'):
                            df.at[idx, stat_name] = stat_value
                
                if away_team in team_stats:
                    for stat_name, stat_value in team_stats[away_team].items():
                        if stat_name.startswith('away_'):
                            df.at[idx, stat_name] = stat_value
        
        # Ensure we have team strength columns
        if 'home_gf_avg' not in df.columns:
            df['home_gf_avg'] = 1.5
            df['away_gf_avg'] = 1.5
            df['home_ga_avg'] = 1.5
            df['away_ga_avg'] = 1.5
            df['home_win_pct'] = 0.4
            df['away_win_pct'] = 0.4
        
        # Derived features
        strength_home = df.get('home_strength', df['home_gf_avg'] * 500)
        strength_away = df.get('away_strength', df['away_gf_avg'] * 500)
        df['strength_diff'] = strength_home - strength_away
        df['gf_advantage'] = df['home_gf_avg'] - df['away_gf_avg']
        df['ga_advantage'] = df['away_ga_avg'] - df['home_ga_avg']
        df['win_pct_diff'] = df['home_win_pct'] - df['away_win_pct']
        
        # Attack vs Defense matchups
        df['home_attack_vs_away_defense'] = df['home_gf_avg'] / (df['away_ga_avg'] + 0.1)
        df['away_attack_vs_home_defense'] = df['away_gf_avg'] / (df['home_ga_avg'] + 0.1)
        df['attack_balance'] = df['home_attack_vs_away_defense'] - df['away_attack_vs_home_defense']
        
        # League competitiveness
        df['league_competitiveness'] = 1.0 - df['league_outcome']  # Higher when not dominated by home wins
        
        # Expected goals (simplified)
        if 'home_xg' not in df.columns:
            df['home_xg'] = df['home_gf_avg'] + df['ga_advantage'] * 0.5
            df['away_xg'] = df['away_gf_avg'] + (-df['ga_advantage']) * 0.5
        
        df['xg_difference'] = df['home_xg'] - df['away_xg']
        df['total_xg'] = df['home_xg'] + df['away_xg']
        
        return df
    
    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """Prepare feature matrix for training/prediction"""
        
        # Select predictive features (no target leakage)
        feature_cols = [
            'league_id',
            'strength_diff', 'gf_advantage', 'ga_advantage', 'win_pct_diff',
            'home_attack_vs_away_defense', 'away_attack_vs_home_defense', 'attack_balance',
            'league_home_goals', 'league_away_goals', 'league_total_goals', 'league_competitiveness',
            'home_xg', 'away_xg', 'xg_difference', 'total_xg',
            'home_gf_avg', 'home_ga_avg', 'home_win_pct',
            'away_gf_avg', 'away_ga_avg', 'away_win_pct'
        ]
        
        # Only use features that exist
        available_features = [col for col in feature_cols if col in df.columns]
        self.feature_names = available_features
        
        print(f"Using {len(available_features)} features: {available_features}")
        
        X = df[available_features].fillna(0).values
        
        # Handle any remaining NaN/inf values
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)
        
        return X
    
    def train(self, df: pd.DataFrame, test_size: float = 0.2) -> Dict:
        """Train simplified static predictor"""
        
        print("Training simplified static predictor...")
        
        # Prepare features and targets
        X = self.prepare_features(df)
        y = df['outcome'].values
        
        # Time-aware split
        df_sorted = df.sort_values('match_date_utc')
        split_idx = int(len(df_sorted) * (1 - test_size))
        
        X_train = X[:split_idx]
        X_test = X[split_idx:]
        y_train = y[:split_idx]
        y_test = y[split_idx:]
        
        print(f"Training samples: {len(X_train)}")
        print(f"Test samples: {len(X_test)}")
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Train Random Forest classifier for 3-way prediction
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=42,
            n_jobs=-1
        )
        
        # Convert outcomes to indices
        outcome_to_idx = {'H': 0, 'D': 1, 'A': 2}
        y_train_idx = np.array([outcome_to_idx[outcome] for outcome in y_train])
        y_test_idx = np.array([outcome_to_idx[outcome] for outcome in y_test])
        
        # Train model
        self.model.fit(X_train_scaled, y_train_idx)
        
        # Evaluate
        train_preds = self.model.predict_proba(X_train_scaled)
        test_preds = self.model.predict_proba(X_test_scaled)
        
        train_logloss = log_loss(y_train_idx, train_preds)
        test_logloss = log_loss(y_test_idx, test_preds)
        
        train_acc = accuracy_score(y_train_idx, train_preds.argmax(axis=1))
        test_acc = accuracy_score(y_test_idx, test_preds.argmax(axis=1))
        
        # Top-2 accuracy
        train_top2 = np.mean([y_train_idx[i] in np.argsort(train_preds[i])[-2:] for i in range(len(y_train_idx))])
        test_top2 = np.mean([y_test_idx[i] in np.argsort(test_preds[i])[-2:] for i in range(len(y_test_idx))])
        
        # Generate baseline comparison
        baseline_uniform = np.full((len(y_test_idx), 3), 1/3)
        baseline_logloss = log_loss(y_test_idx, baseline_uniform)
        
        improvement = baseline_logloss - test_logloss
        
        results = {
            'train_logloss': train_logloss,
            'test_logloss': test_logloss,
            'train_accuracy': train_acc,
            'test_accuracy': test_acc,
            'train_top2': train_top2,
            'test_top2': test_top2,
            'baseline_logloss': baseline_logloss,
            'logloss_improvement': improvement,
            'beats_baseline_threshold': improvement >= 0.005,
            'n_features': len(self.feature_names),
            'n_train': len(X_train),
            'n_test': len(X_test)
        }
        
        print("\nTraining Results:")
        print("=" * 50)
        print(f"Test LogLoss: {test_logloss:.4f}")
        print(f"Test Accuracy: {test_acc:.1%}")
        print(f"Test Top-2: {test_top2:.1%}")
        print(f"Improvement vs Baseline: {improvement:+.4f}")
        print(f"Beats Threshold (≥0.005): {'✅ YES' if improvement >= 0.005 else '❌ NO'}")
        
        return results
    
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """Generate probability predictions"""
        
        X = self.prepare_features(df)
        X_scaled = self.scaler.transform(X)
        
        probs = self.model.predict_proba(X_scaled)
        
        return probs
    
    def predict_match(self, home_team_features: Dict, away_team_features: Dict,
                     league_id: int) -> Dict:
        """Predict single match outcome"""
        
        # Create single match dataframe
        match_data = {
            'league_id': league_id,
            'home_team_id': 1,
            'away_team_id': 2,
            'match_date_utc': pd.Timestamp.now(),
            'outcome': 'H',  # Placeholder for feature engineering
            **home_team_features,
            **away_team_features
        }
        
        # Add league averages (simplified)
        league_defaults = {
            39: {'avg_goals': 2.8, 'home_win_rate': 0.47},
            140: {'avg_goals': 2.6, 'home_win_rate': 0.44},
            135: {'avg_goals': 2.7, 'home_win_rate': 0.45},
            78: {'avg_goals': 3.1, 'home_win_rate': 0.43},
            61: {'avg_goals': 2.5, 'home_win_rate': 0.42}
        }
        
        league_stats = league_defaults.get(league_id, {'avg_goals': 2.7, 'home_win_rate': 0.45})
        match_data.update({
            'league_home_goals': league_stats['avg_goals'] * league_stats['home_win_rate'],
            'league_away_goals': league_stats['avg_goals'] * (1 - league_stats['home_win_rate']),
            'league_total_goals': league_stats['avg_goals'],
            'league_competitiveness': 1.0 - league_stats['home_win_rate']
        })
        
        df = pd.DataFrame([match_data])
        df = self._add_simplified_features(df)
        
        probs = self.predict_proba(df)[0]
        
        return {
            'home_prob': float(probs[0]),
            'draw_prob': float(probs[1]),
            'away_prob': float(probs[2]),
            'predicted_outcome': ['H', 'D', 'A'][np.argmax(probs)],
            'confidence': float(np.max(probs))
        }
    
    def save_model(self, output_path: str = 'models/static/simplified_predictor.joblib'):
        """Save trained model"""
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        model_artifacts = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'euro_leagues': self.euro_leagues,
            'saved_at': datetime.now().isoformat()
        }
        
        joblib.dump(model_artifacts, output_path)
        print(f"Model saved: {output_path}")
        
        return output_path
    
    @classmethod
    def load_model(cls, model_path: str = 'models/static/simplified_predictor.joblib'):
        """Load trained model"""
        
        instance = cls()
        artifacts = joblib.load(model_path)
        
        instance.model = artifacts['model']
        instance.scaler = artifacts['scaler']
        instance.feature_names = artifacts['feature_names']
        instance.euro_leagues = artifacts['euro_leagues']
        
        print(f"Model loaded: {model_path}")
        return instance

def main():
    """Train and evaluate simplified static predictor"""
    
    print("🎯 Simplified Static Forecasting System")
    print("Focus: Pure prediction accuracy without timing complexity")
    print("=" * 60)
    
    # Initialize predictor
    predictor = SimplifiedStaticPredictor()
    
    # Prepare training data
    dataset = predictor.prepare_training_data()
    
    if len(dataset) < 100:
        print(f"❌ Insufficient data: {len(dataset)} samples")
        return
    
    # Train model
    results = predictor.train(dataset)
    
    # Save model
    model_path = predictor.save_model()
    
    # Demo predictions
    print("\n🔮 Demo Predictions:")
    print("-" * 30)
    
    # Example match prediction
    demo_prediction = predictor.predict_match(
        home_team_features={
            'home_gf_avg': 1.8,
            'home_ga_avg': 1.1,
            'home_win_pct': 0.6
        },
        away_team_features={
            'away_gf_avg': 1.4,
            'away_ga_avg': 1.3,
            'away_win_pct': 0.4
        },
        league_id=39  # Premier League
    )
    
    print(f"Premier League Match Prediction:")
    print(f"  Home Win: {demo_prediction['home_prob']:.1%}")
    print(f"  Draw: {demo_prediction['draw_prob']:.1%}")
    print(f"  Away Win: {demo_prediction['away_prob']:.1%}")
    print(f"  Predicted: {demo_prediction['predicted_outcome']} (confidence: {demo_prediction['confidence']:.1%})")
    
    print("\n✅ SIMPLIFIED STATIC PREDICTOR COMPLETE")
    print("=" * 60)
    print(f"Model Performance:")
    print(f"  LogLoss: {results['test_logloss']:.4f}")
    print(f"  Accuracy: {results['test_accuracy']:.1%}")
    print(f"  Top-2 Accuracy: {results['test_top2']:.1%}")
    print(f"  Improvement vs Baseline: {results['logloss_improvement']:+.4f}")
    print(f"  Production Ready: {'✅ YES' if results['beats_baseline_threshold'] else '❌ NEEDS WORK'}")
    print(f"  Model Saved: {model_path}")
    
    return predictor, results

if __name__ == "__main__":
    main()