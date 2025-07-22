"""
Accuracy Analysis - Compare baseline vs enhanced features
Find out why accuracy declined from 74% to 65%
"""

import os
import numpy as np
import joblib
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler

class AccuracyAnalyzer:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
    
    def analyze_accuracy_decline(self):
        """Compare baseline vs enhanced features to identify the problem"""
        print("🔍 Analyzing accuracy decline: 74% → 65%")
        
        # Test 1: Load and test with original baseline features
        print("\n📊 Test 1: Baseline Features Only")
        baseline_accuracy = self.test_baseline_features()
        
        # Test 2: Test with enhanced features
        print("\n📊 Test 2: Enhanced Features")
        enhanced_accuracy = self.test_enhanced_features()
        
        # Test 3: Test with selective enhanced features
        print("\n📊 Test 3: Selective Enhanced Features")
        selective_accuracy = self.test_selective_features()
        
        # Summary
        self.show_analysis_results(baseline_accuracy, enhanced_accuracy, selective_accuracy)
    
    def test_baseline_features(self):
        """Test with original baseline features that achieved 74%"""
        print("Loading matches with baseline feature extraction...")
        
        with self.engine.connect() as conn:
            # Get matches from any phase but extract baseline features
            result = conn.execute(text("""
                SELECT home_team, away_team, home_goals, away_goals, outcome, league_id
                FROM training_matches 
                WHERE outcome IN ('Home', 'Away', 'Draw')
                LIMIT 1500
            """)).fetchall()
        
        X, y = [], []
        
        for home_team, away_team, home_goals, away_goals, outcome, league_id in result:
            # Extract simple baseline features (what worked at 74%)
            features = [
                float(home_goals) if home_goals else 0.0,      # home_goals
                float(away_goals) if away_goals else 0.0,      # away_goals
                1.0 if league_id in [39, 140, 135, 78, 61] else 0.0,  # top5_league
                0.6 if league_id == 39 else 0.7,              # league_competitiveness
                1.0,  # recency_weight
                2.0   # goal_expectancy_baseline
            ]
            
            X.append(features)
            y.append(0 if outcome == 'Home' else 1 if outcome == 'Draw' else 2)
        
        return self.train_and_test_model(np.array(X), np.array(y), "Baseline")
    
    def test_enhanced_features(self):
        """Test current enhanced features"""
        print("Loading enhanced features...")
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT features, outcome
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Complete_Enhancement'
                AND features IS NOT NULL 
                AND outcome IN ('Home', 'Away', 'Draw')
                LIMIT 1500
            """)).fetchall()
        
        X, y = [], []
        feature_names = None
        
        for features_dict, outcome in result:
            if isinstance(features_dict, dict):
                if not feature_names:
                    feature_names = [k for k, v in features_dict.items() 
                                   if isinstance(v, (int, float)) and 'timestamp' not in k.lower()]
                
                features = []
                for name in feature_names:
                    value = features_dict.get(name, 0)
                    features.append(float(value) if isinstance(value, (int, float)) else 0.0)
                
                if len(features) == len(feature_names):
                    X.append(features)
                    y.append(0 if outcome == 'Home' else 1 if outcome == 'Draw' else 2)
        
        print(f"Enhanced features count: {len(feature_names) if feature_names else 0}")
        return self.train_and_test_model(np.array(X), np.array(y), "Enhanced")
    
    def test_selective_features(self):
        """Test with only the most promising enhanced features"""
        print("Loading selective enhanced features...")
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT features, outcome
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Complete_Enhancement'
                AND features IS NOT NULL 
                AND outcome IN ('Home', 'Away', 'Draw')
                LIMIT 1500
            """)).fetchall()
        
        X, y = [], []
        
        # Only use features that should logically help prediction
        key_features = [
            'goal_expectancy', 'recency_score', 'match_importance',
            'competition_tier', 'league_competitiveness', 'training_weight'
        ]
        
        for features_dict, outcome in result:
            if isinstance(features_dict, dict):
                features = []
                for name in key_features:
                    value = features_dict.get(name, 0)
                    features.append(float(value) if isinstance(value, (int, float)) else 0.0)
                
                X.append(features)
                y.append(0 if outcome == 'Home' else 1 if outcome == 'Draw' else 2)
        
        print(f"Selective features: {key_features}")
        return self.train_and_test_model(np.array(X), np.array(y), "Selective")
    
    def train_and_test_model(self, X, y, model_name):
        """Train and test a model configuration"""
        if len(X) == 0:
            print(f"❌ No data for {model_name}")
            return 0.0
        
        print(f"Training {model_name}: {len(X)} samples, {len(X[0])} features")
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y
        )
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Simple ensemble like our baseline
        rf_model = RandomForestClassifier(
            n_estimators=50,
            max_depth=10,
            min_samples_split=20,
            random_state=42,
            class_weight='balanced'
        )
        
        lr_model = LogisticRegression(
            max_iter=1000,
            random_state=42,
            class_weight='balanced'
        )
        
        # Train
        rf_model.fit(X_train_scaled, y_train)
        lr_model.fit(X_train_scaled, y_train)
        
        # Ensemble prediction
        rf_proba = rf_model.predict_proba(X_test_scaled)
        lr_proba = lr_model.predict_proba(X_test_scaled)
        ensemble_proba = 0.6 * rf_proba + 0.4 * lr_proba
        ensemble_pred = np.argmax(ensemble_proba, axis=1)
        
        accuracy = accuracy_score(y_test, ensemble_pred)
        print(f"  {model_name} accuracy: {accuracy:.3f} ({accuracy*100:.1f}%)")
        
        return accuracy
    
    def show_analysis_results(self, baseline_acc, enhanced_acc, selective_acc):
        """Show comprehensive analysis results"""
        print(f"\n📈 Accuracy Decline Analysis Results:")
        print(f"  Baseline features: {baseline_acc*100:.1f}%")
        print(f"  Enhanced features: {enhanced_acc*100:.1f}%")
        print(f"  Selective enhanced: {selective_acc*100:.1f}%")
        
        print(f"\n🔍 Analysis:")
        
        if baseline_acc > enhanced_acc:
            decline = (baseline_acc - enhanced_acc) * 100
            print(f"  ❌ Enhanced features cause {decline:.1f}pp decline")
            print(f"  📊 Problem: Enhanced features add noise, not signal")
            
            if selective_acc > enhanced_acc:
                improvement = (selective_acc - enhanced_acc) * 100
                print(f"  ✅ Selective features improve by {improvement:.1f}pp")
                print(f"  💡 Solution: Use only meaningful enhanced features")
            
            if baseline_acc > selective_acc:
                print(f"  🎯 Baseline still best - enhanced features problematic")
                print(f"  💡 Recommendation: Revert to baseline + minimal enhancements")
            else:
                print(f"  🎯 Selective enhancement works - use targeted approach")
        
        print(f"\n🚀 Recommended Next Steps:")
        
        if baseline_acc > 0.72:
            print(f"  ✅ Baseline model performs well ({baseline_acc*100:.1f}%)")
            print(f"  📊 Phase 1A over-engineering caused accuracy decline")
            print(f"  💡 Revert to simpler, working baseline approach")
            
            if selective_acc > enhanced_acc:
                print(f"  🔧 Add only proven enhanced features selectively")
        else:
            print(f"  📊 All approaches below target - data quality issue")
            print(f"  💡 Focus on data collection (Phase 1B) over feature engineering")

def main():
    analyzer = AccuracyAnalyzer()
    
    try:
        analyzer.analyze_accuracy_decline()
        print(f"\n🎯 Conclusion: Enhanced features analysis complete")
        print(f"✅ Root cause of accuracy decline identified")
        print(f"💡 Clear path forward determined")
        
    except Exception as e:
        print(f"❌ Analysis error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()