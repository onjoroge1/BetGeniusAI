"""
Phase 1A Enhancement System
Instead of collecting new matches, enhance existing 1,893 matches with Phase 1A features
Prepares foundation for Phase 1B collection targeting 15,000 total matches
"""

import asyncio
import json
import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, text
from typing import Dict, List, Any
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Phase1AEnhancementSystem:
    """Enhance existing matches with Phase 1A features for 15K foundation"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL required")
        self.engine = create_engine(self.database_url)
        
        # League classifications for enhancement
        self.league_classifications = {
            # European Big 5 (Tier 1 - Tactical Foundation)
            39: {'name': 'Premier League', 'region': 'Europe', 'tactical_style': 'physical_direct', 
                 'tier': 1, 'competitiveness': 0.95, 'home_advantage': 0.6},
            140: {'name': 'La Liga', 'region': 'Europe', 'tactical_style': 'technical_possession',
                  'tier': 1, 'competitiveness': 0.85, 'home_advantage': 0.6},
            135: {'name': 'Serie A', 'region': 'Europe', 'tactical_style': 'defensive_tactical',
                  'tier': 1, 'competitiveness': 0.9, 'home_advantage': 0.6},
            78: {'name': 'Bundesliga', 'region': 'Europe', 'tactical_style': 'attacking_intensity',
                 'tier': 1, 'competitiveness': 0.85, 'home_advantage': 0.6},
            61: {'name': 'Ligue 1', 'region': 'Europe', 'tactical_style': 'physical_transitional',
                 'tier': 1, 'competitiveness': 0.8, 'home_advantage': 0.6},
            
            # Additional European Leagues (Tier 2)
            40: {'name': 'Championship', 'region': 'Europe', 'tactical_style': 'physical_competitive',
                 'tier': 2, 'competitiveness': 0.75, 'home_advantage': 0.65},
            88: {'name': 'Eredivisie', 'region': 'Europe', 'tactical_style': 'technical_attacking',
                 'tier': 2, 'competitiveness': 0.7, 'home_advantage': 0.6},
            143: {'name': 'Brazilian Serie A', 'region': 'South America', 'tactical_style': 'technical_flair',
                  'tier': 2, 'competitiveness': 0.8, 'home_advantage': 0.75},
            203: {'name': 'Turkish Super Lig', 'region': 'Europe', 'tactical_style': 'passionate_physical',
                  'tier': 2, 'competitiveness': 0.7, 'home_advantage': 0.7},
            179: {'name': 'Scottish Premiership', 'region': 'Europe', 'tactical_style': 'physical_direct',
                  'tier': 2, 'competitiveness': 0.65, 'home_advantage': 0.7},
            
            # Developing Markets (Tier 3 - Target Markets)
            399: {'name': 'Egyptian Premier League', 'region': 'Africa', 'tactical_style': 'organized_physical',
                  'tier': 3, 'competitiveness': 0.6, 'home_advantage': 0.75}
        }
        
    async def enhance_phase1a_foundation(self):
        """Main enhancement process for Phase 1A foundation"""
        logger.info("🚀 Starting Phase 1A Foundation Enhancement")
        logger.info("Enhancing existing 1,893 matches with Phase 1A features")
        
        start_time = time.time()
        
        # Analyze current state
        await self.analyze_current_foundation()
        
        # Enhance all existing matches
        enhanced_count = await self.enhance_existing_matches()
        
        # Classify matches for Phase 1B strategy
        await self.classify_matches_for_phase1b()
        
        # Generate Phase 1B collection targets
        await self.generate_phase1b_targets()
        
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info(f"\n🎯 Phase 1A Enhancement Complete!")
        logger.info(f"Enhanced matches: {enhanced_count}")
        logger.info(f"Enhancement time: {duration:.1f} seconds")
        
        await self.validate_enhancement()
        return enhanced_count
    
    async def analyze_current_foundation(self):
        """Analyze current database foundation"""
        logger.info("\n📊 Analyzing Current Foundation...")
        
        with self.engine.connect() as conn:
            # Total matches
            total = conn.execute(text("SELECT COUNT(*) FROM training_matches")).fetchone()[0]
            
            # League distribution
            league_dist = conn.execute(text("""
                SELECT league_id, COUNT(*) as count
                FROM training_matches
                GROUP BY league_id
                ORDER BY count DESC
            """)).fetchall()
            
            # Date range analysis
            date_range = conn.execute(text("""
                SELECT 
                    MIN(match_date) as earliest,
                    MAX(match_date) as latest,
                    COUNT(CASE WHEN match_date >= '2023-08-01' THEN 1 END) as recent_2023_24,
                    COUNT(CASE WHEN match_date >= '2024-08-01' THEN 1 END) as current_2024_25
                FROM training_matches
            """)).fetchone()
            
            logger.info(f"📈 Foundation Analysis:")
            logger.info(f"  Total matches: {total}")
            logger.info(f"  Date range: {date_range[0]} to {date_range[1]}")
            logger.info(f"  2023-24 season: {date_range[2]} matches")
            logger.info(f"  2024-25 season: {date_range[3]} matches")
            
            logger.info(f"\n🏆 League Distribution:")
            for league_id, count in league_dist[:10]:  # Top 10 leagues
                league_info = self.league_classifications.get(league_id, {'name': f'League {league_id}'})
                logger.info(f"  {league_info['name']}: {count} matches")
    
    async def enhance_existing_matches(self):
        """Enhance all existing matches with Phase 1A features"""
        logger.info("\n🔧 Enhancing existing matches with Phase 1A features...")
        
        enhanced_count = 0
        batch_size = 100
        
        with self.engine.connect() as conn:
            # Get all matches that need enhancement
            result = conn.execute(text("""
                SELECT match_id, league_id, match_date, home_team, away_team, 
                       home_goals, away_goals, outcome, venue, features
                FROM training_matches
                ORDER BY match_date DESC
            """)).fetchall()
            
            total_matches = len(result)
            logger.info(f"Processing {total_matches} matches for enhancement...")
            
            for i in range(0, total_matches, batch_size):
                batch = result[i:i + batch_size]
                
                for match_row in batch:
                    match_id, league_id, match_date, home_team, away_team, home_goals, away_goals, outcome, venue, existing_features = match_row
                    
                    # Create enhanced features
                    enhanced_features = await self.create_phase1a_enhanced_features(
                        match_id, league_id, match_date, home_team, away_team, 
                        home_goals, away_goals, outcome, venue, existing_features
                    )
                    
                    # Get league classification
                    league_info = self.league_classifications.get(league_id, {
                        'region': 'Unknown', 'tactical_style': 'balanced', 'tier': 3
                    })
                    
                    # Update match with enhancements
                    conn.execute(text("""
                        UPDATE training_matches 
                        SET features = :features,
                            region = :region,
                            tactical_style = :tactical_style,
                            collection_phase = :collection_phase
                        WHERE match_id = :match_id
                    """), {
                        "match_id": match_id,
                        "features": json.dumps(enhanced_features),
                        "region": league_info['region'],
                        "tactical_style": league_info['tactical_style'],
                        "collection_phase": "Phase_1A_Enhanced_Foundation"
                    })
                    
                    enhanced_count += 1
                
                conn.commit()
                
                if (i + batch_size) % 500 == 0:
                    logger.info(f"  Progress: {enhanced_count}/{total_matches} matches enhanced")
        
        logger.info(f"✅ Enhanced {enhanced_count} matches with Phase 1A features")
        return enhanced_count
    
    async def create_phase1a_enhanced_features(self, match_id: int, league_id: int, match_date: str,
                                             home_team: str, away_team: str, home_goals: int, 
                                             away_goals: int, outcome: str, venue: str, 
                                             existing_features: str) -> Dict:
        """Create enhanced Phase 1A features for a match"""
        
        # Parse existing features
        try:
            base_features = json.loads(existing_features) if existing_features else {}
        except:
            base_features = {}
        
        # Get league classification
        league_info = self.league_classifications.get(league_id, {
            'region': 'Unknown', 'tactical_style': 'balanced', 'tier': 3,
            'competitiveness': 0.6, 'home_advantage': 0.6
        })
        
        # Enhanced Phase 1A features
        enhanced_features = {
            # Preserve existing features
            **base_features,
            
            # Enhanced tactical features
            'tactical_style_encoding': self._encode_tactical_style(league_info['tactical_style']),
            'regional_intensity': self._get_regional_intensity(league_info['region']),
            'competition_tier': league_info['tier'] / 3.0,  # Normalize to 0-1
            'league_competitiveness': league_info['competitiveness'],
            'league_home_advantage': league_info['home_advantage'],
            
            # Match context enhancements
            'match_importance': self._assess_match_importance(match_date, league_id),
            'season_stage': self._calculate_season_stage(match_date),
            'recency_score': self._calculate_recency_score(match_date),
            'tactical_relevance': self._assess_tactical_relevance(match_date, league_info['tier']),
            
            # Market and geographic factors
            'african_market_flag': 1 if league_info['region'] == 'Africa' else 0,
            'european_tier1_flag': 1 if (league_info['region'] == 'Europe' and league_info['tier'] == 1) else 0,
            'south_american_flag': 1 if league_info['region'] == 'South America' else 0,
            'developing_market_flag': 1 if league_info['tier'] >= 3 else 0,
            
            # Quality and reliability indicators
            'data_quality_score': self._assess_data_quality(match_date, league_info['tier']),
            'prediction_reliability': self._assess_prediction_reliability(league_info),
            'training_value': self._assess_training_value(match_date, league_info),
            
            # Enhanced match characteristics
            'goal_expectancy': (home_goals + away_goals) / 2.0,
            'competitiveness_indicator': abs(home_goals - away_goals) / max(home_goals + away_goals, 1),
            'venue_advantage_realized': 1 if (outcome == 'Home') else 0,
            
            # Phase 1A specific enhancements
            'phase1a_foundation_score': self._calculate_foundation_score(match_date, league_info),
            'tactical_learning_value': self._assess_tactical_learning_value(league_info),
            'cross_league_applicability': self._assess_cross_league_applicability(league_info)
        }
        
        return enhanced_features
    
    def _encode_tactical_style(self, tactical_style: str) -> float:
        """Encode tactical style numerically"""
        style_map = {
            'physical_direct': 0.8,
            'technical_possession': 0.9,
            'defensive_tactical': 0.7,
            'attacking_intensity': 0.85,
            'physical_transitional': 0.75,
            'physical_competitive': 0.75,
            'technical_flair': 0.8,
            'passionate_physical': 0.8,
            'technical_attacking': 0.85,
            'organized_physical': 0.65,
            'balanced': 0.6
        }
        return style_map.get(tactical_style, 0.6)
    
    def _get_regional_intensity(self, region: str) -> float:
        """Get regional football intensity"""
        intensity_map = {
            'Europe': 0.9,
            'South America': 0.95,
            'North America': 0.75,
            'Africa': 0.8,
            'Asia': 0.7,
            'Unknown': 0.5
        }
        return intensity_map.get(region, 0.5)
    
    def _assess_match_importance(self, match_date: str, league_id: int) -> float:
        """Assess match importance based on date and league"""
        try:
            date_obj = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
            month = date_obj.month
            
            # End of season matches are more important
            if month in [4, 5]:  # April-May
                importance = 0.8
            elif month in [2, 3]:  # February-March
                importance = 0.7
            elif month in [12, 1]:  # December-January
                importance = 0.6
            else:
                importance = 0.5
            
            # Top tier leagues have higher importance
            league_info = self.league_classifications.get(league_id, {'tier': 3})
            tier_bonus = (4 - league_info['tier']) * 0.1
            
            return min(1.0, importance + tier_bonus)
        except:
            return 0.5
    
    def _calculate_season_stage(self, match_date: str) -> float:
        """Calculate season stage (0=early, 1=late)"""
        try:
            date_obj = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
            month = date_obj.month
            
            if month in [8, 9]:  # Early season
                return 0.2
            elif month in [10, 11]:  # Mid-early season
                return 0.4
            elif month in [12, 1]:  # Mid season
                return 0.6
            elif month in [2, 3]:  # Late season
                return 0.8
            else:  # End season
                return 1.0
        except:
            return 0.5
    
    def _calculate_recency_score(self, match_date: str) -> float:
        """Calculate how recent the match is"""
        try:
            match_dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
            now = datetime.now(match_dt.tzinfo)
            days_ago = (now - match_dt).days
            
            if days_ago <= 30:
                return 1.0
            elif days_ago <= 90:
                return 0.9
            elif days_ago <= 180:
                return 0.8
            elif days_ago <= 365:
                return 0.7
            elif days_ago <= 730:  # 2 years
                return 0.6
            else:
                return 0.5
        except:
            return 0.5
    
    def _assess_tactical_relevance(self, match_date: str, tier: int) -> float:
        """Assess tactical relevance for current predictions"""
        recency = self._calculate_recency_score(match_date)
        tier_factor = (4 - tier) / 3.0  # Higher tier = more relevant
        return (recency + tier_factor) / 2
    
    def _assess_data_quality(self, match_date: str, tier: int) -> float:
        """Assess data quality score"""
        recency = self._calculate_recency_score(match_date)
        tier_quality = (4 - tier) / 3.0
        base_quality = 0.8  # Assume good base quality
        
        return min(1.0, base_quality + (recency * 0.1) + (tier_quality * 0.1))
    
    def _assess_prediction_reliability(self, league_info: Dict) -> float:
        """Assess how reliable predictions should be for this league"""
        tier_reliability = (4 - league_info['tier']) / 3.0
        competitiveness_factor = league_info['competitiveness']
        
        return (tier_reliability + competitiveness_factor) / 2
    
    def _assess_training_value(self, match_date: str, league_info: Dict) -> float:
        """Assess training value for ML model"""
        recency = self._calculate_recency_score(match_date)
        tier_value = (4 - league_info['tier']) / 3.0
        competitiveness_value = league_info['competitiveness']
        
        return (recency + tier_value + competitiveness_value) / 3
    
    def _calculate_foundation_score(self, match_date: str, league_info: Dict) -> float:
        """Calculate Phase 1A foundation score"""
        components = [
            self._calculate_recency_score(match_date) * 0.3,
            (4 - league_info['tier']) / 3.0 * 0.3,
            league_info['competitiveness'] * 0.2,
            self._get_regional_intensity(league_info['region']) * 0.2
        ]
        return sum(components)
    
    def _assess_tactical_learning_value(self, league_info: Dict) -> float:
        """Assess tactical learning value"""
        style_complexity = self._encode_tactical_style(league_info['tactical_style'])
        tier_factor = (4 - league_info['tier']) / 3.0
        
        return (style_complexity + tier_factor) / 2
    
    def _assess_cross_league_applicability(self, league_info: Dict) -> float:
        """Assess how applicable learnings are across leagues"""
        if league_info['region'] == 'Europe' and league_info['tier'] == 1:
            return 0.9  # European top leagues are widely applicable
        elif league_info['region'] == 'Europe':
            return 0.8
        elif league_info['tier'] <= 2:
            return 0.7
        else:
            return 0.6
    
    async def classify_matches_for_phase1b(self):
        """Classify enhanced matches for Phase 1B collection strategy"""
        logger.info("\n📋 Classifying matches for Phase 1B strategy...")
        
        with self.engine.connect() as conn:
            # Regional classification
            regional_summary = conn.execute(text("""
                SELECT region, COUNT(*) as count, 
                       AVG(CAST(JSON_EXTRACT(features, '$.phase1a_foundation_score') AS FLOAT)) as avg_foundation_score
                FROM training_matches
                WHERE collection_phase = 'Phase_1A_Enhanced_Foundation'
                GROUP BY region
                ORDER BY count DESC
            """)).fetchall()
            
            logger.info("📊 Regional Foundation Analysis:")
            for region, count, avg_score in regional_summary:
                logger.info(f"  {region}: {count} matches (avg foundation score: {avg_score:.3f})")
    
    async def generate_phase1b_targets(self):
        """Generate Phase 1B collection targets to reach 15,000 matches"""
        logger.info("\n🎯 Generating Phase 1B Collection Targets...")
        
        current_total = 1893  # Current foundation
        target_total = 15000
        needed_matches = target_total - current_total
        
        logger.info(f"📈 Phase 1B Collection Strategy:")
        logger.info(f"  Current foundation: {current_total} matches")
        logger.info(f"  Target total: {target_total} matches")
        logger.info(f"  Phase 1B needed: {needed_matches} matches")
        
        # Suggest Phase 1B distribution
        phase1b_distribution = {
            'European Big 5 (additional)': int(needed_matches * 0.4),  # 40%
            'South American leagues': int(needed_matches * 0.25),      # 25%
            'African target markets': int(needed_matches * 0.2),       # 20%
            'Global diversification': int(needed_matches * 0.15)       # 15%
        }
        
        logger.info("\n🌍 Suggested Phase 1B Distribution:")
        for category, count in phase1b_distribution.items():
            logger.info(f"  {category}: {count} matches")
        
        # Save Phase 1B strategy to database
        strategy_data = {
            'current_foundation': current_total,
            'target_total': target_total,
            'phase1b_needed': needed_matches,
            'distribution': phase1b_distribution,
            'generated_at': datetime.now().isoformat()
        }
        
        with self.engine.connect() as conn:
            # Create or update strategy record
            conn.execute(text("""
                INSERT INTO training_matches 
                (match_id, league_id, home_team, away_team, home_goals, away_goals,
                 outcome, match_date, venue, features, collection_phase)
                VALUES (-1, -1, 'Phase1B', 'Strategy', 0, 0, 'Strategy', NOW(), 'Strategy',
                        :strategy_data, 'Phase_1B_Strategy_Record')
                ON CONFLICT (match_id) DO UPDATE SET features = :strategy_data
            """), {"strategy_data": json.dumps(strategy_data)})
            conn.commit()
    
    async def validate_enhancement(self):
        """Validate Phase 1A enhancement results"""
        logger.info("\n🔍 Validating Phase 1A Enhancement...")
        
        with self.engine.connect() as conn:
            # Enhanced matches count
            enhanced_total = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Enhanced_Foundation'
            """)).fetchone()[0]
            
            # Feature quality check
            feature_check = conn.execute(text("""
                SELECT COUNT(*) FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Enhanced_Foundation'
                AND JSON_EXTRACT(features, '$.phase1a_foundation_score') IS NOT NULL
            """)).fetchone()[0]
            
            # Regional enhancement distribution
            regional_enhanced = conn.execute(text("""
                SELECT region, COUNT(*) as count
                FROM training_matches 
                WHERE collection_phase = 'Phase_1A_Enhanced_Foundation'
                GROUP BY region
                ORDER BY count DESC
            """)).fetchall()
            
            logger.info(f"✅ Enhanced matches: {enhanced_total}")
            logger.info(f"✅ Feature completeness: {feature_check}/{enhanced_total} matches")
            
            logger.info("\n📊 Enhanced Regional Distribution:")
            for region, count in regional_enhanced:
                logger.info(f"  {region}: {count} enhanced matches")

async def main():
    """Run Phase 1A Enhancement System"""
    enhancer = Phase1AEnhancementSystem()
    
    try:
        enhanced_count = await enhancer.enhance_phase1a_foundation()
        
        print(f"\n🎉 Phase 1A Enhancement SUCCESS!")
        print(f"✅ Enhanced {enhanced_count} matches with Phase 1A features")
        print(f"🚀 Foundation prepared for Phase 1B collection to 15,000 matches")
        print(f"📊 Ready for enhanced unified model training")
        
    except Exception as e:
        logger.error(f"❌ Phase 1A enhancement failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())