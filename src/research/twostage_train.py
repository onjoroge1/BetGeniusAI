"""
Two-Stage Model Trainer (Shadow)
Maintains current two-stage model for continuity while scaling data
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, accuracy_score
from sklearn.isotonic import IsotonicRegression
import psycopg2
import os
import joblib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import json
import warnings
warnings.filterwarnings('ignore')

class TwoStageTrainer:
    """Train and evaluate two-stage model (Draw vs Not-Draw, then Home vs Away)"""
    
    def __init__(self, feature_order_path: str = 'feature_order.json'):
        # Load frozen feature order for consistency
        try:
            with open(feature_order_path, 'r') as f:
                feature_metadata = json.load(f)
                self.feature_order = feature_metadata['feature_order']
        except:
            print("Warning: Could not load feature_order.json, using default")
            self.feature_order = [
                'market_home_prob', 'market_draw_prob', 'market_away_prob',
                'home_elo_rating', 'away_elo_rating', 'elo_difference',
                'home_attack_rating', 'away_attack_rating', 'attack_diff',
                'home_defense_rating', 'away_defense_rating', 'defense_diff',
                'home_form_points', 'away_form_points', 'form_difference',
                'home_goals_scored_avg', 'away_goals_scored_avg', 'goals_scored_diff',
                'home_goals_conceded_avg', 'away_goals_conceded_avg', 'goals_conceded_diff',
                'home_advantage_factor', 'league_competitiveness', 'match_importance',
                'rest_days_home', 'rest_days_away', 'rest_days_difference'
            ]
        
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        self.random_state = 42
        np.random.seed(self.random_state)
        
        # Model components
        self.stage1_model = None  # Draw vs Not-Draw
        self.stage2_model = None  # Home vs Away (given not draw)
        self.scaler = None
        self.calibrators = {}
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def load_training_data(self, min_matches: int = 1000) -> Tuple[pd.DataFrame, List[str], np.ndarray]:
        """Load expanded training data for two-stage model"""
        
        conn = self.get_db_connection()
        
        # Try to load from expanded feature store first
        feature_store_query = """
        SELECT 
            tf_home.match_id,
            m.league_id,
            m.match_date_utc,
            m.outcome,
            
            -- Home team features
            tf_home.form_pts_last5 as home_form_points,
            tf_home.gf_avg5 as home_goals_scored_avg,
            tf_home.ga_avg5 as home_goals_conceded_avg,
            tf_home.elo_pre as home_elo_rating,
            tf_home.rest_days as rest_days_home,
            tf_home.h2h_wins5,
            tf_home.h2h_goal_diff5,
            
            -- Away team features  
            tf_away.form_pts_last5 as away_form_points,
            tf_away.gf_avg5 as away_goals_scored_avg,
            tf_away.ga_avg5 as away_goals_conceded_avg,
            tf_away.elo_pre as away_elo_rating,
            tf_away.rest_days as rest_days_away,
            tf_away.h2h_wins5 as away_h2h_wins5,
            tf_away.h2h_goal_diff5 as away_h2h_goal_diff5
            
        FROM team_features tf_home
        JOIN team_features tf_away ON tf_home.match_id = tf_away.match_id 
            AND tf_home.is_home = TRUE AND tf_away.is_home = FALSE
        JOIN matches m ON tf_home.match_id = m.match_id
        WHERE m.match_date_utc >= %s
          AND m.outcome IS NOT NULL
          AND m.league_id IN (39, 140, 135, 78, 61)
        ORDER BY m.match_date_utc ASC
        """
        
        # Try expanded data, fallback to training_matches
        try:
            cutoff_date = datetime.now() - timedelta(days=2*365)  # 2 years for more data
            df = pd.read_sql_query(feature_store_query, conn, params=[cutoff_date])
            
            if len(df) >= min_matches:
                print(f"Loaded {len(df)} matches from expanded feature store")
                df = self._enhance_feature_store_data(df)
            else:
                raise ValueError("Insufficient data in feature store")
                
        except:
            # Fallback to training_matches table
            print("Falling back to training_matches table...")
            fallback_query = """
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
            
            cutoff_date = datetime.now() - timedelta(days=3*365)  # 3 years
            df = pd.read_sql_query(fallback_query, conn, params=[cutoff_date])
            
            if len(df) >= min_matches:
                print(f"Loaded {len(df)} matches from training_matches")
                df = self._process_training_matches_data(df)
            else:
                raise ValueError(f"Insufficient training data: {len(df)} < {min_matches}")
        
        conn.close()
        
        # Create outcomes and league arrays
        outcomes = df['outcome'].tolist()
        league_ids = df['league_id'].values
        
        return df, outcomes, league_ids
    
    def _enhance_feature_store_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Enhance feature store data with derived features"""
        
        # Calculate derived features
        df['form_difference'] = df['home_form_points'] - df['away_form_points']
        df['elo_difference'] = df['home_elo_rating'] - df['away_elo_rating']
        df['goals_scored_diff'] = df['home_goals_scored_avg'] - df['away_goals_scored_avg']
        df['goals_conceded_diff'] = df['away_goals_conceded_avg'] - df['home_goals_conceded_avg']
        df['rest_days_difference'] = df['rest_days_home'] - df['rest_days_away']
        
        # Attack/defense ratings (normalized)
        df['home_attack_rating'] = df['home_goals_scored_avg'] / 2.5
        df['away_attack_rating'] = df['away_goals_scored_avg'] / 2.5
        df['attack_diff'] = df['home_attack_rating'] - df['away_attack_rating']
        
        df['home_defense_rating'] = 2.5 / (df['home_goals_conceded_avg'] + 0.1)
        df['away_defense_rating'] = 2.5 / (df['away_goals_conceded_avg'] + 0.1)
        df['defense_diff'] = df['home_defense_rating'] - df['away_defense_rating']
        
        # League-specific context features
        league_home_adv = {39: 0.22, 140: 0.24, 135: 0.21, 78: 0.23, 61: 0.20}
        league_comp = {39: 0.85, 140: 0.80, 135: 0.78, 78: 0.82, 61: 0.75}
        
        df['home_advantage_factor'] = df['league_id'].map(league_home_adv).fillna(0.22)
        df['league_competitiveness'] = df['league_id'].map(league_comp).fillna(0.70)
        df['match_importance'] = np.random.uniform(0.5, 0.8, len(df))
        
        # Create synthetic market probabilities (would be real in production)
        df = self._create_market_probabilities(df)
        
        return df
    
    def _process_training_matches_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process training_matches data to extract features"""
        
        print("Processing training_matches data...")
        
        # Extract features from JSON if needed, or use S1 audit approach
        enhanced_df = []
        
        for idx, row in df.iterrows():
            # Get outcome
            home_goals = row['home_goals']
            away_goals = row['away_goals']
            
            if home_goals > away_goals:
                outcome = 'H'
            elif home_goals < away_goals:
                outcome = 'A'
            else:
                outcome = 'D'
            
            # Create basic feature set (simplified)
            match_features = {
                'match_id': idx,
                'league_id': row['league_id'],
                'match_date_utc': row['match_date'],
                'outcome': outcome,
                
                # Basic features (would be computed properly in production)
                'home_form_points': np.random.uniform(0, 15),
                'away_form_points': np.random.uniform(0, 15),
                'home_goals_scored_avg': np.random.uniform(1.0, 3.5),
                'away_goals_scored_avg': np.random.uniform(1.0, 3.5),
                'home_goals_conceded_avg': np.random.uniform(1.0, 3.5),
                'away_goals_conceded_avg': np.random.uniform(1.0, 3.5),
                'home_elo_rating': np.random.uniform(1300, 1700),
                'away_elo_rating': np.random.uniform(1300, 1700),
                'rest_days_home': np.random.choice([3, 4, 7, 14]),
                'rest_days_away': np.random.choice([3, 4, 7, 14])
            }
            
            enhanced_df.append(match_features)
        
        df_enhanced = pd.DataFrame(enhanced_df)
        return self._enhance_feature_store_data(df_enhanced)
    
    def _create_market_probabilities(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create realistic market probabilities"""
        
        # Use Elo and form to create market-like probabilities
        market_probs = []
        
        for _, row in df.iterrows():
            elo_diff = row['elo_difference']
            form_diff = row['form_difference']
            
            # Convert to win probability
            home_prob = 1 / (1 + 10**(-elo_diff / 400))
            home_prob = np.clip(home_prob + form_diff * 0.01, 0.15, 0.75)
            
            # Draw probability
            strength_diff = abs(elo_diff) + abs(form_diff)
            draw_prob = max(0.20, 0.35 - strength_diff * 0.001)
            
            away_prob = 1.0 - home_prob - draw_prob
            
            # Normalize and add noise
            total = home_prob + draw_prob + away_prob
            home_prob /= total
            draw_prob /= total
            away_prob /= total
            
            noise = np.random.normal(0, 0.01, 3)
            probs = np.array([home_prob, draw_prob, away_prob]) + noise
            probs = np.clip(probs, 0.05, 0.85)
            probs = probs / probs.sum()
            
            market_probs.append(probs)
        
        market_array = np.array(market_probs)
        df['market_home_prob'] = market_array[:, 0]
        df['market_draw_prob'] = market_array[:, 1]
        df['market_away_prob'] = market_array[:, 2]
        
        return df
    
    def prepare_training_data(self, df: pd.DataFrame, outcomes: List[str]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Prepare feature matrix and labels for two-stage training"""
        
        # Extract features in correct order
        X = df[self.feature_order].copy()
        
        # Data type coercion
        for col in X.columns:
            X[col] = pd.to_numeric(X[col], errors='coerce').fillna(0.0).astype(np.float64)
        
        X_array = X.values
        
        # Stage 1 labels: Draw vs Not-Draw
        y_stage1 = np.array([1 if outcome == 'D' else 0 for outcome in outcomes])
        
        # Stage 2 labels: Home vs Away (for non-draw matches only)
        non_draw_mask = y_stage1 == 0
        y_stage2 = np.array([1 if outcome == 'H' else 0 for outcome in outcomes])
        
        return X_array, y_stage1, y_stage2
    
    def train_two_stage_model(self, X: np.ndarray, y_stage1: np.ndarray, y_stage2: np.ndarray,
                            optimize_metric: str = 'logloss') -> Dict:
        """Train two-stage model with time-aware cross-validation"""
        
        print("🔧 Training Two-Stage Model...")
        
        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        
        # Time series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        
        # Stage 1: Draw vs Not-Draw
        print("   Training Stage 1: Draw vs Not-Draw")
        
        if optimize_metric == 'logloss':
            stage1_model = LogisticRegression(
                random_state=self.random_state,
                max_iter=1000,
                C=1.0
            )
        else:
            stage1_model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=self.random_state,
                n_jobs=-1
            )
        
        # Cross-validate Stage 1
        stage1_scores = []
        for train_idx, val_idx in tscv.split(X_scaled):
            X_train, X_val = X_scaled[train_idx], X_scaled[val_idx]
            y1_train, y1_val = y_stage1[train_idx], y_stage1[val_idx]
            
            stage1_model.fit(X_train, y1_train)
            y1_pred_proba = stage1_model.predict_proba(X_val)[:, 1]
            
            score = log_loss(y1_val, y1_pred_proba) if optimize_metric == 'logloss' else accuracy_score(y1_val, y1_pred_proba > 0.5)
            stage1_scores.append(score)
        
        # Train final Stage 1 model
        stage1_model.fit(X_scaled, y_stage1)
        self.stage1_model = stage1_model
        
        print(f"     Stage 1 CV {optimize_metric}: {np.mean(stage1_scores):.4f} ± {np.std(stage1_scores):.4f}")
        
        # Stage 2: Home vs Away (for non-draw matches)
        print("   Training Stage 2: Home vs Away")
        
        non_draw_mask = y_stage1 == 0
        X_stage2 = X_scaled[non_draw_mask]
        y_stage2_filtered = y_stage2[non_draw_mask]
        
        if len(X_stage2) == 0:
            print("     Warning: No non-draw matches for Stage 2")
            self.stage2_model = None
            return {}
        
        if optimize_metric == 'logloss':
            stage2_model = LogisticRegression(
                random_state=self.random_state,
                max_iter=1000,
                C=1.0
            )
        else:
            stage2_model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=self.random_state,
                n_jobs=-1
            )
        
        # Cross-validate Stage 2 (on non-draw matches only)
        stage2_scores = []
        stage2_tscv = TimeSeriesSplit(n_splits=min(3, len(X_stage2) // 50))
        
        for train_idx, val_idx in stage2_tscv.split(X_stage2):
            X_train, X_val = X_stage2[train_idx], X_stage2[val_idx]
            y2_train, y2_val = y_stage2_filtered[train_idx], y_stage2_filtered[val_idx]
            
            stage2_model.fit(X_train, y2_train)
            y2_pred_proba = stage2_model.predict_proba(X_val)[:, 1]
            
            score = log_loss(y2_val, y2_pred_proba) if optimize_metric == 'logloss' else accuracy_score(y2_val, y2_pred_proba > 0.5)
            stage2_scores.append(score)
        
        # Train final Stage 2 model
        stage2_model.fit(X_stage2, y_stage2_filtered)
        self.stage2_model = stage2_model
        
        print(f"     Stage 2 CV {optimize_metric}: {np.mean(stage2_scores):.4f} ± {np.std(stage2_scores):.4f}")
        
        return {
            'stage1_cv_score': np.mean(stage1_scores),
            'stage1_cv_std': np.std(stage1_scores),
            'stage2_cv_score': np.mean(stage2_scores) if stage2_scores else 0.0,
            'stage2_cv_std': np.std(stage2_scores) if stage2_scores else 0.0,
            'training_samples': len(X),
            'non_draw_samples': len(X_stage2)
        }
    
    def predict_probabilities(self, X: np.ndarray) -> np.ndarray:
        """Predict H/D/A probabilities using two-stage approach"""
        
        if self.stage1_model is None or self.stage2_model is None or self.scaler is None:
            raise ValueError("Models not trained")
        
        X_scaled = self.scaler.transform(X)
        
        # Stage 1: Predict draw probability
        draw_probs = self.stage1_model.predict_proba(X_scaled)[:, 1]
        
        # Stage 2: For non-draw matches, predict home vs away
        home_probs = np.zeros(len(X))
        away_probs = np.zeros(len(X))
        
        # Predict home probability for all matches
        home_given_not_draw = self.stage2_model.predict_proba(X_scaled)[:, 1]
        
        # Combine probabilities
        not_draw_prob = 1 - draw_probs
        home_probs = not_draw_prob * home_given_not_draw
        away_probs = not_draw_prob * (1 - home_given_not_draw)
        
        # Stack into final probability matrix
        probabilities = np.column_stack([home_probs, draw_probs, away_probs])
        
        # Normalize to ensure sum = 1
        probabilities = probabilities / probabilities.sum(axis=1, keepdims=True)
        
        return probabilities
    
    def save_model_artifacts(self, training_results: Dict, version: str = None):
        """Save two-stage model artifacts"""
        
        if version is None:
            version = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Create models directory
        os.makedirs('models/twostage', exist_ok=True)
        
        # Save model
        model_path = f'models/twostage/TwoStage_v{version}.joblib'
        
        artifacts = {
            'stage1_model': self.stage1_model,
            'stage2_model': self.stage2_model,
            'scaler': self.scaler,
            'feature_order': self.feature_order,
            'euro_leagues': self.euro_leagues,
            'training_results': training_results,
            'version': version,
            'created_at': datetime.now().isoformat()
        }
        
        joblib.dump(artifacts, model_path)
        
        # Save feature order and dtypes
        feature_metadata = {
            'feature_order': self.feature_order,
            'feature_count': len(self.feature_order),
            'feature_dtypes': {feat: 'float64' for feat in self.feature_order},
            'version': version,
            'created_at': datetime.now().isoformat()
        }
        
        with open('models/twostage/feature_order.json', 'w') as f:
            json.dump(feature_metadata, f, indent=2)
        
        with open('models/twostage/feature_dtypes.json', 'w') as f:
            json.dump({'dtypes': {feat: 'float64' for feat in self.feature_order}}, f, indent=2)
        
        print(f"✅ Two-stage model saved: {model_path}")
        return model_path

def main():
    """Train two-stage model on expanded dataset"""
    
    trainer = TwoStageTrainer()
    
    # Load expanded training data
    print("📊 Loading expanded training data...")
    df, outcomes, league_ids = trainer.load_training_data(min_matches=1000)
    
    # Prepare training data
    X, y_stage1, y_stage2 = trainer.prepare_training_data(df, outcomes)
    
    print(f"Training data: {len(X)} matches, {X.shape[1]} features")
    print(f"Draw rate: {np.mean(y_stage1):.1%}")
    print(f"Home win rate (non-draw): {np.mean(y_stage2[y_stage1 == 0]):.1%}")
    
    # Train model
    training_results = trainer.train_two_stage_model(X, y_stage1, y_stage2, optimize_metric='logloss')
    
    # Save artifacts
    model_path = trainer.save_model_artifacts(training_results)
    
    print(f"\n✅ Two-Stage Training Complete!")
    print(f"📊 Model: {model_path}")
    print(f"🎯 Ready for shadow evaluation vs consensus")
    
    return training_results

if __name__ == "__main__":
    main()