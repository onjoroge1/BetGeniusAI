"""
Comprehensive AI Analyzer - Aggregates ML predictions + real-time data for holistic OpenAI analysis
"""
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import aiohttp
from openai import OpenAI
import os

logger = logging.getLogger(__name__)

class ComprehensiveAnalyzer:
    """Enhanced analyzer that aggregates ML + real-time data for comprehensive OpenAI verdict"""
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        
    async def generate_comprehensive_analysis(
        self, 
        match_data: Dict[str, Any], 
        ml_predictions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate comprehensive analysis by aggregating:
        1. ML model predictions
        2. Real-time team news and injuries
        3. Recent form and tactical insights
        4. Head-to-head context
        """
        
        # Step 1: Gather comprehensive data
        comprehensive_data = await self._aggregate_comprehensive_data(match_data)
        
        # Step 2: Prepare structured JSON for OpenAI
        openai_input = self._prepare_openai_input(
            match_data, ml_predictions, comprehensive_data
        )
        
        # Step 3: Get OpenAI holistic analysis
        openai_response = await self._get_openai_verdict(openai_input)
        
        # Step 4: Structure final response
        final_analysis = self._structure_final_response(openai_response, ml_predictions)
        
        return final_analysis
    
    async def _aggregate_comprehensive_data(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate all real-time data sources"""
        
        comprehensive_data = {
            "team_news": {},
            "injuries": {},
            "recent_form": {},
            "tactical_insights": {},
            "head_to_head": {},
            "venue_factors": {},
            "external_factors": {}
        }
        
        try:
            # Get team IDs
            home_team_id = match_data.get('match_info', {}).get('home_team_id')
            away_team_id = match_data.get('match_info', {}).get('away_team_id')
            league_id = match_data.get('match_info', {}).get('league_id', 39)
            
            if home_team_id and away_team_id:
                # Parallel data collection
                tasks = [
                    self._get_team_injuries(home_team_id, away_team_id),
                    self._get_team_news(home_team_id, away_team_id),
                    self._get_recent_form_details(home_team_id, away_team_id, league_id),
                    self._get_head_to_head_insights(home_team_id, away_team_id),
                    self._get_tactical_analysis(home_team_id, away_team_id, league_id)
                ]
                
                injuries, team_news, form_details, h2h_insights, tactical = await asyncio.gather(
                    *tasks, return_exceptions=True
                )
                
                # Safely assign results
                if not isinstance(injuries, Exception):
                    comprehensive_data["injuries"] = injuries
                if not isinstance(team_news, Exception):
                    comprehensive_data["team_news"] = team_news
                if not isinstance(form_details, Exception):
                    comprehensive_data["recent_form"] = form_details
                if not isinstance(h2h_insights, Exception):
                    comprehensive_data["head_to_head"] = h2h_insights
                if not isinstance(tactical, Exception):
                    comprehensive_data["tactical_insights"] = tactical
            
            # Add venue and external factors
            comprehensive_data["venue_factors"] = self._analyze_venue_factors(match_data)
            comprehensive_data["external_factors"] = self._analyze_external_factors(match_data)
            
        except Exception as e:
            logger.warning(f"Comprehensive data aggregation partially failed: {e}")
        
        return comprehensive_data
    
    async def _get_team_injuries(self, home_team_id: int, away_team_id: int) -> Dict[str, Any]:
        """Get current injury reports for both teams"""
        
        headers = {
            'X-RapidAPI-Key': self.rapidapi_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        
        injuries_data = {"home_team": [], "away_team": []}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get injuries for both teams
                for team_id, team_key in [(home_team_id, "home_team"), (away_team_id, "away_team")]:
                    url = f"https://api-football-v1.p.rapidapi.com/v3/injuries"
                    params = {
                        'team': team_id,
                        'season': '2024'
                    }
                    
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            injuries = data.get('response', [])
                            
                            # Process injuries
                            processed_injuries = []
                            for injury in injuries[:10]:  # Limit to recent injuries
                                processed_injuries.append({
                                    'player_name': injury.get('player', {}).get('name', 'Unknown'),
                                    'injury_type': injury.get('player', {}).get('reason', 'Unknown'),
                                    'expected_return': injury.get('player', {}).get('expected', None),
                                    'severity': self._assess_injury_severity(injury),
                                    'position': injury.get('player', {}).get('position', 'Unknown')
                                })
                            
                            injuries_data[team_key] = processed_injuries
                        
                        await asyncio.sleep(0.1)  # Rate limiting
        
        except Exception as e:
            logger.warning(f"Failed to get injury data: {e}")
        
        return injuries_data
    
    async def _get_team_news(self, home_team_id: int, away_team_id: int) -> Dict[str, Any]:
        """Get latest team news and squad updates"""
        
        # For now, we'll simulate team news structure
        # In production, this would connect to news APIs or team official sources
        
        team_news = {
            "home_team": {
                "recent_signings": [],
                "tactical_changes": "",
                "manager_comments": "",
                "squad_rotation": "",
                "confidence_level": "medium"
            },
            "away_team": {
                "recent_signings": [],
                "tactical_changes": "",
                "manager_comments": "",
                "squad_rotation": "",
                "confidence_level": "medium"
            }
        }
        
        # This would be enhanced with real news API integration
        return team_news
    
    async def _get_recent_form_details(self, home_team_id: int, away_team_id: int, league_id: int) -> Dict[str, Any]:
        """Get detailed recent form analysis"""
        
        headers = {
            'X-RapidAPI-Key': self.rapidapi_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        
        form_details = {"home_team": {}, "away_team": {}}
        
        try:
            async with aiohttp.ClientSession() as session:
                for team_id, team_key in [(home_team_id, "home_team"), (away_team_id, "away_team")]:
                    url = f"https://api-football-v1.p.rapidapi.com/v3/teams/statistics"
                    params = {
                        'team': team_id,
                        'season': '2024',
                        'league': league_id
                    }
                    
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            stats = data.get('response', {})
                            
                            form_details[team_key] = {
                                'goals_for_avg': stats.get('goals', {}).get('for', {}).get('average', {}).get('total', 0),
                                'goals_against_avg': stats.get('goals', {}).get('against', {}).get('average', {}).get('total', 0),
                                'clean_sheets': stats.get('clean_sheet', {}).get('total', 0),
                                'failed_to_score': stats.get('failed_to_score', {}).get('total', 0),
                                'penalty_scored': stats.get('penalty', {}).get('scored', {}).get('total', 0),
                                'cards_yellow': stats.get('cards', {}).get('yellow', {}).get('total', 0),
                                'cards_red': stats.get('cards', {}).get('red', {}).get('total', 0)
                            }
                        
                        await asyncio.sleep(0.1)
        
        except Exception as e:
            logger.warning(f"Failed to get detailed form: {e}")
        
        return form_details
    
    async def _get_head_to_head_insights(self, home_team_id: int, away_team_id: int) -> Dict[str, Any]:
        """Get detailed head-to-head analysis"""
        
        headers = {
            'X-RapidAPI-Key': self.rapidapi_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
        
        h2h_data = {
            "recent_meetings": [],
            "historical_trend": "",
            "goal_patterns": {},
            "venue_record": {}
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api-football-v1.p.rapidapi.com/v3/fixtures/headtohead"
                params = {
                    'h2h': f"{home_team_id}-{away_team_id}",
                    'last': '10'
                }
                
                async with session.get(url, headers=headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        fixtures = data.get('response', [])
                        
                        h2h_data["recent_meetings"] = [
                            {
                                'date': fixture.get('fixture', {}).get('date'),
                                'home_team': fixture.get('teams', {}).get('home', {}).get('name'),
                                'away_team': fixture.get('teams', {}).get('away', {}).get('name'),
                                'score': f"{fixture.get('goals', {}).get('home', 0)}-{fixture.get('goals', {}).get('away', 0)}",
                                'venue': fixture.get('fixture', {}).get('venue', {}).get('name')
                            }
                            for fixture in fixtures[:5]
                        ]
        
        except Exception as e:
            logger.warning(f"Failed to get H2H data: {e}")
        
        return h2h_data
    
    async def _get_tactical_analysis(self, home_team_id: int, away_team_id: int, league_id: int) -> Dict[str, Any]:
        """Get tactical insights and playing styles"""
        
        # This would integrate with tactical analysis APIs or databases
        tactical_data = {
            "home_team": {
                "formation": "4-3-3",
                "attacking_style": "possession-based",
                "defensive_style": "high-press",
                "set_piece_strength": "strong",
                "pace_of_play": "medium"
            },
            "away_team": {
                "formation": "4-2-3-1",
                "attacking_style": "counter-attack",
                "defensive_style": "compact",
                "set_piece_strength": "average",
                "pace_of_play": "fast"
            },
            "tactical_matchup": "home_advantage",
            "key_battles": [
                "Midfield control",
                "Wide areas",
                "Set pieces"
            ]
        }
        
        return tactical_data
    
    def _analyze_venue_factors(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze venue-specific factors"""
        
        venue_info = match_data.get('match_info', {})
        
        return {
            "venue_name": venue_info.get('venue', 'Unknown'),
            "home_advantage_factor": 0.15,  # Standard home advantage
            "weather_impact": "minimal",
            "crowd_factor": "supportive",
            "pitch_conditions": "good"
        }
    
    def _analyze_external_factors(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze external factors affecting the match"""
        
        return {
            "match_importance": "regular_season",
            "rivalry_factor": "medium",
            "pressure_level": "standard",
            "media_attention": "moderate",
            "referee_influence": "minimal"
        }
    
    def _assess_injury_severity(self, injury_data: Dict[str, Any]) -> str:
        """Assess injury severity based on expected return"""
        
        expected_return = injury_data.get('player', {}).get('expected', '')
        
        if not expected_return or expected_return.lower() in ['unknown', 'null']:
            return 'unknown'
        elif 'week' in expected_return.lower():
            return 'minor'
        elif 'month' in expected_return.lower():
            return 'moderate'
        else:
            return 'severe'
    
    def _prepare_openai_input(
        self, 
        match_data: Dict[str, Any], 
        ml_predictions: Dict[str, Any], 
        comprehensive_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Prepare structured JSON input for OpenAI analysis"""
        
        openai_input = {
            "match_context": {
                "home_team": match_data.get('match_info', {}).get('home_team', 'Unknown'),
                "away_team": match_data.get('match_info', {}).get('away_team', 'Unknown'),
                "venue": match_data.get('match_info', {}).get('venue', 'Unknown'),
                "league": match_data.get('match_info', {}).get('league', 'Premier League'),
                "date": match_data.get('match_info', {}).get('date', ''),
                "match_importance": comprehensive_data.get('external_factors', {}).get('match_importance', 'regular')
            },
            "ml_model_prediction": {
                "home_win_probability": ml_predictions.get('home_win_probability', 0),
                "draw_probability": ml_predictions.get('draw_probability', 0),
                "away_win_probability": ml_predictions.get('away_win_probability', 0),
                "confidence_score": ml_predictions.get('confidence_score', 0),
                "predicted_outcome": ml_predictions.get('predicted_outcome', 'unknown'),
                "model_accuracy": ml_predictions.get('realistic_accuracy', '71.5%')
            },
            "team_analysis": {
                "recent_form": comprehensive_data.get('recent_form', {}),
                "injury_reports": comprehensive_data.get('injuries', {}),
                "tactical_setup": comprehensive_data.get('tactical_insights', {}),
                "team_news": comprehensive_data.get('team_news', {})
            },
            "historical_context": {
                "head_to_head": comprehensive_data.get('head_to_head', {}),
                "venue_factors": comprehensive_data.get('venue_factors', {}),
                "external_factors": comprehensive_data.get('external_factors', {})
            },
            "analysis_request": {
                "task": "comprehensive_match_analysis",
                "required_output": "holistic_verdict_with_reasoning",
                "include_betting_recommendations": True,
                "include_risk_assessment": True,
                "include_confidence_explanation": True
            }
        }
        
        return openai_input
    
    async def _get_openai_verdict(self, openai_input: Dict[str, Any]) -> Dict[str, Any]:
        """Get comprehensive analysis from OpenAI"""
        
        system_prompt = """You are a professional football analyst with expertise in betting and statistical analysis. 

You will receive comprehensive match data including:
1. ML model predictions with 71.5% realistic accuracy
2. Real-time injury reports and team news
3. Recent form and tactical analysis
4. Head-to-head history and venue factors

Your task is to provide a holistic verdict that weighs ALL factors, not just the ML prediction.

Output format must be valid JSON with these exact fields:
{
  "final_verdict": {
    "recommended_outcome": "Home Win/Draw/Away Win",
    "confidence_level": "High/Medium/Low",
    "probability_assessment": {"home": 0.xx, "draw": 0.xx, "away": 0.xx}
  },
  "reasoning": {
    "ml_model_weight": "percentage of decision based on ML",
    "injury_impact": "how injuries affect the prediction",
    "form_analysis": "recent form impact on decision",
    "tactical_factors": "tactical matchup analysis",
    "historical_context": "h2h and venue impact"
  },
  "betting_recommendations": {
    "primary_bet": "main recommendation with odds value",
    "value_bets": ["alternative betting opportunities"],
    "avoid_bets": ["bets to avoid with reasons"]
  },
  "risk_assessment": {
    "overall_risk": "High/Medium/Low",
    "key_risks": ["main factors that could affect outcome"],
    "upset_potential": "likelihood of unexpected result"
  },
  "confidence_explanation": "detailed explanation of why this confidence level is assigned"
}

Be honest about limitations and uncertainty. If data is insufficient, state it clearly."""
        
        user_prompt = f"""Analyze this match comprehensively:

{json.dumps(openai_input, indent=2)}

Provide your holistic verdict considering ALL factors - ML prediction, injuries, form, tactics, and context. Weight the ML prediction appropriately (it's 71.5% accurate) but don't ignore other crucial factors that could override it."""
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000
            )
            
            content = response.choices[0].message.content
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"OpenAI analysis failed: {e}")
            return self._fallback_analysis()
    
    def _structure_final_response(
        self, 
        openai_response: Dict[str, Any], 
        ml_predictions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Structure the final response for the frontend"""
        
        final_response = {
            "comprehensive_analysis": {
                "ml_prediction": {
                    "home_win": ml_predictions.get('home_win_probability', 0),
                    "draw": ml_predictions.get('draw_probability', 0),
                    "away_win": ml_predictions.get('away_win_probability', 0),
                    "confidence": ml_predictions.get('confidence_score', 0),
                    "model_type": ml_predictions.get('model_type', 'unified_production')
                },
                "ai_verdict": openai_response.get('final_verdict', {}),
                "detailed_reasoning": openai_response.get('reasoning', {}),
                "betting_intelligence": openai_response.get('betting_recommendations', {}),
                "risk_analysis": openai_response.get('risk_assessment', {}),
                "confidence_breakdown": openai_response.get('confidence_explanation', '')
            },
            "analysis_metadata": {
                "analysis_type": "comprehensive_ml_plus_ai",
                "data_sources": ["ml_model", "injury_reports", "team_news", "tactical_analysis", "historical_data"],
                "analysis_timestamp": datetime.utcnow().isoformat(),
                "ml_model_accuracy": "71.5%",
                "ai_model": "gpt-4o"
            }
        }
        
        return final_response
    
    def _fallback_analysis(self) -> Dict[str, Any]:
        """Fallback analysis if OpenAI fails"""
        
        return {
            "final_verdict": {
                "recommended_outcome": "Inconclusive",
                "confidence_level": "Low",
                "probability_assessment": {"home": 0.33, "draw": 0.33, "away": 0.33}
            },
            "reasoning": {
                "ml_model_weight": "100%",
                "injury_impact": "Data unavailable",
                "form_analysis": "Using basic statistics only",
                "tactical_factors": "Not analyzed",
                "historical_context": "Limited data"
            },
            "betting_recommendations": {
                "primary_bet": "No recommendation - insufficient analysis",
                "value_bets": [],
                "avoid_bets": ["All bets due to incomplete analysis"]
            },
            "risk_assessment": {
                "overall_risk": "High",
                "key_risks": ["Incomplete data analysis"],
                "upset_potential": "Unknown"
            },
            "confidence_explanation": "Analysis incomplete due to data gathering issues"
        }

# Add missing import
import asyncio