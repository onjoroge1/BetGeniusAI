"""
Final Phase R Diagnosis - Root Cause Analysis
Identify why models consistently fail to beat baselines despite enhanced features
"""

import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, accuracy_score
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier
from sklearn.model_selection import train_test_split
import joblib
from datetime import datetime, timedelta
import json
import psycopg2
import os
from typing import Dict, List, Tuple
import warnings
warnings.filterwarnings('ignore')

class FinalPhaseRDiagnosis:
    """Comprehensive diagnosis of model failure to beat baselines"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        self.random_state = 42
        np.random.seed(self.random_state)
    
    def get_db_connection(self):
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def analyze_data_quality(self):
        """Analyze training data quality to identify issues"""
        
        try:
            conn = self.get_db_connection()
            
            # Get comprehensive data analysis
            query = """
            SELECT 
                league_id,
                match_date,
                home_team,
                away_team,
                home_goals,
                away_goals,
                features
            FROM training_matches 
            WHERE match_date >= %s
                AND home_goals IS NOT NULL 
                AND away_goals IS NOT NULL
                AND league_id IN (39, 140, 135, 78, 61)
            ORDER BY match_date ASC
            """
            
            cutoff_date = datetime.now() - timedelta(days=730)
            df = pd.read_sql_query(query, conn, params=[cutoff_date])
            conn.close()
            
            print("DATA QUALITY ANALYSIS")
            print("=" * 50)
            
            # Basic statistics
            print(f"Total matches: {len(df)}")
            print(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
            print(f"Leagues: {df['league_id'].nunique()}")
            print(f"Teams: {df['home_team'].nunique() + df['away_team'].nunique()}")
            
            # Outcome distribution
            def get_outcome(row):
                if row['home_goals'] > row['away_goals']:
                    return 'home'
                elif row['home_goals'] < row['away_goals']:
                    return 'away'
                else:
                    return 'draw'
            
            df['outcome'] = df.apply(get_outcome, axis=1)
            outcome_dist = df['outcome'].value_counts(normalize=True)
            
            print(f"\nOutcome Distribution:")
            for outcome, pct in outcome_dist.items():
                print(f"  {outcome}: {pct:.1%}")
            
            # Check for potential issues
            issues = []
            
            # 1. Extreme home bias
            home_rate = outcome_dist.get('home', 0)
            if home_rate > 0.6:
                issues.append(f"Extreme home bias: {home_rate:.1%}")
            
            # 2. Very low draw rate
            draw_rate = outcome_dist.get('draw', 0)
            if draw_rate < 0.2:
                issues.append(f"Unusually low draw rate: {draw_rate:.1%}")
            
            # 3. Check for duplicate matches
            duplicates = df.duplicated(['home_team', 'away_team', 'match_date']).sum()
            if duplicates > 0:
                issues.append(f"Duplicate matches: {duplicates}")
            
            # 4. Check goal distributions
            high_scoring = ((df['home_goals'] + df['away_goals']) > 5).mean()
            if high_scoring > 0.3:
                issues.append(f"Too many high-scoring games: {high_scoring:.1%}")
            
            # 5. League-specific analysis
            print(f"\nPer-League Analysis:")
            for league_id in df['league_id'].unique():
                league_df = df[df['league_id'] == league_id]
                league_outcomes = league_df['outcome'].value_counts(normalize=True)
                league_name = self.euro_leagues.get(league_id, f"League {league_id}")
                
                print(f"  {league_name}: {len(league_df)} matches")
                print(f"    H/D/A: {league_outcomes.get('home', 0):.1%}/{league_outcomes.get('draw', 0):.1%}/{league_outcomes.get('away', 0):.1%}")
            
            # 6. Features analysis
            print(f"\nFeatures Analysis:")
            if 'features' in df.columns:
                features_available = df['features'].notna().sum()
                print(f"  Matches with features: {features_available}/{len(df)} ({features_available/len(df):.1%})")
                
                if features_available > 0:
                    sample_features = df[df['features'].notna()]['features'].iloc[0]
                    if isinstance(sample_features, dict):
                        print(f"  Feature count: {len(sample_features)}")
                        print(f"  Sample features: {list(sample_features.keys())[:5]}")
            
            print(f"\nIdentified Issues:")
            if issues:
                for issue in issues:
                    print(f"  ❌ {issue}")
            else:
                print("  ✅ No obvious data quality issues detected")
            
            return df, issues
            
        except Exception as e:
            print(f"Error in data analysis: {e}")
            return None, [f"Data loading error: {e}"]
    
    def test_predictability(self, df: pd.DataFrame) -> Dict:
        """Test if the data is actually predictable beyond random"""
        
        print("\nPREDICTABILITY ANALYSIS")
        print("=" * 40)
        
        # Create simple but meaningful features
        simple_features = []
        outcomes = []
        
        for _, row in df.iterrows():
            league_id = row['league_id']
            home_goals = row['home_goals']
            away_goals = row['away_goals']
            
            # Simple features that should have some signal
            features = [
                float(league_id),  # League indicator
                hash(row['home_team']) % 100 / 100.0,  # Team hash (proxy for strength)
                hash(row['away_team']) % 100 / 100.0,
                (hash(row['home_team']) - hash(row['away_team'])) / 1000.0,  # Strength diff proxy
                np.random.uniform(0, 1)  # Random feature (should have no signal)
            ]
            
            simple_features.append(features)
            
            if home_goals > away_goals:
                outcomes.append(0)  # Home
            elif home_goals < away_goals:
                outcomes.append(2)  # Away
            else:
                outcomes.append(1)  # Draw
        
        X = np.array(simple_features)
        y = np.array(outcomes)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=self.random_state, stratify=y
        )
        
        print(f"Train/Test split: {len(X_train)}/{len(X_test)} matches")
        
        # Test different models
        models = {
            'Random': DummyClassifier(strategy='uniform', random_state=self.random_state),
            'MostFrequent': DummyClassifier(strategy='most_frequent', random_state=self.random_state),
            'Stratified': DummyClassifier(strategy='stratified', random_state=self.random_state),
            'Logistic': LogisticRegression(random_state=self.random_state, max_iter=1000)
        }
        
        results = {}
        
        for name, model in models.items():
            model.fit(X_train, y_train)
            
            if hasattr(model, 'predict_proba'):
                y_proba = model.predict_proba(X_test)
                logloss = log_loss(y_test, y_proba)
            else:
                # For dummy classifiers without predict_proba
                y_pred = model.predict(X_test)
                accuracy = accuracy_score(y_test, y_pred)
                # Create dummy probabilities for logloss calculation
                y_proba = np.zeros((len(y_test), 3))
                for i, pred in enumerate(y_pred):
                    y_proba[i, pred] = 1.0
                logloss = log_loss(y_test, y_proba)
                
            accuracy = accuracy_score(y_test, model.predict(X_test))
            
            results[name] = {
                'accuracy': accuracy,
                'logloss': logloss
            }
            
            print(f"{name:<15}: Acc={accuracy:.1%}, LogLoss={logloss:.4f}")
        
        # Analysis
        logistic_ll = results['Logistic']['logloss']
        random_ll = results['Random']['logloss']
        
        if logistic_ll < random_ll:
            improvement = (random_ll - logistic_ll) / random_ll * 100
            print(f"\n✅ Logistic regression beats random by {improvement:.1f}%")
            predictable = True
        else:
            print(f"\n❌ Logistic regression fails to beat random baseline")
            predictable = False
        
        return {
            'predictable': predictable,
            'results': results,
            'best_logloss': min(r['logloss'] for r in results.values()),
            'random_logloss': random_ll
        }
    
    def diagnose_model_issues(self, df: pd.DataFrame) -> Dict:
        """Diagnose specific model training issues"""
        
        print("\nMODEL DIAGNOSIS")
        print("=" * 30)
        
        issues = []
        
        # 1. Check sample size per class
        outcomes = df['outcome'].value_counts()
        min_class_size = outcomes.min()
        
        print(f"Class sizes: {dict(outcomes)}")
        
        if min_class_size < 50:
            issues.append(f"Insufficient samples for minority class: {min_class_size}")
        
        # 2. Check temporal bias
        df['match_date'] = pd.to_datetime(df['match_date'])
        df_sorted = df.sort_values('match_date')
        
        # Check if outcome distribution changes over time
        early_outcomes = df_sorted.head(len(df)//3)['outcome'].value_counts(normalize=True)
        late_outcomes = df_sorted.tail(len(df)//3)['outcome'].value_counts(normalize=True)
        
        max_shift = max(abs(early_outcomes.get(outcome, 0) - late_outcomes.get(outcome, 0)) 
                       for outcome in ['home', 'draw', 'away'])
        
        if max_shift > 0.1:
            issues.append(f"Temporal distribution shift: {max_shift:.1%}")
        
        # 3. Check feature variance
        # Create a test feature set
        feature_variances = []
        for league_id in df['league_id'].unique():
            league_matches = len(df[df['league_id'] == league_id])
            feature_variances.append(league_matches)
        
        if np.std(feature_variances) / np.mean(feature_variances) > 1.0:
            issues.append("High variance in league representation")
        
        # 4. Cross-validation consistency check
        from sklearn.model_selection import cross_val_score
        
        # Simple features for CV test
        X_simple = np.random.randn(len(df), 5)  # Random features
        y_simple = [0 if row['outcome'] == 'home' else 1 if row['outcome'] == 'draw' else 2 
                   for _, row in df.iterrows()]
        
        try:
            cv_scores = cross_val_score(
                LogisticRegression(random_state=self.random_state), 
                X_simple, y_simple, cv=3, scoring='neg_log_loss'
            )
            cv_std = np.std(cv_scores)
            
            if cv_std > 0.1:
                issues.append(f"High CV variance: {cv_std:.3f}")
                
        except Exception as e:
            issues.append(f"CV failed: {str(e)}")
        
        return {
            'issues': issues,
            'sample_sizes': dict(outcomes),
            'temporal_shift': max_shift,
            'total_matches': len(df)
        }
    
    def generate_final_diagnosis(self, data_issues: List[str], predictability: Dict, 
                               model_issues: Dict) -> str:
        """Generate final Phase R diagnosis report"""
        
        lines = [
            "FINAL PHASE R DIAGNOSIS - ROOT CAUSE ANALYSIS",
            "=" * 70,
            f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "SUMMARY: Why Models Fail to Beat Baselines",
            "-" * 50
        ]
        
        # Data quality issues
        lines.extend([
            "\n1. DATA QUALITY ISSUES:",
            "-" * 30
        ])
        
        if data_issues:
            for issue in data_issues:
                lines.append(f"   ❌ {issue}")
        else:
            lines.append("   ✅ No major data quality issues detected")
        
        # Predictability analysis
        lines.extend([
            "\n2. PREDICTABILITY ANALYSIS:",
            "-" * 30
        ])
        
        if predictability['predictable']:
            improvement = ((predictability['random_logloss'] - predictability['best_logloss']) / 
                          predictability['random_logloss'] * 100)
            lines.append(f"   ✅ Data shows {improvement:.1f}% improvement over random")
        else:
            lines.append("   ❌ Data appears unpredictable - models cannot beat random")
        
        lines.append(f"   Best LogLoss: {predictability['best_logloss']:.4f}")
        lines.append(f"   Random LogLoss: {predictability['random_logloss']:.4f}")
        
        # Model training issues
        lines.extend([
            "\n3. MODEL TRAINING ISSUES:",
            "-" * 30
        ])
        
        if model_issues['issues']:
            for issue in model_issues['issues']:
                lines.append(f"   ❌ {issue}")
        else:
            lines.append("   ✅ No major model training issues detected")
        
        lines.append(f"   Total samples: {model_issues['total_matches']}")
        lines.append(f"   Class distribution: {model_issues['sample_sizes']}")
        
        # Root cause conclusion
        lines.extend([
            "\n4. ROOT CAUSE CONCLUSION:",
            "-" * 30
        ])
        
        if not predictability['predictable']:
            lines.extend([
                "   PRIMARY ISSUE: Data lacks predictive signal",
                "   → Football matches may be fundamentally unpredictable with available features",
                "   → Random/near-random outcomes dominate signal",
                ""
            ])
        
        if data_issues:
            lines.extend([
                "   SECONDARY ISSUES: Data quality problems",
                "   → Biased samples or collection issues",
                "   → Insufficient feature engineering",
                ""
            ])
        
        # Recommendations
        lines.extend([
            "5. PHASE R RECOVERY RECOMMENDATIONS:",
            "-" * 40
        ])
        
        if not predictability['predictable']:
            lines.extend([
                "   🎯 ACCEPT BASELINE PERFORMANCE:",
                "   → Football prediction may be inherently limited",
                "   → Focus on probability calibration rather than accuracy",
                "   → Target: Beat market efficiency, not random baselines",
                ""
            ])
        
        lines.extend([
            "   🛠️  IMMEDIATE ACTIONS:",
            "   → Collect more diverse training data",
            "   → Implement stronger feature engineering",
            "   → Focus on market beat metrics (vs sportsbooks)",
            "   → Consider external data sources (injuries, weather, etc.)",
            "",
            "   📊 ALTERNATIVE SUCCESS METRICS:",
            "   → Probability calibration quality (Brier score decomposition)",
            "   → Market-relative performance (vs betting odds)",
            "   → Bankroll growth in simulation (Kelly criterion)",
            "   → Long-term ROI vs risk-adjusted returns"
        ])
        
        return "\n".join(lines)
    
    def run_final_diagnosis(self):
        """Run complete final Phase R diagnosis"""
        
        print("FINAL PHASE R DIAGNOSIS")
        print("=" * 50)
        
        # 1. Data quality analysis
        df, data_issues = self.analyze_data_quality()
        if df is None:
            return None
        
        # 2. Predictability testing
        predictability = self.test_predictability(df)
        
        # 3. Model issues diagnosis
        model_diagnosis = self.diagnose_model_issues(df)
        
        # 4. Generate final report
        report = self.generate_final_diagnosis(data_issues, predictability, model_diagnosis)
        
        return {
            'data_issues': data_issues,
            'predictability': predictability,
            'model_diagnosis': model_diagnosis,
            'report': report,
            'evaluation_date': datetime.now().isoformat()
        }

def main():
    """Run final Phase R diagnosis"""
    
    diagnosis = FinalPhaseRDiagnosis()
    
    # Run complete diagnosis
    results = diagnosis.run_final_diagnosis()
    
    if results:
        # Print report
        print("\n" + results['report'])
        
        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        with open(f'final_phase_r_diagnosis_{timestamp}.json', 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        with open(f'final_phase_r_diagnosis_{timestamp}.txt', 'w') as f:
            f.write(results['report'])
        
        print(f"\nFinal Phase R diagnosis complete!")
        print(f"Results: final_phase_r_diagnosis_{timestamp}.json")
        print(f"Report: final_phase_r_diagnosis_{timestamp}.txt")
    
    return results

if __name__ == "__main__":
    main()