"""
Simple Phase 1A Enhancer
Shows how we enhance existing 1,893 matches for the 15K strategy
"""

import os
import json
from sqlalchemy import create_engine, text
from datetime import datetime

class SimplePhase1AEnhancer:
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.engine = create_engine(self.database_url)
    
    def enhance_foundation(self):
        """Enhance existing matches with Phase 1A features"""
        print("🔧 Enhancing existing 1,893 matches for 15K strategy...")
        
        # First, analyze what we currently have
        self.analyze_current_data()
        
        # Enhance a sample to show the concept
        enhanced_count = self.enhance_sample_matches()
        
        # Show 15K strategy gaps
        self.show_15k_strategy()
        
        return enhanced_count
    
    def analyze_current_data(self):
        """Analyze current database content"""
        print("\n📊 Current Database Analysis:")
        
        with self.engine.connect() as conn:
            # Total matches
            total = conn.execute(text("SELECT COUNT(*) FROM training_matches")).fetchone()[0]
            
            # League breakdown
            leagues = conn.execute(text("""
                SELECT league_id, COUNT(*) as count
                FROM training_matches
                GROUP BY league_id
                ORDER BY count DESC
                LIMIT 10
            """)).fetchall()
            
            print(f"  Total matches: {total}")
            print(f"  Top leagues:")
            
            league_names = {39: 'Premier League', 140: 'La Liga', 135: 'Serie A', 
                          78: 'Bundesliga', 61: 'Ligue 1', 40: 'Championship'}
            
            for league_id, count in leagues:
                name = league_names.get(league_id, f'League {league_id}')
                print(f"    {name}: {count} matches")
    
    def enhance_sample_matches(self):
        """Enhance a sample of matches to demonstrate concept"""
        print("\n🚀 Enhancing sample matches with Phase 1A features...")
        
        enhanced_count = 0
        
        with self.engine.connect() as conn:
            # Get first 100 matches as sample
            matches = conn.execute(text("""
                SELECT match_id, league_id, match_date, features
                FROM training_matches
                LIMIT 100
            """)).fetchall()
            
            for match_id, league_id, match_date, current_features in matches:
                # Parse existing features
                try:
                    features = json.loads(current_features) if current_features else {}
                except:
                    features = {}
                
                # Add Phase 1A enhancements
                enhanced_features = {
                    **features,  # Keep existing features
                    'tactical_style_factor': self.get_tactical_factor(league_id),
                    'regional_intensity': self.get_regional_intensity(league_id),
                    'competition_tier': self.get_competition_tier(league_id),
                    'recency_score': self.calculate_recency(match_date),
                    'phase1a_enhanced': True,
                    'enhancement_timestamp': datetime.now().isoformat()
                }
                
                # Update match
                conn.execute(text("""
                    UPDATE training_matches 
                    SET features = :features,
                        collection_phase = 'Phase_1A_Enhanced_Sample'
                    WHERE match_id = :match_id
                """), {
                    "match_id": match_id,
                    "features": json.dumps(enhanced_features)
                })
                
                enhanced_count += 1
            
            conn.commit()
        
        print(f"  ✅ Enhanced {enhanced_count} matches with Phase 1A features")
        return enhanced_count
    
    def get_tactical_factor(self, league_id):
        """Get tactical style factor for league"""
        tactical_map = {
            39: 0.9,   # Premier League - physical direct
            140: 0.95, # La Liga - technical possession
            135: 0.85, # Serie A - defensive tactical
            78: 0.9,   # Bundesliga - attacking intensity
            61: 0.8    # Ligue 1 - physical transitional
        }
        return tactical_map.get(league_id, 0.7)
    
    def get_regional_intensity(self, league_id):
        """Get regional intensity factor"""
        # European leagues have high intensity
        european_leagues = [39, 140, 135, 78, 61, 40]
        if league_id in european_leagues:
            return 0.9
        else:
            return 0.7
    
    def get_competition_tier(self, league_id):
        """Get competition tier (1=top, 3=developing)"""
        tier_map = {
            39: 1,  # Premier League
            140: 1, # La Liga
            135: 1, # Serie A
            78: 1,  # Bundesliga
            61: 1,  # Ligue 1
            40: 2   # Championship
        }
        return tier_map.get(league_id, 3)
    
    def calculate_recency(self, match_date):
        """Calculate how recent the match is"""
        try:
            if isinstance(match_date, str):
                match_dt = datetime.fromisoformat(match_date.replace('Z', '+00:00'))
            else:
                match_dt = match_date
            
            now = datetime.now(match_dt.tzinfo if match_dt.tzinfo else None)
            days_ago = (now - match_dt).days
            
            if days_ago <= 365:  # Last year
                return 0.9
            elif days_ago <= 730:  # Last 2 years
                return 0.7
            else:
                return 0.5
        except:
            return 0.5
    
    def show_15k_strategy(self):
        """Show what we need for 15K total matches"""
        print("\n🎯 15,000 Match Strategy Analysis:")
        
        current_total = 1893
        target_total = 15000
        needed = target_total - current_total
        
        print(f"  Current foundation: {current_total:,} matches")
        print(f"  Target total: {target_total:,} matches")
        print(f"  Still needed: {needed:,} matches")
        
        print(f"\n📋 Suggested Phase 1B Collection:")
        print(f"  European leagues (additional): {int(needed * 0.4):,} matches (40%)")
        print(f"  South American leagues: {int(needed * 0.25):,} matches (25%)")
        print(f"  African target markets: {int(needed * 0.2):,} matches (20%)")
        print(f"  Global diversification: {int(needed * 0.15):,} matches (15%)")
        
        print(f"\n✨ Benefits of Phase 1A Enhancement:")
        print(f"  ✅ Current matches become higher quality training data")
        print(f"  ✅ Better model accuracy with enhanced features")
        print(f"  ✅ Clear roadmap for reaching 15,000 matches")
        print(f"  ✅ Improved predictions for African target markets")

def main():
    enhancer = SimplePhase1AEnhancer()
    enhanced_count = enhancer.enhance_foundation()
    
    print(f"\n🎉 Phase 1A Enhancement Demonstration Complete!")
    print(f"Enhanced {enhanced_count} sample matches to show the concept")
    print(f"This approach makes our current data more valuable while planning Phase 1B")

if __name__ == "__main__":
    main()