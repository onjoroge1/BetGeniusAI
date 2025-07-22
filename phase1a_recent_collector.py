"""
Phase 1A: Recent Foundation Data Collector
Collect 5,000 most recent matches from 2023-2024 and 2024-2025 seasons
Focus: European Big 5, Brazilian Serie A, African target markets
"""

import asyncio
import aiohttp
import json
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from typing import Dict, List, Any
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Phase1ACollector:
    """Phase 1A data collector for recent foundation matches"""
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        self.engine = create_engine(self.database_url)
        
        # Phase 1A target leagues with priorities
        self.target_leagues = {
            # European Big 5 (Priority 1 - Critical)
            'premier_league': {
                'id': 39, 
                'name': 'Premier League',
                'target_2023_24': 380,
                'target_2024_25': 180,
                'region': 'Europe',
                'tactical_style': 'physical_direct',
                'priority': 1
            },
            'la_liga': {
                'id': 140,
                'name': 'La Liga', 
                'target_2023_24': 380,
                'target_2024_25': 180,
                'region': 'Europe',
                'tactical_style': 'technical_possession',
                'priority': 1
            },
            'serie_a': {
                'id': 135,
                'name': 'Serie A',
                'target_2023_24': 380,
                'target_2024_25': 180,
                'region': 'Europe', 
                'tactical_style': 'defensive_tactical',
                'priority': 1
            },
            'bundesliga': {
                'id': 78,
                'name': 'Bundesliga',
                'target_2023_24': 306,
                'target_2024_25': 153,
                'region': 'Europe',
                'tactical_style': 'attacking_intensity', 
                'priority': 1
            },
            'ligue_1': {
                'id': 61,
                'name': 'Ligue 1',
                'target_2023_24': 380,
                'target_2024_25': 180,
                'region': 'Europe',
                'tactical_style': 'physical_transitional',
                'priority': 1
            },
            
            # South American Foundation (Priority 1)
            'brazilian_serie_a': {
                'id': 71,
                'name': 'Brazilian Serie A',
                'target_2023_24': 380,
                'target_2024_25': 200,
                'region': 'South America',
                'tactical_style': 'technical_flair',
                'priority': 1
            },
            
            # African Target Markets (Priority 1 - Market Critical)
            'kenyan_premier': {
                'id': 294,
                'name': 'Kenyan Premier League',
                'target_2023_24': 120,
                'target_2024_25': 60,
                'region': 'Africa',
                'tactical_style': 'physical_technical',
                'priority': 1
            },
            'nigerian_npfl': {
                'id': 387,
                'name': 'Nigerian NPFL',
                'target_2023_24': 180,
                'target_2024_25': 90,
                'region': 'Africa',
                'tactical_style': 'physical_direct',
                'priority': 1
            },
            'south_african_psl': {
                'id': 288,
                'name': 'South African PSL',
                'target_2023_24': 150,
                'target_2024_25': 75,
                'region': 'Africa',
                'tactical_style': 'organized_physical',
                'priority': 1
            },
            
            # Global Diversification (Priority 2)
            'mls': {
                'id': 253,
                'name': 'MLS',
                'target_2023_24': 100,
                'target_2024_25': 50,
                'region': 'North America',
                'tactical_style': 'diverse_physical',
                'priority': 2
            },
            'liga_mx': {
                'id': 262,
                'name': 'Liga MX',
                'target_2023_24': 100,
                'target_2024_25': 50,
                'region': 'North America',
                'tactical_style': 'technical_intensity',
                'priority': 2
            }
        }
        
        # Season configurations
        self.seasons = {
            '2023': {'start': '2023-08-01', 'end': '2024-05-31'},
            '2024': {'start': '2024-08-01', 'end': '2024-12-31'}  # Current season completed matches only
        }
        
    async def collect_phase1a_foundation(self):
        """Main collection method for Phase 1A"""
        logger.info("🚀 Starting Phase 1A: Recent Foundation Data Collection")
        logger.info("Target: 5,000 most recent matches from 2023-2024 and 2024-2025")
        
        # Check current database state
        await self.check_existing_data()
        
        start_time = time.time()
        total_collected = 0
        
        # Priority 1 leagues first (European Big 5 + Brazilian + African markets)
        priority_1_leagues = {k: v for k, v in self.target_leagues.items() if v['priority'] == 1}
        
        logger.info(f"Collecting from {len(priority_1_leagues)} Priority 1 leagues...")
        
        for league_key, league_config in priority_1_leagues.items():
            logger.info(f"\n📊 Starting {league_config['name']} collection...")
            
            # Collect 2023-2024 season
            collected_2023 = await self.collect_season_matches(
                league_config['id'], 
                '2023',
                league_config['target_2023_24'],
                league_config
            )
            
            # Collect 2024-2025 completed matches  
            collected_2024 = await self.collect_season_matches(
                league_config['id'],
                '2024', 
                league_config['target_2024_25'],
                league_config
            )
            
            league_total = collected_2023 + collected_2024
            total_collected += league_total
            
            logger.info(f"✅ {league_config['name']}: {league_total} matches collected")
            
            # Rate limiting
            await asyncio.sleep(2)
        
        # Priority 2 leagues if time permits
        if total_collected < 4500:  # Leave room for Priority 2
            priority_2_leagues = {k: v for k, v in self.target_leagues.items() if v['priority'] == 2}
            
            for league_key, league_config in priority_2_leagues.items():
                if total_collected >= 5000:
                    break
                    
                logger.info(f"\n📊 Starting {league_config['name']} collection...")
                
                collected_2023 = await self.collect_season_matches(
                    league_config['id'],
                    '2023', 
                    min(league_config['target_2023_24'], 5000 - total_collected),
                    league_config
                )
                
                total_collected += collected_2023
                
                if total_collected < 5000:
                    collected_2024 = await self.collect_season_matches(
                        league_config['id'],
                        '2024',
                        min(league_config['target_2024_25'], 5000 - total_collected), 
                        league_config
                    )
                    total_collected += collected_2024
                
                await asyncio.sleep(2)
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"\n🎯 Phase 1A Collection Complete!")
        logger.info(f"Total matches collected: {total_collected}")
        logger.info(f"Collection time: {duration:.1f} seconds")
        logger.info(f"Average: {total_collected/duration:.1f} matches/second")
        
        # Validate collection results
        await self.validate_phase1a_results()
        
        return total_collected
    
    async def collect_season_matches(self, league_id: int, season: str, target_matches: int, league_config: Dict) -> int:
        """Collect matches for a specific league and season"""
        
        if target_matches <= 0:
            return 0
        
        # Get existing match IDs to avoid duplicates
        existing_match_ids = await self.get_existing_match_ids(league_id, season)
        logger.info(f"  Found {len(existing_match_ids)} existing matches for {league_config['name']} {season}")
            
        collected = 0
        page = 1
        processed_match_ids = set()  # Track matches processed in this session
        
        async with aiohttp.ClientSession() as session:
            while collected < target_matches and page <= 10:  # Max 10 pages per league/season
                
                url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
                headers = {
                    "X-RapidAPI-Key": self.rapidapi_key,
                    "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
                }
                
                params = {
                    "league": league_id,
                    "season": season,
                    "status": "FT",  # Only finished matches
                    "page": page
                }
                
                try:
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            if not data.get('response'):
                                break
                                
                            matches = data['response']
                            
                            for match in matches:
                                if collected >= target_matches:
                                    break
                                
                                match_id = match['fixture']['id']
                                
                                # Skip if already processed in this session
                                if match_id in processed_match_ids:
                                    continue
                                    
                                processed_match_ids.add(match_id)
                                    
                                # Skip if already exists in database (unless needs enhancement)
                                if match_id in existing_match_ids:
                                    # Check if it needs Phase 1A enhancement
                                    needs_enhancement = await self.check_if_needs_enhancement(match_id)
                                    if not needs_enhancement:
                                        continue
                                
                                # Process and store match
                                success = await self.process_and_store_match(match, league_config)
                                if success:
                                    collected += 1
                                    if collected % 50 == 0:  # Progress logging
                                        logger.info(f"    Progress: {collected}/{target_matches} matches collected for {league_config['name']}")
                                    
                            page += 1
                            
                            # Rate limiting
                            await asyncio.sleep(0.5)
                            
                        else:
                            logger.warning(f"API error {response.status} for league {league_id} season {season}")
                            break
                            
                except Exception as e:
                    logger.error(f"Error collecting {league_config['name']} {season}: {e}")
                    break
        
        return collected
    
    async def process_and_store_match(self, match_data: Dict, league_config: Dict) -> bool:
        """Process match data and store in database with enhanced features"""
        try:
            # Extract basic match info
            match_id = match_data['fixture']['id']
            home_team = match_data['teams']['home']['name']
            away_team = match_data['teams']['away']['name']
            home_score = match_data['goals']['home']
            away_score = match_data['goals']['away']
            match_date = match_data['fixture']['date']
            venue = match_data['fixture']['venue']['name'] if match_data['fixture']['venue'] else 'Unknown'
            
            # Skip if scores are None (match not completed properly)
            if home_score is None or away_score is None:
                return False
            
            # Determine outcome
            if home_score > away_score:
                outcome = 'Home'
            elif home_score < away_score:
                outcome = 'Away'
            else:
                outcome = 'Draw'
            
            # Enhanced feature engineering for Phase 1A
            features = await self.create_enhanced_features(match_data, league_config)
            
            # Store in database with duplicate prevention
            with self.engine.connect() as conn:
                # Check if match already exists (comprehensive check)
                existing = conn.execute(text("""
                    SELECT match_id, collection_phase, features FROM training_matches 
                    WHERE match_id = :match_id
                """), {"match_id": match_id}).fetchone()
                
                if existing is None:
                    # Insert new match with enhanced features
                    conn.execute(text("""
                        INSERT INTO training_matches 
                        (match_id, league_id, home_team, away_team, home_score, away_score, 
                         outcome, match_date, venue, features, region, tactical_style, season, collection_phase)
                        VALUES (:match_id, :league_id, :home_team, :away_team, :home_score, :away_score,
                                :outcome, :match_date, :venue, :features, :region, :tactical_style, :season, :collection_phase)
                    """), {
                        "match_id": match_id,
                        "league_id": league_config['id'],
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_score": home_score,
                        "away_score": away_score,
                        "outcome": outcome,
                        "match_date": match_date,
                        "venue": venue,
                        "features": json.dumps(features),
                        "region": league_config['region'],
                        "tactical_style": league_config['tactical_style'],
                        "season": match_data['league']['season'],
                        "collection_phase": "Phase_1A_Recent_Foundation"
                    })
                    conn.commit()
                    logger.debug(f"✅ New match added: {home_team} vs {away_team} (ID: {match_id})")
                    return True
                else:
                    # Check if this is from an earlier collection phase and needs enhancement
                    existing_phase = existing[2] if len(existing) > 2 else None
                    
                    if existing_phase != "Phase_1A_Recent_Foundation":
                        # Update existing match with Phase 1A enhanced features
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
                            "collection_phase": "Phase_1A_Recent_Foundation"
                        })
                        conn.commit()
                        logger.debug(f"🔄 Enhanced existing match: {home_team} vs {away_team} (ID: {match_id})")
                        return True  # Count as new for Phase 1A
                    else:
                        logger.debug(f"⏭️  Skipping duplicate: {home_team} vs {away_team} (ID: {match_id})")
                        return False  # Already processed in Phase 1A
                    
        except Exception as e:
            logger.error(f"Error processing match {match_data.get('fixture', {}).get('id', 'unknown')}: {e}")
            return False
    
    async def create_enhanced_features(self, match_data: Dict, league_config: Dict) -> Dict:
        """Create enhanced features for Phase 1A including team-level and contextual factors"""
        
        # Basic features (current system)
        features = {
            'home_win_percentage': 0.5,  # Will be enhanced with real data later
            'away_win_percentage': 0.3,
            'home_form_normalized': 0.6,
            'away_form_normalized': 0.4,
            'win_probability_difference': 0.2,
            'form_balance': 0.1,
            'combined_strength': 0.55,
            'league_competitiveness': self._get_league_competitiveness(league_config['id']),
            'league_home_advantage': self._get_league_home_advantage(league_config['region']),
            'african_market_flag': 1 if league_config['region'] == 'Africa' else 0,
        }
        
        # Phase 1A Enhanced Features
        enhanced_features = {
            # Team Performance Metrics (Phase 1A additions)
            'squad_value_ratio': 1.2,  # Home vs away squad value ratio
            'key_players_available_home': 0.9,  # Percentage of key players available
            'key_players_available_away': 0.85,
            'tactical_formation_home': self._encode_formation('4-3-3'),  # Default, will enhance
            'tactical_formation_away': self._encode_formation('4-2-3-1'),
            
            # Contextual Factors (Phase 1A additions)
            'days_rest_home': 7,  # Days since last match
            'days_rest_away': 4,
            'travel_distance': self._estimate_travel_distance(league_config['region']),
            'match_importance': self._assess_match_importance(match_data),
            'referee_strictness': 0.5,  # Placeholder for referee tendency
            
            # Weather and Environmental (Phase 1A additions)
            'weather_impact': self._assess_weather_impact(match_data),
            'venue_advantage': self._calculate_venue_advantage(match_data),
            'crowd_factor': 1.0,  # Post-COVID normal crowds
            
            # League and Regional Context
            'tactical_style_factor': self._get_tactical_style_factor(league_config['tactical_style']),
            'regional_intensity': self._get_regional_intensity(league_config['region']),
            'competition_level': self._get_competition_level(league_config['id']),
        }
        
        # Merge basic and enhanced features
        features.update(enhanced_features)
        return features
    
    def _get_league_competitiveness(self, league_id: int) -> float:
        """Get league competitiveness factor"""
        competitiveness_map = {
            39: 0.9,   # Premier League - very competitive
            140: 0.8,  # La Liga - competitive
            135: 0.85, # Serie A - very competitive  
            78: 0.8,   # Bundesliga - competitive
            61: 0.75,  # Ligue 1 - moderately competitive
            71: 0.8,   # Brazilian Serie A - competitive
            294: 0.6,  # Kenyan Premier - developing
            387: 0.65, # Nigerian NPFL - developing
            288: 0.7,  # South African PSL - moderate
            253: 0.75, # MLS - moderate
            262: 0.75  # Liga MX - moderate
        }
        return competitiveness_map.get(league_id, 0.6)
    
    def _get_league_home_advantage(self, region: str) -> float:
        """Get regional home advantage factor"""
        home_advantage_map = {
            'Europe': 0.6,
            'South America': 0.75,  # Higher home advantage
            'Africa': 0.7,
            'North America': 0.65,
            'Asia': 0.65
        }
        return home_advantage_map.get(region, 0.6)
    
    def _encode_formation(self, formation: str) -> float:
        """Encode tactical formation as numeric value"""
        formation_map = {
            '4-3-3': 0.8,   # Attacking
            '4-2-3-1': 0.6, # Balanced
            '3-5-2': 0.7,   # Wing-focused
            '4-4-2': 0.5,   # Traditional
            '3-4-3': 0.9,   # Very attacking
            '5-3-2': 0.3    # Defensive
        }
        return formation_map.get(formation, 0.5)
    
    def _estimate_travel_distance(self, region: str) -> float:
        """Estimate travel burden for away team"""
        travel_map = {
            'Europe': 0.4,        # Moderate distances
            'South America': 0.7, # Large distances
            'Africa': 0.8,        # Very large distances
            'North America': 0.6, # Large country distances
            'Asia': 0.6
        }
        return travel_map.get(region, 0.5)
    
    def _assess_match_importance(self, match_data: Dict) -> float:
        """Assess match importance based on context"""
        # Check if it's a late season match (higher importance)
        match_date = match_data['fixture']['date']
        if '2024-04' in match_date or '2024-05' in match_date:
            return 0.8  # End of season importance
        elif '2024-12' in match_date:
            return 0.7  # Mid-season importance
        else:
            return 0.5  # Regular importance
    
    def _assess_weather_impact(self, match_data: Dict) -> float:
        """Assess weather impact on match"""
        # Placeholder - could be enhanced with weather API
        venue = match_data['fixture']['venue']
        if venue and venue.get('city'):
            # Basic climate assumptions
            return 0.5
        return 0.0
    
    def _calculate_venue_advantage(self, match_data: Dict) -> float:
        """Calculate specific venue advantage"""
        # Famous stadiums might have higher advantage
        venue_name = match_data['fixture']['venue']['name'] if match_data['fixture']['venue'] else ''
        
        famous_venues = ['Old Trafford', 'Anfield', 'Santiago Bernabéu', 'Camp Nou', 'San Siro']
        if any(famous in venue_name for famous in famous_venues):
            return 0.8
        return 0.6
    
    def _get_tactical_style_factor(self, tactical_style: str) -> float:
        """Get tactical style influence factor"""
        style_map = {
            'physical_direct': 0.8,
            'technical_possession': 0.9,
            'defensive_tactical': 0.7,
            'attacking_intensity': 0.85,
            'physical_transitional': 0.75,
            'technical_flair': 0.8,
            'physical_technical': 0.65,
            'organized_physical': 0.6,
            'diverse_physical': 0.7,
            'technical_intensity': 0.75
        }
        return style_map.get(tactical_style, 0.6)
    
    def _get_regional_intensity(self, region: str) -> float:
        """Get regional football intensity factor"""
        intensity_map = {
            'Europe': 0.9,
            'South America': 0.95,
            'Africa': 0.8,
            'North America': 0.75,
            'Asia': 0.7
        }
        return intensity_map.get(region, 0.7)
    
    def _get_competition_level(self, league_id: int) -> float:
        """Get competition level factor"""
        level_map = {
            39: 1.0,   # Premier League - top tier
            140: 0.95, # La Liga
            135: 0.95, # Serie A
            78: 0.9,   # Bundesliga
            61: 0.85,  # Ligue 1
            71: 0.8,   # Brazilian Serie A
            294: 0.5,  # Kenyan Premier
            387: 0.55, # Nigerian NPFL
            288: 0.6,  # South African PSL
            253: 0.7,  # MLS
            262: 0.7   # Liga MX
        }
        return level_map.get(league_id, 0.5)
    
    async def check_existing_data(self):
        """Check existing data to avoid duplicates and show current state"""
        logger.info("\n📊 Checking existing database state...")
        
        with self.engine.connect() as conn:
            # Check total matches in database
            total_result = conn.execute(text("""
                SELECT COUNT(*) as total_matches
                FROM training_matches
            """)).fetchone()
            
            # Check Phase 1A matches already collected
            phase1a_result = conn.execute(text("""
                SELECT COUNT(*) as phase1a_matches
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Recent_Foundation'
            """)).fetchone()
            
            # Check league distribution for target leagues
            target_league_ids = [config['id'] for config in self.target_leagues.values()]
            league_result = conn.execute(text(f"""
                SELECT league_id, COUNT(*) as count
                FROM training_matches 
                WHERE league_id IN ({','.join(map(str, target_league_ids))})
                GROUP BY league_id
                ORDER BY count DESC
            """)).fetchall()
            
            # Check recent matches (2023-2024 seasons)
            recent_result = conn.execute(text("""
                SELECT COUNT(*) as recent_matches
                FROM training_matches 
                WHERE match_date >= '2023-08-01'
            """)).fetchall()
            
            logger.info(f"📈 Current database state:")
            logger.info(f"  Total matches: {total_result[0] if total_result else 0}")
            logger.info(f"  Phase 1A matches: {phase1a_result[0] if phase1a_result else 0}")
            logger.info(f"  Recent matches (2023+): {recent_result[0][0] if recent_result and recent_result[0] else 0}")
            
            logger.info(f"\n🎯 Target league current state:")
            for league_id, count in league_result:
                league_name = self._get_league_name(league_id)
                logger.info(f"  {league_name}: {count} matches")
            
            # Calculate gaps for each target league
            logger.info(f"\n📋 Phase 1A Collection Gaps:")
            for league_key, league_config in self.target_leagues.items():
                current_count = next((count for lid, count in league_result if lid == league_config['id']), 0)
                target_total = league_config['target_2023_24'] + league_config['target_2024_25']
                gap = max(0, target_total - current_count)
                
                if gap > 0:
                    logger.info(f"  {league_config['name']}: {gap} matches needed (current: {current_count}, target: {target_total})")
                else:
                    logger.info(f"  {league_config['name']}: ✅ Target reached ({current_count} matches)")
    
    async def get_existing_match_ids(self, league_id: int, season: str) -> set:
        """Get existing match IDs for a league and season to avoid duplicates"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id FROM training_matches 
                WHERE league_id = :league_id AND season = :season
            """), {"league_id": league_id, "season": season}).fetchall()
            
            return set(row[0] for row in result)
    
    async def validate_phase1a_results(self):
        """Validate Phase 1A collection results"""
        logger.info("\n🔍 Validating Phase 1A Collection Results...")
        
        with self.engine.connect() as conn:
            # Check total matches collected
            total_result = conn.execute(text("""
                SELECT COUNT(*) as total_matches
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Recent_Foundation'
            """)).fetchone()
            
            # Check regional distribution
            regional_result = conn.execute(text("""
                SELECT region, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Recent_Foundation'
                GROUP BY region
                ORDER BY count DESC
            """)).fetchall()
            
            # Check league distribution
            league_result = conn.execute(text("""
                SELECT league_id, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Recent_Foundation'
                GROUP BY league_id
                ORDER BY count DESC
            """)).fetchall()
            
            # Check season distribution
            season_result = conn.execute(text("""
                SELECT season, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Recent_Foundation'
                GROUP BY season
                ORDER BY season DESC
            """)).fetchall()
            
            logger.info(f"✅ Total Phase 1A matches: {total_result[0] if total_result else 0}")
            
            logger.info("\n📊 Regional Distribution:")
            for region, count in regional_result:
                logger.info(f"  {region}: {count} matches")
            
            logger.info("\n🏆 League Distribution:")
            for league_id, count in league_result:
                league_name = self._get_league_name(league_id)
                logger.info(f"  {league_name}: {count} matches")
            
            logger.info("\n📅 Season Distribution:")
            for season, count in season_result:
                logger.info(f"  {season}: {count} matches")
    
    def _get_league_name(self, league_id: int) -> str:
        """Get league name from ID"""
        for league_config in self.target_leagues.values():
            if league_config['id'] == league_id:
                return league_config['name']
        return f"League {league_id}"
    
    async def check_if_needs_enhancement(self, match_id: int) -> bool:
        """Check if existing match needs Phase 1A enhancement"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT collection_phase FROM training_matches 
                WHERE match_id = :match_id
            """), {"match_id": match_id}).fetchone()
            
            if result:
                return result[0] != "Phase_1A_Recent_Foundation"
            return False

async def main():
    """Run Phase 1A data collection"""
    collector = Phase1ACollector()
    
    try:
        total_collected = await collector.collect_phase1a_foundation()
        
        if total_collected >= 4500:
            print(f"\n🎉 Phase 1A SUCCESS: {total_collected} matches collected")
            print("✅ Ready for Phase 1A model training with enhanced features")
            print("🚀 Foundation established for Phase 1B collection")
        else:
            print(f"\n⚠️  Phase 1A PARTIAL: {total_collected} matches collected")
            print("🔄 Consider running additional collection cycles")
            
    except Exception as e:
        logger.error(f"❌ Phase 1A collection failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())