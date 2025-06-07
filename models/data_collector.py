"""
BetGenius AI Backend - Sports Data Collection
Collects real football data from RapidAPI and processes it for ML
"""

import aiohttp
import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from utils.config import settings, get_rapidapi_headers
from models.player_analyzer import PlayerPerformanceAnalyzer

logger = logging.getLogger(__name__)

class SportsDataCollector:
    """Collects and processes sports data from RapidAPI Football API"""
    
    def __init__(self):
        self.base_url = settings.RAPIDAPI_FOOTBALL_URL
        self.headers = get_rapidapi_headers()
        self.cache = {}  # Simple in-memory cache
        self.player_analyzer = PlayerPerformanceAnalyzer()
        
    async def get_match_data(self, match_id: int) -> Optional[Dict[str, Any]]:
        """
        Collect comprehensive match data for prediction
        Returns processed data ready for ML models
        """
        try:
            logger.info(f"Collecting data for match {match_id}")
            
            # Get match details first
            match_details = await self._get_match_details(match_id)
            if not match_details:
                logger.error(f"No match details found for {match_id}")
                return None
                
            home_team_id = match_details['teams']['home']['id']
            away_team_id = match_details['teams']['away']['id']
            
            # Collect all required data concurrently
            tasks = [
                self._get_team_statistics(home_team_id),
                self._get_team_statistics(away_team_id),
                self._get_team_form(home_team_id, 10),
                self._get_team_form(away_team_id, 10),
                self._get_head_to_head(home_team_id, away_team_id, 10),
                self._get_team_injuries(home_team_id),
                self._get_team_injuries(away_team_id)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle any failed requests
            home_stats, away_stats, home_form, away_form, h2h_data, home_injuries, away_injuries = results
            
            # Replace exceptions with empty data
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Task {i} failed: {result}")
                    results[i] = {} if i < 2 else []
                    
            # Unpack results with proper typing
            home_stats, away_stats, home_form, away_form, h2h_data, home_injuries, away_injuries = results
            
            # Get player performance analysis (hybrid approach)
            try:
                player_analysis = await self.player_analyzer.analyze_key_players_impact(
                    home_team_id, away_team_id
                )
            except Exception as e:
                logger.warning(f"Player analysis failed: {e}")
                player_analysis = self.player_analyzer._fallback_player_analysis()
            
            # Process into structured format
            processed_data = {
                'match_info': {
                    'match_id': match_id,
                    'home_team': match_details['teams']['home']['name'],
                    'away_team': match_details['teams']['away']['name'],
                    'venue': match_details['fixture']['venue']['name'],
                    'date': match_details['fixture']['date'],
                    'league': match_details.get('league', {}).get('name', 'Premier League'),
                    'round': match_details.get('league', {}).get('round', 'Regular Season')
                },
                'features': self._extract_ml_features(
                    home_stats if not isinstance(home_stats, Exception) else {},
                    away_stats if not isinstance(away_stats, Exception) else {},
                    home_form if not isinstance(home_form, Exception) else [],
                    away_form if not isinstance(away_form, Exception) else [],
                    h2h_data if not isinstance(h2h_data, Exception) else [],
                    home_injuries if not isinstance(home_injuries, Exception) else [],
                    away_injuries if not isinstance(away_injuries, Exception) else [],
                    player_analysis
                ),
                'raw_data': {
                    'match_details': match_details,
                    'home_stats': home_stats,
                    'away_stats': away_stats,
                    'home_form': home_form,
                    'away_form': away_form,
                    'h2h_data': h2h_data,
                    'home_injuries': home_injuries,
                    'away_injuries': away_injuries,
                    'player_analysis': player_analysis
                }
            }
            
            return processed_data
            
        except Exception as e:
            logger.error(f"Failed to collect match data for {match_id}: {e}")
            return None
    
    async def get_upcoming_matches(self, league_id: int = 39, limit: int = 10) -> List[Dict]:
        """Get upcoming matches for a league"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {
                "league": league_id,
                "season": 2024,
                "next": limit,
                "status": "NS"  # Not Started
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('response', [])
                    else:
                        logger.error(f"API request failed: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Failed to get upcoming matches: {e}")
            return []
    
    async def _get_match_details(self, match_id: int) -> Optional[Dict]:
        """Get specific match details"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {"id": match_id}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        fixtures = data.get('response', [])
                        return fixtures[0] if fixtures else None
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to get match details for {match_id}: {e}")
            return None
    
    async def _get_team_statistics(self, team_id: int, season: int = 2024) -> Dict:
        """Get comprehensive team statistics"""
        try:
            url = f"{self.base_url}/teams/statistics"
            params = {
                "league": 39,  # Premier League
                "season": season,
                "team": team_id
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('response', {})
                    return {}
                    
        except Exception as e:
            logger.error(f"Failed to get team statistics for {team_id}: {e}")
            return {}
    
    async def _get_team_form(self, team_id: int, last_games: int = 10) -> List[Dict]:
        """Get team's recent form"""
        try:
            url = f"{self.base_url}/fixtures"
            params = {
                "team": team_id,
                "last": last_games,
                "status": "FT"  # Full Time
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('response', [])
                    return []
                    
        except Exception as e:
            logger.error(f"Failed to get team form for {team_id}: {e}")
            return []
    
    async def _get_head_to_head(self, team1_id: int, team2_id: int, last_games: int = 10) -> List[Dict]:
        """Get head-to-head history"""
        try:
            url = f"{self.base_url}/fixtures/headtohead"
            params = {
                "h2h": f"{team1_id}-{team2_id}",
                "last": last_games
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('response', [])
                    return []
                    
        except Exception as e:
            logger.error(f"Failed to get H2H for {team1_id} vs {team2_id}: {e}")
            return []
    
    async def _get_team_injuries(self, team_id: int) -> List[Dict]:
        """Get team injury list"""
        try:
            url = f"{self.base_url}/injuries"
            params = {
                "team": team_id,
                "season": 2024
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('response', [])
                    return []
                    
        except Exception as e:
            logger.error(f"Failed to get injuries for {team_id}: {e}")
            return []
    
    def _extract_ml_features(self, home_stats: Dict, away_stats: Dict, 
                           home_form: List, away_form: List, h2h_data: List,
                           home_injuries: List, away_injuries: List, 
                           player_analysis: Dict = None) -> Dict:
        """Extract ML features from raw data"""
        
        features = {}
        
        try:
            # Team strength features
            features['home_goals_per_game'] = self._safe_get(home_stats, ['goals', 'for', 'average', 'home'], 0.0)
            features['away_goals_per_game'] = self._safe_get(away_stats, ['goals', 'for', 'average', 'away'], 0.0)
            features['home_goals_against_per_game'] = self._safe_get(home_stats, ['goals', 'against', 'average', 'home'], 0.0)
            features['away_goals_against_per_game'] = self._safe_get(away_stats, ['goals', 'against', 'average', 'away'], 0.0)
            
            # Win percentages
            features['home_win_percentage'] = self._safe_get(home_stats, ['fixtures', 'wins', 'home'], 0) / max(1, self._safe_get(home_stats, ['fixtures', 'played', 'home'], 1))
            features['away_win_percentage'] = self._safe_get(away_stats, ['fixtures', 'wins', 'away'], 0) / max(1, self._safe_get(away_stats, ['fixtures', 'played', 'away'], 1))
            
            # Form features (last 5 games)
            features['home_form_points'] = self._calculate_form_points(home_form[:5])
            features['away_form_points'] = self._calculate_form_points(away_form[:5])
            features['home_goals_last_5'] = self._calculate_recent_goals(home_form[:5], 'home')
            features['away_goals_last_5'] = self._calculate_recent_goals(away_form[:5], 'away')
            
            # Head-to-head features
            features['h2h_home_wins'] = self._count_h2h_wins(h2h_data, home_stats.get('team', {}).get('id'))
            features['h2h_away_wins'] = self._count_h2h_wins(h2h_data, away_stats.get('team', {}).get('id'))
            features['h2h_avg_goals'] = self._calculate_h2h_avg_goals(h2h_data)
            
            # Injury impact
            features['home_key_injuries'] = len([inj for inj in home_injuries if inj.get('type') == 'Missing'])
            features['away_key_injuries'] = len([inj for inj in away_injuries if inj.get('type') == 'Missing'])
            
            # Derived features
            features['goal_difference_home'] = features['home_goals_per_game'] - features['home_goals_against_per_game']
            features['goal_difference_away'] = features['away_goals_per_game'] - features['away_goals_against_per_game']
            features['form_difference'] = features['home_form_points'] - features['away_form_points']
            features['strength_difference'] = features['home_win_percentage'] - features['away_win_percentage']
            
            # Context features
            features['total_goals_tendency'] = (features['home_goals_per_game'] + features['away_goals_per_game'] + 
                                               features['home_goals_against_per_game'] + features['away_goals_against_per_game']) / 2
            
        except Exception as e:
            logger.error(f"Error extracting features: {e}")
            # Return minimal feature set on error
            features = {key: 0.0 for key in [
                'home_goals_per_game', 'away_goals_per_game', 'home_goals_against_per_game', 
                'away_goals_against_per_game', 'home_win_percentage', 'away_win_percentage',
                'home_form_points', 'away_form_points', 'goal_difference_home', 'goal_difference_away'
            ]}
        
        return features
    
    def _safe_get(self, data: Dict, keys: List[str], default: Any) -> Any:
        """Safely get nested dictionary value"""
        try:
            result = data
            for key in keys:
                result = result[key]
            return float(result) if isinstance(result, (int, float, str)) else default
        except (KeyError, TypeError, ValueError):
            return default
    
    def _calculate_form_points(self, recent_matches: List) -> int:
        """Calculate points from recent form (3 for win, 1 for draw, 0 for loss)"""
        points = 0
        for match in recent_matches:
            try:
                home_goals = match.get('goals', {}).get('home', 0)
                away_goals = match.get('goals', {}).get('away', 0)
                
                if home_goals > away_goals:
                    points += 3  # Win
                elif home_goals == away_goals:
                    points += 1  # Draw
                # Loss = 0 points
                    
            except (KeyError, TypeError):
                continue
                
        return points
    
    def _calculate_recent_goals(self, recent_matches: List, venue: str) -> float:
        """Calculate average goals in recent matches"""
        total_goals = 0
        valid_matches = 0
        
        for match in recent_matches:
            try:
                if venue == 'home':
                    goals = match.get('goals', {}).get('home', 0)
                else:
                    goals = match.get('goals', {}).get('away', 0)
                    
                total_goals += goals
                valid_matches += 1
                
            except (KeyError, TypeError):
                continue
                
        return total_goals / max(1, valid_matches)
    
    def _count_h2h_wins(self, h2h_data: List, team_id: int) -> int:
        """Count wins in head-to-head matches"""
        wins = 0
        for match in h2h_data:
            try:
                home_team_id = match.get('teams', {}).get('home', {}).get('id')
                away_team_id = match.get('teams', {}).get('away', {}).get('id')
                home_goals = match.get('goals', {}).get('home', 0)
                away_goals = match.get('goals', {}).get('away', 0)
                
                if team_id == home_team_id and home_goals > away_goals:
                    wins += 1
                elif team_id == away_team_id and away_goals > home_goals:
                    wins += 1
                    
            except (KeyError, TypeError):
                continue
                
        return wins
    
    def _calculate_h2h_avg_goals(self, h2h_data: List) -> float:
        """Calculate average total goals in H2H matches"""
        total_goals = 0
        valid_matches = 0
        
        for match in h2h_data:
            try:
                home_goals = match.get('goals', {}).get('home', 0)
                away_goals = match.get('goals', {}).get('away', 0)
                total_goals += home_goals + away_goals
                valid_matches += 1
                
            except (KeyError, TypeError):
                continue
                
        return total_goals / max(1, valid_matches)
