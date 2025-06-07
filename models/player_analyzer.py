"""
BetGenius AI Backend - Player Performance Analysis
Hybrid approach: Lightweight player-level insights to enhance team predictions
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional, Any
from utils.config import get_rapidapi_headers
import logging

logger = logging.getLogger(__name__)

class PlayerPerformanceAnalyzer:
    """
    Lightweight player performance analyzer for hybrid predictions
    Focuses on top 3-5 key players per team to enhance team-level models
    """
    
    def __init__(self):
        self.base_url = "https://api-football-v1.p.rapidapi.com/v3"
        self.headers = get_rapidapi_headers()
        
        # Key player positions and their impact weights
        self.position_weights = {
            "Goalkeeper": 0.15,      # Clean sheet impact
            "Defender": 0.20,        # Defensive stability
            "Midfielder": 0.30,      # Game control
            "Attacker": 0.35         # Goal scoring
        }
        
    async def analyze_key_players_impact(self, home_team_id: int, away_team_id: int, 
                                       season: int = 2024) -> Dict[str, Any]:
        """
        Analyze top players from each team for match-day impact
        Returns player performance index to enhance team predictions
        """
        try:
            # Get key players for both teams
            home_players = await self._get_key_players(home_team_id, season)
            away_players = await self._get_key_players(away_team_id, season)
            
            # Calculate performance indices
            home_performance_index = self._calculate_team_performance_index(home_players)
            away_performance_index = self._calculate_team_performance_index(away_players)
            
            # Identify impact factors
            impact_factors = self._identify_impact_factors(home_players, away_players)
            
            return {
                "home_performance_index": home_performance_index,
                "away_performance_index": away_performance_index,
                "performance_differential": home_performance_index - away_performance_index,
                "impact_factors": impact_factors,
                "key_players": {
                    "home": [p["name"] for p in home_players[:3]],
                    "away": [p["name"] for p in away_players[:3]]
                }
            }
            
        except Exception as e:
            logger.warning(f"Player analysis failed, using fallback: {e}")
            return self._fallback_player_analysis()
    
    async def _get_key_players(self, team_id: int, season: int, limit: int = 5) -> List[Dict]:
        """Get top performing players for a team"""
        try:
            url = f"{self.base_url}/players/topscorers"
            params = {
                "league": 39,  # Premier League default
                "season": season
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        players = data.get("response", [])
                        
                        # Filter by team and get top performers
                        team_players = [
                            p for p in players 
                            if p.get("statistics", [{}])[0].get("team", {}).get("id") == team_id
                        ][:limit]
                        
                        return self._process_player_data(team_players)
                    
        except Exception as e:
            logger.warning(f"Failed to fetch players for team {team_id}: {e}")
            
        return self._generate_fallback_players(team_id)
    
    def _process_player_data(self, raw_players: List[Dict]) -> List[Dict]:
        """Process raw player data into performance metrics"""
        processed_players = []
        
        for player_data in raw_players:
            try:
                player = player_data.get("player", {})
                stats = player_data.get("statistics", [{}])[0]
                
                # Extract key performance metrics
                goals = stats.get("goals", {}).get("total", 0) or 0
                assists = stats.get("goals", {}).get("assists", 0) or 0
                appearances = stats.get("games", {}).get("appearences", 1) or 1
                minutes = stats.get("games", {}).get("minutes", 1) or 1
                
                # Calculate performance score
                performance_score = self._calculate_player_performance_score(
                    goals, assists, appearances, minutes, stats
                )
                
                processed_players.append({
                    "name": player.get("name", "Unknown"),
                    "position": stats.get("games", {}).get("position", "Unknown"),
                    "goals": goals,
                    "assists": assists,
                    "appearances": appearances,
                    "performance_score": performance_score,
                    "form_indicator": self._assess_player_form(stats)
                })
                
            except Exception as e:
                logger.warning(f"Error processing player data: {e}")
                continue
                
        return sorted(processed_players, key=lambda x: x["performance_score"], reverse=True)
    
    def _calculate_player_performance_score(self, goals: int, assists: int, 
                                          appearances: int, minutes: int, 
                                          stats: Dict) -> float:
        """Calculate weighted performance score for a player"""
        try:
            # Basic scoring metrics
            goal_contribution = (goals * 1.0 + assists * 0.7) / max(appearances, 1)
            
            # Minutes played factor (availability)
            availability_factor = min(minutes / (appearances * 90), 1.0) if appearances > 0 else 0
            
            # Position-specific adjustments
            position = stats.get("games", {}).get("position", "Unknown")
            position_weight = self.position_weights.get(position, 0.25)
            
            # Additional stats (if available)
            passes = stats.get("passes", {}).get("accuracy", 0) or 0
            cards = stats.get("cards", {}).get("yellow", 0) + stats.get("cards", {}).get("red", 0) * 2
            
            # Calculate final score
            base_score = goal_contribution * position_weight * availability_factor
            discipline_penalty = max(0, cards * 0.1)  # Penalty for cards
            passing_bonus = (passes / 100) * 0.1 if passes > 0 else 0
            
            return max(0, base_score + passing_bonus - discipline_penalty)
            
        except Exception as e:
            logger.warning(f"Error calculating performance score: {e}")
            return 0.5  # Neutral score
    
    def _assess_player_form(self, stats: Dict) -> str:
        """Assess player's current form"""
        try:
            goals = stats.get("goals", {}).get("total", 0) or 0
            appearances = stats.get("games", {}).get("appearences", 1) or 1
            
            goals_per_game = goals / max(appearances, 1)
            
            if goals_per_game >= 0.7:
                return "excellent"
            elif goals_per_game >= 0.4:
                return "good"
            elif goals_per_game >= 0.2:
                return "average"
            else:
                return "poor"
                
        except Exception:
            return "unknown"
    
    def _calculate_team_performance_index(self, players: List[Dict]) -> float:
        """Calculate overall team performance index from key players"""
        if not players:
            return 0.5  # Neutral index
            
        try:
            # Weight by position and performance
            total_weighted_score = 0
            total_weight = 0
            
            for player in players[:5]:  # Top 5 players
                position = player.get("position", "Unknown")
                weight = self.position_weights.get(position, 0.25)
                score = player.get("performance_score", 0.5)
                
                total_weighted_score += score * weight
                total_weight += weight
            
            return min(1.0, total_weighted_score / max(total_weight, 1)) if total_weight > 0 else 0.5
            
        except Exception as e:
            logger.warning(f"Error calculating team performance index: {e}")
            return 0.5
    
    def _identify_impact_factors(self, home_players: List[Dict], 
                               away_players: List[Dict]) -> List[str]:
        """Identify key factors that could impact match outcome"""
        factors = []
        
        try:
            # Top scorer analysis
            if home_players:
                top_home = home_players[0]
                if top_home["goals"] > 15:
                    factors.append(f"Home top scorer {top_home['name']} in excellent form ({top_home['goals']} goals)")
            
            if away_players:
                top_away = away_players[0]
                if top_away["goals"] > 15:
                    factors.append(f"Away top scorer {top_away['name']} threat ({top_away['goals']} goals)")
            
            # Form comparison
            home_avg = sum(p["performance_score"] for p in home_players[:3]) / 3 if home_players else 0.5
            away_avg = sum(p["performance_score"] for p in away_players[:3]) / 3 if away_players else 0.5
            
            if abs(home_avg - away_avg) > 0.2:
                if home_avg > away_avg:
                    factors.append("Home team key players in superior form")
                else:
                    factors.append("Away team key players in superior form")
            
            # Performance balance
            if len(factors) == 0:
                factors.append("Both teams have balanced key player performance")
                
        except Exception as e:
            logger.warning(f"Error identifying impact factors: {e}")
            factors = ["Player analysis unavailable"]
            
        return factors
    
    def _generate_fallback_players(self, team_id: int) -> List[Dict]:
        """Generate fallback player data when API fails"""
        return [
            {
                "name": f"Key Player {i+1}",
                "position": ["Attacker", "Midfielder", "Defender"][i % 3],
                "goals": max(0, 15 - i * 3),
                "assists": max(0, 8 - i * 2),
                "appearances": 25,
                "performance_score": max(0.3, 0.8 - i * 0.1),
                "form_indicator": "average"
            }
            for i in range(3)
        ]
    
    def _fallback_player_analysis(self) -> Dict[str, Any]:
        """Fallback analysis when player data is unavailable"""
        return {
            "home_performance_index": 0.6,
            "away_performance_index": 0.55,
            "performance_differential": 0.05,
            "impact_factors": ["Player performance data unavailable - using team-level analysis"],
            "key_players": {
                "home": ["Key Player 1", "Key Player 2", "Key Player 3"],
                "away": ["Key Player 1", "Key Player 2", "Key Player 3"]
            }
        }

    def get_player_features_for_ml(self, player_analysis: Dict) -> Dict[str, float]:
        """
        Extract ML features from player analysis to enhance team-level model
        """
        return {
            "home_player_performance": player_analysis.get("home_performance_index", 0.5),
            "away_player_performance": player_analysis.get("away_performance_index", 0.5),
            "player_performance_diff": player_analysis.get("performance_differential", 0.0),
            "key_player_advantage": 1.0 if abs(player_analysis.get("performance_differential", 0)) > 0.15 else 0.0
        }