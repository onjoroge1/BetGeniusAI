"""
Comprehensive Data Collection Strategy - Full Dataset Design
Based on existing 1,893 training matches with features
"""

import psycopg2
import pandas as pd
import json
import os
from typing import Dict, List, Optional
from datetime import datetime

class ComprehensiveDataStrategy:
    """Analyze existing data and design comprehensive collection strategy"""
    
    def __init__(self):
        self.euro_leagues = {
            39: 'Premier League',
            140: 'La Liga',
            135: 'Serie A', 
            78: 'Bundesliga',
            61: 'Ligue 1'
        }
        
        # African leagues for target market
        self.african_leagues = {
            88: 'Kenya Premier League',
            143: 'Uganda Premier League',
            203: 'South African Premier Division',
            179: 'Tanzanian Premier League'
        }
    
    def analyze_existing_data(self) -> Dict:
        """Analyze what we already have in training_matches"""
        
        print("ANALYZING EXISTING TRAINING DATA")
        print("=" * 50)
        
        try:
            conn = psycopg2.connect(os.environ['DATABASE_URL'])
            
            # Overall statistics
            query1 = """
            SELECT 
                COUNT(*) as total_matches,
                COUNT(DISTINCT league_id) as leagues,
                COUNT(DISTINCT season) as seasons,
                COUNT(CASE WHEN features IS NOT NULL THEN 1 END) as with_features,
                MIN(match_date) as earliest,
                MAX(match_date) as latest
            FROM training_matches
            """
            
            overall_stats = pd.read_sql_query(query1, conn).iloc[0]
            
            # Per-league breakdown
            query2 = """
            SELECT 
                league_id,
                COUNT(*) as matches,
                COUNT(DISTINCT season) as seasons,
                COUNT(CASE WHEN features IS NOT NULL THEN 1 END) as with_features,
                MIN(match_date) as earliest,
                MAX(match_date) as latest
            FROM training_matches 
            GROUP BY league_id 
            ORDER BY matches DESC
            """
            
            league_stats = pd.read_sql_query(query2, conn)
            
            # Sample features to understand structure
            query3 = """
            SELECT features 
            FROM training_matches 
            WHERE features IS NOT NULL 
            LIMIT 3
            """
            
            sample_features = pd.read_sql_query(query3, conn)
            
            conn.close()
            
            return {
                'overall': overall_stats.to_dict(),
                'per_league': league_stats.to_dict('records'),
                'sample_features': sample_features['features'].tolist()
            }
            
        except Exception as e:
            print(f"Error analyzing data: {e}")
            return {}
    
    def design_comprehensive_dataset(self) -> Dict:
        """Design comprehensive data collection strategy"""
        
        print("\nCOMPREHENSIVE DATA COLLECTION STRATEGY")
        print("=" * 50)
        
        strategy = {
            "current_status": {
                "existing_matches": 1893,
                "leagues_covered": 10,
                "primary_league": "Premier League (960 matches)",
                "feature_richness": "JSONB features column available"
            },
            
            "core_data_layers": {
                "1_match_basics": {
                    "description": "Basic match outcome data",
                    "fields": [
                        "match_id", "league_id", "season", "match_date",
                        "home_team", "away_team", "home_goals", "away_goals", "outcome",
                        "venue", "referee", "attendance"
                    ],
                    "status": "✅ HAVE",
                    "coverage": "1,893 matches across 10 leagues"
                },
                
                "2_team_performance": {
                    "description": "Team strength and recent form metrics",
                    "fields": [
                        "home_elo", "away_elo", "elo_difference",
                        "home_form_pts", "away_form_pts", "form_difference",
                        "home_attack_rating", "away_attack_rating",
                        "home_defense_rating", "away_defense_rating",
                        "home_win_pct", "away_win_pct", "h2h_record"
                    ],
                    "status": "🔄 PARTIAL",
                    "coverage": "Basic features in JSONB, need enhancement"
                },
                
                "3_tactical_context": {
                    "description": "Playing style and tactical setup",
                    "fields": [
                        "home_formation", "away_formation",
                        "home_playing_style", "away_playing_style",
                        "possession_tendency", "attacking_tendency",
                        "pressing_intensity", "defensive_line_height"
                    ],
                    "status": "❌ MISSING",
                    "coverage": "Need tactical analysis integration"
                },
                
                "4_player_availability": {
                    "description": "Key player injuries and suspensions",
                    "fields": [
                        "home_key_players_out", "away_key_players_out",
                        "home_injury_severity", "away_injury_severity",
                        "home_suspension_count", "away_suspension_count",
                        "home_player_value_missing", "away_player_value_missing"
                    ],
                    "status": "❌ MISSING",
                    "coverage": "Critical for real-world accuracy"
                },
                
                "5_match_context": {
                    "description": "Situational and motivational factors",
                    "fields": [
                        "league_position_home", "league_position_away",
                        "points_gap", "relegation_pressure", "title_pressure",
                        "european_qualification_pressure", "derby_flag",
                        "rest_days_difference", "fixture_congestion",
                        "season_phase", "weather_conditions"
                    ],
                    "status": "🔄 PARTIAL",
                    "coverage": "Some context in features, need expansion"
                },
                
                "6_market_intelligence": {
                    "description": "Betting market and public sentiment",
                    "fields": [
                        "opening_odds_home", "opening_odds_draw", "opening_odds_away",
                        "closing_odds_home", "closing_odds_draw", "closing_odds_away",
                        "line_movement", "betting_volume", "public_sentiment",
                        "sharp_money_indicators", "market_efficiency_score"
                    ],
                    "status": "❌ MISSING",
                    "coverage": "Would significantly improve predictions"
                },
                
                "7_expected_performance": {
                    "description": "Pre-match performance expectations",
                    "fields": [
                        "home_xg_avg", "away_xg_avg", "xg_difference",
                        "home_xga_avg", "away_xga_avg", "xga_difference",
                        "expected_possession", "expected_shots",
                        "expected_corners", "expected_cards"
                    ],
                    "status": "🔄 PARTIAL",
                    "coverage": "Basic xG in features, need enhancement"
                }
            },
            
            "data_sources_needed": {
                "primary_apis": [
                    "RapidAPI Football (match data, team stats)",
                    "Football-Data.org (historical results)",
                    "API-Sports (comprehensive stats)",
                    "FiveThirtyEight (team ratings, predictions)"
                ],
                "supplementary_sources": [
                    "TransferMarkt (player values, injuries)",
                    "SofaScore (detailed match stats)",
                    "Opta/Stats Perform (advanced metrics)",
                    "Betting APIs (odds data)",
                    "Weather APIs (match conditions)"
                ],
                "manual_curation": [
                    "Tactical analysis from expert sources",
                    "Derby/rivalry classifications",
                    "Manager style classifications",
                    "Stadium atmosphere ratings"
                ]
            },
            
            "target_dataset_size": {
                "european_leagues": {
                    "target_matches_per_league": 1500,  # 5 seasons
                    "leagues": 5,
                    "total_matches": 7500,
                    "feature_completeness": "90%+"
                },
                "african_leagues": {
                    "target_matches_per_league": 500,   # 3 seasons
                    "leagues": 4,
                    "total_matches": 2000,
                    "feature_completeness": "70%+"
                },
                "total_comprehensive_dataset": 9500
            },
            
            "quality_requirements": {
                "minimum_features_per_match": 25,
                "maximum_missing_data_percentage": 10,
                "temporal_coverage": "2019-2024 (5 years)",
                "validation_methodology": "Time-series split with 6-month holdout",
                "feature_leakage_prevention": "T-24h cutoff for all features"
            }
        }
        
        return strategy
    
    def prioritize_collection_phases(self) -> List[Dict]:
        """Prioritize data collection phases by impact and feasibility"""
        
        phases = [
            {
                "phase": "Phase 1A: Enhance Existing Data",
                "priority": "HIGH",
                "timeline": "1-2 weeks",
                "description": "Enhance existing 1,893 matches with missing features",
                "tasks": [
                    "Extract and standardize existing JSONB features",
                    "Calculate missing team strength metrics",
                    "Add league context and seasonal factors",
                    "Compute head-to-head records",
                    "Add match importance scoring"
                ],
                "expected_improvement": "15-20% accuracy gain",
                "feasibility": "HIGH - uses existing data"
            },
            
            {
                "phase": "Phase 1B: Historical Backfill",
                "priority": "HIGH", 
                "timeline": "2-3 weeks",
                "description": "Expand to 5,000+ matches with RapidAPI",
                "tasks": [
                    "Collect 3-5 seasons per European league",
                    "Backfill African league data", 
                    "Standardize team and venue data",
                    "Calculate rolling team metrics",
                    "Build comprehensive match database"
                ],
                "expected_improvement": "10-15% accuracy gain",
                "feasibility": "MEDIUM - API rate limits"
            },
            
            {
                "phase": "Phase 2: Player & Injury Intelligence",
                "priority": "MEDIUM",
                "timeline": "3-4 weeks", 
                "description": "Add player availability and impact scoring",
                "tasks": [
                    "Integrate injury/suspension APIs",
                    "Build key player identification system",
                    "Calculate player impact scores",
                    "Track lineup changes and rotations",
                    "Model player absence effects"
                ],
                "expected_improvement": "8-12% accuracy gain",
                "feasibility": "MEDIUM - data complexity"
            },
            
            {
                "phase": "Phase 3: Market Intelligence",
                "priority": "MEDIUM",
                "timeline": "4-6 weeks",
                "description": "Integrate betting market data and sentiment",
                "tasks": [
                    "Collect historical odds data",
                    "Track line movements and volume",
                    "Build market efficiency indicators",
                    "Integrate public sentiment metrics",
                    "Create market-anchored features"
                ],
                "expected_improvement": "5-8% accuracy gain",
                "feasibility": "LOW - expensive data sources"
            },
            
            {
                "phase": "Phase 4: Advanced Context",
                "priority": "LOW",
                "timeline": "6-8 weeks",
                "description": "Add tactical analysis and situational context",
                "tasks": [
                    "Tactical formation analysis",
                    "Weather condition integration",
                    "Stadium atmosphere modeling",
                    "Manager style classification",
                    "Psychological pressure indicators"
                ],
                "expected_improvement": "3-5% accuracy gain", 
                "feasibility": "LOW - manual curation needed"
            }
        ]
        
        return phases
    
    def generate_implementation_plan(self, analysis: Dict, strategy: Dict, phases: List[Dict]) -> str:
        """Generate actionable implementation plan"""
        
        plan = f"""
# COMPREHENSIVE DATA COLLECTION IMPLEMENTATION PLAN

## Current State Assessment
✅ **Strong Foundation**: {analysis['overall']['total_matches']} matches across {analysis['overall']['leagues']} leagues
✅ **Feature-Rich**: JSONB features column with structured data
✅ **European Focus**: Premier League (960 matches) well-covered
⚠️  **Feature Gaps**: Missing player, tactical, and market data
⚠️  **African Coverage**: Limited data for target markets

## Immediate Actions (Next 1-2 Weeks)

### 1. Data Quality Audit
```sql
-- Check feature completeness
SELECT 
    league_id,
    COUNT(*) as matches,
    COUNT(CASE WHEN features IS NOT NULL THEN 1 END) as with_features,
    AVG(CASE WHEN features IS NOT NULL THEN 1 ELSE 0 END) * 100 as feature_coverage
FROM training_matches 
GROUP BY league_id;
```

### 2. Feature Standardization  
- Extract all features from JSONB into structured columns
- Standardize team strength calculations across leagues
- Implement time-aware feature engineering (T-24h constraint)
- Calculate missing derived features (elo_diff, form_diff, etc.)

### 3. Enhanced Model Training
- Use existing 1,893 matches for immediate improvement
- Implement proper time-series validation
- Compare against verified 36.8% baseline
- Target: 45-50% accuracy with enhanced features

## Medium-Term Expansion (2-8 Weeks)

### Phase 1B: Historical Backfill
**Target**: Expand to 5,000+ matches
- Premier League: 1,500 matches (5 seasons) 
- La Liga: 1,200 matches (4 seasons)
- Serie A: 1,200 matches (4 seasons)
- Bundesliga: 1,200 matches (4 seasons)
- Ligue 1: 1,200 matches (4 seasons)

### Phase 2: African Market Focus
**Target**: 2,000+ African league matches
- Kenya Premier League: 500 matches
- Uganda Premier League: 400 matches
- South African Premier Division: 600 matches
- Tanzanian Premier League: 500 matches

### Phase 3: Player Intelligence Layer
**High-Impact Features**:
- Key player injury status (availability at T-24h)
- Squad rotation and fatigue indicators
- Player value-weighted team strength
- Lineup prediction based on recent patterns

## Success Metrics

### Accuracy Targets
- **Current Baseline**: 36.8% (verified)
- **Phase 1A Target**: 45-50% (enhanced features)
- **Phase 1B Target**: 52-55% (more data)
- **Phase 2 Target**: 55-58% (player intelligence)
- **Phase 3 Target**: 58-60% (market anchoring)

### Data Quality Gates
- Feature completeness: >90% for core features
- Time coverage: 5+ years historical data
- League coverage: 5 European + 4 African leagues
- Validation accuracy: Within 2% of test accuracy

## Resource Requirements

### Technical Infrastructure
- Enhanced database schema for structured features
- Feature engineering pipeline with T-24h constraints
- Model training infrastructure with proper validation
- API integration framework with rate limiting

### Data Sources (Priority Order)
1. **Internal Enhancement**: Existing training_matches table
2. **RapidAPI Football**: Historical match expansion
3. **Player APIs**: Injury and availability data
4. **Market APIs**: Betting odds and line movements

### Timeline Summary
- **Week 1-2**: Enhance existing data, achieve 45-50% accuracy
- **Week 3-6**: Historical backfill to 5,000+ matches
- **Week 7-10**: Player intelligence integration
- **Week 11-16**: Market data and advanced features

## Next Immediate Step
**Start with Phase 1A**: Enhance existing 1,893 matches by extracting and standardizing features from JSONB column. This gives immediate improvement with zero additional API costs.
"""
        
        return plan

def main():
    """Generate comprehensive data strategy"""
    
    strategy_analyzer = ComprehensiveDataStrategy()
    
    # Analyze existing data
    analysis = strategy_analyzer.analyze_existing_data()
    
    # Design comprehensive strategy  
    strategy = strategy_analyzer.design_comprehensive_dataset()
    
    # Prioritize phases
    phases = strategy_analyzer.prioritize_collection_phases()
    
    # Generate implementation plan
    plan = strategy_analyzer.generate_implementation_plan(analysis, strategy, phases)
    
    # Save comprehensive analysis
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    os.makedirs('reports', exist_ok=True)
    
    with open(f'reports/comprehensive_data_strategy_{timestamp}.json', 'w') as f:
        json.dump({
            'analysis': analysis,
            'strategy': strategy, 
            'phases': phases,
            'timestamp': timestamp
        }, f, indent=2, default=str)
    
    with open(f'reports/implementation_plan_{timestamp}.md', 'w') as f:
        f.write(plan)
    
    print(plan)
    print(f"\nDetailed analysis saved:")
    print(f"  Strategy: reports/comprehensive_data_strategy_{timestamp}.json")
    print(f"  Plan: reports/implementation_plan_{timestamp}.md")

if __name__ == "__main__":
    main()