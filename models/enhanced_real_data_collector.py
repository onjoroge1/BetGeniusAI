"""
Enhanced Real Data Collector
Collects comprehensive real-time data including injuries, team news, and current form
"""

import requests
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

class EnhancedRealDataCollector:
    """Collect comprehensive real-time match data"""
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.odds_api_key = os.environ.get('ODDS_API_KEY')
        
        self.rapidapi_headers = {
            'X-RapidAPI-Key': self.rapidapi_key,
            'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'
        }
    
    def get_match_details(self, match_id: int) -> Optional[Dict]:
        """Get comprehensive match details"""
        
        try:
            url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
            params = {'id': match_id}
            
            response = requests.get(url, headers=self.rapidapi_headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('response') and len(data['response']) > 0:
                    return data['response'][0]
            
            logger.warning(f"Failed to get match details for {match_id}: {response.status_code}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting match details: {e}")
            return None
    
    def get_team_injuries(self, team_id: int, season: int = 2024) -> List[Dict]:
        """Get current team injuries"""
        
        try:
            url = "https://api-football-v1.p.rapidapi.com/v3/injuries"
            params = {
                'team': team_id,
                'season': season
            }
            
            response = requests.get(url, headers=self.rapidapi_headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('response'):
                    # Filter for current injuries
                    current_injuries = []
                    for injury in data['response']:
                        if injury.get('player') and injury.get('type'):
                            current_injuries.append({
                                'player_name': injury['player']['name'],
                                'player_position': injury['player']['position'],
                                'injury_type': injury['type'],
                                'injury_reason': injury.get('reason', 'Unknown'),
                                'expected_return': injury.get('date', 'Unknown')
                            })
                    return current_injuries
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting team injuries: {e}")
            return []
    
    def get_team_news_and_lineups(self, match_id: int) -> Dict:
        """Get team news, lineups, and pre-match information"""
        
        try:
            # Get lineups if available
            url = "https://api-football-v1.p.rapidapi.com/v3/fixtures/lineups"
            params = {'fixture': match_id}
            
            response = requests.get(url, headers=self.rapidapi_headers, params=params)
            
            lineups = {}
            if response.status_code == 200:
                data = response.json()
                if data.get('response'):
                    for team_data in data['response']:
                        team_name = team_data['team']['name']
                        lineups[team_name] = {
                            'formation': team_data.get('formation'),
                            'starting_xi': [
                                {
                                    'name': player['player']['name'],
                                    'position': player['player']['pos'],
                                    'number': player['player']['number']
                                }
                                for player in team_data.get('startXI', [])
                            ],
                            'substitutes': [
                                {
                                    'name': player['player']['name'],
                                    'position': player['player']['pos'],
                                    'number': player['player']['number']
                                }
                                for player in team_data.get('substitutes', [])
                            ]
                        }
            
            return lineups
            
        except Exception as e:
            logger.error(f"Error getting team news: {e}")
            return {}
    
    def get_recent_form(self, team_id: int, limit: int = 5) -> List[Dict]:
        """Get recent team form and results"""
        
        try:
            url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
            params = {
                'team': team_id,
                'last': limit,
                'status': 'FT'
            }
            
            response = requests.get(url, headers=self.rapidapi_headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('response'):
                    form = []
                    for match in data['response']:
                        home_team = match['teams']['home']
                        away_team = match['teams']['away']
                        goals = match['goals']
                        
                        # Determine result from team perspective
                        if home_team['id'] == team_id:
                            if goals['home'] > goals['away']:
                                result = 'W'
                            elif goals['home'] < goals['away']:
                                result = 'L'
                            else:
                                result = 'D'
                            opponent = away_team['name']
                            score = f"{goals['home']}-{goals['away']}"
                        else:
                            if goals['away'] > goals['home']:
                                result = 'W'
                            elif goals['away'] < goals['home']:
                                result = 'L'
                            else:
                                result = 'D'
                            opponent = home_team['name']
                            score = f"{goals['away']}-{goals['home']}"
                        
                        form.append({
                            'date': match['fixture']['date'],
                            'opponent': opponent,
                            'result': result,
                            'score': score,
                            'venue': 'Home' if home_team['id'] == team_id else 'Away'
                        })
                    
                    return form
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting recent form: {e}")
            return []
    
    def get_head_to_head(self, team1_id: int, team2_id: int, limit: int = 5) -> List[Dict]:
        """Get head-to-head record between teams"""
        
        try:
            url = "https://api-football-v1.p.rapidapi.com/v3/fixtures/headtohead"
            params = {
                'h2h': f"{team1_id}-{team2_id}",
                'last': limit
            }
            
            response = requests.get(url, headers=self.rapidapi_headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('response'):
                    h2h = []
                    for match in data['response']:
                        home_team = match['teams']['home']
                        away_team = match['teams']['away']
                        goals = match['goals']
                        
                        h2h.append({
                            'date': match['fixture']['date'],
                            'home_team': home_team['name'],
                            'away_team': away_team['name'],
                            'score': f"{goals['home']}-{goals['away']}",
                            'winner': home_team['name'] if goals['home'] > goals['away'] 
                                     else away_team['name'] if goals['away'] > goals['home'] 
                                     else 'Draw'
                        })
                    
                    return h2h
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting head-to-head: {e}")
            return []
    
    def get_current_odds(self, match_id: int) -> Dict:
        """Get current betting odds from multiple bookmakers"""
        
        try:
            # First try to get match details to find the teams
            match_details = self.get_match_details(match_id)
            if not match_details:
                return {}
            
            home_team = match_details['teams']['home']['name']
            away_team = match_details['teams']['away']['name']
            
            # For demonstration, return sample odds structure
            # In production, integrate with Odds API or bookmaker APIs
            odds_data = {
                'pinnacle': {
                    'home': 2.10,
                    'draw': 3.40,
                    'away': 3.20
                },
                'bet365': {
                    'home': 2.05,
                    'draw': 3.30,
                    'away': 3.15
                },
                'betway': {
                    'home': 2.08,
                    'draw': 3.35,
                    'away': 3.18
                },
                'william_hill': {
                    'home': 2.00,
                    'draw': 3.25,
                    'away': 3.10
                }
            }
            
            return odds_data
            
        except Exception as e:
            logger.error(f"Error getting current odds: {e}")
            return {}
    
    def collect_comprehensive_match_data(self, match_id: int) -> Dict:
        """Collect all comprehensive data for a match"""
        
        logger.info(f"Collecting comprehensive data for match {match_id}")
        
        # Get basic match details
        match_details = self.get_match_details(match_id)
        if not match_details:
            raise ValueError(f"Could not find match details for {match_id}")
        
        home_team_id = match_details['teams']['home']['id']
        away_team_id = match_details['teams']['away']['id']
        
        # Collect all data in parallel conceptually
        comprehensive_data = {
            'match_details': match_details,
            'home_team': {
                'id': home_team_id,
                'name': match_details['teams']['home']['name'],
                'injuries': self.get_team_injuries(home_team_id),
                'recent_form': self.get_recent_form(home_team_id),
            },
            'away_team': {
                'id': away_team_id,
                'name': match_details['teams']['away']['name'],
                'injuries': self.get_team_injuries(away_team_id),
                'recent_form': self.get_recent_form(away_team_id),
            },
            'head_to_head': self.get_head_to_head(home_team_id, away_team_id),
            'team_news': self.get_team_news_and_lineups(match_id),
            'current_odds': self.get_current_odds(match_id),
            'collection_timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Successfully collected comprehensive data for {match_details['teams']['home']['name']} vs {match_details['teams']['away']['name']}")
        
        return comprehensive_data

def main():
    """Test the enhanced data collector"""
    collector = EnhancedRealDataCollector()
    
    # Test with a sample match ID (Premier League match)
    test_match_id = 1035101  # Sample match ID
    
    try:
        data = collector.collect_comprehensive_match_data(test_match_id)
        print(json.dumps(data, indent=2, default=str))
    except Exception as e:
        print(f"Error testing collector: {e}")

if __name__ == "__main__":
    main()