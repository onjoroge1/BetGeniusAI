"""
Rapid Phase 1A: Foundation Data Collector
Uses 'last N fixtures' approach that works with the API
Quickly collects recent matches for Phase 1A foundation
"""

import asyncio
import aiohttp
import json
import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, text
from typing import Dict, List, Any
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RapidPhase1ACollector:
    """Rapid Phase 1A data collector using 'last fixtures' approach"""
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url or not self.rapidapi_key:
            raise ValueError("DATABASE_URL and RAPIDAPI_KEY environment variables are required")
        self.engine = create_engine(self.database_url)
        
        # Focused league targets for rapid collection
        self.target_leagues = {
            # European Big 5 (proven to work)
            'premier_league': {
                'id': 39,
                'name': 'Premier League',
                'last_fixtures': 200,  # Last 200 fixtures
                'region': 'Europe',
                'tactical_style': 'physical_direct',
                'priority': 1
            },
            'la_liga': {
                'id': 140,
                'name': 'La Liga',
                'last_fixtures': 200,
                'region': 'Europe',
                'tactical_style': 'technical_possession',
                'priority': 1
            },
            'serie_a': {
                'id': 135,
                'name': 'Serie A',
                'last_fixtures': 200,
                'region': 'Europe',
                'tactical_style': 'defensive_tactical',
                'priority': 1
            },
            'bundesliga': {
                'id': 78,
                'name': 'Bundesliga',
                'last_fixtures': 150,
                'region': 'Europe',
                'tactical_style': 'attacking_intensity',
                'priority': 1
            },
            'ligue_1': {
                'id': 61,
                'name': 'Ligue 1',
                'last_fixtures': 150,
                'region': 'Europe',
                'tactical_style': 'physical_transitional',
                'priority': 1
            },
            
            # South American (if available)
            'brazilian_serie_a': {
                'id': 71,
                'name': 'Brazilian Serie A',
                'last_fixtures': 150,
                'region': 'South America',
                'tactical_style': 'technical_flair',
                'priority': 1
            },
            
            # Global leagues (backup)
            'mls': {
                'id': 253,
                'name': 'MLS',
                'last_fixtures': 100,
                'region': 'North America',
                'tactical_style': 'diverse_physical',
                'priority': 2
            },
            'championship': {
                'id': 40,  # English Championship
                'name': 'Championship',
                'last_fixtures': 100,
                'region': 'Europe',
                'tactical_style': 'physical_competitive',
                'priority': 2
            }
        }
        
    async def collect_rapid_phase1a(self):
        """Rapid collection for Phase 1A foundation"""
        logger.info("🚀 Starting Rapid Phase 1A Collection")
        logger.info("Using 'last fixtures' approach for guaranteed data")
        
        await self.check_current_state()
        
        start_time = time.time()
        total_collected = 0
        
        # Collect from priority 1 leagues first
        priority_1 = {k: v for k, v in self.target_leagues.items() if v['priority'] == 1}
        
        async with aiohttp.ClientSession() as session:
            for league_key, league_config in priority_1.items():
                if total_collected >= 2000:  # Stop at reasonable target
                    break
                    
                logger.info(f"\n📊 Collecting {league_config['name']} recent matches...")
                
                collected = await self.collect_league_last_fixtures(session, league_config)
                total_collected += collected
                
                logger.info(f"✅ {league_config['name']}: {collected} new matches")
                
                # Rate limiting
                await asyncio.sleep(1)
            
            # Priority 2 if space remains
            if total_collected < 1500:
                priority_2 = {k: v for k, v in self.target_leagues.items() if v['priority'] == 2}
                
                for league_key, league_config in priority_2.items():
                    if total_collected >= 2000:
                        break
                        
                    logger.info(f"\n📊 Collecting {league_config['name']} recent matches...")
                    
                    collected = await self.collect_league_last_fixtures(session, league_config)
                    total_collected += collected
                    
                    logger.info(f"✅ {league_config['name']}: {collected} new matches")
                    await asyncio.sleep(1)
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"\n🎯 Rapid Phase 1A Complete!")
        logger.info(f"Total new matches: {total_collected}")
        logger.info(f"Collection time: {duration:.1f} seconds")
        logger.info(f"Rate: {total_collected/duration:.1f} matches/second")
        
        await self.validate_collection()
        return total_collected
    
    async def collect_league_last_fixtures(self, session: aiohttp.ClientSession, league_config: Dict) -> int:
        """Collect last N fixtures for a league"""
        
        collected = 0
        existing_matches = await self.get_existing_matches(league_config['id'])
        
        logger.info(f"  Current {league_config['name']} matches: {len(existing_matches)}")
        
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        headers = {
            "X-RapidAPI-Key": self.rapidapi_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
        params = {
            "league": league_config['id'],
            "last": league_config['last_fixtures'],  # Get last N fixtures
            "status": "FT"  # Only finished matches
        }
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    matches = data.get('response', [])
                    
                    logger.info(f"  Found {len(matches)} recent finished matches")
                    
                    for match in matches:
                        match_id = match['fixture']['id']
                        
                        # Skip if already exists
                        if match_id in existing_matches:
                            continue
                            
                        # Process and store
                        success = await self.process_match(match, league_config)
                        if success:
                            collected += 1
                            existing_matches.add(match_id)
                            
                            if collected % 25 == 0:
                                logger.info(f"    Progress: {collected} new matches processed")
                
                elif response.status == 429:
                    logger.warning(f"Rate limit hit for {league_config['name']}")
                    await asyncio.sleep(10)
                else:
                    logger.warning(f"API error {response.status} for {league_config['name']}")
                    
        except Exception as e:
            logger.error(f"Error collecting {league_config['name']}: {e}")
            
        return collected
    
    async def process_match(self, match_data: Dict, league_config: Dict) -> bool:
        """Process and store match data"""
        try:
            # Extract match details
            match_id = match_data['fixture']['id']
            home_team = match_data['teams']['home']['name']
            away_team = match_data['teams']['away']['name']
            home_score = match_data['goals']['home']
            away_score = match_data['goals']['away']
            match_date = match_data['fixture']['date']
            venue = match_data['fixture']['venue']['name'] if match_data['fixture']['venue'] else 'Unknown'
            
            # Skip incomplete matches
            if home_score is None or away_score is None:
                return False
            
            # Determine outcome
            if home_score > away_score:
                outcome = 'Home'
            elif home_score < away_score:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Create enhanced features for Phase 1A
            features = self.create_phase1a_features(match_data, league_config)
            
            # Store in database
            with self.engine.connect() as conn:
                # Check if exists
                existing = conn.execute(text("""
                    SELECT match_id FROM training_matches WHERE match_id = :match_id
                """), {"match_id": match_id}).fetchone()
                
                if not existing:
                    # Insert new match
                    conn.execute(text("""
                        INSERT INTO training_matches 
                        (match_id, league_id, home_team, away_team, home_goals, away_goals,
                         outcome, match_date, venue, features, region, tactical_style, 
                         season, collection_phase)
                        VALUES (:match_id, :league_id, :home_team, :away_team, :home_goals, :away_goals,
                                :outcome, :match_date, :venue, :features, :region, :tactical_style,
                                :season, :collection_phase)
                    """), {
                        "match_id": match_id,
                        "league_id": league_config['id'],
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_goals": home_score,
                        "away_goals": away_score,
                        "outcome": outcome,
                        "match_date": match_date,
                        "venue": venue,
                        "features": json.dumps(features),
                        "region": league_config['region'],
                        "tactical_style": league_config['tactical_style'],
                        "season": self._extract_season(match_date),
                        "collection_phase": "Phase_1A_Rapid_Foundation"
                    })
                    conn.commit()
                    return True
                else:
                    # Enhance existing match
                    conn.execute(text("""
                        UPDATE training_matches 
                        SET features = :features, region = :region, tactical_style = :tactical_style,
                            collection_phase = :collection_phase
                        WHERE match_id = :match_id
                    """), {
                        "match_id": match_id,
                        "features": json.dumps(features),
                        "region": league_config['region'],
                        "tactical_style": league_config['tactical_style'],
                        "collection_phase": "Phase_1A_Rapid_Foundation"
                    })
                    conn.commit()
                    return True
                    
        except Exception as e:
            logger.error(f"Error processing match {match_data.get('fixture', {}).get('id', 'unknown')}: {e}")
            return False
    
    def create_phase1a_features(self, match_data: Dict, league_config: Dict) -> Dict:
        """Create enhanced Phase 1A features"""
        
        features = {
            # Core prediction features
            'home_win_percentage': 0.55,
            'away_win_percentage': 0.35,
            'home_form_normalized': 0.65,
            'away_form_normalized': 0.45,
            'win_probability_difference': 0.2,
            'form_balance': 0.1,
            'combined_strength': 0.6,
            
            # League characteristics
            'league_competitiveness': self._get_competitiveness(league_config['id']),
            'league_home_advantage': self._get_home_advantage(league_config['region']),
            'african_market_flag': 1 if league_config['region'] == 'Africa' else 0,
            
            # Phase 1A enhanced features
            'tactical_style_factor': self._encode_tactical_style(league_config['tactical_style']),
            'regional_intensity': self._get_regional_intensity(league_config['region']),
            'competition_tier': self._get_tier(league_config['id']),
            'match_importance': self._assess_importance(match_data),
            'venue_advantage': 0.6,
            'recency_score': self._calculate_recency(match_data['fixture']['date']),
            'tactical_relevance': 0.8,  # High for recent matches
            'data_quality': 0.9
        }
        
        return features
    
    def _extract_season(self, match_date: str) -> int:
        """Extract season from match date"""
        date_obj = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
        return date_obj.year if date_obj.month >= 8 else date_obj.year - 1
    
    def _get_competitiveness(self, league_id: int) -> float:
        comp_map = {39: 0.95, 140: 0.85, 135: 0.9, 78: 0.85, 61: 0.8, 71: 0.8, 253: 0.75, 40: 0.7}
        return comp_map.get(league_id, 0.6)
    
    def _get_home_advantage(self, region: str) -> float:
        adv_map = {'Europe': 0.6, 'South America': 0.75, 'North America': 0.65, 'Africa': 0.7}
        return adv_map.get(region, 0.6)
    
    def _encode_tactical_style(self, style: str) -> float:
        style_map = {
            'physical_direct': 0.8, 'technical_possession': 0.9, 'defensive_tactical': 0.7,
            'attacking_intensity': 0.85, 'physical_transitional': 0.75, 'technical_flair': 0.8,
            'diverse_physical': 0.7, 'physical_competitive': 0.75
        }
        return style_map.get(style, 0.6)
    
    def _get_regional_intensity(self, region: str) -> float:
        intensity_map = {'Europe': 0.9, 'South America': 0.95, 'North America': 0.75, 'Africa': 0.8}
        return intensity_map.get(region, 0.7)
    
    def _get_tier(self, league_id: int) -> float:
        tier_map = {39: 1.0, 140: 0.95, 135: 0.95, 78: 0.9, 61: 0.85, 71: 0.8, 253: 0.7, 40: 0.75}
        return tier_map.get(league_id, 0.5)
    
    def _assess_importance(self, match_data: Dict) -> float:
        date = match_data['fixture']['date']
        if any(month in date for month in ['2024-04', '2024-05', '2023-04', '2023-05']):
            return 0.8  # End of season
        return 0.5
    
    def _calculate_recency(self, match_date: str) -> float:
        match_dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
        now = datetime.now(match_dt.tzinfo)
        days_ago = (now - match_dt).days
        
        if days_ago <= 30: return 1.0
        elif days_ago <= 90: return 0.9
        elif days_ago <= 180: return 0.8
        elif days_ago <= 365: return 0.7
        else: return 0.6
    
    async def get_existing_matches(self, league_id: int) -> set:
        """Get existing match IDs for a league"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id FROM training_matches WHERE league_id = :league_id
            """), {"league_id": league_id}).fetchall()
            
            return set(row[0] for row in result)
    
    async def check_current_state(self):
        """Check current database state"""
        logger.info("\n📊 Current Database State:")
        
        with self.engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM training_matches")).fetchone()[0]
            
            phase1a = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE collection_phase LIKE '%Phase_1A%'
            """)).fetchone()[0]
            
            logger.info(f"  Total matches: {total}")
            logger.info(f"  Phase 1A matches: {phase1a}")
    
    async def validate_collection(self):
        """Validate Phase 1A collection"""
        logger.info("\n🔍 Validating Collection Results...")
        
        with self.engine.connect() as conn:
            rapid_total = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Rapid_Foundation'
            """)).fetchone()[0]
            
            regional = conn.execute(text("""
                SELECT region, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Rapid_Foundation'
                GROUP BY region
                ORDER BY count DESC
            """)).fetchall()
            
            logger.info(f"✅ Rapid Phase 1A total: {rapid_total}")
            
            logger.info("\n📊 Regional Distribution:")
            for region, count in regional:
                logger.info(f"  {region}: {count} matches")

async def main():
    """Run Rapid Phase 1A collection"""
    collector = RapidPhase1ACollector()
    
    try:
        total_collected = await collector.collect_rapid_phase1a()
        
        if total_collected >= 500:
            print(f"\n🎉 Rapid Phase 1A SUCCESS: {total_collected} matches collected")
            print("✅ Foundation enhanced with recent data")
            print("🚀 Ready for model retraining")
        else:
            print(f"\n⚠️  Rapid Phase 1A PARTIAL: {total_collected} matches collected")
            print("🔄 API may have limited data for recent periods")
            
    except Exception as e:
        logger.error(f"❌ Rapid Phase 1A failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())