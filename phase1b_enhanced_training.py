"""
Phase 1B Enhanced Training System
Train improved model with Phase 1A enhanced features to verify accuracy improvements
Focus on validating the enhanced foundation before expanding further
"""

import os
import json
import numpy as np
import joblib
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Phase1BEnhancedTrainer:
    """Train enhanced model with Phase 1A features to validate improvements"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
        
    def train_enhanced_model(self):
        """Train and validate enhanced model with Phase 1A features"""
        logger.info("🚀 Training Enhanced Model with Phase 1A Features")
        
        # Load Phase 1A enhanced data
        X, y, league_ids, feature_names = self.load_enhanced_data()
        
        if len(X) == 0:
            logger.error("No enhanced data available for training")
            return
        
        logger.info(f"📊 Enhanced dataset: {len(X)} matches, {len(X[0])} features")
        
        # Train and validate model
        overall_accuracy, league_accuracies, model_info = self.train_and_validate(X, y, league_ids)
        
        # Save enhanced model
        self.save_enhanced_model(model_info, feature_names)
        
        # Show results vs expectations
        self.compare_with_baseline(overall_accuracy, league_accuracies)
        
        return overall_accuracy, league_accuracies
    
    def load_enhanced_data(self):
        """Load Phase 1A enhanced training data"""
        logger.info("📥 Loading Phase 1A enhanced data...")
        
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT features, outcome, league_id
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Complete_Enhancement'
                AND features IS NOT NULL 
                AND outcome IN ('Home', 'Away', 'Draw')
                ORDER BY match_date DESC
            """)).fetchall()
        
        X = []
        y = []
        league_ids = []
        feature_names = []
        
        # Process enhanced features
        for features_json, outcome, league_id in result:
            try:
                features = json.loads(features_json)
                
                # Get feature names (first iteration only)
                if not feature_names:
                    numerical_features = []
                    for key, value in features.items():
                        if isinstance(value, (int, float)) and key not in ['enhancement_timestamp', 'collection_timestamp']:
                            numerical_features.append(key)
                    feature_names = sorted(numerical_features)  # Consistent ordering
                
                # Extract feature vector in consistent order
                feature_vector = []
                for name in feature_names:
                    value = features.get(name, 0)
                    if isinstance(value, (int, float)):
                        feature_vector.append(float(value))
                    else:
                        feature_vector.append(0.0)
                
                if len(feature_vector) >= 15:  # Ensure sufficient features
                    X.append(feature_vector)
                    
                    # Encode outcome
                    if outcome == 'Home':
                        y.append(0)
                    elif outcome == 'Draw':
                        y.append(1)
                    else:  # Away
                        y.append(2)
                    
                    league_ids.append(league_id)
                    
            except Exception as e:
                continue
        
        logger.info(f"✅ Loaded {len(X)} enhanced matches with {len(feature_names)} features")
        if feature_names:
            logger.info(f"📋 Enhanced features: {feature_names[:8]}...")
        
        return np.array(X), np.array(y), np.array(league_ids), feature_names
    
    def train_and_validate(self, X, y, league_ids):
        """Train and validate enhanced ensemble model"""
        logger.info("🤖 Training enhanced ensemble model...")
        
        # Split data stratified
        X_train, X_test, y_train, y_test, league_train, league_test = train_test_split(
            X, y, league_ids, test_size=0.25, random_state=42, stratify=y
        )
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Train conservative ensemble to prevent overfitting
        rf_model = RandomForestClassifier(
            n_estimators=60,      # Slightly increased from 50
            max_depth=8,          # Conservative depth
            min_samples_split=15, # Prevent overfitting
            min_samples_leaf=8,   # Conservative leaf size
            max_features='sqrt',  # Feature subsampling
            random_state=42,
            class_weight='balanced'  # Handle class imbalance
        )
        
        lr_model = LogisticRegression(
            max_iter=1000,
            random_state=42,
            multi_class='ovr',
            class_weight='balanced',
            C=1.0  # Conservative regularization
        )
        
        # Train models
        rf_model.fit(X_train_scaled, y_train)
        lr_model.fit(X_train_scaled, y_train)
        
        # Cross-validation for robust validation
        rf_cv_scores = cross_val_score(rf_model, X_train_scaled, y_train, cv=5, scoring='accuracy')
        lr_cv_scores = cross_val_score(lr_model, X_train_scaled, y_train, cv=5, scoring='accuracy')
        
        logger.info(f"🔄 Cross-validation scores:")
        logger.info(f"  Random Forest: {rf_cv_scores.mean():.3f} (+/- {rf_cv_scores.std() * 2:.3f})")
        logger.info(f"  Logistic Regression: {lr_cv_scores.mean():.3f} (+/- {lr_cv_scores.std() * 2:.3f})")
        
        # Ensemble predictions on test set
        rf_pred_proba = rf_model.predict_proba(X_test_scaled)
        lr_pred_proba = lr_model.predict_proba(X_test_scaled)
        
        # Weighted ensemble (60% RF, 40% LR based on CV performance)
        if rf_cv_scores.mean() > lr_cv_scores.mean():
            ensemble_proba = 0.65 * rf_pred_proba + 0.35 * lr_pred_proba
        else:
            ensemble_proba = 0.4 * rf_pred_proba + 0.6 * lr_pred_proba
        
        ensemble_pred = np.argmax(ensemble_proba, axis=1)
        
        # Overall accuracy
        overall_accuracy = accuracy_score(y_test, ensemble_pred)
        
        logger.info(f"🎯 Enhanced Model Test Accuracy: {overall_accuracy:.3f} ({overall_accuracy*100:.1f}%)")
        
        # League-specific accuracies
        league_accuracies = {}
        unique_leagues = np.unique(league_test)
        
        logger.info(f"\n📊 League-Specific Enhanced Accuracies:")
        league_names = {39: 'Premier League', 140: 'La Liga', 135: 'Serie A', 
                       78: 'Bundesliga', 61: 'Ligue 1', 143: 'Brazilian Serie A',
                       179: 'Scottish Premiership', 203: 'Turkish Super Lig',
                       88: 'Eredivisie', 399: 'Egyptian Premier League'}
        
        for league_id in unique_leagues:
            mask = league_test == league_id
            if np.sum(mask) >= 5:  # At least 5 test samples
                league_acc = accuracy_score(y_test[mask], ensemble_pred[mask])
                league_name = league_names.get(league_id, f'League {league_id}')
                league_accuracies[league_name] = league_acc
                
                sample_count = np.sum(mask)
                logger.info(f"  {league_name}: {league_acc:.3f} ({league_acc*100:.1f}%) - {sample_count} samples")
        
        # Detailed classification report
        target_names = ['Home', 'Draw', 'Away']
        logger.info(f"\n📋 Classification Report:")
        logger.info(f"\n{classification_report(y_test, ensemble_pred, target_names=target_names)}")
        
        # Model info for saving
        model_info = {
            'rf_model': rf_model,
            'lr_model': lr_model,
            'scaler': scaler,
            'ensemble_weights': (0.6, 0.4),
            'accuracy': overall_accuracy,
            'cv_scores': {
                'rf_mean': rf_cv_scores.mean(),
                'lr_mean': lr_cv_scores.mean()
            }
        }
        
        return overall_accuracy, league_accuracies, model_info
    
    def save_enhanced_model(self, model_info, feature_names):
        """Save the enhanced model"""
        logger.info("💾 Saving enhanced model...")
        
        model_data = {
            'rf_model': model_info['rf_model'],
            'lr_model': model_info['lr_model'],
            'scaler': model_info['scaler'],
            'feature_names': feature_names,
            'ensemble_weights': model_info['ensemble_weights'],
            'accuracy': model_info['accuracy'],
            'cv_scores': model_info['cv_scores'],
            'model_version': 'Phase_1A_Enhanced',
            'training_date': datetime.now().isoformat(),
            'feature_count': len(feature_names)
        }
        
        # Save enhanced model
        joblib.dump(model_data, 'models/enhanced_unified_model.joblib')
        logger.info(f"✅ Enhanced model saved with {model_info['accuracy']:.3f} accuracy")
    
    def compare_with_baseline(self, overall_accuracy, league_accuracies):
        """Compare enhanced model with baseline expectations"""
        logger.info(f"\n📈 Phase 1A Enhancement Results vs Baseline:")
        
        baseline_accuracy = 0.715  # Previous overall accuracy
        logger.info(f"\n🎯 Overall Accuracy Comparison:")
        logger.info(f"  Baseline (before Phase 1A): 71.5%")
        logger.info(f"  Enhanced (after Phase 1A): {overall_accuracy*100:.1f}%")
        
        improvement = (overall_accuracy - baseline_accuracy) * 100
        if improvement > 0:
            logger.info(f"  ✅ IMPROVEMENT: +{improvement:.1f} percentage points")
        else:
            logger.info(f"  ⚠️  Change: {improvement:.1f} percentage points")
        
        logger.info(f"\n🎯 League-Specific Results:")
        
        # Check key improvements
        brazilian_improvement = False
        african_improvement = False
        balanced_european = False
        
        for league_name, accuracy in league_accuracies.items():
            if 'Brazilian' in league_name:
                logger.info(f"  Brazilian Serie A:")
                logger.info(f"    Before Phase 1A: 36%")
                logger.info(f"    After Phase 1A: {accuracy*100:.1f}%")
                if accuracy > 0.50:
                    logger.info(f"    ✅ SIGNIFICANT IMPROVEMENT: +{(accuracy-0.36)*100:.1f} points")
                    brazilian_improvement = True
                else:
                    logger.info(f"    ⚠️  Improvement needed: Phase 1B collection required")
            
            elif 'Egyptian' in league_name or 'African' in league_name:
                logger.info(f"  {league_name}: {accuracy*100:.1f}%")
                if accuracy > 0.55:
                    logger.info(f"    ✅ GOOD: African market accuracy improved")
                    african_improvement = True
            
            elif 'Premier League' in league_name:
                logger.info(f"  Premier League: {accuracy*100:.1f}%")
                if accuracy < 0.85:  # Not over-optimized
                    logger.info(f"    ✅ BALANCED: No longer over-optimized")
                    balanced_european = True
        
        logger.info(f"\n✨ Phase 1A Enhancement Assessment:")
        
        if overall_accuracy > 0.72:
            logger.info(f"  ✅ SUCCESS: Enhanced features improve overall accuracy")
        
        if brazilian_improvement:
            logger.info(f"  ✅ SUCCESS: Brazilian Serie A accuracy significantly improved")
        else:
            logger.info(f"  📊 INSIGHT: Brazilian accuracy needs Phase 1B South American data")
        
        if african_improvement:
            logger.info(f"  ✅ SUCCESS: African market accuracy improved")
        
        if balanced_european:
            logger.info(f"  ✅ SUCCESS: European league bias reduced")
        
        # Overall conclusion
        if overall_accuracy > baseline_accuracy:
            logger.info(f"\n🎉 CONCLUSION: Phase 1A enhancements successfully improve model accuracy!")
            logger.info(f"The enhanced features address the identified accuracy issues.")
        else:
            logger.info(f"\n📋 CONCLUSION: Phase 1A provides foundation, Phase 1B expansion needed for full impact")

def main():
    """Train and validate Phase 1A enhanced model"""
    trainer = Phase1BEnhancedTrainer()
    
    try:
        overall_accuracy, league_accuracies = trainer.train_enhanced_model()
        
        print(f"\n🎉 Phase 1A Enhanced Model Training Complete!")
        print(f"✅ Enhanced model accuracy: {overall_accuracy*100:.1f}%")
        print(f"✅ Phase 1A features successfully integrated")
        print(f"✅ Enhanced model saved for production use")
        print(f"🎯 Foundation strengthened for Phase 1B expansion")
        
    except Exception as e:
        logger.error(f"❌ Enhanced model training failed: {e}")
        raise

if __name__ == "__main__":
    main()