"""
Quick ML Test - Test current multi-context accuracy with 1180 matches
"""
import json
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_current_ml_performance():
    """Test ML performance with current diverse dataset"""
    engine = create_engine(os.environ.get('DATABASE_URL'))
    
    # Load all available data
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT features, outcome, league_id
            FROM training_matches 
            WHERE features IS NOT NULL AND outcome IS NOT NULL
        """))
        
        training_data = []
        for row in result:
            try:
                features_raw = row[0]
                if isinstance(features_raw, str):
                    features = json.loads(features_raw)
                else:
                    features = features_raw
                    
                training_data.append({
                    'features': features,
                    'outcome': row[1],
                    'league_id': row[2]
                })
            except:
                continue
    
    logger.info(f"Testing with {len(training_data)} diverse matches")
    
    # Categorize into contexts
    home_dominant = []
    competitive = []
    away_strong = []
    
    for sample in training_data:
        features = sample['features']
        
        # Calculate strength indicators
        home_strength = (
            features.get('home_goals_per_game', 1.5) * 0.3 +
            features.get('home_win_percentage', 0.45) * 0.4 +
            features.get('home_form_points', 8) / 15.0 * 0.2 +
            max(0, features.get('strength_difference', 0.15)) * 0.1
        )
        
        away_strength = (
            features.get('away_goals_per_game', 1.3) * 0.3 +
            features.get('away_win_percentage', 0.30) * 0.4 +
            features.get('away_form_points', 6) / 15.0 * 0.2 +
            max(0, -features.get('strength_difference', 0.15)) * 0.1
        )
        
        strength_gap = home_strength - away_strength
        
        if strength_gap > 0.25:
            home_dominant.append(sample)
        elif strength_gap < -0.15:
            away_strong.append(sample)
        else:
            competitive.append(sample)
    
    # Test each context
    context_results = {}
    
    for context_name, context_data in [
        ('home_dominant', home_dominant),
        ('competitive', competitive), 
        ('away_strong', away_strong)
    ]:
        if len(context_data) < 30:
            continue
            
        accuracy = test_context_model(context_data, context_name)
        context_results[context_name] = accuracy
        logger.info(f"{context_name}: {accuracy:.1%} accuracy with {len(context_data)} samples")
    
    # Overall test
    overall_accuracy = test_overall_model(training_data)
    
    return overall_accuracy, context_results, len(training_data)

def test_context_model(context_data, context_name):
    """Test model for specific context"""
    # Prepare features
    X, y = prepare_context_features(context_data, context_name)
    
    if len(X) < 30:
        return 0
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )
    
    # Scale
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Train optimized model for context
    if context_name == 'home_dominant':
        model = RandomForestClassifier(
            n_estimators=150, max_depth=12, 
            class_weight={0: 1.4, 1: 1.0, 2: 0.5}, 
            random_state=42, n_jobs=-1
        )
    elif context_name == 'competitive':
        model = RandomForestClassifier(
            n_estimators=200, max_depth=15,
            class_weight='balanced_subsample',
            random_state=42, n_jobs=-1
        )
    else:  # away_strong
        model = RandomForestClassifier(
            n_estimators=120, max_depth=16,
            class_weight={0: 0.5, 1: 1.0, 2: 1.5},
            random_state=42, n_jobs=-1
        )
    
    # Train and test
    model.fit(X_train_scaled, y_train)
    y_pred = model.predict(X_test_scaled)
    
    return accuracy_score(y_test, y_pred)

def prepare_context_features(context_data, context_name):
    """Prepare features for context"""
    features = []
    labels = []
    
    for sample in context_data:
        try:
            sf = sample['features']
            outcome = sample['outcome']
            
            # Extract core features
            hgpg = sf.get('home_goals_per_game', 1.5)
            agpg = sf.get('away_goals_per_game', 1.3)
            hwp = sf.get('home_win_percentage', 0.45)
            awp = sf.get('away_win_percentage', 0.30)
            hfp = sf.get('home_form_points', 8)
            afp = sf.get('away_form_points', 6)
            
            # Context-specific features
            if context_name == 'home_dominant':
                feature_vector = [
                    hgpg, hwp, hfp/15.0, hgpg * hwp,
                    agpg, awp, afp/15.0,
                    hgpg - agpg, hwp - awp, (hfp - afp)/15.0,
                    sf.get('strength_difference', 0.15)
                ]
            elif context_name == 'competitive':
                feature_vector = [
                    hgpg, agpg, hwp, awp, hfp/15.0, afp/15.0,
                    abs(hgpg - agpg), abs(hwp - awp), abs(hfp - afp)/15.0,
                    (hgpg + agpg)/2, (hwp + awp)/2,
                    sf.get('total_goals_tendency', 2.8)/4.0
                ]
            else:  # away_strong
                feature_vector = [
                    agpg, awp, afp/15.0, agpg * awp,
                    hgpg, hwp, hfp/15.0,
                    agpg - hgpg, awp - hwp, (afp - hfp)/15.0,
                    -sf.get('strength_difference', 0.15)
                ]
            
            # Label encoding
            label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
            
            features.append(feature_vector)
            labels.append(label)
            
        except:
            continue
    
    return np.array(features), np.array(labels)

def test_overall_model(training_data):
    """Test overall model performance"""
    # Simple overall test
    X, y = prepare_simple_features(training_data)
    
    if len(X) < 50:
        return 0
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Ensemble model
    model = RandomForestClassifier(
        n_estimators=200, max_depth=15,
        class_weight='balanced',
        random_state=42, n_jobs=-1
    )
    
    model.fit(X_train_scaled, y_train)
    y_pred = model.predict(X_test_scaled)
    
    return accuracy_score(y_test, y_pred)

def prepare_simple_features(training_data):
    """Prepare simple features for overall test"""
    features = []
    labels = []
    
    for sample in training_data:
        try:
            sf = sample['features']
            outcome = sample['outcome']
            
            feature_vector = [
                sf.get('home_goals_per_game', 1.5),
                sf.get('away_goals_per_game', 1.3),
                sf.get('home_win_percentage', 0.45),
                sf.get('away_win_percentage', 0.30),
                sf.get('home_form_points', 8) / 15.0,
                sf.get('away_form_points', 6) / 15.0,
                sf.get('strength_difference', 0.15),
                sf.get('form_difference', 2.0) / 10.0,
                sf.get('total_goals_tendency', 2.8) / 4.0
            ]
            
            label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
            
            features.append(feature_vector)
            labels.append(label)
            
        except:
            continue
    
    return np.array(features), np.array(labels)

def main():
    """Run quick ML test"""
    overall_accuracy, context_results, total_samples = test_current_ml_performance()
    
    print(f"""
QUICK ML TEST RESULTS - DIVERSE LEAGUE DATA
==========================================

Dataset: {total_samples} matches from multiple European leagues

Multi-Context Performance:
{chr(10).join([f'- {context}: {accuracy:.1%}' for context, accuracy in context_results.items()])}

Overall Accuracy: {overall_accuracy:.1%}

Target Achievement:
- 70% Target: {overall_accuracy >= 0.70}
- Home Dominant: {context_results.get('home_dominant', 0) >= 0.70}
- Competitive: {context_results.get('competitive', 0) >= 0.70}
- Away Strong: {context_results.get('away_strong', 0) >= 0.70}

Status: {'EXCELLENT - TARGET ACHIEVED' if overall_accuracy >= 0.70 else 'GOOD PROGRESS - CONTINUING EXPANSION'}
    """)
    
    return overall_accuracy >= 0.70

if __name__ == "__main__":
    success = main()