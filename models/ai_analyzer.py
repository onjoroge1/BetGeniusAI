"""
BetGenius AI Backend - AI-Powered Analysis
Uses OpenAI GPT-4o to explain ML predictions in human language
"""

import json
import logging
from typing import Dict, List, Any, Optional
from openai import OpenAI

from utils.config import settings, get_openai_config

logger = logging.getLogger(__name__)

class AIAnalyzer:
    """AI-powered analysis using OpenAI GPT-4o for prediction explanations"""
    
    def __init__(self):
        self.config = get_openai_config()
        self.client = OpenAI(api_key=self.config['api_key'])
        # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        self.model = "gpt-4o"
        
    async def analyze_prediction(self, match_data: Dict, ml_prediction: Dict) -> Dict[str, Any]:
        """
        Generate human-readable analysis of ML predictions
        Explains WHY the prediction makes sense
        """
        try:
            logger.info("Generating AI analysis...")
            
            # Extract key information
            match_info = match_data['match_info']
            features = match_data['features']
            raw_data = match_data.get('raw_data', {})
            
            # Build comprehensive prompt
            analysis_prompt = self._build_analysis_prompt(
                match_info, features, ml_prediction, raw_data
            )
            
            # Get AI analysis
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are BetGenius AI, an expert football analyst who explains betting predictions clearly and transparently. Always provide specific data-driven reasoning and calculate value bets. Respond in JSON format."
                    },
                    {
                        "role": "user", 
                        "content": analysis_prompt
                    }
                ],
                response_format={"type": "json_object"},
                temperature=self.config['temperature'],
                max_tokens=self.config['max_tokens']
            )
            
            # Parse response
            ai_response = json.loads(response.choices[0].message.content)
            
            # Structure the analysis
            analysis = {
                'explanation': ai_response.get('explanation', 'Analysis unavailable'),
                'confidence_factors': ai_response.get('confidence_factors', []),
                'betting_recommendations': ai_response.get('betting_recommendations', {}),
                'risk_assessment': ai_response.get('risk_assessment', 'Medium risk'),
                'value_analysis': ai_response.get('value_analysis', 'Moderate value'),
                'key_stats': ai_response.get('key_stats', [])
            }
            
            return analysis
            
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return self._fallback_analysis(match_data, ml_prediction)
    
    def _build_analysis_prompt(self, match_info: Dict, features: Dict, 
                             ml_prediction: Dict, raw_data: Dict) -> str:
        """Build comprehensive prompt for AI analysis"""
        
        home_team = match_info['home_team']
        away_team = match_info['away_team']
        venue = match_info.get('venue', 'Unknown Stadium')
        
        # Key statistics for context
        home_win_prob = ml_prediction['home_win_probability']
        draw_prob = ml_prediction['draw_probability']
        away_win_prob = ml_prediction['away_win_probability']
        confidence = ml_prediction['confidence_score']
        
        prompt = f"""
Analyze this football match prediction and explain WHY it makes sense:

MATCH: {home_team} vs {away_team} at {venue}

ML PREDICTIONS:
- {home_team} Win: {home_win_prob:.1%}
- Draw: {draw_prob:.1%} 
- {away_team} Win: {away_win_prob:.1%}
- Confidence: {confidence:.1%}

KEY FEATURES:
- Home Goals/Game: {features.get('home_goals_per_game', 0):.2f}
- Away Goals/Game: {features.get('away_goals_per_game', 0):.2f}
- Home Win %: {features.get('home_win_percentage', 0):.1%}
- Away Win %: {features.get('away_win_percentage', 0):.1%}
- Home Form Points: {features.get('home_form_points', 0)}/15
- Away Form Points: {features.get('away_form_points', 0)}/15
- H2H Home Wins: {features.get('h2h_home_wins', 0)}
- H2H Away Wins: {features.get('h2h_away_wins', 0)}

Provide analysis in this JSON format:
{{
    "explanation": "Clear 2-3 sentence explanation of why the prediction makes sense",
    "confidence_factors": [
        "Factor 1 supporting the prediction", 
        "Factor 2 supporting the prediction",
        "Factor 3 supporting the prediction"
    ],
    "betting_recommendations": {{
        "best_value": "Which bet offers best value",
        "safest_bet": "Lowest risk option",
        "avoid": "What to avoid betting on"
    }},
    "risk_assessment": "Low/Medium/High risk with brief explanation",
    "value_analysis": "Assessment of betting value opportunity",
    "key_stats": [
        "Most important statistic 1",
        "Most important statistic 2", 
        "Most important statistic 3"
    ]
}}

Focus on DATA-DRIVEN insights, not generic football knowledge. Explain the numbers.
"""
        
        return prompt.strip()
    
    def _fallback_analysis(self, match_data: Dict, ml_prediction: Dict) -> Dict[str, Any]:
        """Fallback analysis when AI is unavailable"""
        
        match_info = match_data['match_info']
        features = match_data['features']
        
        home_team = match_info['home_team']
        away_team = match_info['away_team']
        
        home_prob = ml_prediction['home_win_probability']
        confidence = ml_prediction['confidence_score']
        
        # Generate basic analysis
        if home_prob > 0.6:
            explanation = f"{home_team} are strong favorites based on superior home form and recent performance metrics."
        elif home_prob > 0.4:
            explanation = f"Close contest expected between {home_team} and {away_team} with slight home advantage."
        else:
            explanation = f"{away_team} have the edge despite playing away, supported by strong recent form."
        
        # Basic confidence factors
        confidence_factors = []
        if features.get('home_win_percentage', 0) > 0.6:
            confidence_factors.append(f"{home_team} strong home record this season")
        if features.get('home_form_points', 0) > 10:
            confidence_factors.append(f"{home_team} excellent recent form")
        if features.get('goal_difference_home', 0) > 0.5:
            confidence_factors.append(f"{home_team} positive goal difference")
        
        if not confidence_factors:
            confidence_factors = ["Analysis based on available team statistics", "Historical performance data", "Recent form indicators"]
        
        return {
            'explanation': explanation,
            'confidence_factors': confidence_factors,
            'betting_recommendations': {
                'best_value': ml_prediction['recommended_bet'],
                'safest_bet': 'Over 1.5 Goals',
                'avoid': 'High-risk accumulator bets'
            },
            'risk_assessment': f"{'Low' if confidence > 0.8 else 'Medium' if confidence > 0.6 else 'High'} risk based on {confidence:.0%} model confidence",
            'value_analysis': 'Standard market conditions - compare with bookmaker odds',
            'key_stats': [
                f"Home goals per game: {features.get('home_goals_per_game', 0):.2f}",
                f"Away goals per game: {features.get('away_goals_per_game', 0):.2f}",
                f"Model confidence: {confidence:.0%}"
            ]
        }
    
    def generate_swahili_analysis(self, analysis: Dict, match_info: Dict) -> Dict[str, str]:
        """Generate Swahili translation of analysis (future feature)"""
        # Placeholder for multi-language support
        # Would use OpenAI to translate the analysis to Swahili
        try:
            home_team = match_info['home_team']
            away_team = match_info['away_team']
            
            # Basic Swahili translation (would be enhanced with proper AI translation)
            swahili_analysis = {
                'explanation': f"{home_team} wana uwezekano mkubwa wa kushinda kutokana na hali nzuri ya nyumbani.",
                'summary': f"Mchezo kati ya {home_team} na {away_team} - {home_team} wanatarajiwa kushinda."
            }
            
            return swahili_analysis
            
        except Exception as e:
            logger.error(f"Swahili translation failed: {e}")
            return {
                'explanation': 'Uchambuzi haupatikani kwa Kiswahili',
                'summary': 'Muhtasari haupatikani'
            }
