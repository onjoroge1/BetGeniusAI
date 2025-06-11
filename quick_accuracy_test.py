"""
Quick Accuracy Test - Test current performance with 1300 matches
"""
import json
import numpy as np
from sqlalchemy import create_engine, text
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_current_accuracy():
    """Test accuracy with expanded 1300 match dataset"""
    engine = create_engine(os.environ.get('DATABASE_URL'))
    
    # Load expanded dataset
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT features, outcome
            FROM training_matches 
            WHERE features IS NOT NULL AND outcome IS NOT NULL
        """))
        
        data = []
        for row in result:
            try:
                features_raw = row[0]
                if isinstance(features_raw, str):
                    features = json.loads(features_raw)
                else:
                    features = features_raw
                    
                data.append({'features': features, 'outcome': row[1]})
            except:
                continue
    
    logger.info(f"Testing with {len(data)} diverse matches")
    
    # Test multi-context approach
    context_results = test_contexts(data)
    
    # Test overall system
    overall_result = test_overall_system(data)
    
    return overall_result, context_results

def test_contexts(data):
    """Test individual contexts"""
    # Categorize matches
    home_dominant = []
    competitive = []
    away_strong = []
    
    for sample in data:
        features = sample['features']
        
        home_strength = (
            features.get('home_goals_per_game', 1.5) * 0.25 +
            features.get('home_win_percentage', 0.44) * 0.35 +
            features.get('home_form_points', 8) / 15.0 * 0.25 +
            max(0, features.get('strength_difference', 0.15)) * 0.15
        )
        
        away_strength = (
            features.get('away_goals_per_game', 1.3) * 0.25 +
            features.get('away_win_percentage', 0.32) * 0.35 +
            features.get('away_form_points', 6) / 15.0 * 0.25 +
            max(0, -features.get('strength_difference', 0.15)) * 0.15
        )
        
        strength_gap = home_strength - away_strength
        
        if strength_gap > 0.25:
            home_dominant.append(sample)
        elif strength_gap < -0.15:
            away_strong.append(sample)
        else:
            competitive.append(sample)
    
    # Test each context
    results = {}
    
    for context_name, context_data in [
        ('home_dominant', home_dominant),
        ('competitive', competitive),
        ('away_strong', away_strong)
    ]:
        if len(context_data) >= 40:
            accuracy = test_context_performance(context_data, context_name)
            results[context_name] = accuracy
            logger.info(f"{context_name}: {accuracy:.1%} with {len(context_data)} samples")
    
    return results

def test_context_performance(context_data, context_name):
    """Test performance for specific context"""
    X, y = prepare_features(context_data, context_name)
    
    if len(X) < 40:
        return 0
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # Optimized model for context
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
    
    model.fit(X_train_scaled, y_train)
    y_pred = model.predict(X_test_scaled)
    
    return accuracy_score(y_test, y_pred)

def prepare_features(context_data, context_name):
    """Prepare features for context"""
    features = []
    labels = []
    
    for sample in context_data:
        try:
            sf = sample['features']
            outcome = sample['outcome']
            
            hgpg = sf.get('home_goals_per_game', 1.5)
            agpg = sf.get('away_goals_per_game', 1.3)
            hwp = sf.get('home_win_percentage', 0.44)
            awp = sf.get('away_win_percentage', 0.32)
            hfp = sf.get('home_form_points', 8)
            afp = sf.get('away_form_points', 6)
            
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
                    sf.get('total_goals_tendency', 2.7)/4.0
                ]
            else:  # away_strong
                feature_vector = [
                    agpg, awp, afp/15.0, agpg * awp,
                    hgpg, hwp, hfp/15.0,
                    agpg - hgpg, awp - hwp, (afp - hfp)/15.0,
                    -sf.get('strength_difference', 0.15)
                ]
            
            label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
            
            features.append(feature_vector)
            labels.append(label)
            
        except:
            continue
    
    return np.array(features), np.array(labels)

def test_overall_system(data):
    """Test overall system performance"""
    X, y = prepare_overall_features(data)
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    model = RandomForestClassifier(
        n_estimators=250, max_depth=18,
        class_weight='balanced',
        random_state=42, n_jobs=-1
    )
    
    model.fit(X_train_scaled, y_train)
    y_pred = model.predict(X_test_scaled)
    
    return accuracy_score(y_test, y_pred)

def prepare_overall_features(data):
    """Prepare features for overall test"""
    features = []
    labels = []
    
    for sample in data:
        try:
            sf = sample['features']
            outcome = sample['outcome']
            
            feature_vector = [
                sf.get('home_goals_per_game', 1.5),
                sf.get('away_goals_per_game', 1.3),
                sf.get('home_win_percentage', 0.44),
                sf.get('away_win_percentage', 0.32),
                sf.get('home_form_points', 8) / 15.0,
                sf.get('away_form_points', 6) / 15.0,
                sf.get('strength_difference', 0.15),
                sf.get('form_difference', 2.0) / 10.0,
                sf.get('total_goals_tendency', 2.7) / 4.0,
                abs(sf.get('home_goals_per_game', 1.5) - sf.get('away_goals_per_game', 1.3)),
                abs(sf.get('home_win_percentage', 0.44) - sf.get('away_win_percentage', 0.32))
            ]
            
            label = 2 if outcome == 'Home' else (1 if outcome == 'Draw' else 0)
            
            features.append(feature_vector)
            labels.append(label)
            
        except:
            continue
    
    return np.array(features), np.array(labels)

def main():
    """Run accuracy test"""
    overall_accuracy, context_results = test_current_accuracy()
    
    print(f"""
ACCURACY TEST - 1300 MATCHES FROM 4 EUROPEAN LEAGUES
===================================================

Multi-Context Performance:
{chr(10).join([f'- {context}: {accuracy:.1%}' for context, accuracy in context_results.items()])}

Overall System Accuracy: {overall_accuracy:.1%}

Target Analysis:
- 70% Target: {'✓ ACHIEVED' if overall_accuracy >= 0.70 else '✗ NEEDS IMPROVEMENT'}
- Home Dominant: {'✓ EXCELLENT' if context_results.get('home_dominant', 0) >= 0.80 else ('✓ GOOD' if context_results.get('home_dominant', 0) >= 0.70 else '✗ NEEDS WORK')}
- Competitive: {'✓ EXCELLENT' if context_results.get('competitive', 0) >= 0.70 else '✗ NEEDS MORE DATA'}
- Away Strong: {'✓ EXCELLENT' if context_results.get('away_strong', 0) >= 0.70 else '✗ NEEDS MORE DATA'}

Status: {'PRODUCTION READY' if overall_accuracy >= 0.70 else 'CONTINUE EXPANSION'}
    """)
    
    return overall_accuracy >= 0.70

if __name__ == "__main__":
    success = main()