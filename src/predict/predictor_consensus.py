"""
Consensus Predictor - Production forecaster using calibrated consensus
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import psycopg2
import os
import joblib
import yaml
from datetime import datetime, timedelta
import json
from src.consensus.calibrate_consensus import ConsensusCalibrator
import warnings
warnings.filterwarnings('ignore')

class ConsensusPredictor:
    """Production predictor using calibrated consensus forecasts"""
    
    def __init__(self, config_path: str = 'config/leagues.yml'):
        # Load league configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.euro_leagues = {
            39: 'English Premier League',
            140: 'La Liga Santander', 
            135: 'Serie A',
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        # Load calibrators
        self.calibrator = ConsensusCalibrator()
        try:
            self.calibrator.load_calibrators('latest')
            self.calibrators_loaded = True
        except:
            print("Warning: No calibrators found, using raw consensus")
            self.calibrators_loaded = False
    
    def get_db_connection(self):
        """Get database connection"""
        return psycopg2.connect(os.environ['DATABASE_URL'])
    
    def get_optimal_time_bucket(self, match_date: datetime, league_id: int) -> str:
        """Get optimal time bucket based on time to kickoff and league settings"""
        
        time_to_kickoff = match_date - datetime.now()
        hours_to_kickoff = time_to_kickoff.total_seconds() / 3600
        
        # Get league timing preferences
        league_config = self.config['leagues'].get(league_id, {})
        timing_config = league_config.get('timing', self.config['global']['default_timing'])
        
        optimal_window = timing_config['optimal_window_hours']
        avoid_window = timing_config['avoid_window_hours']
        
        # Select bucket based on timing preferences and availability
        if hours_to_kickoff >= 24:
            return '24h'
        elif hours_to_kickoff >= 12 and hours_to_kickoff < optimal_window[0]:
            return '12h'  
        elif hours_to_kickoff >= 6 and hours_to_kickoff >= optimal_window[1]:
            return '6h'
        elif hours_to_kickoff >= 3 and hours_to_kickoff > avoid_window[0]:
            return '3h'
        elif hours_to_kickoff >= 1 and hours_to_kickoff > avoid_window[1]:
            return '1h'
        else:
            return 'close'
    
    def get_consensus_prediction(self, match_id: int, time_bucket: str = None) -> Optional[Dict]:
        """Get consensus prediction for match"""
        
        conn = self.get_db_connection()
        
        # Get match info
        match_query = """
        SELECT match_id, league_id, match_date_utc, home_team_id, away_team_id
        FROM matches 
        WHERE match_id = %s
        """
        
        match_df = pd.read_sql_query(match_query, conn, params=[match_id])
        
        if len(match_df) == 0:
            conn.close()
            return None
        
        match_info = match_df.iloc[0]
        league_id = match_info['league_id']
        match_date = pd.to_datetime(match_info['match_date_utc'])
        
        # Determine optimal time bucket if not specified
        if time_bucket is None:
            time_bucket = self.get_optimal_time_bucket(match_date, league_id)
        
        # Get consensus prediction
        consensus_query = """
        SELECT 
            consensus_h,
            consensus_d,
            consensus_a,
            dispersion_h,
            dispersion_d,
            dispersion_a,
            n_books,
            consensus_method,
            created_at
        FROM consensus_predictions
        WHERE match_id = %s AND time_bucket = %s
        ORDER BY created_at DESC
        LIMIT 1
        """
        
        consensus_df = pd.read_sql_query(consensus_query, conn, params=[match_id, time_bucket])
        conn.close()
        
        if len(consensus_df) == 0:
            return None
        
        consensus = consensus_df.iloc[0]
        
        # Apply calibration if available
        raw_probs = np.array([consensus['consensus_h'], consensus['consensus_d'], consensus['consensus_a']])
        
        if self.calibrators_loaded:
            try:
                cal_h, cal_d, cal_a = self.calibrator.apply_calibration(
                    np.array([consensus['consensus_h']]),
                    np.array([consensus['consensus_d']]),
                    np.array([consensus['consensus_a']]),
                    league_id, time_bucket
                )
                calibrated_probs = np.array([cal_h[0], cal_d[0], cal_a[0]])
            except:
                calibrated_probs = raw_probs
        else:
            calibrated_probs = raw_probs
        
        # Calculate confidence measures
        avg_dispersion = np.mean([consensus['dispersion_h'], consensus['dispersion_d'], consensus['dispersion_a']])
        max_prob = np.max(calibrated_probs)
        entropy = -np.sum(calibrated_probs * np.log(calibrated_probs + 1e-10))
        
        # Determine prediction confidence
        if avg_dispersion < 0.05 and max_prob > 0.6:
            confidence = 'high'
        elif avg_dispersion < 0.10 and max_prob > 0.45:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        # Get league-specific thresholds
        league_config = self.config['leagues'].get(league_id, {})
        min_edge = league_config.get('timing', {}).get('min_edge_threshold', 0.03)
        
        # Calculate edge (simplified - would compare to best available odds in practice)
        uniform_prob = 1/3
        max_edge = max_prob - uniform_prob
        has_edge = max_edge >= min_edge
        
        return {
            'match_id': match_id,
            'league_id': league_id,
            'league_name': self.euro_leagues.get(league_id, f"League_{league_id}"),
            'time_bucket': time_bucket,
            'time_to_kickoff_hours': (match_date - datetime.now()).total_seconds() / 3600,
            
            # Probabilities
            'probabilities': {
                'home': float(calibrated_probs[0]),
                'draw': float(calibrated_probs[1]),
                'away': float(calibrated_probs[2])
            },
            'raw_probabilities': {
                'home': float(raw_probs[0]),
                'draw': float(raw_probs[1]),
                'away': float(raw_probs[2])
            },
            
            # Uncertainty measures
            'uncertainty': {
                'dispersion_avg': float(avg_dispersion),
                'entropy': float(entropy),
                'max_probability': float(max_prob)
            },
            
            # Prediction details
            'prediction': {
                'most_likely': ['home', 'draw', 'away'][np.argmax(calibrated_probs)],
                'confidence': confidence,
                'has_edge': has_edge,
                'estimated_edge': float(max_edge)
            },
            
            # Metadata
            'metadata': {
                'n_books_used': int(consensus['n_books']),
                'consensus_method': consensus['consensus_method'],
                'calibrated': self.calibrators_loaded,
                'created_at': consensus['created_at'].isoformat() if consensus['created_at'] else None
            }
        }
    
    def predict_matches(self, match_ids: List[int], time_bucket: str = None) -> List[Dict]:
        """Get consensus predictions for multiple matches"""
        
        predictions = []
        
        for match_id in match_ids:
            prediction = self.get_consensus_prediction(match_id, time_bucket)
            if prediction:
                predictions.append(prediction)
        
        return predictions
    
    def get_upcoming_matches(self, league_ids: List[int] = None, 
                           days_ahead: int = 7, limit: int = 50) -> List[Dict]:
        """Get predictions for upcoming matches"""
        
        if league_ids is None:
            league_ids = list(self.euro_leagues.keys())
        
        conn = self.get_db_connection()
        
        query = """
        SELECT match_id, league_id, match_date_utc, home_team_id, away_team_id
        FROM matches 
        WHERE match_date_utc > NOW() 
          AND match_date_utc < NOW() + INTERVAL '%s days'
          AND league_id = ANY(%s)
        ORDER BY match_date_utc
        LIMIT %s
        """
        
        matches_df = pd.read_sql_query(query, conn, params=[days_ahead, league_ids, limit])
        conn.close()
        
        if len(matches_df) == 0:
            return []
        
        match_ids = matches_df['match_id'].tolist()
        return self.predict_matches(match_ids)
    
    def get_betting_recommendations(self, predictions: List[Dict], 
                                  max_recommendations: int = 5) -> List[Dict]:
        """Filter predictions to betting recommendations based on edge and confidence"""
        
        recommendations = []
        
        for pred in predictions:
            # Apply league-specific filters
            league_id = pred['league_id']
            league_config = self.config['leagues'].get(league_id, {})
            
            timing_config = league_config.get('timing', self.config['global']['default_timing'])
            min_edge = timing_config['min_edge_threshold']
            
            operations_config = league_config.get('operations', {})
            kelly_fraction = operations_config.get('kelly_fraction', 0.25)
            max_stake_pct = operations_config.get('max_stake_percentage', 0.05)
            
            # Check if prediction meets betting criteria
            has_sufficient_edge = pred['prediction']['estimated_edge'] >= min_edge
            has_good_confidence = pred['prediction']['confidence'] in ['high', 'medium']
            time_window_ok = pred['time_to_kickoff_hours'] >= 1.0  # At least 1 hour ahead
            
            if has_sufficient_edge and has_good_confidence and time_window_ok:
                # Calculate Kelly bet size (simplified)
                edge = pred['prediction']['estimated_edge']
                prob = pred['probabilities'][pred['prediction']['most_likely']]
                
                # Simplified Kelly calculation (would use actual odds in practice)
                estimated_odds = 1 / prob
                kelly_size = kelly_fraction * edge
                recommended_stake = min(kelly_size, max_stake_pct)
                
                recommendation = {
                    **pred,
                    'recommendation': {
                        'action': 'bet',
                        'outcome': pred['prediction']['most_likely'],
                        'stake_percentage': float(recommended_stake),
                        'kelly_fraction_used': kelly_fraction,
                        'reasoning': f"Edge: {edge:.1%}, Confidence: {pred['prediction']['confidence']}"
                    }
                }
                
                recommendations.append(recommendation)
        
        # Sort by estimated edge (descending) and limit
        recommendations.sort(key=lambda x: x['prediction']['estimated_edge'], reverse=True)
        return recommendations[:max_recommendations]
    
    def generate_prediction_report(self, predictions: List[Dict]) -> str:
        """Generate human-readable prediction report"""
        
        if not predictions:
            return "No predictions available."
        
        lines = [
            "BETGENIUS AI CONSENSUS PREDICTIONS",
            "=" * 50,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Predictions: {len(predictions)}",
            ""
        ]
        
        # Group by league
        by_league = {}
        for pred in predictions:
            league_name = pred['league_name']
            if league_name not in by_league:
                by_league[league_name] = []
            by_league[league_name].append(pred)
        
        for league_name, league_preds in by_league.items():
            lines.append(f"{league_name.upper()}:")
            lines.append("-" * 30)
            
            for pred in league_preds:
                probs = pred['probabilities']
                most_likely = pred['prediction']['most_likely']
                confidence = pred['prediction']['confidence']
                
                # Format probability display
                prob_str = f"H:{probs['home']:.1%} D:{probs['draw']:.1%} A:{probs['away']:.1%}"
                
                # Time to kickoff
                hours_to_ko = pred['time_to_kickoff_hours']
                if hours_to_ko >= 24:
                    time_str = f"{hours_to_ko/24:.1f}d"
                else:
                    time_str = f"{hours_to_ko:.1f}h"
                
                lines.append(f"  Match {pred['match_id']} ({time_str}): {prob_str}")
                lines.append(f"    Prediction: {most_likely.upper()} ({confidence} confidence)")
                
                if pred['prediction']['has_edge']:
                    edge = pred['prediction']['estimated_edge']
                    lines.append(f"    Edge: {edge:.1%} ⭐")
                
                lines.append("")
            
            lines.append("")
        
        # Summary statistics
        high_conf = sum(1 for p in predictions if p['prediction']['confidence'] == 'high')
        with_edge = sum(1 for p in predictions if p['prediction']['has_edge'])
        
        lines.extend([
            "SUMMARY:",
            "-" * 15,
            f"High confidence: {high_conf}/{len(predictions)} ({high_conf/len(predictions):.1%})",
            f"With edge: {with_edge}/{len(predictions)} ({with_edge/len(predictions):.1%})",
            f"Average max probability: {np.mean([p['uncertainty']['max_probability'] for p in predictions]):.1%}",
            ""
        ])
        
        return "\n".join(lines)

def main():
    """Demo consensus predictor"""
    
    predictor = ConsensusPredictor()
    
    # Get upcoming predictions
    print("🔮 Getting upcoming match predictions...")
    predictions = predictor.get_upcoming_matches(limit=20)
    
    if not predictions:
        print("No upcoming matches with consensus data found")
        return
    
    # Generate betting recommendations
    recommendations = predictor.get_betting_recommendations(predictions, max_recommendations=5)
    
    # Display report
    report = predictor.generate_prediction_report(predictions)
    print(report)
    
    if recommendations:
        print("BETTING RECOMMENDATIONS:")
        print("=" * 30)
        for rec in recommendations:
            rec_details = rec['recommendation']
            print(f"Match {rec['match_id']} ({rec['league_name']})")
            print(f"  Bet: {rec_details['outcome'].upper()}")
            print(f"  Stake: {rec_details['stake_percentage']:.1%} of bankroll")
            print(f"  Reason: {rec_details['reasoning']}")
            print()
    
    print(f"✅ Consensus predictions complete!")
    return predictions, recommendations

if __name__ == "__main__":
    main()