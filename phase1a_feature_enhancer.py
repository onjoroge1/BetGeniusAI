"""
Phase 1A Feature Enhancement System
Add team strength, H2H records, contextual factors, and xG to existing clean features
Target: Boost accuracy from 48.8% to 55%+
"""

import os
import json
import numpy as np
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
import warnings
warnings.filterwarnings('ignore')

class Phase1AFeatureEnhancer:
    """Enhance existing features with team performance, H2H, and contextual data"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
        # League tier mappings for context
        self.league_tiers = {
            39: 1, 140: 1, 135: 1, 78: 1, 61: 1,  # Tier 1: Top European
            88: 2, 203: 2, 143: 2, 179: 2,        # Tier 2: Secondary
            399: 3                                  # Tier 3: Developing
        }
        
        self.home_advantage_by_league = {
            39: 0.58, 140: 0.62, 135: 0.56, 78: 0.54, 61: 0.59,  # European
            88: 0.65, 203: 0.68, 143: 0.72, 179: 0.70, 399: 0.75  # Others
        }
    
    def load_historical_data(self) -> pd.DataFrame:
        """Load all training matches with chronological ordering"""
        
        print("LOADING HISTORICAL MATCH DATA")
        print("=" * 40)
        
        query = """
        SELECT 
            id, match_id, league_id, season, home_team, away_team,
            match_date, outcome, home_goals, away_goals, features,
            home_team_id, away_team_id
        FROM training_matches 
        WHERE outcome IS NOT NULL AND features IS NOT NULL
        ORDER BY match_date
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        print(f"Loaded {len(df)} matches")
        print(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
        print(f"Leagues: {df['league_id'].nunique()}")
        
        return df
    
    def calculate_team_strength_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate rolling team strength metrics"""
        
        print("CALCULATING TEAM STRENGTH FEATURES")
        print("=" * 40)
        
        enhanced_features = []
        
        for idx, match in df.iterrows():
            if idx % 200 == 0:
                print(f"Processing match {idx}/{len(df)}")
            
            match_date = match['match_date']
            home_team = match['home_team']
            away_team = match['away_team']
            league_id = match['league_id']
            
            # Look back 6 months for team performance
            lookback_date = match_date - timedelta(days=180)
            
            # Get historical matches for both teams
            historical_matches = df[
                (df['match_date'] < match_date) & 
                (df['match_date'] >= lookback_date) &
                (df['league_id'] == league_id)
            ]
            
            # Home team stats
            home_matches = historical_matches[
                (historical_matches['home_team'] == home_team) |
                (historical_matches['away_team'] == home_team)
            ]
            
            # Away team stats  
            away_matches = historical_matches[
                (historical_matches['home_team'] == away_team) |
                (historical_matches['away_team'] == away_team)
            ]
            
            # Calculate team performance metrics
            home_stats = self._calculate_team_stats(home_matches, home_team)
            away_stats = self._calculate_team_stats(away_matches, away_team)
            
            # Head-to-head analysis
            h2h_stats = self._calculate_h2h_stats(historical_matches, home_team, away_team)
            
            # Contextual factors
            context_stats = self._calculate_contextual_factors(match, historical_matches, league_id)
            
            # Expected goals based on team averages
            xg_stats = self._calculate_expected_goals(home_stats, away_stats, league_id)
            
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
    
    def _calculate_team_stats(self, team_matches: pd.DataFrame, team_name: str) -> Dict:
        """Calculate performance statistics for a team"""
        
        if len(team_matches) == 0:
            return self._default_team_stats('home')
        
        # Separate home/away performances
        home_matches = team_matches[team_matches['home_team'] == team_name]
        away_matches = team_matches[team_matches['away_team'] == team_name]
        
        # Points calculation
        home_points = self._calculate_points(home_matches, 'home')
        away_points = self._calculate_points(away_matches, 'away')
        total_points = home_points + away_points
        total_matches = len(team_matches)
        
        # Goals statistics
        home_goals_for = home_matches['home_goals'].sum() if len(home_matches) > 0 else 0
        home_goals_against = home_matches['away_goals'].sum() if len(home_matches) > 0 else 0
        away_goals_for = away_matches['away_goals'].sum() if len(away_matches) > 0 else 0
        away_goals_against = away_matches['home_goals'].sum() if len(away_matches) > 0 else 0
        
        total_goals_for = home_goals_for + away_goals_for
        total_goals_against = home_goals_against + away_goals_against
        
        # Calculate averages
        ppg = total_points / max(total_matches, 1)
        gpg = total_goals_for / max(total_matches, 1)
        gapg = total_goals_against / max(total_matches, 1)
        
        # Recent form (last 5 matches)
        recent_matches = team_matches.tail(5) if len(team_matches) >= 5 else team_matches
        recent_points = 0
        for _, match in recent_matches.iterrows():
            if match['home_team'] == team_name:
                recent_points += self._get_points_from_outcome(match['outcome'], 'home')
            else:
                recent_points += self._get_points_from_outcome(match['outcome'], 'away')
        
        recent_form = recent_points / max(len(recent_matches), 1)
        
        # Win percentages
        wins = len(team_matches[
            ((team_matches['home_team'] == team_name) & (team_matches['outcome'] == 'Home')) |
            ((team_matches['away_team'] == team_name) & (team_matches['outcome'] == 'Away'))
        ])
        
        draws = len(team_matches[team_matches['outcome'] == 'Draw'])
        
        win_pct = wins / max(total_matches, 1)
        draw_pct = draws / max(total_matches, 1)
        
        return {
            'ppg': ppg,
            'gpg': gpg, 
            'gapg': gapg,
            'goal_diff_pg': gpg - gapg,
            'recent_form': recent_form,
            'win_pct': win_pct,
            'draw_pct': draw_pct,
            'matches_played': total_matches
        }
    
    def _calculate_points(self, matches: pd.DataFrame, perspective: str) -> int:
        """Calculate points from matches from team's perspective"""
        points = 0
        for _, match in matches.iterrows():
            points += self._get_points_from_outcome(match['outcome'], perspective)
        return points
    
    def _get_points_from_outcome(self, outcome: str, perspective: str) -> int:
        """Get points (3-1-0) from match outcome"""
        if outcome == 'Draw':
            return 1
        elif (outcome == 'Home' and perspective == 'home') or (outcome == 'Away' and perspective == 'away'):
            return 3
        else:
            return 0
    
    def _default_team_stats(self, prefix: str) -> Dict:
        """Default stats when no historical data available"""
        return {
            'ppg': 1.0,
            'gpg': 1.2,
            'gapg': 1.2,
            'goal_diff_pg': 0.0,
            'recent_form': 1.0,
            'win_pct': 0.33,
            'draw_pct': 0.33,
            'matches_played': 0
        }
    
    def _calculate_h2h_stats(self, historical_matches: pd.DataFrame, home_team: str, away_team: str) -> Dict:
        """Calculate head-to-head statistics"""
        
        h2h_matches = historical_matches[
            ((historical_matches['home_team'] == home_team) & (historical_matches['away_team'] == away_team)) |
            ((historical_matches['home_team'] == away_team) & (historical_matches['away_team'] == home_team))
        ]
        
        if len(h2h_matches) == 0:
            return {
                'h2h_home_wins': 0,
                'h2h_draws': 0,
                'h2h_away_wins': 0,
                'h2h_total_matches': 0,
                'h2h_avg_goals': 2.5,
                'h2h_home_advantage': 0.5
            }
        
        # Count outcomes from current match perspective
        home_wins = len(h2h_matches[
            ((h2h_matches['home_team'] == home_team) & (h2h_matches['outcome'] == 'Home')) |
            ((h2h_matches['away_team'] == home_team) & (h2h_matches['outcome'] == 'Away'))
        ])
        
        draws = len(h2h_matches[h2h_matches['outcome'] == 'Draw'])
        away_wins = len(h2h_matches) - home_wins - draws
        
        avg_goals = (h2h_matches['home_goals'] + h2h_matches['away_goals']).mean()
        
        # Home advantage in this fixture
        fixture_home_wins = len(h2h_matches[
            (h2h_matches['home_team'] == home_team) & (h2h_matches['outcome'] == 'Home')
        ])
        fixture_home_matches = len(h2h_matches[h2h_matches['home_team'] == home_team])
        home_advantage = fixture_home_wins / max(fixture_home_matches, 1) if fixture_home_matches > 0 else 0.5
        
        return {
            'h2h_home_wins': home_wins,
            'h2h_draws': draws,
            'h2h_away_wins': away_wins,
            'h2h_total_matches': len(h2h_matches),
            'h2h_avg_goals': avg_goals,
            'h2h_home_advantage': home_advantage
        }
    
    def _calculate_contextual_factors(self, match: pd.Series, historical_matches: pd.DataFrame, league_id: int) -> Dict:
        """Calculate contextual match factors"""
        
        # League context
        league_tier = self.league_tiers.get(league_id, 3)
        league_home_advantage = self.home_advantage_by_league.get(league_id, 0.60)
        
        # Season phase (0 = start, 1 = end)
        match_date = match['match_date']
        if hasattr(match_date, 'month'):
            month = match_date.month
            if month >= 8:  # Aug-Dec
                season_phase = (month - 8) / 4
            else:  # Jan-May  
                season_phase = 0.5 + (month / 10)
        else:
            season_phase = 0.5
        
        # Match importance (based on league tier and season phase)
        match_importance = 0.5 + (league_tier * 0.15) + (season_phase * 0.2)
        
        # League average goals (from historical data)
        if len(historical_matches) > 0:
            league_avg_goals = (historical_matches['home_goals'] + historical_matches['away_goals']).mean()
        else:
            league_avg_goals = 2.5
        
        return {
            'league_tier': league_tier,
            'league_home_advantage': league_home_advantage,
            'season_phase': season_phase,
            'match_importance': match_importance,
            'league_avg_goals': league_avg_goals
        }
    
    def _calculate_expected_goals(self, home_stats: Dict, away_stats: Dict, league_id: int) -> Dict:
        """Calculate expected goals based on team averages"""
        
        # Base expected goals from team averages
        home_attack_strength = home_stats['gpg']
        home_defense_strength = home_stats['gapg']
        away_attack_strength = away_stats['gpg']
        away_defense_strength = away_stats['gapg']
        
        # Apply home advantage
        home_advantage_factor = self.home_advantage_by_league.get(league_id, 0.60)
        
        # Expected goals calculation
        home_xg = (home_attack_strength * away_defense_strength * home_advantage_factor) / 1.2
        away_xg = (away_attack_strength * home_defense_strength * (1 - home_advantage_factor + 0.5)) / 1.2
        
        # Ensure reasonable bounds
        home_xg = max(0.5, min(4.0, home_xg))
        away_xg = max(0.5, min(4.0, away_xg))
        
        return {
            'home_xg': home_xg,
            'away_xg': away_xg,
            'xg_difference': home_xg - away_xg,
            'total_xg': home_xg + away_xg
        }
    
    def combine_with_existing_features(self, df: pd.DataFrame, enhanced_features: pd.DataFrame) -> pd.DataFrame:
        """Combine enhanced features with existing JSONB features"""
        
        print("COMBINING WITH EXISTING FEATURES")
        print("=" * 40)
        
        # Extract existing JSONB features
        legitimate_features = [
            'season_stage', 'recency_score', 'training_weight', 'competition_tier',
            'foundation_value', 'match_importance', 'data_quality_score', 'regional_intensity',
            'tactical_relevance', 'african_market_flag', 'european_tier1_flag', 'south_american_flag',
            'league_home_advantage', 'premier_league_weight', 'developing_market_flag',
            'league_competitiveness', 'prediction_reliability', 'tactical_style_encoding',
            'competitiveness_indicator', 'cross_league_applicability'
        ]
        
        existing_feature_matrix = []
        for _, row in df.iterrows():
            features_dict = row['features']
            feature_row = []
            
            if isinstance(features_dict, dict):
                for feature_name in legitimate_features:
                    value = features_dict.get(feature_name, 0.0)
                    if isinstance(value, (int, float)):
                        feature_row.append(float(value))
                    elif isinstance(value, bool):
                        feature_row.append(float(value))
                    else:
                        try:
                            feature_row.append(float(value))
                        except:
                            feature_row.append(0.0)
            else:
                feature_row = [0.0] * len(legitimate_features)
            
            existing_feature_matrix.append(feature_row)
        
        existing_features_df = pd.DataFrame(existing_feature_matrix, columns=legitimate_features)
        
        # Add prefixes to enhanced features to avoid conflicts
        enhanced_features_prefixed = enhanced_features.copy()
        enhanced_features_prefixed.columns = [f'enh_{col}' for col in enhanced_features.columns]
        
        # Combine all features
        combined_features = pd.concat([existing_features_df, enhanced_features_prefixed], axis=1)
        
        print(f"Existing features: {existing_features_df.shape[1]}")
        print(f"Enhanced features: {enhanced_features_prefixed.shape[1]}")
        print(f"Combined features: {combined_features.shape[1]}")
        
        return combined_features
    
    def train_enhanced_models(self, X: pd.DataFrame, y: np.ndarray) -> Dict:
        """Train models with enhanced feature set"""
        
        print("TRAINING ENHANCED MODELS")
        print("=" * 40)
        
        # Time-aware split
        split_idx = int(0.8 * len(X))
        X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        print(f"Training: {len(X_train)} matches")
        print(f"Testing: {len(X_test)} matches")
        
        # Handle missing values and remove low-variance features
        X_train_filled = X_train.fillna(X_train.median())
        X_test_filled = X_test.fillna(X_train.median())  # Use training medians
        
        feature_variance = X_train_filled.var()
        informative_features = feature_variance[feature_variance > 0.001].index.tolist()
        print(f"Using {len(informative_features)} informative features")
        
        X_train_clean = X_train_filled[informative_features]
        X_test_clean = X_test_filled[informative_features]
        
        models = {}
        
        # Enhanced Random Forest
        rf = RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_split=15,
            min_samples_leaf=8,
            max_features='sqrt',
            random_state=42,
            class_weight='balanced'
        )
        
        rf.fit(X_train_clean, y_train)
        rf_calibrated = CalibratedClassifierCV(rf, method='isotonic', cv=3)
        rf_calibrated.fit(X_train_clean, y_train)
        
        rf_probs = rf_calibrated.predict_proba(X_test_clean)
        rf_preds = rf.predict(X_test_clean)
        
        models['enhanced_random_forest'] = {
            'accuracy': accuracy_score(y_test, rf_preds),
            'log_loss': log_loss(y_test, rf_probs),
            'brier_score': self._multiclass_brier_score(y_test, rf_probs),
            'model': rf_calibrated,
            'features_used': informative_features
        }
        
        # Enhanced Logistic Regression
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train_clean)
        X_test_scaled = scaler.transform(X_test_clean)
        
        lr = LogisticRegression(
            max_iter=1000,
            random_state=42,
            class_weight='balanced',
            multi_class='multinomial',
            C=0.5
        )
        
        lr.fit(X_train_scaled, y_train)
        
        lr_probs = lr.predict_proba(X_test_scaled)
        lr_preds = lr.predict(X_test_scaled)
        
        models['enhanced_logistic_regression'] = {
            'accuracy': accuracy_score(y_test, lr_preds),
            'log_loss': log_loss(y_test, lr_probs),
            'brier_score': self._multiclass_brier_score(y_test, lr_probs),
            'model': lr,
            'scaler': scaler,
            'features_used': informative_features
        }
        
        # Feature importance analysis
        feature_importance = pd.DataFrame({
            'feature': informative_features,
            'importance': rf.feature_importances_
        }).sort_values('importance', ascending=False)
        
        print(f"\nTop 10 Enhanced Features:")
        for _, row in feature_importance.head(10).iterrows():
            print(f"  {row['feature']}: {row['importance']:.4f}")
        
        models['feature_importance'] = feature_importance
        
        return models, y_test
    
    def _multiclass_brier_score(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Calculate multiclass Brier score"""
        y_true_binary = np.zeros((len(y_true), y_prob.shape[1]))
        for i, label in enumerate(y_true):
            y_true_binary[i, label] = 1
        return np.mean(np.sum((y_prob - y_true_binary) ** 2, axis=1))
    
    def evaluate_enhancement_results(self, models: Dict, baseline_accuracy: float = 0.488) -> Dict:
        """Evaluate enhancement results against baseline"""
        
        print(f"\nPHASE 1A ENHANCEMENT EVALUATION")
        print("=" * 50)
        
        results = {}
        
        print(f"{'Model':<25} | {'Accuracy':<8} | {'vs Baseline':<12} | {'Status'}")
        print("-" * 70)
        print(f"{'Clean Baseline':<25} | {baseline_accuracy:.3f}   | {'BASELINE':<12} | {'Reference'}")
        print("-" * 70)
        
        for model_name, model_data in models.items():
            if model_name == 'feature_importance':
                continue
                
            accuracy = model_data['accuracy']
            improvement = (accuracy - baseline_accuracy) / baseline_accuracy * 100
            
            if accuracy > 0.55:
                status = "🎯 TARGET ACHIEVED"
            elif accuracy > 0.52:
                status = "📈 EXCELLENT PROGRESS"
            elif accuracy > baseline_accuracy:
                status = "✅ IMPROVED"
            else:
                status = "⚠️ NO IMPROVEMENT"
            
            results[model_name] = {
                'accuracy': accuracy,
                'improvement': improvement,
                'status': status,
                'log_loss': model_data['log_loss'],
                'brier_score': model_data['brier_score']
            }
            
            print(f"{model_name.replace('_', ' ').title():<25} | {accuracy:.3f}   | {improvement:+8.1f}%   | {status}")
        
        return results

def main():
    """Run Phase 1A feature enhancement"""
    
    enhancer = Phase1AFeatureEnhancer()
    
    try:
        print("PHASE 1A FEATURE ENHANCEMENT")
        print("=" * 50)
        print("Target: Boost accuracy from 48.8% to 55%+")
        print("Adding: Team strength, H2H records, contextual factors, xG")
        
        # Load historical data
        df = enhancer.load_historical_data()
        
        # Calculate enhanced features
        enhanced_features = enhancer.calculate_team_strength_features(df)
        
        # Combine with existing features
        combined_features = enhancer.combine_with_existing_features(df, enhanced_features)
        
        # Prepare target variable
        outcome_mapping = {'Home': 0, 'Draw': 1, 'Away': 2}
        y = df['outcome'].map(outcome_mapping).values
        
        # Train enhanced models
        models, y_test = enhancer.train_enhanced_models(combined_features, y)
        
        # Evaluate results
        results = enhancer.evaluate_enhancement_results(models)
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        os.makedirs('reports', exist_ok=True)
        
        enhancement_results = {
            'timestamp': timestamp,
            'phase': '1A_feature_enhancement',
            'baseline_accuracy': 0.488,
            'target_accuracy': 0.55,
            'models': {k: v for k, v in models.items() if k != 'feature_importance'},
            'results': results,
            'feature_importance': models.get('feature_importance', pd.DataFrame()).head(20).to_dict('records')
        }
        
        json_path = f'reports/phase1a_enhancement_{timestamp}.json'
        with open(json_path, 'w') as f:
            json.dump(enhancement_results, f, indent=2, default=str)
        
        # Summary
        best_model = max(results.keys(), key=lambda x: results[x]['accuracy'])
        best_accuracy = results[best_model]['accuracy']
        improvement = results[best_model]['improvement']
        
        print(f"\n" + "="*60)
        print("PHASE 1A ENHANCEMENT COMPLETE")
        print("="*60)
        print(f"Best Model: {best_model.replace('_', ' ').title()}")
        print(f"Accuracy: {best_accuracy:.1%} (was 48.8%)")
        print(f"Improvement: {improvement:+.1f}%")
        
        if best_accuracy >= 0.55:
            print("🎯 TARGET ACHIEVED: 55%+ accuracy reached!")
        elif best_accuracy >= 0.52:
            print("📈 EXCELLENT PROGRESS: Close to target")
        elif improvement > 0:
            print("✅ SUCCESSFUL ENHANCEMENT")
        else:
            print("⚠️ Enhancement needs refinement")
        
        print(f"Results saved: {json_path}")
        
    finally:
        enhancer.conn.close()

if __name__ == "__main__":
    main()