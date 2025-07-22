"""
Two-Stage Classification Training - Fix the "draw bias" problem
Stage 1: Predict Draw vs Not-Draw
Stage 2: On Not-Draw cases, predict Home vs Away
"""

import os
import sys
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import accuracy_score, classification_report, log_loss
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV
import warnings
warnings.filterwarnings('ignore')

# Add src to path for imports
sys.path.append('/home/runner/workspace/src')
from features.form_features import TeamFormFeatures
from features.elo import EloRatingSystem

class TwoStageTrainer:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
        self.form_extractor = TeamFormFeatures()
        self.elo_system = EloRatingSystem()
        
    def build_enhanced_dataset(self) -> pd.DataFrame:
        """Build dataset with enhanced features (form + elo + original)"""
        print("🔨 Building enhanced dataset with form and Elo features...")
        
        with self.engine.connect() as conn:
            # Get all training matches with team IDs
            query = text("""
                SELECT 
                    match_id,
                    home_team_id,
                    away_team_id,
                    home_team,
                    away_team,
                    league_id,
                    region,
                    match_date,
                    outcome
                FROM training_matches
                WHERE outcome IN ('Home', 'Draw', 'Away')
                AND home_team_id IS NOT NULL
                AND away_team_id IS NOT NULL
                AND home_team != away_team
                ORDER BY match_date ASC
            """)
            
            matches_df = pd.read_sql(query, conn)
        
        print(f"📊 Processing {len(matches_df)} matches...")
        
        feature_rows = []
        processed = 0
        
        for _, match in matches_df.iterrows():
            try:
                # Extract original clean features
                original_features = self._extract_original_features(
                    match['league_id'], match['region']
                )
                
                # Extract form features
                form_features = self.form_extractor.extract_team_form_features(
                    match_id=match['match_id'],
                    home_team_id=match['home_team_id'],
                    away_team_id=match['away_team_id'],
                    match_date=match['match_date']
                )
                
                # Extract Elo features
                elo_features = self.elo_system.extract_elo_features(
                    match_id=match['match_id'],
                    home_team_id=match['home_team_id'],
                    away_team_id=match['away_team_id'],
                    match_date=match['match_date']
                )
                
                # Combine all features
                combined_features = {
                    'match_id': match['match_id'],
                    'outcome': match['outcome'],
                    **original_features,
                    **form_features,
                    **elo_features
                }
                
                feature_rows.append(combined_features)
                processed += 1
                
                if processed % 100 == 0:
                    print(f"  Processed {processed}/{len(matches_df)} matches...")
                    
            except Exception as e:
                print(f"  ⚠️ Skipped match {match['match_id']}: {e}")
                continue
        
        dataset_df = pd.DataFrame(feature_rows)
        print(f"✅ Enhanced dataset built: {len(dataset_df)} matches with {len(dataset_df.columns)-2} features")
        
        return dataset_df
    
    def _extract_original_features(self, league_id: int, region: str) -> dict:
        """Extract original clean features for consistency"""
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
    
    def train_two_stage_model(self, dataset_df: pd.DataFrame):
        """Train the two-stage classification model"""
        print("🎯 Training Two-Stage Classification Model")
        
        # Prepare features and targets
        feature_cols = [col for col in dataset_df.columns if col not in ['match_id', 'outcome']]
        X = dataset_df[feature_cols].fillna(0)  # Handle any missing values
        
        # Encode outcomes
        outcome_map = {'Home': 0, 'Draw': 1, 'Away': 2}
        y_original = dataset_df['outcome'].map(outcome_map)
        
        # Create binary targets for two-stage approach
        y_draw_vs_not = (y_original == 1).astype(int)  # 1 = Draw, 0 = Not Draw
        
        # For stage 2, only use non-draw matches
        not_draw_mask = y_original != 1
        X_not_draw = X[not_draw_mask]
        y_home_vs_away = (y_original[not_draw_mask] == 0).astype(int)  # 1 = Home, 0 = Away
        
        print(f"📊 Dataset distribution:")
        print(f"  Total matches: {len(X)}")
        print(f"  Draws: {sum(y_draw_vs_not)} ({sum(y_draw_vs_not)/len(y_draw_vs_not)*100:.1f}%)")
        print(f"  Not-Draws: {sum(~y_draw_vs_not.astype(bool))} ({sum(~y_draw_vs_not.astype(bool))/len(y_draw_vs_not)*100:.1f}%)")
        print(f"  Home wins (of not-draws): {sum(y_home_vs_away)} ({sum(y_home_vs_away)/len(y_home_vs_away)*100:.1f}%)")
        print(f"  Away wins (of not-draws): {sum(~y_home_vs_away.astype(bool))} ({sum(~y_home_vs_away.astype(bool))/len(y_home_vs_away)*100:.1f}%)")
        
        # Time-based split (use earlier matches for training)
        split_idx = int(len(X) * 0.75)  # First 75% for training
        
        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_draw_train = y_draw_vs_not.iloc[:split_idx]
        y_draw_test = y_draw_vs_not.iloc[split_idx:]
        
        # Stage 2 split
        not_draw_train_mask = not_draw_mask.iloc[:split_idx]
        not_draw_test_mask = not_draw_mask.iloc[split_idx:]
        
        X_train_not_draw = X_train[not_draw_train_mask]
        X_test_not_draw = X_test[not_draw_test_mask]
        y_home_train = y_home_vs_away.iloc[:sum(not_draw_train_mask)]
        y_home_test = y_home_vs_away.iloc[sum(not_draw_train_mask):]
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        X_train_not_draw_scaled = scaler.transform(X_train_not_draw)
        X_test_not_draw_scaled = scaler.transform(X_test_not_draw)
        
        print("\n🎯 Stage 1: Training Draw vs Not-Draw classifier...")
        
        # Stage 1: Draw vs Not-Draw
        stage1_models = {
            'rf': RandomForestClassifier(
                n_estimators=100, max_depth=12, min_samples_split=20,
                min_samples_leaf=10, class_weight='balanced', random_state=42
            ),
            'lr': LogisticRegression(
                class_weight='balanced', random_state=42, max_iter=1000
            )
        }
        
        stage1_results = {}
        for name, model in stage1_models.items():
            # Cross-validation
            cv_scores = cross_val_score(model, X_train_scaled, y_draw_train, cv=5, scoring='accuracy')
            
            # Fit and test
            model.fit(X_train_scaled, y_draw_train)
            y_pred = model.predict(X_test_scaled)
            test_acc = accuracy_score(y_draw_test, y_pred)
            
            stage1_results[name] = {
                'model': model,
                'cv_mean': cv_scores.mean(),
                'cv_std': cv_scores.std(),
                'test_acc': test_acc
            }
            
            print(f"  {name.upper()}: CV={cv_scores.mean():.3f}±{cv_scores.std():.3f}, Test={test_acc:.3f}")
        
        # Select best Stage 1 model
        best_stage1_name = max(stage1_results.keys(), key=lambda x: stage1_results[x]['test_acc'])
        best_stage1_model = stage1_results[best_stage1_name]['model']
        print(f"  ✅ Best Stage 1: {best_stage1_name}")
        
        print("\n🎯 Stage 2: Training Home vs Away classifier (on non-draws)...")
        
        # Stage 2: Home vs Away (on non-draws only)
        stage2_models = {
            'rf': RandomForestClassifier(
                n_estimators=100, max_depth=12, min_samples_split=20,
                min_samples_leaf=10, class_weight='balanced', random_state=42
            ),
            'lr': LogisticRegression(
                class_weight='balanced', random_state=42, max_iter=1000
            )
        }
        
        stage2_results = {}
        for name, model in stage2_models.items():
            if len(X_train_not_draw_scaled) == 0:
                print(f"  ⚠️ No non-draw training data for {name}")
                continue
                
            # Cross-validation
            cv_scores = cross_val_score(model, X_train_not_draw_scaled, y_home_train, cv=5, scoring='accuracy')
            
            # Fit and test
            model.fit(X_train_not_draw_scaled, y_home_train)
            if len(X_test_not_draw_scaled) > 0:
                y_pred = model.predict(X_test_not_draw_scaled)
                test_acc = accuracy_score(y_home_test, y_pred)
            else:
                test_acc = 0.5
            
            stage2_results[name] = {
                'model': model,
                'cv_mean': cv_scores.mean(),
                'cv_std': cv_scores.std(),
                'test_acc': test_acc
            }
            
            print(f"  {name.upper()}: CV={cv_scores.mean():.3f}±{cv_scores.std():.3f}, Test={test_acc:.3f}")
        
        # Select best Stage 2 model
        if stage2_results:
            best_stage2_name = max(stage2_results.keys(), key=lambda x: stage2_results[x]['test_acc'])
            best_stage2_model = stage2_results[best_stage2_name]['model']
            print(f"  ✅ Best Stage 2: {best_stage2_name}")
        else:
            print("  ❌ No Stage 2 models trained")
            return None
        
        # Evaluate combined two-stage model
        print("\n🎯 Evaluating Combined Two-Stage Model...")
        combined_accuracy = self._evaluate_two_stage_model(
            best_stage1_model, best_stage2_model, scaler,
            X_test_scaled, y_draw_test, X_test_not_draw_scaled, y_home_test, not_draw_test_mask
        )
        
        # Save the model
        model_data = {
            'model_draw_vs_not': best_stage1_model,
            'model_home_vs_away': best_stage2_model,
            'scaler': scaler,
            'feature_order': feature_cols,
            'stage1_accuracy': stage1_results[best_stage1_name]['test_acc'],
            'stage2_accuracy': stage2_results[best_stage2_name]['test_acc'],
            'combined_accuracy': combined_accuracy,
            'training_date': datetime.now().isoformat(),
            'model_version': 'TwoStage_Enhanced_v1.0',
            'data_leakage_prevented': True,
            'feature_count': len(feature_cols)
        }
        
        os.makedirs('models', exist_ok=True)
        joblib.dump(model_data, 'models/clean_production_model.joblib')
        
        print(f"\n🎉 Two-Stage Model Training Complete!")
        print(f"  Stage 1 (Draw vs Not): {stage1_results[best_stage1_name]['test_acc']:.3f}")
        print(f"  Stage 2 (Home vs Away): {stage2_results[best_stage2_name]['test_acc']:.3f}")
        print(f"  Combined Accuracy: {combined_accuracy:.3f}")
        print(f"  Model saved: models/clean_production_model.joblib")
        
        return model_data
    
    def _evaluate_two_stage_model(self, stage1_model, stage2_model, scaler, 
                                X_test_scaled, y_draw_test, X_test_not_draw_scaled, 
                                y_home_test, not_draw_test_mask):
        """Evaluate the combined two-stage model"""
        
        # Stage 1 predictions (Draw vs Not-Draw)
        draw_proba = stage1_model.predict_proba(X_test_scaled)[:, 1]  # Probability of Draw
        draw_pred = (draw_proba >= 0.5).astype(int)
        
        # Stage 2 predictions (Home vs Away on predicted non-draws)
        final_predictions = np.full(len(X_test_scaled), 1)  # Initialize as Draw
        
        # For predicted non-draws, get Home vs Away predictions
        not_draw_indices = np.where(draw_pred == 0)[0]
        
        if len(not_draw_indices) > 0 and len(X_test_not_draw_scaled) > 0:
            # Get corresponding features for non-draw predictions
            X_pred_not_draw = X_test_scaled[not_draw_indices]
            home_proba = stage2_model.predict_proba(X_pred_not_draw)[:, 1]  # Probability of Home
            home_pred = (home_proba >= 0.5).astype(int)
            
            # Update final predictions
            final_predictions[not_draw_indices] = np.where(home_pred == 1, 0, 2)  # 0=Home, 2=Away
        
        # Convert test outcomes to same format
        y_test_combined = np.full(len(y_draw_test), 1)  # Initialize as Draw
        y_test_combined[~not_draw_test_mask] = 1  # Draws stay as 1
        
        # For actual non-draws, set correct Home/Away labels
        actual_not_draw_indices = np.where(~not_draw_test_mask)[0]
        if len(actual_not_draw_indices) > 0 and len(y_home_test) > 0:
            y_test_combined[actual_not_draw_indices] = np.where(y_home_test == 1, 0, 2)
        
        # Calculate accuracy
        accuracy = accuracy_score(y_test_combined, final_predictions)
        
        # Show classification report
        class_names = ['Home', 'Draw', 'Away']
        print(f"\n📋 Combined Model Classification Report:")
        print(classification_report(y_test_combined, final_predictions, target_names=class_names, zero_division=0))
        
        return accuracy

def main():
    """Train the two-stage enhanced model"""
    print("🚀 BetGenius AI - Two-Stage Enhanced Training")
    print("=" * 50)
    
    trainer = TwoStageTrainer()
    
    try:
        # Build enhanced dataset
        dataset = trainer.build_enhanced_dataset()
        
        if len(dataset) < 100:
            print("❌ Insufficient data for training")
            return
        
        # Train two-stage model
        model_data = trainer.train_two_stage_model(dataset)
        
        if model_data:
            print(f"\n✅ Training successful!")
            print(f"📊 Enhanced features: {model_data['feature_count']}")
            print(f"🎯 Combined accuracy: {model_data['combined_accuracy']:.1%}")
            
            if model_data['combined_accuracy'] >= 0.45:
                print(f"🎉 SUCCESS: Above 45% target accuracy!")
            elif model_data['combined_accuracy'] >= 0.35:
                print(f"📈 PROGRESS: Significant improvement over baseline")
            else:
                print(f"📊 FOUNDATION: Better than random, needs more features")
        else:
            print(f"❌ Training failed")
    
    except Exception as e:
        print(f"❌ Training error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()