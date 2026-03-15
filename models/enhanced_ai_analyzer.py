"""
Enhanced AI Analyzer
Uses OpenAI to analyze comprehensive match data and provide intelligent insights
"""

import os
import json
from typing import Dict, List, Any, Optional
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

class EnhancedAIAnalyzer:
    """Enhanced AI analyzer using comprehensive match data"""
    
    def __init__(self):
        self.client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        # the newest OpenAI model is "gpt-4o" which was released May 13, 2024.
        # do not change this unless explicitly requested by the user
        self.model = "gpt-4o"
    
    def format_match_context(self, match_data: Dict) -> str:
        """Format comprehensive match data for AI analysis"""
        
        match_details = match_data.get('match_details', {})
        home_team = match_data.get('home_team', {})
        away_team = match_data.get('away_team', {})
        h2h = match_data.get('head_to_head', [])
        team_news = match_data.get('team_news', {})
        odds = match_data.get('current_odds', {})
        
        context = f"""
MATCH ANALYSIS REQUEST

=== BASIC MATCH INFORMATION ===
Match: {home_team.get('name', 'Unknown')} vs {away_team.get('name', 'Unknown')}
Date: {match_details.get('fixture', {}).get('date', 'Unknown')}
Venue: {match_details.get('fixture', {}).get('venue', {}).get('name', 'Unknown')}
League: {match_details.get('league', {}).get('name', 'Unknown')}

=== HOME TEAM ANALYSIS ===
Team: {home_team.get('name', 'Unknown')}

Recent Form (Last 5 matches):
"""
        
        # Add home team form
        for i, match in enumerate(home_team.get('recent_form', [])[:5]):
            context += f"  {i+1}. vs {match.get('opponent', 'Unknown')} ({match.get('venue', 'Unknown')}) - {match.get('result', 'Unknown')} {match.get('score', 'Unknown')}\n"
        
        # Add home team injuries
        injuries = home_team.get('injuries', [])
        if injuries:
            context += f"\nCurrent Injuries ({len(injuries)} players):\n"
            for injury in injuries[:5]:  # Limit to 5 most recent
                context += f"  - {injury.get('player_name', 'Unknown')} ({injury.get('player_position', 'Unknown')}): {injury.get('injury_type', 'Unknown')}\n"
        else:
            context += "\nCurrent Injuries: No significant injuries reported\n"
        
        context += f"""
=== AWAY TEAM ANALYSIS ===
Team: {away_team.get('name', 'Unknown')}

Recent Form (Last 5 matches):
"""
        
        # Add away team form
        for i, match in enumerate(away_team.get('recent_form', [])[:5]):
            context += f"  {i+1}. vs {match.get('opponent', 'Unknown')} ({match.get('venue', 'Unknown')}) - {match.get('result', 'Unknown')} {match.get('score', 'Unknown')}\n"
        
        # Add away team injuries
        injuries = away_team.get('injuries', [])
        if injuries:
            context += f"\nCurrent Injuries ({len(injuries)} players):\n"
            for injury in injuries[:5]:  # Limit to 5 most recent
                context += f"  - {injury.get('player_name', 'Unknown')} ({injury.get('player_position', 'Unknown')}): {injury.get('injury_type', 'Unknown')}\n"
        else:
            context += "\nCurrent Injuries: No significant injuries reported\n"
        
        # Add head-to-head
        if h2h:
            context += f"\n=== HEAD-TO-HEAD RECORD (Last {len(h2h)} meetings) ===\n"
            for match in h2h:
                context += f"  {match.get('date', 'Unknown')}: {match.get('home_team', 'Unknown')} {match.get('score', 'Unknown')} {match.get('away_team', 'Unknown')} (Winner: {match.get('winner', 'Unknown')})\n"
        
        # Add team news/lineups if available
        if team_news:
            context += "\n=== TEAM NEWS & LINEUPS ===\n"
            for team_name, lineup in team_news.items():
                if lineup.get('formation'):
                    context += f"{team_name} Formation: {lineup['formation']}\n"
                    
                    starting_xi = lineup.get('starting_xi', [])
                    if starting_xi:
                        context += f"Key Starting XI: {', '.join([p['name'] for p in starting_xi[:5]])}\n"
        
        # Add betting odds
        if odds:
            context += "\n=== CURRENT BETTING ODDS ===\n"
            for bookmaker, odd_set in odds.items():
                context += f"{bookmaker.title()}: Home {odd_set.get('home', 'N/A')} | Draw {odd_set.get('draw', 'N/A')} | Away {odd_set.get('away', 'N/A')}\n"
        
        return context
    
    def analyze_match_comprehensive(self, match_data: Dict, prediction_result: Dict) -> Dict[str, Any]:
        """Provide comprehensive AI analysis of the match"""
        
        context = self.format_match_context(match_data)
        
        # Add prediction context
        probs = prediction_result.get('probabilities', {})
        prediction = prediction_result.get('prediction', 'Unknown')
        confidence = prediction_result.get('confidence', 0)
        
        prediction_context = f"""
=== AI MODEL PREDICTION ===
Model Type: Simple Weighted Consensus (Outperforms complex models)
Home Win: {probs.get('home', 0):.1%}
Draw: {probs.get('draw', 0):.1%}
Away Win: {probs.get('away', 0):.1%}
Predicted Outcome: {prediction.title()}
Confidence Level: {confidence:.1%}
Quality Score: {prediction_result.get('quality_score', 0):.1%}
"""
        
        # Create comprehensive analysis prompt
        prompt = f"""You are BetGenius AI, Africa's premier sports prediction expert. Analyze this football match comprehensively using the provided data.

{context}

{prediction_context}

Please provide a comprehensive analysis in JSON format with the following structure:
{{
    "match_overview": "Brief overview of the match significance and context",
    "key_factors": [
        "List of 3-5 key factors that will influence the match outcome"
    ],
    "team_analysis": {{
        "home_team": {{
            "strengths": ["List of current strengths"],
            "weaknesses": ["List of concerns/weaknesses"],
            "form_assessment": "Current form analysis",
            "injury_impact": "Impact of injuries on performance"
        }},
        "away_team": {{
            "strengths": ["List of current strengths"],
            "weaknesses": ["List of concerns/weaknesses"],
            "form_assessment": "Current form analysis",
            "injury_impact": "Impact of injuries on performance"
        }}
    }},
    "prediction_analysis": {{
        "model_assessment": "Analysis of the AI model's prediction",
        "confidence_factors": ["Factors supporting the confidence level"],
        "risk_factors": ["Potential risks or uncertainties"],
        "value_assessment": "Assessment of betting value based on odds vs probability"
    }},
    "betting_recommendations": {{
        "primary_bet": "Main betting recommendation with reasoning",
        "alternative_bets": ["Alternative betting options"],
        "risk_level": "Low/Medium/High",
        "suggested_stake": "Conservative/Moderate/Aggressive"
    }},
    "final_verdict": "Concise final assessment and recommendation"
}}

Focus on providing actionable insights based on the real data provided. Be honest about uncertainties and explain your reasoning clearly."""
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are BetGenius AI, an expert football analyst. Provide comprehensive, data-driven analysis in JSON format. Be thorough but concise, and always base your analysis on the provided data."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000
            )
            
            analysis = json.loads(response.choices[0].message.content)
            
            # Add metadata
            analysis['metadata'] = {
                'model_used': self.model,
                'analysis_timestamp': match_data.get('collection_timestamp'),
                'data_sources': ['RapidAPI Football', 'Multiple Bookmakers', 'AI Analysis'],
                'confidence_calibrated': True
            }
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error in AI analysis: {e}")
            return {
                'error': 'Failed to generate AI analysis',
                'error_details': str(e),
                'fallback_analysis': self.generate_fallback_analysis(match_data, prediction_result)
            }
    
    def generate_fallback_analysis(self, match_data: Dict, prediction_result: Dict) -> Dict[str, Any]:
        """Generate basic analysis if AI fails"""
        
        home_team = match_data.get('home_team', {}).get('name', 'Home Team')
        away_team = match_data.get('away_team', {}).get('name', 'Away Team')
        prediction = prediction_result.get('prediction', 'draw')
        confidence = prediction_result.get('confidence', 0.5)
        
        return {
            'match_overview': f"Match between {home_team} and {away_team}",
            'prediction_summary': f"Model predicts {prediction} with {confidence:.1%} confidence",
            'key_factors': [
                'Recent team form',
                'Head-to-head record',
                'Current injuries',
                'Home advantage'
            ],
            'recommendation': 'Analysis based on quantitative model prediction',
            'note': 'Fallback analysis due to AI service unavailability'
        }
    
    def analyze_multisport_match(
        self,
        context: Dict,
        prediction_result: Dict,
        sport_key: str,
    ) -> Dict[str, Any]:
        sport_label = "basketball" if "basketball" in sport_key else "hockey"
        sport_upper = "NBA" if "basketball" in sport_key else "NHL"

        home_info = context.get("home_team", {})
        away_info = context.get("away_team", {})
        match = context.get("match_info", {})
        odds = context.get("odds", {})
        h2h = context.get("h2h", [])

        home_name = home_info.get("name", "Home")
        away_name = away_info.get("name", "Away")

        ctx = f"""
MATCH ANALYSIS REQUEST — {sport_upper}

=== BASIC MATCH INFORMATION ===
Match: {home_name} vs {away_name}
Date: {match.get('commence_time', 'Unknown')}
League: {match.get('league_name', sport_upper)}
Sport: {sport_label.title()}

=== HOME TEAM: {home_name} ===

Season Record:
"""
        hs = home_info.get("season_stats", {})
        ctx += f"  W-L: {hs.get('wins', '?')}-{hs.get('losses', '?')} ({hs.get('win_pct', 0):.3f})\n"
        ctx += f"  Home Record: {hs.get('home_record', 'N/A')}\n"
        ctx += f"  PPG: {hs.get('points_per_game', 0)} | PAPG: {hs.get('points_against_per_game', 0)}\n"
        ctx += f"  Streak: {hs.get('streak', 'N/A')} | Last 10: {hs.get('last_10', 'N/A')}\n"
        ctx += f"  Conference: {hs.get('conference', 'N/A')} | Playoff Position: {hs.get('playoff_position', 'N/A')}\n"

        rest_h = home_info.get("rest", {})
        ctx += f"  Rest Days: {rest_h.get('rest_days', 'N/A')} | Back-to-Back: {'YES' if rest_h.get('is_back_to_back') else 'No'}\n"

        ctx += "\nRecent Form (last games):\n"
        for i, g in enumerate(home_info.get("recent_form", [])[:5]):
            ctx += f"  {i+1}. vs {g.get('opponent', '?')} ({g.get('venue', '?')}) — {g.get('result', '?')} {g.get('score', '?')}\n"

        ctx += f"\n=== AWAY TEAM: {away_name} ===\n\nSeason Record:\n"
        aws = away_info.get("season_stats", {})
        ctx += f"  W-L: {aws.get('wins', '?')}-{aws.get('losses', '?')} ({aws.get('win_pct', 0):.3f})\n"
        ctx += f"  Away Record: {aws.get('away_record', 'N/A')}\n"
        ctx += f"  PPG: {aws.get('points_per_game', 0)} | PAPG: {aws.get('points_against_per_game', 0)}\n"
        ctx += f"  Streak: {aws.get('streak', 'N/A')} | Last 10: {aws.get('last_10', 'N/A')}\n"
        ctx += f"  Conference: {aws.get('conference', 'N/A')} | Playoff Position: {aws.get('playoff_position', 'N/A')}\n"

        rest_a = away_info.get("rest", {})
        ctx += f"  Rest Days: {rest_a.get('rest_days', 'N/A')} | Back-to-Back: {'YES' if rest_a.get('is_back_to_back') else 'No'}\n"

        ctx += "\nRecent Form (last games):\n"
        for i, g in enumerate(away_info.get("recent_form", [])[:5]):
            ctx += f"  {i+1}. vs {g.get('opponent', '?')} ({g.get('venue', '?')}) — {g.get('result', '?')} {g.get('score', '?')}\n"

        if h2h:
            ctx += f"\n=== HEAD-TO-HEAD (Last {len(h2h)} meetings) ===\n"
            for m in h2h:
                ctx += f"  {m.get('date', '?')}: {m.get('home_team', '?')} {m.get('score', '?')} {m.get('away_team', '?')} (Winner: {m.get('winner', '?')})\n"

        if odds:
            ctx += "\n=== CURRENT ODDS ===\n"
            ctx += f"  Moneyline: Home {odds.get('home_odds', 'N/A')} | Away {odds.get('away_odds', 'N/A')}\n"
            if odds.get("home_spread") is not None:
                ctx += f"  Spread: Home {odds['home_spread']:+.1f} ({odds.get('home_spread_odds', 'N/A')})\n"
            if odds.get("total_line") is not None:
                ctx += f"  Total: {odds['total_line']} (Over {odds.get('over_odds', 'N/A')} | Under {odds.get('under_odds', 'N/A')})\n"

        prob_h = prediction_result.get("prob_home", 0.5)
        prob_a = prediction_result.get("prob_away", 0.5)
        pick = prediction_result.get("pick", "?")
        conf = prediction_result.get("confidence", 0)

        pred_ctx = f"""
=== AI MODEL PREDICTION ===
Model Type: V3 Multisport LightGBM (46 features, 7 groups)
Home Win: {prob_h:.1%}
Away Win: {prob_a:.1%}
Predicted Outcome: {'Home' if pick == 'H' else 'Away'}
Confidence Level: {conf:.1%}
Features Used: {prediction_result.get('features_used', 0)} of {prediction_result.get('total_features', 46)}
"""

        prompt = f"""You are BetGenius AI, an expert {sport_label} analyst specializing in {sport_upper} predictions. Analyze this {sport_label} match comprehensively using the provided data.

{ctx}

{pred_ctx}

Provide a comprehensive analysis in JSON format:
{{
    "match_overview": "Brief overview of the match significance — include playoff implications, rivalry context, and rest/schedule factors",
    "key_factors": [
        "List 3-5 key factors. For {sport_label}, prioritize: rest/back-to-back impact, home court/ice advantage, recent form streaks, head-to-head history, and pace/scoring matchup"
    ],
    "team_analysis": {{
        "home_team": {{
            "strengths": ["Current strengths"],
            "weaknesses": ["Concerns or weaknesses"],
            "form_assessment": "Recent form analysis",
            "rest_impact": "Impact of rest days or back-to-back schedule"
        }},
        "away_team": {{
            "strengths": ["Current strengths"],
            "weaknesses": ["Concerns or weaknesses"],
            "form_assessment": "Recent form analysis",
            "rest_impact": "Impact of rest days or back-to-back schedule"
        }}
    }},
    "prediction_analysis": {{
        "model_assessment": "Analysis of the AI model's prediction",
        "confidence_factors": ["Factors supporting the confidence level"],
        "risk_factors": ["Potential risks or uncertainties"],
        "value_assessment": "Assessment of betting value — moneyline, spread ({odds.get('home_spread', 'N/A')}), and total ({odds.get('total_line', 'N/A')}) analysis"
    }},
    "betting_recommendations": {{
        "primary_bet": "Main recommendation with reasoning (moneyline, spread, or total)",
        "alternative_bets": ["Alternative options including spread and totals"],
        "risk_level": "Low/Medium/High",
        "suggested_stake": "Conservative/Moderate/Aggressive"
    }},
    "final_verdict": "Concise final assessment and recommendation"
}}

Focus on {sport_label}-specific factors: rest/back-to-back impact, home court/ice advantage, pace and scoring trends, playoff positioning. Be honest about uncertainties."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"You are BetGenius AI, an expert {sport_upper} analyst. Provide comprehensive, data-driven analysis in JSON format. Base your analysis on the provided data.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000,
            )

            analysis = json.loads(response.choices[0].message.content)
            analysis["metadata"] = {
                "model_used": self.model,
                "sport": sport_key,
                "data_sources": ["MultisportV3", "The Odds API", "AI Analysis"],
                "confidence_calibrated": True,
            }
            return analysis

        except Exception as e:
            logger.error(f"Multisport AI analysis error: {e}")
            return {
                "match_overview": f"{home_name} vs {away_name} — {sport_upper} match analysis",
                "key_factors": [
                    "Recent team form",
                    "Head-to-head record",
                    "Home advantage",
                    "Rest / schedule impact",
                ],
                "recommendation": "Analysis based on quantitative model prediction",
                "note": "Fallback analysis due to AI service unavailability",
            }

    def generate_match_summary(self, analysis: Dict, prediction: Dict) -> str:
        """Generate a concise match summary for display"""
        
        if 'error' in analysis:
            return f"Match prediction: {prediction.get('prediction', 'Unknown')} with {prediction.get('confidence', 0):.1%} confidence. Full analysis unavailable."
        
        summary = f"""
