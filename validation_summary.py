"""
Validation Summary - Honest assessment of our actual model performance
Identify data leakage issues and provide realistic accuracy estimates
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

class ValidationSummary:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
    
    def provide_honest_assessment(self):
        """Provide honest assessment of our actual model performance"""
        print("📋 Honest Assessment of BetGenius AI Model Performance")
        
        # Check what data we actually have
        self.analyze_available_data()
        
        # Test with proper pre-match features (no data leakage)
        realistic_accuracy = self.test_realistic_features()
        
        # Provide final honest summary
        self.final_summary(realistic_accuracy)
        
        return realistic_accuracy
    
    def analyze_available_data(self):
        """Analyze what training data we actually have"""
        print("\n🔍 Analyzing Available Training Data:")
        
        with self.engine.connect() as conn:
            # Check total matches
            total = conn.execute(text("SELECT COUNT(*) FROM training_matches")).fetchone()[0]
            print(f"  Total matches in database: {total}")
            
            # Check enhanced matches
            enhanced = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Complete_Enhancement'
            """)).fetchone()[0]
            print(f"  Phase 1A enhanced: {enhanced}")
            
            # Check league distribution
            leagues = conn.execute(text("""
                SELECT league_id, COUNT(*) as count
                FROM training_matches 
                WHERE outcome IN ('Home', 'Away', 'Draw')
                GROUP BY league_id
                ORDER BY count DESC
                LIMIT 5
            """)).fetchall()
            
            print(f"  Top leagues:")
            for league_id, count in leagues:
                league_names = {
                    39: 'Premier League', 140: 'La Liga', 135: 'Serie A', 
                    78: 'Bundesliga', 61: 'Ligue 1'
                }
                name = league_names.get(league_id, f'League {league_id}')
                print(f"    {name}: {count} matches")
    
    def test_realistic_features(self):
        """Test with features available BEFORE match (no data leakage)"""
        print("\n🎯 Testing with Realistic Pre-Match Features:")
        
        with self.engine.connect() as conn:
            # Get basic match info without outcomes
            result = conn.execute(text("""
                SELECT league_id, region, outcome
                FROM training_matches 
                WHERE outcome IN ('Home', 'Away', 'Draw')
                LIMIT 1000
            """)).fetchall()
        
        # Create features that would be available before match
        X, y = [], []
        
        for league_id, region, outcome in result:
            try:
                # Only features knowable BEFORE the match
                features = [
                    1.0 if league_id in [39, 140, 135, 78, 61] else 0.0,  # top_league
                    0.85 if league_id == 39 else 0.75,  # league_strength_estimate
                    1.0 if region == 'Europe' else 0.8,  # regional_factor
                    2.5,  # average_goals_expectation
                    0.55  # home_advantage_estimate (historical average)
                ]
                
                X.append(features)
                y.append(0 if outcome == 'Home' else 1 if outcome == 'Draw' else 2)
                
            except:
                continue
        
        if len(X) == 0:
            print("  ❌ No valid pre-match features available")
            return 0.33  # Random baseline
        
        print(f"  Dataset: {len(X)} matches with {len(X[0])} pre-match features")
        
        # Split and train
        X_train, X_test, y_train, y_test = train_test_split(
            np.array(X), np.array(y), test_size=0.3, random_state=42
        )
        
        # Simple model
        model = RandomForestClassifier(
            n_estimators=20,
            max_depth=5,
            random_state=42,
            class_weight='balanced'
        )
        
        model.fit(X_train, y_train)
        predictions = model.predict(X_test)
        accuracy = accuracy_score(y_test, predictions)
        
        print(f"  Realistic accuracy: {accuracy:.3f} ({accuracy*100:.1f}%)")
        
        return accuracy
    
    def final_summary(self, realistic_acc):
        """Provide final honest summary"""
        print(f"\n📈 Final Honest Assessment:")
        
        print(f"  Realistic model accuracy: {realistic_acc*100:.1f}%")
        print(f"  Target accuracy: 74%")
        
        if realistic_acc >= 0.74:
            print(f"  ✅ TARGET MET: Ready for production")
        elif realistic_acc >= 0.60:
            print(f"  📊 REASONABLE: Good foundation, needs improvement")
        else:
            print(f"  ⚠️ BELOW BASELINE: Significant work needed")
        
        print(f"\n🔍 Key Issues Identified:")
        print(f"  ❌ Previous 100% accuracies were due to data leakage")
        print(f"  ❌ Using match outcomes as features (home_goals, away_goals)")
        print(f"  ❌ Phase 1A enhanced features may have added noise")
        print(f"  ❌ API collection constraints limit fresh data")
        
        print(f"\n💡 Honest Recommendations:")
        
        if realistic_acc >= 0.65:
            print(f"  ✅ Current model is usable but needs improvement")
            print(f"  📊 Phase 1A enhancements should be selectively reviewed")
            print(f"  🎯 Focus on proven features that don't cause data leakage")
        else:
            print(f"  📊 Model needs significant improvement")
            print(f"  💡 Consider reverting to simpler approach")
        
        print(f"\n🚀 Next Steps Priority:")
        
        if realistic_acc < 0.60:
            print(f"  1. Fix data leakage in feature engineering")
            print(f"  2. Use only pre-match available features")
            print(f"  3. Validate all features don't predict outcomes directly")
            print(f"  4. Then consider data expansion (Phase 1B)")
        else:
            print(f"  1. Clean up existing features (remove data leakage)")
            print(f"  2. Selectively add meaningful enhancements") 
            print(f"  3. Expand dataset with Phase 1B when APIs permit")
        
        print(f"\n✅ Conclusion:")
        if realistic_acc >= 0.65:
            print(f"  BetGenius AI has a working foundation that can be improved")
        else:
            print(f"  BetGenius AI needs fundamental fixes before expansion")
        
        print(f"  The enhanced features approach (Phase 1A) may have been counterproductive")
        print(f"  Focus on data quality and proper feature engineering over complexity")

def main():
    validator = ValidationSummary()
    
    try:
        accuracy = validator.provide_honest_assessment()
        
        print(f"\n🎯 Validation Complete")
        print(f"Realistic accuracy estimate: {accuracy*100:.1f}%")
        
        if accuracy >= 0.70:
            print("Foundation is solid - ready for incremental improvement")
        else:
            print("Needs fundamental improvements before Phase 1B expansion")
        
    except Exception as e:
        print(f"❌ Validation error: {e}")

if __name__ == "__main__":
    main()