"""
Quick Two-Stage Model Test - Prove the concept works to fix draw bias
Uses existing data with basic features plus simple team strength indicators
"""

import os
import numpy as np
import pandas as pd
import joblib
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.preprocessing import StandardScaler
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

class QuickTwoStageTest:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
    
    def build_quick_dataset(self):
        """Build dataset with basic features plus simple team strength"""
        print("🔨 Building quick enhanced dataset...")
        
        with self.engine.connect() as conn:
            # Get matches with basic info
            result = conn.execute(text("""
                SELECT 
                    home_team, away_team, league_id, region, outcome, match_date
                FROM training_matches 
                WHERE outcome IN ('Home', 'Away', 'Draw')
                AND home_team != away_team
                AND league_id IS NOT NULL
                ORDER BY match_date
            """)).fetchall()
        
        X, y = [], []
        
        # Simple team strength lookup (based on team names for quick testing)
        team_strength = self._build_simple_team_strength()
        
        for home_team, away_team, league_id, region, outcome, match_date in result:
            try:
                # Original clean features
                original_features = self._extract_original_features(league_id, region)
                
                # Simple team strength features
                home_strength = team_strength.get(home_team, 0.5)
                away_strength = team_strength.get(away_team, 0.5)
                
                # Enhanced features
                enhanced_features = {
                    **original_features,
                    'home_team_strength': home_strength,
                    'away_team_strength': away_strength,
                    'strength_diff': home_strength - away_strength,
                    'strength_sum': home_strength + away_strength,
                    'home_advantage': 0.55,  # Standard home advantage
                    'match_competitiveness': abs(home_strength - away_strength),
                    'total_quality': (home_strength + away_strength) / 2,
                    'home_favored': int(home_strength > away_strength + 0.1),
                    'away_favored': int(away_strength > home_strength + 0.1),
                    'even_match': int(abs(home_strength - away_strength) < 0.1)
                }
                
                X.append(list(enhanced_features.values()))
                
                # Encode outcome
                if outcome == 'Home':
                    y.append(0)
                elif outcome == 'Draw':
                    y.append(1)
                else:  # Away
                    y.append(2)
                    
            except Exception as e:
                continue
        
        feature_names = list(enhanced_features.keys())
        print(f"✅ Dataset built: {len(X)} matches, {len(feature_names)} features")
        
        return np.array(X), np.array(y), feature_names
    
    def _build_simple_team_strength(self):
        """Build simple team strength based on win rates"""
        team_strength = {}
        
        with self.engine.connect() as conn:
            # Home team stats
            home_stats = conn.execute(text("""
                SELECT 
                    home_team,
                    COUNT(*) as matches,
                    SUM(CASE WHEN outcome = 'Home' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'Draw' THEN 1 ELSE 0 END) as draws
                FROM training_matches
                WHERE outcome IN ('Home', 'Draw', 'Away')
                GROUP BY home_team
                HAVING COUNT(*) >= 5
            """)).fetchall()
            
            for home_team, matches, wins, draws in home_stats:
                points = wins * 3 + draws
                max_points = matches * 3
                strength = points / max_points if max_points > 0 else 0.5
                team_strength[home_team] = strength
            
            # Away team stats
            away_stats = conn.execute(text("""
                SELECT 
                    away_team,
                    COUNT(*) as matches,
                    SUM(CASE WHEN outcome = 'Away' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN outcome = 'Draw' THEN 1 ELSE 0 END) as draws
                FROM training_matches
                WHERE outcome IN ('Home', 'Draw', 'Away')
                GROUP BY away_team
                HAVING COUNT(*) >= 5
            """)).fetchall()
            
            for away_team, matches, wins, draws in away_stats:
                points = wins * 3 + draws
                max_points = matches * 3
                strength = points / max_points if max_points > 0 else 0.5
                
                # Average with home strength if exists
                if away_team in team_strength:
                    team_strength[away_team] = (team_strength[away_team] + strength) / 2
                else:
                    team_strength[away_team] = strength
        
        print(f"📊 Team strengths calculated for {len(team_strength)} teams")
        return team_strength
    
    def _extract_original_features(self, league_id, region):
        """Extract original clean features"""
        tier1_leagues = [39, 140, 135, 78, 61]
        tier2_leagues = [88, 203, 179]
        
        if league_id in tier1_leagues:
            league_tier = 1.0
            league_competitiveness = 0.85
            expected_goals = 2.7
        elif league_id in tier2_leagues:
            league_tier = 0.7
            league_competitiveness = 0.75
            expected_goals = 2.4
        else:
            league_tier = 0.5
            league_competitiveness = 0.65
            expected_goals = 2.2
        
        if region == 'Europe':
            regional_strength = 1.0
        elif region == 'South America':
            regional_strength = 0.9
        elif region == 'Africa':
            regional_strength = 0.7
        else:
            regional_strength = 0.6
        
        home_advantage_factor = 0.55
        
        if league_id == 39:
            match_importance = 0.9
        elif league_id in tier1_leagues:
            match_importance = 0.8
        else:
            match_importance = 0.7
        
        premier_league_indicator = 1.0 if league_id == 39 else 0.0
        top5_league_indicator = 1.0 if league_id in tier1_leagues else 0.0
        
        return {
            'league_tier': league_tier,
            'league_competitiveness': league_competitiveness,
            'regional_strength': regional_strength,
            'home_advantage_factor': home_advantage_factor,
            'expected_goals_avg': expected_goals,
            'match_importance': match_importance,
            'premier_league_indicator': premier_league_indicator,
            'top5_league_indicator': top5_league_indicator
        }
    
    def train_two_stage_model(self, X, y, feature_names):
        """Train and test two-stage model"""
        print("\n🎯 Training Two-Stage Model")
        
        # Time-based split (75% train, 25% test)
        split_idx = int(len(X) * 0.75)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        print(f"📊 Train: {len(X_train)}, Test: {len(X_test)}")
        
        # Check class distribution
        unique, counts = np.unique(y_train, return_counts=True)
        class_dist = dict(zip(unique, counts))
        print(f"📈 Class distribution - Home: {class_dist.get(0, 0)}, Draw: {class_dist.get(1, 0)}, Away: {class_dist.get(2, 0)}")
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Stage 1: Draw vs Not-Draw
        print("\n🎯 Stage 1: Draw vs Not-Draw")
        y_draw_train = (y_train == 1).astype(int)
        y_draw_test = (y_test == 1).astype(int)
        
        stage1_model = RandomForestClassifier(
            n_estimators=50, max_depth=10, min_samples_split=20,
            class_weight='balanced', random_state=42
        )
        stage1_model.fit(X_train_scaled, y_draw_train)
        
        stage1_pred = stage1_model.predict(X_test_scaled)
        stage1_proba = stage1_model.predict_proba(X_test_scaled)[:, 1]
        stage1_acc = accuracy_score(y_draw_test, stage1_pred)
        
        print(f"  Stage 1 Accuracy: {stage1_acc:.3f}")
        print(f"  Draw detection: {np.sum(stage1_pred)} predicted draws out of {np.sum(y_draw_test)} actual")
        
        # Stage 2: Home vs Away (on non-draws)
        print("\n🎯 Stage 2: Home vs Away (on non-draws)")
        
        # Training data for stage 2 (non-draws only)
        not_draw_train_mask = y_train != 1
        not_draw_test_mask = y_test != 1
        
        X_train_not_draw = X_train_scaled[not_draw_train_mask]
        y_home_train = (y_train[not_draw_train_mask] == 0).astype(int)  # 1=Home, 0=Away
        
        X_test_not_draw = X_test_scaled[not_draw_test_mask]
        y_home_test = (y_test[not_draw_test_mask] == 0).astype(int)
        
        print(f"  Stage 2 training: {len(X_train_not_draw)} non-draw matches")
        print(f"  Stage 2 testing: {len(X_test_not_draw)} non-draw matches")
        
        stage2_model = RandomForestClassifier(
            n_estimators=50, max_depth=10, min_samples_split=15,
            class_weight='balanced', random_state=42
        )
        stage2_model.fit(X_train_not_draw, y_home_train)
        
        if len(X_test_not_draw) > 0:
            stage2_pred = stage2_model.predict(X_test_not_draw)
            stage2_acc = accuracy_score(y_home_test, stage2_pred)
            print(f"  Stage 2 Accuracy: {stage2_acc:.3f}")
        else:
            stage2_acc = 0.5
            print(f"  Stage 2: No test data available")
        
        # Combined model evaluation
        print("\n🎯 Combined Two-Stage Model Evaluation")
        combined_predictions = self._combine_predictions(stage1_proba, stage2_model, X_test_scaled, not_draw_test_mask)
        combined_acc = accuracy_score(y_test, combined_predictions)
        
        print(f"  Combined Accuracy: {combined_acc:.3f} ({combined_acc*100:.1f}%)")
        print(f"  Improvement over random (33.3%): {(combined_acc-0.333)*100:.1f} percentage points")
        
        # Show confusion matrix
        print("\n📊 Confusion Matrix:")
        cm = confusion_matrix(y_test, combined_predictions)
        class_names = ['Home', 'Draw', 'Away']
        print(f"           Predicted")
        print(f"Actual     Home  Draw  Away")
        for i, actual in enumerate(class_names):
            print(f"{actual:6s}   {cm[i][0]:4d}  {cm[i][1]:4d}  {cm[i][2]:4d}")
        
        # Classification report
        print(f"\n📋 Classification Report:")
        print(classification_report(y_test, combined_predictions, target_names=class_names, zero_division=0))
        
        # Save the model
        model_data = {
            'model_draw_vs_not': stage1_model,
            'model_home_vs_away': stage2_model,
            'scaler': scaler,
            'feature_order': feature_names,
            'stage1_accuracy': stage1_acc,
            'stage2_accuracy': stage2_acc,
            'combined_accuracy': combined_acc,
            'training_date': datetime.now().isoformat(),
            'model_version': 'TwoStage_Quick_v1.0',
            'feature_count': len(feature_names)
        }
        
        os.makedirs('models', exist_ok=True)
        joblib.dump(model_data, 'models/clean_production_model.joblib')
        print(f"\n💾 Model saved: models/clean_production_model.joblib")
        
        return combined_acc
    
    def _combine_predictions(self, stage1_proba, stage2_model, X_test_scaled, not_draw_test_mask):
        """Combine stage 1 and stage 2 predictions"""
        n_test = len(X_test_scaled)
        combined_pred = np.full(n_test, 1)  # Initialize as Draw
        
        # Get indices where stage 1 predicts "not draw"
        not_draw_pred_mask = stage1_proba < 0.5
        
        if np.sum(not_draw_pred_mask) > 0:
            # For predicted non-draws, get stage 2 predictions
            X_pred_not_draw = X_test_scaled[not_draw_pred_mask]
            stage2_proba = stage2_model.predict_proba(X_pred_not_draw)[:, 1]  # Prob of Home
            
            # Convert to final predictions
            home_pred = stage2_proba >= 0.5
            combined_pred[not_draw_pred_mask] = np.where(home_pred, 0, 2)  # 0=Home, 2=Away
        
        return combined_pred

