"""
Phase 1B Enhanced Training System
Train models using expanded 5,151 match dataset from European leagues
Goal: Push accuracy beyond 50.1% Phase 1A baseline toward 55% target
"""

import os
import json
import numpy as np
import pandas as pd
import psycopg2
import joblib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss, classification_report
import warnings
warnings.filterwarnings('ignore')

class Phase1BTrainingSystem:
    """Enhanced training system with expanded European dataset"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
        # Phase 1A optimal feature set (43 features proved optimal)
        self.base_features = [
            'season_stage', 'recency_score', 'training_weight', 'competition_tier',
            'foundation_value', 'match_importance', 'regional_intensity', 'tactical_relevance',
            'african_market_flag', 'european_tier1_flag', 'south_american_flag',
            'league_home_advantage', 'premier_league_weight', 'developing_market_flag',
            'league_competitiveness', 'prediction_reliability', 'tactical_style_encoding',
            'competitiveness_indicator', 'cross_league_applicability'
        ]
        
        # Enhanced features from Phase 1A (will be generated dynamically)
        self.enhanced_features = [
            'enh_home_ppg', 'enh_home_gpg', 'enh_home_gapg', 'enh_home_goal_diff_pg', 
            'enh_home_recent_form', 'enh_home_win_pct', 'enh_home_draw_pct', 'enh_home_matches_played',
            'enh_away_ppg', 'enh_away_gpg', 'enh_away_gapg', 'enh_away_goal_diff_pg',
            'enh_away_recent_form', 'enh_away_win_pct', 'enh_away_draw_pct', 'enh_away_matches_played',
            'enh_h2h_home_wins', 'enh_h2h_draws', 'enh_h2h_away_wins', 'enh_h2h_total_matches',
            'enh_h2h_avg_goals', 'enh_h2h_home_advantage', 'enh_league_tier',
            'enh_league_home_advantage', 'enh_season_phase', 'enh_match_importance',
            'enh_league_avg_goals', 'enh_home_xg', 'enh_away_xg', 'enh_xg_difference', 'enh_total_xg'
        ]
        
        self.all_features = self.base_features + self.enhanced_features
        
    def load_expanded_dataset(self) -> pd.DataFrame:
        """Load the expanded 5,151 match dataset"""
        
        print("LOADING EXPANDED EUROPEAN DATASET")
        print("=" * 40)
        
        query = """
        SELECT 
            match_id, league_id, season, home_team, away_team,
            match_date, home_goals, away_goals, outcome, features
        FROM training_matches 
        WHERE outcome IS NOT NULL
        ORDER BY match_date ASC
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        print(f"Loaded {len(df)} matches")
        print(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
        print(f"Leagues: {df['league_id'].nunique()}")
        print(f"Seasons: {df['season'].nunique()}")
        
        # Verify European league coverage
        league_counts = df['league_id'].value_counts()
        print(f"\nLeague Distribution:")
        for league_id, count in league_counts.head(7).items():
            league_names = {
                135: 'Serie A', 140: 'La Liga', 39: 'Premier League',
                78: 'Bundesliga', 61: 'Ligue 1', 88: 'Eredivisie'
            }
            name = league_names.get(league_id, f'League {league_id}')
            print(f"  {name}: {count} matches")
        
        return df
    
    def generate_enhanced_features_v2(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate enhanced features using expanded dataset (Phase 1B version)"""
        
        print("\nGENERATING PHASE 1B ENHANCED FEATURES")
        print("=" * 40)
        print("Using expanded dataset for better team performance calculations")
        
        enhanced_features = []
        
        for idx, match in df.iterrows():
            if idx % 500 == 0:
                print(f"Processing match {idx}/{len(df)}")
            
            match_date = match['match_date']
            home_team = match['home_team']
            away_team = match['away_team']
            league_id = match['league_id']
            
            # Extended lookback with more data available
            lookback_date = match_date - timedelta(days=365)  # 1 year lookback
            
            # Historical matches for analysis
            historical_matches = df[
                (df['match_date'] < match_date) & 
                (df['match_date'] >= lookback_date) &
                (df['league_id'] == league_id)
            ]
            
            # Calculate enhanced team statistics
            home_stats = self._calculate_enhanced_team_stats_v2(historical_matches, home_team, 'home')
            away_stats = self._calculate_enhanced_team_stats_v2(historical_matches, away_team, 'away')
            
            # Head-to-head with extended history
            h2h_stats = self._calculate_enhanced_h2h_stats_v2(historical_matches, home_team, away_team)
            
            # League context with bigger dataset
            context_stats = self._calculate_enhanced_context_v2(match, historical_matches, league_id)
            
            # Expected goals with improved accuracy
            xg_stats = self._calculate_enhanced_xg_v2(home_stats, away_stats, league_id, historical_matches)
            
            # Combine all enhanced features
            enhanced_match_features = {
                **home_stats,
                **away_stats,
                **h2h_stats,
                **context_stats,
                **xg_stats
            }
            
            enhanced_features.append(enhanced_match_features)
        
        enhanced_df = pd.DataFrame(enhanced_features)
        
        print(f"Generated {enhanced_df.shape[1]} enhanced features")
        print(f"Feature completeness: {(enhanced_df.notna()).sum().sum() / (enhanced_df.shape[0] * enhanced_df.shape[1]) * 100:.1f}%")
        
        return enhanced_df
    
    def _calculate_enhanced_team_stats_v2(self, team_matches: pd.DataFrame, team_name: str, prefix: str) -> Dict:
        """Calculate enhanced team statistics with improved accuracy"""
        
        if len(team_matches) == 0:
            return self._default_enhanced_stats_v2(prefix)
        
        # All matches involving this team
        team_involved = team_matches[
            (team_matches['home_team'] == team_name) | 
            (team_matches['away_team'] == team_name)
        ]
        
        if len(team_involved) == 0:
            return self._default_enhanced_stats_v2(prefix)
        
        # Separate home and away performances
        home_matches = team_involved[team_involved['home_team'] == team_name]
        away_matches = team_involved[team_involved['away_team'] == team_name]
        
        # Points calculation
        total_points = 0
        total_matches = len(team_involved)
        
        for _, match in team_involved.iterrows():
            if match['home_team'] == team_name:
                if match['outcome'] == 'Home':
                    total_points += 3
                elif match['outcome'] == 'Draw':
                    total_points += 1
            else:  # Away team
                if match['outcome'] == 'Away':
                    total_points += 3
                elif match['outcome'] == 'Draw':
                    total_points += 1
        
        # Goals statistics
        goals_for = 0
        goals_against = 0
        
        for _, match in team_involved.iterrows():
            if match['home_team'] == team_name:
                goals_for += match['home_goals']
                goals_against += match['away_goals']
            else:
                goals_for += match['away_goals']
                goals_against += match['home_goals']
        
        # Enhanced metrics
        ppg = total_points / max(total_matches, 1)
        gpg = goals_for / max(total_matches, 1)
        gapg = goals_against / max(total_matches, 1)
        goal_diff_pg = gpg - gapg
        
        # Recent form (last 8 matches with more data available)
        recent_matches = team_involved.tail(8) if len(team_involved) >= 8 else team_involved
        recent_points = 0
        
        for _, match in recent_matches.iterrows():
            if match['home_team'] == team_name:
                if match['outcome'] == 'Home':
                    recent_points += 3
                elif match['outcome'] == 'Draw':
                    recent_points += 1
            else:
                if match['outcome'] == 'Away':
                    recent_points += 3
                elif match['outcome'] == 'Draw':
                    recent_points += 1
        
        recent_form = recent_points / max(len(recent_matches), 1)
        
        # Win/draw percentages
        wins = 0
        draws = 0
        
        for _, match in team_involved.iterrows():
            if match['outcome'] == 'Draw':
                draws += 1
            elif ((match['home_team'] == team_name and match['outcome'] == 'Home') or
                  (match['away_team'] == team_name and match['outcome'] == 'Away')):
                wins += 1
        
        win_pct = wins / max(total_matches, 1)
        draw_pct = draws / max(total_matches, 1)
        
        return {
            f'enh_{prefix}_ppg': ppg,
            f'enh_{prefix}_gpg': gpg,
            f'enh_{prefix}_gapg': gapg,
            f'enh_{prefix}_goal_diff_pg': goal_diff_pg,
            f'enh_{prefix}_recent_form': recent_form,
            f'enh_{prefix}_win_pct': win_pct,
            f'enh_{prefix}_draw_pct': draw_pct,
            f'enh_{prefix}_matches_played': total_matches
        }
    
    def _calculate_enhanced_h2h_stats_v2(self, historical_matches: pd.DataFrame, home_team: str, away_team: str) -> Dict:
        """Calculate enhanced head-to-head statistics"""
        
        h2h_matches = historical_matches[
            ((historical_matches['home_team'] == home_team) & (historical_matches['away_team'] == away_team)) |
            ((historical_matches['home_team'] == away_team) & (historical_matches['away_team'] == home_team))
        ]
        
        if len(h2h_matches) == 0:
            return {
                'enh_h2h_home_wins': 0, 'enh_h2h_draws': 0, 'enh_h2h_away_wins': 0,
                'enh_h2h_total_matches': 0, 'enh_h2h_avg_goals': 2.5,
                'enh_h2h_home_advantage': 0.5
            }
        
        home_wins = len(h2h_matches[
            (h2h_matches['home_team'] == home_team) & (h2h_matches['outcome'] == 'Home')
        ])
        away_wins = len(h2h_matches[
            (h2h_matches['away_team'] == home_team) & (h2h_matches['outcome'] == 'Away')
        ])
        draws = len(h2h_matches[h2h_matches['outcome'] == 'Draw'])
        
        total_goals = (h2h_matches['home_goals'] + h2h_matches['away_goals']).sum()
        avg_goals = total_goals / len(h2h_matches)
        
        home_advantage = (home_wins + 0.5 * draws) / len(h2h_matches)
        
        return {
            'enh_h2h_home_wins': home_wins,
            'enh_h2h_draws': draws, 
            'enh_h2h_away_wins': away_wins,
            'enh_h2h_total_matches': len(h2h_matches),
            'enh_h2h_avg_goals': avg_goals,
            'enh_h2h_home_advantage': home_advantage
        }
    
    def _calculate_enhanced_context_v2(self, match: pd.Series, historical_matches: pd.DataFrame, league_id: int) -> Dict:
        """Calculate enhanced contextual factors"""
        
        # League tier mapping with expanded coverage
        tier_mapping = {
            39: 1, 140: 1, 135: 1, 78: 1, 61: 1,  # Big 5
            88: 2, 94: 2, 144: 2  # Strong tier 2
        }
        
        league_tier = tier_mapping.get(league_id, 3)
        
        # Season phase calculation
        match_date = match['match_date']
        month = match_date.month
        
        if month >= 8:  # August onwards - early season
            season_phase = (month - 8) / 4
        elif month <= 5:  # Up to May - mid to late season
            season_phase = (month + 4) / 4
        else:  # June/July - off season
            season_phase = 0.1
        
        # Match importance based on league tier and timing
        base_importance = 0.9 if league_tier == 1 else 0.7
        if month in [4, 5]:  # End of season - more important
            match_importance = base_importance * 1.2
        else:
            match_importance = base_importance
        
        # League averages from historical data
        if len(historical_matches) > 0:
            league_avg_goals = (historical_matches['home_goals'] + historical_matches['away_goals']).mean()
            league_home_advantage = (historical_matches['outcome'] == 'Home').mean()
        else:
            league_avg_goals = 2.7
            league_home_advantage = 0.45
        
        return {
            'enh_league_tier': league_tier,
            'enh_league_home_advantage': league_home_advantage,
            'enh_season_phase': season_phase,
            'enh_match_importance': match_importance,
            'enh_league_avg_goals': league_avg_goals
        }
    
    def _calculate_enhanced_xg_v2(self, home_stats: Dict, away_stats: Dict, league_id: int, historical_matches: pd.DataFrame) -> Dict:
        """Calculate enhanced expected goals with improved accuracy"""
        
        # Extract team scoring rates
        home_gpg = home_stats.get('enh_home_gpg', 1.3)
        home_gapg = home_stats.get('enh_home_gapg', 1.3)
        away_gpg = away_stats.get('enh_away_gpg', 1.2)
        away_gapg = away_stats.get('enh_away_gapg', 1.4)
        
        # League home advantage factors
        home_advantage_factors = {
            39: 1.15, 140: 1.18, 135: 1.12, 78: 1.10, 61: 1.16,
            88: 1.20, 94: 1.18
        }
        home_advantage = home_advantage_factors.get(league_id, 1.14)
        
        # Expected goals calculation with home advantage
        home_xg = (home_gpg * home_advantage + (2.7 - away_gapg)) / 2
        away_xg = (away_gpg / home_advantage + (2.7 - home_gapg)) / 2
        
        # Normalize to realistic ranges
        home_xg = max(0.5, min(3.5, home_xg))
        away_xg = max(0.5, min(3.5, away_xg))
        
        return {
            'enh_home_xg': home_xg,
            'enh_away_xg': away_xg,
            'enh_xg_difference': home_xg - away_xg,
            'enh_total_xg': home_xg + away_xg
        }
    
    def _default_enhanced_stats_v2(self, prefix: str) -> Dict:
        """Default enhanced stats when no historical data"""
        return {
            f'enh_{prefix}_ppg': 1.2,
            f'enh_{prefix}_gpg': 1.3,
            f'enh_{prefix}_gapg': 1.3,
            f'enh_{prefix}_goal_diff_pg': 0.0,
            f'enh_{prefix}_recent_form': 1.2,
            f'enh_{prefix}_win_pct': 0.35,
            f'enh_{prefix}_draw_pct': 0.25,
            f'enh_{prefix}_matches_played': 0
        }
    
    def prepare_training_data(self, df: pd.DataFrame, enhanced_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare training data combining base and enhanced features"""
        
        print("\nPREPARING PHASE 1B TRAINING DATA")
        print("=" * 40)
        
        # Extract base features from stored JSON
        base_feature_data = []
        for _, row in df.iterrows():
            features = row['features']
            if isinstance(features, str):
                features = json.loads(features)
            
            feature_row = []
            for feature in self.base_features:
                feature_row.append(features.get(feature, 0.0))
            
            base_feature_data.append(feature_row)
        
        base_df = pd.DataFrame(base_feature_data, columns=self.base_features)
        
        # Combine base and enhanced features
        combined_df = pd.concat([base_df, enhanced_df], axis=1)
        
        # Ensure we have the expected 43 features
        expected_features = len(self.base_features) + len(self.enhanced_features)
        
        print(f"Base features: {len(self.base_features)}")
        print(f"Enhanced features: {len(self.enhanced_features)}")
        print(f"Total features: {combined_df.shape[1]}")
        print(f"Expected: {expected_features}")
        
        if combined_df.shape[1] != expected_features:
            print(f"WARNING: Feature count mismatch!")
        
        # Handle missing values
        combined_df = combined_df.fillna(combined_df.median())
        
        # Prepare target variable
        y = df['outcome'].map({'Home': 0, 'Draw': 1, 'Away': 2}).values
        X = combined_df.values
        
        print(f"Training data shape: {X.shape}")
        print(f"Target distribution: {np.bincount(y)}")
        
        return X, y
    
    def train_phase1b_models(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """Train Phase 1B models with expanded dataset"""
        
        print("\nTRAINING PHASE 1B MODELS")
        print("=" * 40)
        print("Using 5,151 match dataset for enhanced accuracy")
        
        # Time-aware train/test split (80/20)
        split_idx = int(0.8 * len(X))
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        print(f"Training set: {X_train.shape[0]} matches")
        print(f"Test set: {X_test.shape[0]} matches")
        
        results = {}
        
        # Model 1: Enhanced Random Forest (Phase 1A champion)
        print("\nTraining Enhanced Random Forest...")
        rf_model = RandomForestClassifier(
            n_estimators=300,  # Increased for larger dataset
            max_depth=10,      # Slightly deeper
            min_samples_split=12,
            min_samples_leaf=6,
            class_weight='balanced',
            random_state=42,
            n_jobs=-1
        )
        
        # Calibrated classifier for probability calibration
        rf_calibrated = CalibratedClassifierCV(rf_model, method='isotonic', cv=3)
        rf_calibrated.fit(X_train, y_train)
        
        # Predictions and evaluation
        rf_pred = rf_calibrated.predict(X_test)
        rf_pred_proba = rf_calibrated.predict_proba(X_test)
        
        rf_accuracy = accuracy_score(y_test, rf_pred)
        rf_log_loss = log_loss(y_test, rf_pred_proba)
        # Calculate multiclass Brier score (average of binary Brier scores)
        rf_brier_scores = []
        for i in range(3):  # 3 classes
            y_binary = (y_test == i).astype(int)
            rf_brier_scores.append(brier_score_loss(y_binary, rf_pred_proba[:, i]))
        rf_brier = np.mean(rf_brier_scores)
        
        # Cross-validation for robustness
        cv_scores = cross_val_score(rf_calibrated, X_train, y_train, cv=5, scoring='accuracy')
        
        results['enhanced_random_forest'] = {
            'model': rf_calibrated,
            'accuracy': rf_accuracy,
            'log_loss': rf_log_loss,
            'brier_score': rf_brier,
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
            'feature_importance': rf_model.feature_importances_ if hasattr(rf_model, 'feature_importances_') else None
        }
        
        print(f"Random Forest - Accuracy: {rf_accuracy:.4f}")
        print(f"Random Forest - Log Loss: {rf_log_loss:.4f}")
        print(f"Random Forest - CV: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
        
        # Model 2: Enhanced Logistic Regression
        print("\nTraining Enhanced Logistic Regression...")
        
        # Scale features for logistic regression
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        lr_model = LogisticRegression(
            C=1.0,  # Regularization strength
            class_weight='balanced',
            multi_class='multinomial',
            max_iter=1000,
            random_state=42
        )
        
        lr_calibrated = CalibratedClassifierCV(lr_model, method='isotonic', cv=3)
        lr_calibrated.fit(X_train_scaled, y_train)
        
        lr_pred = lr_calibrated.predict(X_test_scaled)
        lr_pred_proba = lr_calibrated.predict_proba(X_test_scaled)
        
        lr_accuracy = accuracy_score(y_test, lr_pred)
        lr_log_loss = log_loss(y_test, lr_pred_proba)
        # Calculate multiclass Brier score for logistic regression
        lr_brier_scores = []
        for i in range(3):
            y_binary = (y_test == i).astype(int)
            lr_brier_scores.append(brier_score_loss(y_binary, lr_pred_proba[:, i]))
        lr_brier = np.mean(lr_brier_scores)
        
        results['enhanced_logistic_regression'] = {
            'model': lr_calibrated,
            'scaler': scaler,
            'accuracy': lr_accuracy,
            'log_loss': lr_log_loss,
            'brier_score': lr_brier
        }
        
        print(f"Logistic Regression - Accuracy: {lr_accuracy:.4f}")
        print(f"Logistic Regression - Log Loss: {lr_log_loss:.4f}")
        
        # Model 3: Ensemble (if both models are reasonable)
        if rf_accuracy > 0.40 and lr_accuracy > 0.40:
            print("\nCreating Ensemble Model...")
            
            # Simple averaging ensemble
            ensemble_proba = (rf_pred_proba + lr_pred_proba) / 2
            ensemble_pred = np.argmax(ensemble_proba, axis=1)
            
            ensemble_accuracy = accuracy_score(y_test, ensemble_pred)
            ensemble_log_loss = log_loss(y_test, ensemble_proba)
            # Calculate multiclass Brier score for ensemble
            ensemble_brier_scores = []
            for i in range(3):
                y_binary = (y_test == i).astype(int)
                ensemble_brier_scores.append(brier_score_loss(y_binary, ensemble_proba[:, i]))
            ensemble_brier = np.mean(ensemble_brier_scores)
            
            results['ensemble'] = {
                'accuracy': ensemble_accuracy,
                'log_loss': ensemble_log_loss,
                'brier_score': ensemble_brier
            }
            
            print(f"Ensemble - Accuracy: {ensemble_accuracy:.4f}")
            print(f"Ensemble - Log Loss: {ensemble_log_loss:.4f}")
        
        return results
    
    def save_phase1b_models(self, results: Dict, feature_names: List[str]) -> str:
        """Save Phase 1B trained models"""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs('models', exist_ok=True)
        
        # Save best performing model
        best_model = None
        best_accuracy = 0
        best_name = ""
        
        for name, result in results.items():
            if 'accuracy' in result and result['accuracy'] > best_accuracy:
                best_accuracy = result['accuracy']
                best_model = result
                best_name = name
        
        if best_model:
            model_path = f'models/phase1b_production_model_{timestamp}.joblib'
            
            model_data = {
                'model': best_model.get('model'),
                'scaler': best_model.get('scaler'),
                'feature_names': feature_names,
                'accuracy': best_accuracy,
                'model_type': best_name,
                'training_timestamp': timestamp,
                'dataset_size': 5151,
                'phase': '1B'
            }
            
            joblib.dump(model_data, model_path)
            print(f"\nSaved best model ({best_name}): {model_path}")
            print(f"Model accuracy: {best_accuracy:.4f}")
        
        return model_path if best_model else ""
    
    def run_phase1b_training(self) -> Dict:
        """Complete Phase 1B training workflow"""
        
        print("PHASE 1B ENHANCED TRAINING SYSTEM")
        print("=" * 50)
        print("Goal: Push beyond 50.1% Phase 1A baseline with 5,151 match dataset")
        
        # Load expanded dataset
        df = self.load_expanded_dataset()
        
        # Generate enhanced features using expanded data
        enhanced_df = self.generate_enhanced_features_v2(df)
        
        # Prepare training data
        X, y = self.prepare_training_data(df, enhanced_df)
        
        # Train models
        results = self.train_phase1b_models(X, y)
        
        # Save models
        feature_names = self.base_features + self.enhanced_features
        model_path = self.save_phase1b_models(results, feature_names)
        
        # Generate comprehensive report
        report = {
            'timestamp': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'phase': '1B_enhanced_training',
            'dataset_size': len(df),
            'feature_count': len(feature_names),
            'baseline_accuracy': 0.501,  # Phase 1A result
            'models': {}
        }
        
        for name, result in results.items():
            if 'accuracy' in result:
                report['models'][name] = {
                    'accuracy': result['accuracy'],
                    'log_loss': result.get('log_loss', 0),
                    'brier_score': result.get('brier_score', 0),
                    'cv_performance': result.get('cv_mean', 0)
                }
        
        # Determine success
        best_accuracy = max([r.get('accuracy', 0) for r in results.values()])
        improvement = best_accuracy - 0.501
        
        report['best_accuracy'] = best_accuracy
        report['improvement_over_phase1a'] = improvement
        report['target_achievement'] = best_accuracy >= 0.55
        report['model_path'] = model_path
        
        print(f"\nPHASE 1B TRAINING COMPLETE")
        print("=" * 30)
        print(f"Best accuracy: {best_accuracy:.4f}")
        print(f"Phase 1A baseline: 50.1%")
        print(f"Improvement: {improvement:+.3f}")
        print(f"Target (55%): {'✅ ACHIEVED' if best_accuracy >= 0.55 else '📈 Progress'}")
        
        return report

def main():
    """Run Phase 1B enhanced training"""
    
    trainer = Phase1BTrainingSystem()
    
    try:
        results = trainer.run_phase1b_training()
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        os.makedirs('reports', exist_ok=True)
        
        results_path = f'reports/phase1b_training_{timestamp}.json'
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\nTraining results saved: {results_path}")
        
        return results
        
    finally:
        trainer.conn.close()

if __name__ == "__main__":
    main()