🎯 BETGENIUS AI PREDICTION

{analysis.get('match_overview', 'Match analysis')}

📊 PREDICTION: {prediction.get('prediction', 'Unknown').title()} ({prediction.get('confidence', 0):.1%} confidence)

🔍 KEY FACTORS:
{chr(10).join(['• ' + factor for factor in analysis.get('key_factors', [])[:3]])}

💡 RECOMMENDATION: {analysis.get('betting_recommendations', {}).get('primary_bet', 'See full analysis')}

⚡ VERDICT: {analysis.get('final_verdict', 'Based on comprehensive data analysis')}
"""
        return summary.strip()

def main():
    """Test the enhanced AI analyzer"""
    analyzer = EnhancedAIAnalyzer()
    
    # Test with sample data
    sample_match_data = {
        'match_details': {
            'fixture': {'date': '2024-01-15T15:00:00Z', 'venue': {'name': 'Old Trafford'}},
            'league': {'name': 'Premier League'}
        },
        'home_team': {
            'name': 'Manchester United',
            'recent_form': [
                {'opponent': 'Arsenal', 'venue': 'Home', 'result': 'W', 'score': '2-1'},
                {'opponent': 'Chelsea', 'venue': 'Away', 'result': 'D', 'score': '1-1'}
            ],
            'injuries': [
                {'player_name': 'Marcus Rashford', 'player_position': 'Forward', 'injury_type': 'Muscle injury'}
            ]
        },
        'away_team': {
            'name': 'Liverpool',
            'recent_form': [
                {'opponent': 'City', 'venue': 'Away', 'result': 'L', 'score': '0-2'},
                {'opponent': 'Brighton', 'venue': 'Home', 'result': 'W', 'score': '3-0'}
            ],
            'injuries': []
        }
    }
    
    sample_prediction = {
        'probabilities': {'home': 0.45, 'draw': 0.30, 'away': 0.25},
        'prediction': 'home',
        'confidence': 0.72
    }
    
    analysis = analyzer.analyze_match_comprehensive(sample_match_data, sample_prediction)
    print(json.dumps(analysis, indent=2))

if __name__ == "__main__":
    main()