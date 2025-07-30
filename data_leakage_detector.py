"""
Data Leakage Detector - Find and remove features that leak match outcomes
The 100% accuracy indicates severe data leakage in features
"""

import os
import json
import numpy as np
import pandas as pd
import psycopg2
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

class DataLeakageDetector:
    """Detect features that contain information about match outcomes"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        
    def analyze_feature_leakage(self):
        """Analyze each feature for potential data leakage"""
        
        print("DATA LEAKAGE ANALYSIS")
        print("=" * 50)
        
        # Load data
        query = """
        SELECT 
            home_team, away_team, match_date, outcome, 
            home_goals, away_goals, features
        FROM training_matches 
        WHERE outcome IS NOT NULL AND features IS NOT NULL
        ORDER BY match_date
        LIMIT 100
        """
        
        df = pd.read_sql_query(query, self.conn)
        
        # Extract features
        all_features = []
        feature_names = set()
        
        for _, row in df.iterrows():
            features_dict = row['features']
            if isinstance(features_dict, dict):
                feature_names.update(features_dict.keys())
        
        feature_names = sorted(list(feature_names))
        
        # Create feature matrix
        feature_matrix = []
        for _, row in df.iterrows():
            features_dict = row['features']
            feature_row = []
            
            for feature_name in feature_names:
                if isinstance(features_dict, dict) and feature_name in features_dict:
                    value = features_dict[feature_name]
                    if isinstance(value, (int, float)):
                        feature_row.append(float(value))
                    elif isinstance(value, bool):
                        feature_row.append(float(value))
                    else:
                        feature_row.append(0.0)
                else:
                    feature_row.append(0.0)
            
            # Add goal difference (KNOWN LEAKAGE FEATURE)
            feature_row.append(row['home_goals'] - row['away_goals'])
            feature_row.append(row['home_goals'] + row['away_goals'])
            
            feature_matrix.append(feature_row)
        
        feature_names.extend(['goal_difference', 'total_goals'])
        feature_df = pd.DataFrame(feature_matrix, columns=feature_names)
        
        # Create target
        outcome_mapping = {'Home': 0, 'Draw': 1, 'Away': 2}
        y = df['outcome'].map(outcome_mapping).values
        
        print(f"Analyzing {len(feature_names)} features for leakage...")
        
        # Test each feature individually
        leakage_scores = {}
        
        for feature in feature_names:
            if feature_df[feature].var() > 0.001:  # Skip constant features
                
                X_single = feature_df[[feature]]
                
                # Train/test split
                X_train, X_test, y_train, y_test = train_test_split(
                    X_single, y, test_size=0.3, random_state=42, stratify=y
                )
                
                # Simple model with just this feature
                rf = RandomForestClassifier(n_estimators=50, random_state=42)
                rf.fit(X_train, y_train)
                
                accuracy = rf.score(X_test, y_test)
                leakage_scores[feature] = accuracy
        
        # Sort by leakage potential
        sorted_features = sorted(leakage_scores.items(), key=lambda x: x[1], reverse=True)
        
        print(f"\nFEATURE LEAKAGE ANALYSIS (Single Feature Accuracy):")
        print("-" * 60)
        print(f"{'Feature':<30} | {'Accuracy':<8} | {'Leakage Risk'}")
        print("-" * 60)
        
        for feature, accuracy in sorted_features:
            if accuracy > 0.8:
                risk = "🔴 SEVERE"
            elif accuracy > 0.6:
                risk = "🟡 HIGH"
            elif accuracy > 0.4:
                risk = "🟠 MEDIUM"
            else:
                risk = "🟢 LOW"
            
            print(f"{feature:<30} | {accuracy:.3f}   | {risk}")
        
        # Identify clean features (no leakage)
        clean_features = [f for f, acc in sorted_features if acc < 0.45]
        leaky_features = [f for f, acc in sorted_features if acc >= 0.45]
        
        print(f"\n" + "="*60)
        print("LEAKAGE SUMMARY")
        print("="*60)
        print(f"🔴 LEAKY FEATURES ({len(leaky_features)}): {leaky_features[:10]}{'...' if len(leaky_features) > 10 else ''}")
        print(f"🟢 CLEAN FEATURES ({len(clean_features)}): {clean_features[:10]}{'...' if len(clean_features) > 10 else ''}")
        
        return clean_features, leaky_features, feature_df, y
    
    def test_clean_model(self, clean_features, feature_df, y):
        """Test model performance with only clean features"""
        
        print(f"\nTESTING CLEAN MODEL (No Data Leakage)")
        print("=" * 50)
        
        if len(clean_features) == 0:
            print("❌ No clean features available!")
            return None
        
        # Use only clean features
        X_clean = feature_df[clean_features]
        
        print(f"Using {len(clean_features)} clean features:")
        for feature in clean_features[:10]:
            print(f"  - {feature}")
        if len(clean_features) > 10:
            print(f"  ... and {len(clean_features) - 10} more")
        
        # Time-aware split
        split_idx = int(0.8 * len(X_clean))
        X_train, X_test = X_clean.iloc[:split_idx], X_clean.iloc[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # Train model
        rf = RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            min_samples_split=10,
            random_state=42,
            class_weight='balanced'
        )
        
        rf.fit(X_train, y_train)
        
        # Evaluate
        train_accuracy = rf.score(X_train, y_train)
        test_accuracy = rf.score(X_test, y_test)
        
        # Calculate baselines
        home_rate = np.mean(y_test == 0)
        draw_rate = np.mean(y_test == 1) 
        away_rate = np.mean(y_test == 2)
        
        uniform_baseline = 1/3
        frequency_baseline = max(home_rate, draw_rate, away_rate)
        
        print(f"\nCLEAN MODEL RESULTS:")
        print(f"  Training Accuracy: {train_accuracy:.1%}")
        print(f"  Test Accuracy: {test_accuracy:.1%}")
        print(f"  Uniform Baseline: {uniform_baseline:.1%}")
        print(f"  Frequency Baseline: {frequency_baseline:.1%}")
        
        improvement = (test_accuracy - uniform_baseline) / uniform_baseline * 100
        print(f"  Improvement vs Uniform: {improvement:+.1f}%")
        
        # Feature importance
        importance_df = pd.DataFrame({
            'feature': clean_features,
            'importance': rf.feature_importances_
        }).sort_values('importance', ascending=False)
        
        print(f"\nTop Clean Features by Importance:")
        for _, row in importance_df.head(5).iterrows():
            print(f"  {row['feature']}: {row['importance']:.4f}")
        
        return {
            'test_accuracy': test_accuracy,
            'train_accuracy': train_accuracy,
            'features_used': clean_features,
            'feature_importance': importance_df,
            'improvement': improvement
        }

def main():
    """Run data leakage detection and clean model testing"""
    
    detector = DataLeakageDetector()
    
    try:
        # Analyze leakage
        clean_features, leaky_features, feature_df, y = detector.analyze_feature_leakage()
        
        # Test clean model
        clean_results = detector.test_clean_model(clean_features, feature_df, y)
        
        if clean_results:
            print(f"\n" + "="*60)
            print("AUTHENTIC PREDICTION ACCURACY")
            print("="*60)
            print(f"Clean Model Accuracy: {clean_results['test_accuracy']:.1%}")
            print(f"Features Used: {len(clean_results['features_used'])}")
            
            if clean_results['test_accuracy'] > 0.45:
                print("✅ EXCELLENT: Above 45% threshold!")
            elif clean_results['test_accuracy'] > 0.40:
                print("✅ GOOD: Above 40% threshold")
            elif clean_results['test_accuracy'] > 0.35:
                print("⚠️  ACCEPTABLE: Above random baseline")
            else:
                print("❌ POOR: Need better features")
        
    finally:
        detector.conn.close()

if __name__ == "__main__":
    main()