def main():
    print("🚀 Quick Two-Stage Model Test")
    print("Testing concept to fix draw bias issue")
    print("=" * 45)
    
    tester = QuickTwoStageTest()
    
    try:
        # Build dataset
        X, y, feature_names = tester.build_quick_dataset()
        
        if len(X) < 100:
            print("❌ Insufficient data")
            return
        
        # Train and test two-stage model
        accuracy = tester.train_two_stage_model(X, y, feature_names)
        
        print(f"\n🎯 Results Summary:")
        print(f"  Two-Stage Accuracy: {accuracy:.1%}")
        
        if accuracy >= 0.50:
            print(f"  ✅ SUCCESS: Significantly above random!")
        elif accuracy >= 0.40:
            print(f"  📈 PROGRESS: Good improvement over baseline")
        elif accuracy >= 0.35:
            print(f"  📊 IMPROVEMENT: Better than previous 27.3%")
        else:
            print(f"  📊 BASELINE: Similar to previous performance")
        
        print(f"\n🚀 Next steps:")
        if accuracy >= 0.40:
            print(f"  • Two-stage approach works! Implement full feature engineering")
            print(f"  • Add proper form features (last 5 matches)")
            print(f"  • Add Elo ratings and head-to-head data")
            print(f"  • Target: 60%+ with complete features")
        else:
            print(f"  • Need more sophisticated team strength features")
            print(f"  • Consider different model architectures")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()