"""
Advanced Phase 1A Enhancement - Push toward 55% target
Advanced feature engineering, ensemble methods, and model optimization
"""

import os
import json
import numpy as np
import pandas as pd
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from sklearn.model_selection import train_test_split, StratifiedKFold
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler, PolynomialFeatures
from sklearn.metrics import accuracy_score, log_loss, brier_score_loss
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_selection import SelectKBest, f_classif
import warnings
warnings.filterwarnings('ignore')

class AdvancedPhase1AEnhancer:
    """Advanced feature engineering and model optimization"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def load_enhanced_dataset(self) -> Tuple[pd.DataFrame, np.ndarray]:
        """Load the enhanced dataset from previous phase"""
        
        print("LOADING ENHANCED DATASET")
        print("=" * 30)
        
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
        
        # Extract existing features
        legitimate_features = [
            'season_stage', 'recency_score', 'training_weight', 'competition_tier',
            'foundation_value', 'match_importance', 'data_quality_score', 'regional_intensity',
            'tactical_relevance', 'african_market_flag', 'european_tier1_flag', 'south_american_flag',
            'league_home_advantage', 'premier_league_weight', 'developing_market_flag',
            'league_competitiveness', 'prediction_reliability', 'tactical_style_encoding',
            'competitiveness_indicator', 'cross_league_applicability'
        ]
        
        feature_matrix = []
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
            
            feature_matrix.append(feature_row)
        
        X_base = pd.DataFrame(feature_matrix, columns=legitimate_features)
        
        # Add enhanced features from team performance analysis
        enhanced_features = self._calculate_comprehensive_features(df)
        
        # Combine features
        X_combined = pd.concat([X_base, enhanced_features], axis=1)
        
        # Target variable
        outcome_mapping = {'Home': 0, 'Draw': 1, 'Away': 2}
        y = df['outcome'].map(outcome_mapping).values
        
        print(f"Combined dataset: {X_combined.shape}")
        print(f"Features: {X_combined.shape[1]}")
        
        return X_combined, y
    
    def _calculate_comprehensive_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate comprehensive enhanced features with advanced engineering"""
        
        print("CALCULATING ADVANCED FEATURES")
        print("=" * 30)
        
        features_list = []
        
        for idx, match in df.iterrows():
            if idx % 300 == 0:
                print(f"Processing {idx}/{len(df)}")
            
            match_date = match['match_date']
            home_team = match['home_team']
            away_team = match['away_team']
            league_id = match['league_id']
            
            # Historical lookback
            lookback_6m = match_date - timedelta(days=180)
            lookback_12m = match_date - timedelta(days=365)
            
            historical_matches = df[
                (df['match_date'] < match_date) & 
                (df['match_date'] >= lookback_12m) &
                (df['league_id'] == league_id)
            ]
            
            recent_matches = historical_matches[historical_matches['match_date'] >= lookback_6m]
            
            # Advanced team statistics
            home_stats = self._advanced_team_stats(historical_matches, recent_matches, home_team, True)
            away_stats = self._advanced_team_stats(historical_matches, recent_matches, away_team, False)
            
            # Advanced head-to-head
            h2h_stats = self._advanced_h2h_stats(historical_matches, home_team, away_team)
            
            # Form and momentum
            form_stats = self._calculate_form_momentum(recent_matches, home_team, away_team)
            
            # Match context and pressure
            context_stats = self._calculate_match_context(match, historical_matches, league_id)
            
            # Advanced expected outcomes
            prediction_stats = self._calculate_prediction_features(home_stats, away_stats, h2h_stats, context_stats)
            
            # Combine all
            match_features = {
                **home_stats,
                **away_stats,
                **h2h_stats,
                **form_stats,
                **context_stats,
                **prediction_stats
            }
            
            features_list.append(match_features)
        
        enhanced_df = pd.DataFrame(features_list)
        
        # Add interaction features
        enhanced_df = self._add_interaction_features(enhanced_df)
        
        print(f"Generated {enhanced_df.shape[1]} advanced features")
        
        return enhanced_df
    
    def _advanced_team_stats(self, historical: pd.DataFrame, recent: pd.DataFrame, team: str, is_home: bool) -> Dict:
        """Calculate advanced team statistics"""
        
        prefix = 'home_' if is_home else 'away_'
        
        # All matches for the team
        team_historical = historical[
            (historical['home_team'] == team) | (historical['away_team'] == team)
        ]
        
        team_recent = recent[
            (recent['home_team'] == team) | (recent['away_team'] == team)
        ]
        
        if len(team_historical) == 0:
            return self._default_advanced_stats(prefix)
        
        # Performance metrics
        points_historical = self._calculate_team_points(team_historical, team)
        points_recent = self._calculate_team_points(team_recent, team)
        
        goals_for_hist, goals_against_hist = self._calculate_team_goals(team_historical, team)
        goals_for_recent, goals_against_recent = self._calculate_team_goals(team_recent, team)
        
        # Advanced metrics
        stats = {
            f'{prefix}ppg_historical': points_historical / max(len(team_historical), 1),
            f'{prefix}ppg_recent': points_recent / max(len(team_recent), 1),
            f'{prefix}gpg_historical': goals_for_hist / max(len(team_historical), 1),
            f'{prefix}gpg_recent': goals_for_recent / max(len(team_recent), 1),
            f'{prefix}gapg_historical': goals_against_hist / max(len(team_historical), 1),
            f'{prefix}gapg_recent': goals_against_recent / max(len(team_recent), 1),
            f'{prefix}form_trend': self._calculate_form_trend(team_recent, team),
            f'{prefix}consistency': self._calculate_consistency(team_historical, team),
            f'{prefix}home_away_split': self._calculate_home_away_performance(team_historical, team, is_home),
            f'{prefix}big_match_performance': self._calculate_big_match_performance(team_historical, team),
            f'{prefix}recent_momentum': self._calculate_momentum(team_recent, team)
        }
        
        return stats
    
    def _calculate_team_points(self, matches: pd.DataFrame, team: str) -> int:
        """Calculate total points for team"""
        points = 0
        for _, match in matches.iterrows():
            if match['home_team'] == team:
                if match['outcome'] == 'Home':
                    points += 3
                elif match['outcome'] == 'Draw':
                    points += 1
            else:  # Away team
                if match['outcome'] == 'Away':
                    points += 3
                elif match['outcome'] == 'Draw':
                    points += 1
        return points
    
    def _calculate_team_goals(self, matches: pd.DataFrame, team: str) -> Tuple[int, int]:
        """Calculate goals for and against"""
        goals_for = goals_against = 0
        
        for _, match in matches.iterrows():
            if match['home_team'] == team:
                goals_for += match['home_goals']
                goals_against += match['away_goals']
            else:
                goals_for += match['away_goals']
                goals_against += match['home_goals']
        
        return goals_for, goals_against
    
    def _calculate_form_trend(self, recent_matches: pd.DataFrame, team: str) -> float:
        """Calculate form trend (improving/declining)"""
        if len(recent_matches) < 3:
            return 0.0
        
        # Get points from last 5 matches in chronological order
        team_matches = recent_matches[
            (recent_matches['home_team'] == team) | (recent_matches['away_team'] == team)
        ].tail(5)
        
        points_sequence = []
        for _, match in team_matches.iterrows():
            if match['home_team'] == team:
                if match['outcome'] == 'Home':
                    points_sequence.append(3)
                elif match['outcome'] == 'Draw':
                    points_sequence.append(1)
                else:
                    points_sequence.append(0)
            else:
                if match['outcome'] == 'Away':
                    points_sequence.append(3)
                elif match['outcome'] == 'Draw':
                    points_sequence.append(1)
                else:
                    points_sequence.append(0)
        
        if len(points_sequence) < 3:
            return 0.0
        
        # Calculate trend (recent vs earlier)
        recent_avg = np.mean(points_sequence[-2:]) if len(points_sequence) >= 2 else 0
        earlier_avg = np.mean(points_sequence[:-2]) if len(points_sequence) > 2 else recent_avg
        
        return recent_avg - earlier_avg
    
    def _calculate_consistency(self, matches: pd.DataFrame, team: str) -> float:
        """Calculate team consistency (lower variance in results)"""
        if len(matches) < 3:
            return 0.5
        
        points_list = []
        team_matches = matches[
            (matches['home_team'] == team) | (matches['away_team'] == team)
        ]
        
        for _, match in team_matches.iterrows():
            if match['home_team'] == team:
                if match['outcome'] == 'Home':
                    points_list.append(3)
                elif match['outcome'] == 'Draw':
                    points_list.append(1)
                else:
                    points_list.append(0)
            else:
                if match['outcome'] == 'Away':
                    points_list.append(3)
                elif match['outcome'] == 'Draw':
                    points_list.append(1)
                else:
                    points_list.append(0)
        
        if len(points_list) < 2:
            return 0.5
        
        # Lower standard deviation = higher consistency
        return max(0.0, 1.0 - (np.std(points_list) / 3.0))
    
    def _calculate_home_away_performance(self, matches: pd.DataFrame, team: str, is_home: bool) -> float:
        """Calculate home/away performance differential"""
        home_matches = matches[matches['home_team'] == team]
        away_matches = matches[matches['away_team'] == team]
        
        home_ppg = self._calculate_team_points(home_matches, team) / max(len(home_matches), 1)
        away_ppg = self._calculate_team_points(away_matches, team) / max(len(away_matches), 1)
        
        if is_home:
            return home_ppg - away_ppg
        else:
            return away_ppg - home_ppg
    
    def _calculate_big_match_performance(self, matches: pd.DataFrame, team: str) -> float:
        """Performance against strong opposition (placeholder)"""
        # Simplified: assume teams with more matches are stronger
        total_points = self._calculate_team_points(matches, team)
        return total_points / max(len(matches), 1)
    
    def _calculate_momentum(self, recent_matches: pd.DataFrame, team: str) -> float:
        """Recent momentum calculation"""
        team_matches = recent_matches[
            (recent_matches['home_team'] == team) | (recent_matches['away_team'] == team)
        ].tail(3)
        
        if len(team_matches) == 0:
            return 0.5
        
        points = self._calculate_team_points(team_matches, team)
        return points / (len(team_matches) * 3)  # Normalize to 0-1
    
    def _default_advanced_stats(self, prefix: str) -> Dict:
        """Default stats when no data available"""
        return {
            f'{prefix}ppg_historical': 1.0,
            f'{prefix}ppg_recent': 1.0,
            f'{prefix}gpg_historical': 1.2,
            f'{prefix}gpg_recent': 1.2,
            f'{prefix}gapg_historical': 1.2,
            f'{prefix}gapg_recent': 1.2,
            f'{prefix}form_trend': 0.0,
            f'{prefix}consistency': 0.5,
            f'{prefix}home_away_split': 0.0,
            f'{prefix}big_match_performance': 1.0,
            f'{prefix}recent_momentum': 0.5
        }
    
    def _advanced_h2h_stats(self, historical: pd.DataFrame, home_team: str, away_team: str) -> Dict:
        """Advanced head-to-head statistics"""
        
        h2h_matches = historical[
            ((historical['home_team'] == home_team) & (historical['away_team'] == away_team)) |
            ((historical['home_team'] == away_team) & (historical['away_team'] == home_team))
        ]
        
        if len(h2h_matches) == 0:
            return {
                'h2h_matches': 0,
                'h2h_home_win_rate': 0.5,
                'h2h_avg_goals': 2.5,
                'h2h_goal_trend': 0.0,
                'h2h_recent_advantage': 0.0
            }
        
        # Win rates from current home team perspective
        home_wins = len(h2h_matches[
            ((h2h_matches['home_team'] == home_team) & (h2h_matches['outcome'] == 'Home')) |
            ((h2h_matches['away_team'] == home_team) & (h2h_matches['outcome'] == 'Away'))
        ])
        
        recent_h2h = h2h_matches.tail(3)
        recent_advantage = 0
        for _, match in recent_h2h.iterrows():
            if ((match['home_team'] == home_team and match['outcome'] == 'Home') or
                (match['away_team'] == home_team and match['outcome'] == 'Away')):
                recent_advantage += 1
            elif match['outcome'] == 'Draw':
                recent_advantage += 0.5
        
        return {
            'h2h_matches': len(h2h_matches),
            'h2h_home_win_rate': home_wins / len(h2h_matches),
            'h2h_avg_goals': (h2h_matches['home_goals'] + h2h_matches['away_goals']).mean(),
            'h2h_goal_trend': (h2h_matches['home_goals'] + h2h_matches['away_goals']).tail(3).mean() - 
                             (h2h_matches['home_goals'] + h2h_matches['away_goals']).mean(),
            'h2h_recent_advantage': recent_advantage / max(len(recent_h2h), 1)
        }
    
    def _calculate_form_momentum(self, recent: pd.DataFrame, home_team: str, away_team: str) -> Dict:
        """Calculate team form and momentum indicators"""
        
        home_recent = recent[
            (recent['home_team'] == home_team) | (recent['away_team'] == home_team)
        ].tail(5)
        
        away_recent = recent[
            (recent['home_team'] == away_team) | (recent['away_team'] == away_team)
        ].tail(5)
        
        home_form = self._calculate_team_points(home_recent, home_team) / max(len(home_recent), 1)
        away_form = self._calculate_team_points(away_recent, away_team) / max(len(away_recent), 1)
        
        return {
            'form_difference': home_form - away_form,
            'combined_form': (home_form + away_form) / 2,
            'form_variance': abs(home_form - away_form),
            'home_form_strength': home_form / 3.0,  # Normalize
            'away_form_strength': away_form / 3.0
        }
    
    def _calculate_match_context(self, match: pd.Series, historical: pd.DataFrame, league_id: int) -> Dict:
        """Calculate match context and importance"""
        
        # League-specific context
        league_tiers = {39: 1, 140: 1, 135: 1, 78: 1, 61: 1}
        league_tier = league_tiers.get(league_id, 2)
        
        # Season timing
        match_date = match['match_date']
        if hasattr(match_date, 'month'):
            month = match_date.month
            season_pressure = 0.5 + (0.3 * (month % 6) / 6)  # Higher pressure mid-season
        else:
            season_pressure = 0.5
        
        # League averages for context
        if len(historical) > 0:
            league_avg_goals = (historical['home_goals'] + historical['away_goals']).mean()
            league_home_advantage = len(historical[historical['outcome'] == 'Home']) / len(historical)
        else:
            league_avg_goals = 2.5
            league_home_advantage = 0.45
        
        return {
            'league_tier': league_tier,
            'season_pressure': season_pressure,
            'league_avg_goals': league_avg_goals,
            'league_home_advantage': league_home_advantage,
            'match_importance_context': league_tier * season_pressure
        }
    
    def _calculate_prediction_features(self, home_stats: Dict, away_stats: Dict, 
                                     h2h_stats: Dict, context_stats: Dict) -> Dict:
        """Calculate prediction-oriented features"""
        
        # Expected outcome probabilities based on team strength
        home_strength = home_stats.get('home_ppg_recent', 1.0) * context_stats.get('league_home_advantage', 0.45)
        away_strength = away_stats.get('away_ppg_recent', 1.0) * (1 - context_stats.get('league_home_advantage', 0.45))
        
        total_strength = home_strength + away_strength + 0.5  # Draw factor
        
        expected_home_prob = home_strength / total_strength
        expected_away_prob = away_strength / total_strength
        expected_draw_prob = 0.5 / total_strength
        
        # Normalize
        total_prob = expected_home_prob + expected_draw_prob + expected_away_prob
        expected_home_prob /= total_prob
        expected_draw_prob /= total_prob
        expected_away_prob /= total_prob
        
        # Advanced expected goals
        home_xg = (home_stats.get('home_gpg_recent', 1.2) + 
                  context_stats.get('league_avg_goals', 2.5) * 0.45)
        away_xg = (away_stats.get('away_gpg_recent', 1.2) + 
                  context_stats.get('league_avg_goals', 2.5) * 0.35)
        
        return {
            'expected_home_prob': expected_home_prob,
            'expected_draw_prob': expected_draw_prob,
            'expected_away_prob': expected_away_prob,
            'prob_entropy': -np.sum([p * np.log(p + 1e-10) for p in [expected_home_prob, expected_draw_prob, expected_away_prob]]),
            'advanced_home_xg': home_xg,
            'advanced_away_xg': away_xg,
            'advanced_xg_diff': home_xg - away_xg,
            'match_unpredictability': abs(expected_home_prob - expected_away_prob)
        }
    
    def _add_interaction_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add interaction features between key variables"""
        
        print("Adding interaction features...")
        
        # Key interactions that might matter
        interactions = [
            ('home_ppg_recent', 'away_ppg_recent'),
            ('expected_home_prob', 'h2h_home_win_rate'),
            ('form_difference', 'h2h_recent_advantage'),
            ('advanced_home_xg', 'advanced_away_xg'),
            ('home_recent_momentum', 'away_recent_momentum')
        ]
        
        for feat1, feat2 in interactions:
            if feat1 in df.columns and feat2 in df.columns:
                df[f'{feat1}_x_{feat2}'] = df[feat1] * df[feat2]
                df[f'{feat1}_diff_{feat2}'] = df[feat1] - df[feat2]
        
        return df
    
    def train_advanced_ensemble(self, X: pd.DataFrame, y: np.ndarray) -> Dict:
        """Train advanced ensemble models"""
        
        print("TRAINING ADVANCED ENSEMBLE")
        print("=" * 40)
        
        # Fill missing values
        X_filled = X.fillna(X.median())
        
        # Time-aware split
        split_idx = int(0.8 * len(X_filled))
        X_train, X_test = X_filled.iloc[:split_idx], X_filled.iloc[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        print(f"Training: {len(X_train)}, Testing: {len(X_test)}")
        
        # Feature selection
        selector = SelectKBest(f_classif, k=min(50, X_train.shape[1]))  # Top 50 features
        X_train_selected = selector.fit_transform(X_train, y_train)
        X_test_selected = selector.transform(X_test)
        
        selected_features = X_train.columns[selector.get_support()].tolist()
        print(f"Selected {len(selected_features)} best features")
        
        models = {}
        
        # 1. Optimized Random Forest
        rf = RandomForestClassifier(
            n_estimators=300,
            max_depth=10,
            min_samples_split=12,
            min_samples_leaf=6,
            max_features='sqrt',
            random_state=42,
            class_weight='balanced',
            n_jobs=-1
        )
        
        rf.fit(X_train_selected, y_train)
        rf_calibrated = CalibratedClassifierCV(rf, method='isotonic', cv=3)
        rf_calibrated.fit(X_train_selected, y_train)
        
        rf_probs = rf_calibrated.predict_proba(X_test_selected)
        rf_preds = rf.predict(X_test_selected)
        
        models['optimized_random_forest'] = {
            'accuracy': accuracy_score(y_test, rf_preds),
            'log_loss': log_loss(y_test, rf_probs),
            'brier_score': self._multiclass_brier_score(y_test, rf_probs),
            'model': rf_calibrated
        }
        
        # 2. Gradient Boosting
        gb = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42
        )
        
        gb.fit(X_train_selected, y_train)
        gb_calibrated = CalibratedClassifierCV(gb, method='isotonic', cv=3)
        gb_calibrated.fit(X_train_selected, y_train)
        
        gb_probs = gb_calibrated.predict_proba(X_test_selected)
        gb_preds = gb.predict(X_test_selected)
        
        models['gradient_boosting'] = {
            'accuracy': accuracy_score(y_test, gb_preds),
            'log_loss': log_loss(y_test, gb_probs),
            'brier_score': self._multiclass_brier_score(y_test, gb_probs),
            'model': gb_calibrated
        }
        
        # 3. Voting Ensemble
        voting_clf = VotingClassifier(
            estimators=[
                ('rf', rf),
                ('gb', gb)
            ],
            voting='soft'
        )
        
        voting_clf.fit(X_train_selected, y_train)
        voting_calibrated = CalibratedClassifierCV(voting_clf, method='isotonic', cv=3)
        voting_calibrated.fit(X_train_selected, y_train)
        
        voting_probs = voting_calibrated.predict_proba(X_test_selected)
        voting_preds = voting_clf.predict(X_test_selected)
        
        models['voting_ensemble'] = {
            'accuracy': accuracy_score(y_test, voting_preds),
            'log_loss': log_loss(y_test, voting_probs),
            'brier_score': self._multiclass_brier_score(y_test, voting_probs),
            'model': voting_calibrated
        }
        
        # Feature importance from best model
        best_model_name = max(models.keys(), key=lambda x: models[x]['accuracy'])
        
        if 'random_forest' in best_model_name:
            feature_importance = pd.DataFrame({
                'feature': selected_features,
                'importance': rf.feature_importances_
            }).sort_values('importance', ascending=False)
        else:
            feature_importance = pd.DataFrame({
                'feature': selected_features,
                'importance': gb.feature_importances_
            }).sort_values('importance', ascending=False)
        
        print(f"\nTop 10 Advanced Features:")
        for _, row in feature_importance.head(10).iterrows():
            print(f"  {row['feature']}: {row['importance']:.4f}")
        
        models['feature_importance'] = feature_importance
        models['selected_features'] = selected_features
        
        return models, y_test
    
    def _multiclass_brier_score(self, y_true: np.ndarray, y_prob: np.ndarray) -> float:
        """Calculate multiclass Brier score"""
        y_true_binary = np.zeros((len(y_true), y_prob.shape[1]))
        for i, label in enumerate(y_true):
            y_true_binary[i, label] = 1
        return np.mean(np.sum((y_prob - y_true_binary) ** 2, axis=1))
    
    def evaluate_advanced_results(self, models: Dict, baseline_accuracy: float = 0.501) -> Dict:
        """Evaluate advanced enhancement results"""
        
        print(f"\nADVANCED ENHANCEMENT EVALUATION")
        print("=" * 50)
        
        results = {}
        
        print(f"{'Model':<25} | {'Accuracy':<8} | {'vs Enhanced':<12} | {'Status'}")
        print("-" * 75)
        print(f"{'Enhanced Baseline':<25} | {baseline_accuracy:.3f}   | {'BASELINE':<12} | {'Reference'}")
        print("-" * 75)
        
        for model_name, model_data in models.items():
            if model_name in ['feature_importance', 'selected_features']:
                continue
                
            accuracy = model_data['accuracy']
            improvement = (accuracy - baseline_accuracy) / baseline_accuracy * 100
            
            if accuracy >= 0.55:
                status = "🎯 TARGET ACHIEVED"
            elif accuracy >= 0.53:
                status = "🚀 EXCELLENT"
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
    """Run advanced Phase 1A enhancement"""
    
    enhancer = AdvancedPhase1AEnhancer()
    
    try:
        print("ADVANCED PHASE 1A ENHANCEMENT")
        print("=" * 50)
        print("Target: Push from 50.1% toward 55%")
        print("Methods: Advanced features + ensemble models")
        
        # Load enhanced dataset
        X, y = enhancer.load_enhanced_dataset()
        
        # Train advanced ensemble
        models, y_test = enhancer.train_advanced_ensemble(X, y)
        
        # Evaluate results
        results = enhancer.evaluate_advanced_results(models)
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        os.makedirs('reports', exist_ok=True)
        
        advanced_results = {
            'timestamp': timestamp,
            'phase': 'advanced_1a_enhancement',
            'baseline_accuracy': 0.501,
            'target_accuracy': 0.55,
            'models': {k: v for k, v in models.items() if k not in ['feature_importance', 'selected_features']},
            'results': results,
            'feature_importance': models.get('feature_importance', pd.DataFrame()).head(15).to_dict('records'),
            'features_used': len(models.get('selected_features', []))
        }
        
        json_path = f'reports/advanced_phase1a_{timestamp}.json'
        with open(json_path, 'w') as f:
            json.dump(advanced_results, f, indent=2, default=str)
        
        # Summary
        best_model = max(results.keys(), key=lambda x: results[x]['accuracy'])
        best_accuracy = results[best_model]['accuracy']
        improvement = results[best_model]['improvement']
        
        print(f"\n" + "="*60)
        print("ADVANCED PHASE 1A COMPLETE")
        print("="*60)
        print(f"Best Model: {best_model.replace('_', ' ').title()}")
        print(f"Accuracy: {best_accuracy:.1%} (was 50.1%)")
        print(f"Improvement: {improvement:+.1f}%")
        
        if best_accuracy >= 0.55:
            print("🎯 TARGET ACHIEVED: 55%+ accuracy reached!")
            print("Phase 1A enhancement successful!")
        elif best_accuracy >= 0.53:
            print("🚀 EXCELLENT PROGRESS: Very close to target")
        elif improvement > 0:
            print("✅ CONTINUED IMPROVEMENT")
        else:
            print("⚠️ Need different approach")
        
        print(f"Results saved: {json_path}")
        
    finally:
        enhancer.conn.close()

if __name__ == "__main__":
    main()