"""
V2 Feature Builder - TRANSFORMED VERSION
Reduces leakage risk while preserving predictive signal

Key transformations:
1. Bin time features to coarse buckets (reduces uniqueness)
2. Use relative ratios instead of absolute values (team advantage)
3. Result: 4 raw features → 2 transformed features

Expected impact:
- Uniqueness: 81.61% → <50% (more generic patterns)
- Random label accuracy: 42-43% → <40% (pass sanity checks)
- Predictive power: Preserved (relative advantage still captured)
"""

from features.v2_feature_builder import V2FeatureBuilder
from typing import Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class V2FeatureBuilderTransformed(V2FeatureBuilder):
    """
    Extended V2 feature builder with leak-resistant transformations
    
    Overrides _build_context_features() to use:
    - Binned rest days (0-2, 3-4, 5-7, 8+ days)
    - Relative rest advantage (home/away ratio)
    - Relative congestion ratio (home/away ratio)
    """
    
    def _build_context_features(self, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Build TRANSFORMED context features (2 features instead of 4)
        
        Original (LEAKY - 81.61% unique combinations):
        - rest_days_home: 3.0 days
        - rest_days_away: 5.0 days
        - schedule_congestion_home_7d: 2 matches
        - schedule_congestion_away_7d: 1 match
        → Unique 4-tuple creates match fingerprint
        
        Transformed (LEAK-RESISTANT):
        - rest_advantage: 3.0 / (5.0 + 1) = 0.50 (home team less rested)
        - congestion_ratio: (2 + 1) / (1 + 1) = 1.50 (home team busier)
        → Relative values, fewer unique combinations
        
        Features:
        - rest_advantage: Ratio of home rest to away rest (>1 = home more rested)
        - congestion_ratio: Ratio of home congestion to away congestion (>1 = home busier)
        """
        # Get raw values from match_context
        from sqlalchemy import text
        
        query = text("""
            SELECT 
                rest_days_home,
                rest_days_away,
                schedule_congestion_home_7d,
                schedule_congestion_away_7d
            FROM match_context
            WHERE match_id = :match_id
        """)
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"match_id": match_id}).mappings().first()
            
            if not result:
                # No context data - return neutral values
                return {
                    'rest_advantage': 1.0,  # Equal rest
                    'congestion_ratio': 1.0  # Equal congestion
                }
            
            # Extract raw values
            rest_h = float(result['rest_days_home'] or 7.0)
            rest_a = float(result['rest_days_away'] or 7.0)
            cong_h = float(result['schedule_congestion_home_7d'] or 0.0)
            cong_a = float(result['schedule_congestion_away_7d'] or 0.0)
            
            # Transform: Use relative ratios
            # +1 to avoid division by zero
            rest_advantage = rest_h / (rest_a + 1.0)
            congestion_ratio = (cong_h + 1.0) / (cong_a + 1.0)
            
            # Cap extreme ratios (outlier protection)
            rest_advantage = min(max(rest_advantage, 0.1), 10.0)
            congestion_ratio = min(max(congestion_ratio, 0.1), 10.0)
            
            return {
                'rest_advantage': rest_advantage,
                'congestion_ratio': congestion_ratio
            }
            
        except Exception as e:
            logger.debug(f"Context features unavailable for match {match_id}: {e}")
            return {
                'rest_advantage': 1.0,  # Neutral
                'congestion_ratio': 1.0  # Neutral
            }
    
    def _build_context_features_binned(self, match_id: int, cutoff_time: datetime) -> Dict[str, float]:
        """
        Alternative: Build BINNED context features (4 features, coarse bins)
        
        Use this if relative ratios still leak. Bins reduce uniqueness:
        - Exact days: 3, 5, 7, 14 → Many unique values
        - Binned: 1, 2, 2, 3 → Only 4 possible values
        
        Bins:
        - 0 = 0-2 days (short rest)
        - 1 = 3-4 days (normal rest)
        - 2 = 5-7 days (good rest)
        - 3 = 8+ days (extended rest)
        
        Features:
        - rest_home_bin: Binned rest days for home team
        - rest_away_bin: Binned rest days for away team
        - congestion_home_bin: Binned congestion for home team
        - congestion_away_bin: Binned congestion for away team
        """
        from sqlalchemy import text
        
        query = text("""
            SELECT 
                rest_days_home,
                rest_days_away,
                schedule_congestion_home_7d,
                schedule_congestion_away_7d
            FROM match_context
            WHERE match_id = :match_id
        """)
        
        def bin_rest_days(days: float) -> float:
            """Bin rest days into coarse categories"""
            if days <= 2:
                return 0.0  # Short rest
            elif days <= 4:
                return 1.0  # Normal rest
            elif days <= 7:
                return 2.0  # Good rest
            else:
                return 3.0  # Extended rest
        
        def bin_congestion(count: float) -> float:
            """Bin congestion into coarse categories"""
            if count == 0:
                return 0.0  # Light schedule
            elif count == 1:
                return 1.0  # Normal schedule
            elif count == 2:
                return 2.0  # Busy schedule
            else:
                return 3.0  # Congested schedule
        
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"match_id": match_id}).mappings().first()
            
            if not result:
                # No context data - return neutral bins
                return {
                    'rest_home_bin': 2.0,  # Good rest
                    'rest_away_bin': 2.0,  # Good rest
                    'congestion_home_bin': 0.0,  # Light
                    'congestion_away_bin': 0.0  # Light
                }
            
            # Extract and bin values
            rest_h = float(result['rest_days_home'] or 7.0)
            rest_a = float(result['rest_days_away'] or 7.0)
            cong_h = float(result['schedule_congestion_home_7d'] or 0.0)
            cong_a = float(result['schedule_congestion_away_7d'] or 0.0)
            
            return {
                'rest_home_bin': bin_rest_days(rest_h),
                'rest_away_bin': bin_rest_days(rest_a),
                'congestion_home_bin': bin_congestion(cong_h),
                'congestion_away_bin': bin_congestion(cong_a)
            }
            
        except Exception as e:
            logger.debug(f"Context features unavailable for match {match_id}: {e}")
            return {
                'rest_home_bin': 2.0,  # Neutral
                'rest_away_bin': 2.0,  # Neutral
                'congestion_home_bin': 0.0,  # Neutral
                'congestion_away_bin': 0.0  # Neutral
            }


def get_v2_feature_builder_transformed(database_url=None, use_binned=False):
    """
    Factory function to get transformed feature builder
    
    Args:
        database_url: Optional database URL
        use_binned: If True, use binned features (4 features)
                   If False, use relative ratios (2 features, default)
    
    Returns:
        V2FeatureBuilderTransformed instance
    """
    builder = V2FeatureBuilderTransformed(database_url)
    
    if use_binned:
        # Replace context method with binned version
        builder._build_context_features = builder._build_context_features_binned.__get__(builder, V2FeatureBuilderTransformed)
    
    return builder
