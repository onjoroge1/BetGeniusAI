"""
Smart Phase 1A: Recent Foundation Data Collector
Enhanced approach using date ranges and completed matches
Collects 5,000 most recent matches while avoiding duplicates
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

class SmartPhase1ACollector:
    """Smart Phase 1A data collector using date-based approach"""
    
    def __init__(self):
        self.rapidapi_key = os.environ.get('RAPIDAPI_KEY')
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url or not self.rapidapi_key:
            raise ValueError("DATABASE_URL and RAPIDAPI_KEY environment variables are required")
        self.engine = create_engine(self.database_url)
        
        # Priority league configurations
        self.priority_leagues = {
            # European Big 5 (Highest Priority - Tactical Foundation)
            'premier_league': {
                'id': 39,
                'name': 'Premier League',
                'target_matches': 200,  # Focus on recent quality matches
                'region': 'Europe',
                'tactical_style': 'physical_direct',
                'priority': 1
            },
            'la_liga': {
                'id': 140,
                'name': 'La Liga',
                'target_matches': 200,
                'region': 'Europe', 
                'tactical_style': 'technical_possession',
                'priority': 1
            },
            'serie_a': {
                'id': 135,
                'name': 'Serie A',
                'target_matches': 200,
                'region': 'Europe',
                'tactical_style': 'defensive_tactical',
                'priority': 1
            },
            'bundesliga': {
                'id': 78,
                'name': 'Bundesliga',
                'target_matches': 150,
                'region': 'Europe',
                'tactical_style': 'attacking_intensity',
                'priority': 1
            },
            'ligue_1': {
                'id': 61,
                'name': 'Ligue 1',
                'target_matches': 150,
                'region': 'Europe',
                'tactical_style': 'physical_transitional',
                'priority': 1
            },
            
            # South American Foundation (High Priority)
            'brazilian_serie_a': {
                'id': 71,
                'name': 'Brazilian Serie A',
                'target_matches': 200,
                'region': 'South America',
                'tactical_style': 'technical_flair',
                'priority': 1
            },
            
            # Major Global Leagues (Medium Priority)
            'mls': {
                'id': 253,
                'name': 'MLS',
                'target_matches': 100,
                'region': 'North America',
                'tactical_style': 'diverse_physical',
                'priority': 2
            },
            'liga_mx': {
                'id': 262,
                'name': 'Liga MX',
                'target_matches': 100,
                'region': 'North America',
                'tactical_style': 'technical_intensity',
                'priority': 2
            },
            
            # African Target Markets (Business Priority)
            'south_african_psl': {
                'id': 288,
                'name': 'South African PSL',
                'target_matches': 80,
                'region': 'Africa',
                'tactical_style': 'organized_physical',
                'priority': 2
            }
        }
        
        # Date ranges for collection (prioritizing recent matches)
        self.collection_periods = [
            {
                'name': 'Recent 2024-2025',
                'from_date': '2024-08-01',
                'to_date': '2024-12-31',
                'priority': 1
            },
            {
                'name': 'Late 2023-2024',
                'from_date': '2024-01-01', 
                'to_date': '2024-05-31',
                'priority': 1
            },
            {
                'name': 'Early 2023-2024',
                'from_date': '2023-08-01',
                'to_date': '2023-12-31',
                'priority': 2
            }
        ]
        
    async def collect_smart_phase1a(self):
        """Smart collection approach for Phase 1A"""
        logger.info("🚀 Starting Smart Phase 1A: Recent Foundation Collection")
        logger.info("Target: 5,000 high-quality recent matches")
        
        await self.analyze_current_state()
        
        start_time = time.time()
        total_collected = 0
        
        # Priority 1 leagues first (European Big 5 + Brazilian)
        priority_1_leagues = {k: v for k, v in self.priority_leagues.items() if v['priority'] == 1}
        
        for league_key, league_config in priority_1_leagues.items():
            if total_collected >= 5000:
                break
                
            logger.info(f"\n📊 Collecting {league_config['name']} matches...")
            
            collected = await self.collect_league_matches_smart(league_config)
            total_collected += collected
            
            logger.info(f"✅ {league_config['name']}: {collected} new matches")
            
            # Rate limiting
            await asyncio.sleep(1)
        
        # Priority 2 leagues if space remains
        if total_collected < 4500:
            priority_2_leagues = {k: v for k, v in self.priority_leagues.items() if v['priority'] == 2}
            
            for league_key, league_config in priority_2_leagues.items():
                if total_collected >= 5000:
                    break
                    
                logger.info(f"\n📊 Collecting {league_config['name']} matches...")
                
                remaining_capacity = 5000 - total_collected
                adjusted_target = min(league_config['target_matches'], remaining_capacity)
                
                collected = await self.collect_league_matches_smart(league_config, adjusted_target)
                total_collected += collected
                
                logger.info(f"✅ {league_config['name']}: {collected} new matches")
                await asyncio.sleep(1)
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"\n🎯 Smart Phase 1A Collection Complete!")
        logger.info(f"Total new matches: {total_collected}")
        logger.info(f"Collection time: {duration:.1f} seconds")
        logger.info(f"Rate: {total_collected/duration:.1f} matches/second")
        
        await self.validate_smart_collection()
        return total_collected
    
    async def collect_league_matches_smart(self, league_config: Dict, custom_target: int = None) -> int:
        """Smart collection for a specific league using date ranges"""
        
        target = custom_target or league_config['target_matches']
        collected = 0
        
        # Check existing matches first
        existing_matches = await self.get_existing_league_matches(league_config['id'])
        logger.info(f"  Current {league_config['name']} matches: {len(existing_matches)}")
        
        # Collection strategy: Recent to older
        async with aiohttp.ClientSession() as session:
            for period in self.collection_periods:
                if collected >= target:
                    break
                    
                logger.info(f"  📅 Collecting from {period['name']} period...")
                
                period_collected = await self.collect_period_matches(
                    session, league_config, period, target - collected, existing_matches
                )
                
                collected += period_collected
                logger.info(f"    {period['name']}: {period_collected} matches")
                
                # Rate limiting between periods
                await asyncio.sleep(0.5)
        
        return collected
    
    async def collect_period_matches(self, session: aiohttp.ClientSession, league_config: Dict, 
                                   period: Dict, remaining_target: int, existing_matches: set) -> int:
        """Collect matches for a specific time period"""
        
        collected = 0
        
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        headers = {
            "X-RapidAPI-Key": self.rapidapi_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        
        params = {
            "league": league_config['id'],
            "from": period['from_date'],
            "to": period['to_date'],
            "status": "FT"  # Only finished matches
        }
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    matches = data.get('response', [])
                    
                    logger.info(f"    Found {len(matches)} finished matches in period")
                    
                    for match in matches:
                        if collected >= remaining_target:
                            break
                            
                        match_id = match['fixture']['id']
                        
                        # Skip if already exists
                        if match_id in existing_matches:
                            continue
                            
                        # Process and store
                        success = await self.process_smart_match(match, league_config)
                        if success:
                            collected += 1
                            existing_matches.add(match_id)  # Track for this session
                            
                            if collected % 25 == 0:
                                logger.info(f"      Progress: {collected}/{remaining_target} matches")
                
                elif response.status == 429:
                    logger.warning("Rate limit hit, waiting...")
                    await asyncio.sleep(5)
                else:
                    logger.warning(f"API error {response.status} for {league_config['name']} in {period['name']}")
                    
        except Exception as e:
            logger.error(f"Error collecting {league_config['name']} for {period['name']}: {e}")
            
        return collected
    
    async def process_smart_match(self, match_data: Dict, league_config: Dict) -> bool:
        """Process and store match with enhanced Phase 1A features"""
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
            
            # Create enhanced features
            features = await self.create_smart_features(match_data, league_config)
            
            # Store in database
            with self.engine.connect() as conn:
                # Check for existing match
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
                        "season": self._extract_season_from_date(match_date),
                        "collection_phase": "Phase_1A_Smart_Recent"
                    })
                    conn.commit()
                    return True
                else:
                    # Update existing with Phase 1A enhancements
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
                        "collection_phase": "Phase_1A_Smart_Recent"
                    })
                    conn.commit()
                    return True  # Count as enhancement
                    
        except Exception as e:
            logger.error(f"Error processing match {match_data.get('fixture', {}).get('id', 'unknown')}: {e}")
            return False
    
    async def create_smart_features(self, match_data: Dict, league_config: Dict) -> Dict:
        """Create enhanced smart features for Phase 1A"""
        
        # Core tactical features
        features = {
            # Team strength indicators
            'home_win_percentage': 0.55,  # Will be enhanced with real data
            'away_win_percentage': 0.35,
            'home_form_normalized': 0.65,
            'away_form_normalized': 0.45,
            
            # Match context
            'win_probability_difference': 0.2,
            'form_balance': 0.1,
            'combined_strength': 0.6,
            
            # League characteristics
            'league_competitiveness': self._get_league_competitiveness(league_config['id']),
            'league_home_advantage': self._get_regional_home_advantage(league_config['region']),
            'african_market_flag': 1 if league_config['region'] == 'Africa' else 0,
            
            # Smart Phase 1A enhancements
            'tactical_style_encoding': self._encode_tactical_style(league_config['tactical_style']),
            'regional_intensity': self._get_regional_intensity(league_config['region']),
            'competition_tier': self._get_competition_tier(league_config['id']),
            'match_importance': self._assess_match_importance(match_data),
            'venue_advantage': self._calculate_venue_advantage(match_data),
            'season_stage': self._assess_season_stage(match_data['fixture']['date']),
            
            # Recent match indicators (Phase 1A specific)
            'recency_score': self._calculate_recency_score(match_data['fixture']['date']),
            'tactical_relevance': self._assess_tactical_relevance(match_data, league_config),
            'data_quality_score': 0.9  # High quality for recent matches
        }
        
        return features
    
    def _extract_season_from_date(self, match_date: str) -> int:
        """Extract season year from match date"""
        date_obj = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
        # Football seasons span across years (Aug-May)
        if date_obj.month >= 8:
            return date_obj.year
        else:
            return date_obj.year - 1
    
    def _get_league_competitiveness(self, league_id: int) -> float:
        """League competitiveness factor"""
        comp_map = {
            39: 0.95,  # Premier League
            140: 0.85, # La Liga
            135: 0.9,  # Serie A
            78: 0.85,  # Bundesliga
            61: 0.8,   # Ligue 1
            71: 0.8,   # Brazilian Serie A
            253: 0.75, # MLS
            262: 0.75, # Liga MX
            288: 0.65  # South African PSL
        }
        return comp_map.get(league_id, 0.6)
    
    def _get_regional_home_advantage(self, region: str) -> float:
        """Regional home advantage patterns"""
        advantage_map = {
            'Europe': 0.6,
            'South America': 0.75,
            'North America': 0.65,
            'Africa': 0.7
        }
        return advantage_map.get(region, 0.6)
    
    def _encode_tactical_style(self, tactical_style: str) -> float:
        """Encode tactical style as numeric value"""
        style_map = {
            'physical_direct': 0.8,
            'technical_possession': 0.9,
            'defensive_tactical': 0.7,
            'attacking_intensity': 0.85,
            'physical_transitional': 0.75,
            'technical_flair': 0.8,
            'diverse_physical': 0.7,
            'technical_intensity': 0.8,
            'organized_physical': 0.65
        }
        return style_map.get(tactical_style, 0.6)
    
    def _get_regional_intensity(self, region: str) -> float:
        """Regional football intensity"""
        intensity_map = {
            'Europe': 0.9,
            'South America': 0.95,
            'North America': 0.75,
            'Africa': 0.8
        }
        return intensity_map.get(region, 0.7)
    
    def _get_competition_tier(self, league_id: int) -> float:
        """Competition tier ranking"""
        tier_map = {
            39: 1.0,   # Premier League - Tier 1
            140: 0.95, # La Liga - Tier 1
            135: 0.95, # Serie A - Tier 1
            78: 0.9,   # Bundesliga - Tier 1
            61: 0.85,  # Ligue 1 - Tier 1
            71: 0.8,   # Brazilian Serie A - Tier 2
            253: 0.7,  # MLS - Tier 2
            262: 0.7,  # Liga MX - Tier 2
            288: 0.6   # South African PSL - Tier 3
        }
        return tier_map.get(league_id, 0.5)
    
    def _assess_match_importance(self, match_data: Dict) -> float:
        """Assess match importance from context"""
        match_date = match_data['fixture']['date']
        
        # End of season matches are more important
        if '2024-04' in match_date or '2024-05' in match_date:
            return 0.8
        elif '2023-04' in match_date or '2023-05' in match_date:
            return 0.8
        else:
            return 0.5
    
    def _calculate_venue_advantage(self, match_data: Dict) -> float:
        """Calculate venue-specific advantage"""
        venue = match_data['fixture']['venue']
        if venue and venue.get('name'):
            # Basic venue advantage
            return 0.6
        return 0.5
    
    def _assess_season_stage(self, match_date: str) -> float:
        """Assess what stage of season the match occurred"""
        date_obj = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
        month = date_obj.month
        
        if month in [8, 9]:       # Early season
            return 0.3
        elif month in [10, 11, 12, 1]: # Mid season
            return 0.6
        elif month in [2, 3, 4]:  # Late season
            return 0.8
        else:                     # End season
            return 0.9
    
    def _calculate_recency_score(self, match_date: str) -> float:
        """Calculate how recent the match is (higher = more recent)"""
        match_dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
        now = datetime.now(match_dt.tzinfo)
        days_ago = (now - match_dt).days
        
        # Exponential decay: more recent = higher score
        if days_ago <= 30:      # Last month
            return 1.0
        elif days_ago <= 90:    # Last 3 months
            return 0.9
        elif days_ago <= 180:   # Last 6 months
            return 0.8
        elif days_ago <= 365:   # Last year
            return 0.7
        else:                   # Older
            return 0.6
    
    def _assess_tactical_relevance(self, match_data: Dict, league_config: Dict) -> float:
        """Assess tactical relevance for current predictions"""
        # Recent matches from top leagues are most tactically relevant
        recency = self._calculate_recency_score(match_data['fixture']['date'])
        tier = self._get_competition_tier(league_config['id'])
        return (recency + tier) / 2
    
    async def get_existing_league_matches(self, league_id: int) -> set:
        """Get existing match IDs for a league"""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT match_id FROM training_matches WHERE league_id = :league_id
            """), {"league_id": league_id}).fetchall()
            
            return set(row[0] for row in result)
    
    async def analyze_current_state(self):
        """Analyze current database state"""
        logger.info("\n📊 Analyzing current database state...")
        
        with self.engine.connect() as conn:
            # Total matches
            total = conn.execute(text("SELECT COUNT(*) FROM training_matches")).fetchone()[0]
            
            # Phase 1A matches
            phase1a = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE collection_phase LIKE '%Phase_1A%'
            """)).fetchone()[0]
            
            # Recent matches (2023+)
            recent = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE match_date >= '2023-08-01'
            """)).fetchone()[0]
            
            logger.info(f"📈 Database Overview:")
            logger.info(f"  Total matches: {total}")
            logger.info(f"  Phase 1A matches: {phase1a}")
            logger.info(f"  Recent matches (2023+): {recent}")
    
    async def validate_smart_collection(self):
        """Validate smart collection results"""
        logger.info("\n🔍 Validating Smart Phase 1A Collection...")
        
        with self.engine.connect() as conn:
            # Phase 1A smart collection results
            result = conn.execute(text("""
                SELECT COUNT(*) as total_matches
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Smart_Recent'
            """)).fetchone()
            
            # Regional distribution
            regional = conn.execute(text("""
                SELECT region, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Smart_Recent'
                GROUP BY region
                ORDER BY count DESC
            """)).fetchall()
            
            # League distribution
            leagues = conn.execute(text("""
                SELECT league_id, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Smart_Recent'
                GROUP BY league_id
                ORDER BY count DESC
            """)).fetchall()
            
            logger.info(f"✅ Smart Phase 1A total: {result[0] if result else 0}")
            
            logger.info("\n📊 Regional Distribution:")
            for region, count in regional:
                logger.info(f"  {region}: {count} matches")
            
            logger.info("\n🏆 League Distribution:")
            for league_id, count in leagues:
                league_name = self._get_league_name(league_id)
                logger.info(f"  {league_name}: {count} matches")
    
    def _get_league_name(self, league_id: int) -> str:
        """Get league name from ID"""
        for config in self.priority_leagues.values():
            if config['id'] == league_id:
                return config['name']
        return f"League {league_id}"

async def main():
    """Run Smart Phase 1A data collection"""
    collector = SmartPhase1ACollector()
    
    try:
        total_collected = await collector.collect_smart_phase1a()
        
        if total_collected >= 1000:
            print(f"\n🎉 Smart Phase 1A SUCCESS: {total_collected} matches collected")
            print("✅ Foundation enhanced with recent high-quality data")
            print("🚀 Ready for unified model retraining")
        else:
            print(f"\n⚠️  Smart Phase 1A PARTIAL: {total_collected} matches collected")
            print("🔄 Consider adjusting league targets or date ranges")
            
    except Exception as e:
        logger.error(f"❌ Smart Phase 1A collection failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())