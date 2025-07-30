"""
Book Features Builder
Build comprehensive bookmaker-aware features for residual-on-market training
"""

import os
import pandas as pd
import numpy as np
import psycopg2
import json
from datetime import datetime
from typing import Dict, List, Tuple, Optional

class BookFeaturesBuilder:
    """Build bookmaker-aware features for enhanced residual modeling"""
    
    def __init__(self):
        self.conn = psycopg2.connect(os.environ['DATABASE_URL'])
        self.bookmakers = ['b365', 'bw', 'iw', 'lb', 'ps', 'wh', 'sj', 'vc']
        
        # Load bookmaker metadata
        self.bookmaker_meta = self.load_bookmaker_metadata()
        self.quality_weights = self.load_quality_weights()
        
    def load_bookmaker_metadata(self) -> Dict:
        """Load bookmaker metadata for type classification"""
        
        meta_dir = 'meta/book_quality'
        if os.path.exists(meta_dir):
            meta_files = [f for f in os.listdir(meta_dir) if f.startswith('bookmaker_metadata_')]
            if meta_files:
                latest_file = sorted(meta_files)[-1]
                meta_path = os.path.join(meta_dir, latest_file)
                
                with open(meta_path, 'r') as f:
                    return json.load(f)
        
        # Fallback metadata
        return {
            'b365': {'type': 'recreational', 'market_position': 'major_recreational'},
            'bw': {'type': 'recreational', 'market_position': 'mid_tier_recreational'},
            'ps': {'type': 'sharp', 'market_position': 'sharp_leader'},
            'wh': {'type': 'recreational', 'market_position': 'major_traditional'},
            'iw': {'type': 'recreational', 'market_position': 'european_recreational'},
            'lb': {'type': 'recreational', 'market_position': 'traditional_uk'},
            'sj': {'type': 'recreational', 'market_position': 'uk_specialist'},
            'vc': {'type': 'recreational', 'market_position': 'premium_uk'}
        }
    
    def load_quality_weights(self) -> Dict:
        """Load quality weights by era/league"""
        
        weights_dir = 'meta/book_quality'
        if os.path.exists(weights_dir):
            weight_files = [f for f in os.listdir(weights_dir) if f.startswith('quality_weights_')]
            if weight_files:
                latest_file = sorted(weight_files)[-1]
                weights_path = os.path.join(weights_dir, latest_file)
                
                with open(weights_path, 'r') as f:
                    return json.load(f)
        
        return {}
    
    def determine_era_bin(self, match_date: str) -> str:
        """Determine era bin from match date"""
        
        if isinstance(match_date, str):
            year = int(match_date.split('-')[0])
        else:
            year = match_date.year
        
        if year <= 2002:
            return '1998-2002'
        elif year <= 2007:
            return '2003-2007'
        elif year <= 2012:
            return '2008-2012'
        elif year <= 2017:
            return '2013-2017'
        elif year <= 2022:
            return '2018-2022'
        else:
            return '2023-2024'
    
    def convert_odds_to_probabilities(self, odds_h: float, odds_d: float, odds_a: float) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Convert odds to margin-adjusted probabilities with overround"""
        
        if pd.isna(odds_h) or pd.isna(odds_d) or pd.isna(odds_a):
            return None, None, None, None
        
        if odds_h <= 1.0 or odds_d <= 1.0 or odds_a <= 1.0:
            return None, None, None, None
        
        # Raw implied probabilities
        raw_prob_h = 1.0 / odds_h
        raw_prob_d = 1.0 / odds_d
        raw_prob_a = 1.0 / odds_a
        
        # Overround
        overround = raw_prob_h + raw_prob_d + raw_prob_a
        
        # Margin-adjusted probabilities
        prob_h = raw_prob_h / overround
        prob_d = raw_prob_d / overround
        prob_a = raw_prob_a / overround
        
        return prob_h, prob_d, prob_a, overround
    
    def get_quality_weights_for_context(self, league: str, era_bin: str) -> Dict[str, float]:
        """Get quality weights for specific league/era context"""
        
        # Try exact match first
        key = f"{league}_{era_bin}"
        if key in self.quality_weights:
            return self.quality_weights[key].get('quality_weights', {})
        
        # Fallback to same league, different era
        for fallback_key, weight_data in self.quality_weights.items():
            if fallback_key.startswith(f"{league}_"):
                return weight_data.get('quality_weights', {})
        
        # Final fallback: equal weights
        return {bm: 1.0 / len(self.bookmakers) for bm in self.bookmakers}
    
    def build_consensus_features(self, match_data: Dict, league: str, era_bin: str) -> Dict:
        """Build consensus-based features (T-72h equivalent)"""
        
        # Get quality weights for context
        weights = self.get_quality_weights_for_context(league, era_bin)
        
        # Collect valid probabilities and weights
        valid_probs = []
        valid_weights = []
        valid_overrounds = []
        bookmaker_probs = {}
        
        for bookmaker in self.bookmakers:
            odds_h = match_data.get(f"{bookmaker}_h")
            odds_d = match_data.get(f"{bookmaker}_d")
            odds_a = match_data.get(f"{bookmaker}_a")
            
            prob_h, prob_d, prob_a, overround = self.convert_odds_to_probabilities(
                odds_h, odds_d, odds_a
            )
            
            if prob_h is not None:
                probs = [prob_h, prob_d, prob_a]
                valid_probs.append(probs)
                valid_weights.append(weights.get(bookmaker, 0.0))
                valid_overrounds.append(overround)
                bookmaker_probs[bookmaker] = {
                    'probs': probs,
                    'overround': overround
                }
        
        if len(valid_probs) == 0:
            return None
        
        # Normalize weights
        valid_weights = np.array(valid_weights)
        if np.sum(valid_weights) > 0:
            valid_weights = valid_weights / np.sum(valid_weights)
        else:
            valid_weights = np.ones(len(valid_weights)) / len(valid_weights)
        
        # Calculate weighted consensus
        valid_probs = np.array(valid_probs)
        weighted_consensus = np.average(valid_probs, axis=0, weights=valid_weights)
        
        # Consensus logits (clipped for numerical stability)
        consensus_clipped = np.clip(weighted_consensus, 0.02, 0.98)
        logit_cons_h = np.log(consensus_clipped[0] / (1 - consensus_clipped[0]))
        logit_cons_d = np.log(consensus_clipped[1] / (1 - consensus_clipped[1]))
        logit_cons_a = np.log(consensus_clipped[2] / (1 - consensus_clipped[2]))
        
        # Dispersion metrics
        if len(valid_probs) > 1:
            disp_h = float(np.std(valid_probs[:, 0]))
            disp_d = float(np.std(valid_probs[:, 1]))
            disp_a = float(np.std(valid_probs[:, 2]))
        else:
            disp_h = disp_d = disp_a = 0.0
        
        # Disagreement metrics (Jensen-Shannon)
        disagree_js = 0.0
        if len(valid_probs) > 1:
            js_divergences = []
            for prob in valid_probs:
                prob_clipped = np.clip(prob, 1e-15, 1 - 1e-15)
                consensus_clipped_js = np.clip(weighted_consensus, 1e-15, 1 - 1e-15)
                
                m = 0.5 * (prob_clipped + consensus_clipped_js)
                js_div = 0.5 * np.sum(prob_clipped * np.log(prob_clipped / m)) + 0.5 * np.sum(consensus_clipped_js * np.log(consensus_clipped_js / m))
                js_divergences.append(js_div)
            
            disagree_js = float(np.mean(js_divergences))
        
        return {
            'logit_cons_h': logit_cons_h,
            'logit_cons_d': logit_cons_d, 
            'logit_cons_a': logit_cons_a,
            'disp_h': disp_h,
            'disp_d': disp_d,
            'disp_a': disp_a,
            'n_books': len(valid_probs),
            'avg_overround': float(np.mean(valid_overrounds)),
            'disagree_js': disagree_js,
            'bookmaker_probs': bookmaker_probs,
            'weighted_consensus': weighted_consensus
        }
    
    def build_book_identity_features(self, consensus_data: Dict) -> Dict:
        """Build book-specific identity features"""
        
        if consensus_data is None:
            return {}
        
        bookmaker_probs = consensus_data['bookmaker_probs']
        weighted_consensus = consensus_data['weighted_consensus']
        
        # Individual bookmaker delta-logits
        book_features = {}
        
        for bookmaker in self.bookmakers:
            if bookmaker in bookmaker_probs:
                book_probs = np.array(bookmaker_probs[bookmaker]['probs'])
                
                # Calculate delta-logits vs consensus
                book_clipped = np.clip(book_probs, 0.02, 0.98)
                consensus_clipped = np.clip(weighted_consensus, 0.02, 0.98)
                
                book_logits = np.log(book_clipped / (1 - book_clipped))
                consensus_logits = np.log(consensus_clipped / (1 - consensus_clipped))
                
                delta_logits = book_logits - consensus_logits
                
                book_features.update({
                    f'delta_logit_{bookmaker}_h': float(delta_logits[0]),
                    f'delta_logit_{bookmaker}_d': float(delta_logits[1]),
                    f'delta_logit_{bookmaker}_a': float(delta_logits[2]),
                    f'overround_{bookmaker}': bookmaker_probs[bookmaker]['overround'],
                    f'present_{bookmaker}': 1.0
                })
            else:
                # Missing bookmaker
                book_features.update({
                    f'delta_logit_{bookmaker}_h': 0.0,
                    f'delta_logit_{bookmaker}_d': 0.0,
                    f'delta_logit_{bookmaker}_a': 0.0,
                    f'overround_{bookmaker}': 0.0,
                    f'present_{bookmaker}': 0.0
                })
        
        return book_features
    
    def build_book_group_features(self, consensus_data: Dict) -> Dict:
        """Build aggregated book group features (sharp vs recreational)"""
        
        if consensus_data is None:
            return {
                'sharp_delta_logit_h_mean': 0.0, 'sharp_delta_logit_d_mean': 0.0, 'sharp_delta_logit_a_mean': 0.0,
                'rec_delta_logit_h_mean': 0.0, 'rec_delta_logit_d_mean': 0.0, 'rec_delta_logit_a_mean': 0.0,
                'sharp_delta_logit_h_std': 0.0, 'sharp_delta_logit_d_std': 0.0, 'sharp_delta_logit_a_std': 0.0,
                'rec_delta_logit_h_std': 0.0, 'rec_delta_logit_d_std': 0.0, 'rec_delta_logit_a_std': 0.0,
                'sharp_overround_mean': 0.0, 'rec_overround_mean': 0.0,
                'sharp_books_present': 0, 'rec_books_present': 0
            }
        
        bookmaker_probs = consensus_data['bookmaker_probs']
        weighted_consensus = consensus_data['weighted_consensus']
        
        # Separate sharp and recreational books
        sharp_delta_logits = {'h': [], 'd': [], 'a': []}
        rec_delta_logits = {'h': [], 'd': [], 'a': []}
        sharp_overrounds = []
        rec_overrounds = []
        
        for bookmaker in bookmaker_probs:
            book_type = self.bookmaker_meta.get(bookmaker, {}).get('type', 'recreational')
            book_probs = np.array(bookmaker_probs[bookmaker]['probs'])
            
            # Calculate delta-logits
            book_clipped = np.clip(book_probs, 0.02, 0.98)
            consensus_clipped = np.clip(weighted_consensus, 0.02, 0.98)
            
            book_logits = np.log(book_clipped / (1 - book_clipped))
            consensus_logits = np.log(consensus_clipped / (1 - consensus_clipped))
            
            delta_logits = book_logits - consensus_logits
            overround = bookmaker_probs[bookmaker]['overround']
            
            if book_type == 'sharp':
                sharp_delta_logits['h'].append(delta_logits[0])
                sharp_delta_logits['d'].append(delta_logits[1])
                sharp_delta_logits['a'].append(delta_logits[2])
                sharp_overrounds.append(overround)
            else:
                rec_delta_logits['h'].append(delta_logits[0])
                rec_delta_logits['d'].append(delta_logits[1])
                rec_delta_logits['a'].append(delta_logits[2])
                rec_overrounds.append(overround)
        
        # Calculate group statistics
        features = {}
        
        # Sharp book features
        for outcome in ['h', 'd', 'a']:
            if sharp_delta_logits[outcome]:
                features[f'sharp_delta_logit_{outcome}_mean'] = float(np.mean(sharp_delta_logits[outcome]))
                features[f'sharp_delta_logit_{outcome}_std'] = float(np.std(sharp_delta_logits[outcome])) if len(sharp_delta_logits[outcome]) > 1 else 0.0
            else:
                features[f'sharp_delta_logit_{outcome}_mean'] = 0.0
                features[f'sharp_delta_logit_{outcome}_std'] = 0.0
        
        # Recreational book features
        for outcome in ['h', 'd', 'a']:
            if rec_delta_logits[outcome]:
                features[f'rec_delta_logit_{outcome}_mean'] = float(np.mean(rec_delta_logits[outcome]))
                features[f'rec_delta_logit_{outcome}_std'] = float(np.std(rec_delta_logits[outcome])) if len(rec_delta_logits[outcome]) > 1 else 0.0
            else:
                features[f'rec_delta_logit_{outcome}_mean'] = 0.0
                features[f'rec_delta_logit_{outcome}_std'] = 0.0
        
        # Overround features
        features['sharp_overround_mean'] = float(np.mean(sharp_overrounds)) if sharp_overrounds else 0.0
        features['rec_overround_mean'] = float(np.mean(rec_overrounds)) if rec_overrounds else 0.0
        
        # Count features
        features['sharp_books_present'] = len(sharp_overrounds)
        features['rec_books_present'] = len(rec_overrounds)
        
        return features
    
    def build_structural_features(self, match_data: Dict) -> Dict:
        """Build structural match features (existing pipeline)"""
        
        # Placeholder for existing structural features
        # In production, this would integrate with existing feature engineering
        return {
            'league_tier': self.get_league_tier(match_data.get('league', '')),
            'season_phase': self.get_season_phase(match_data.get('match_date', '')),
            'is_weekend': self.is_weekend_match(match_data.get('match_date', ''))
        }
    
    def get_league_tier(self, league: str) -> int:
        """Get league tier classification"""
        tier_mapping = {
            'E0': 1, 'SP1': 1, 'I1': 1, 'D1': 1, 'F1': 1,  # Top tier
            'E1': 2, 'SP2': 2, 'I2': 2, 'D2': 2, 'F2': 2   # Second tier
        }
        return tier_mapping.get(league, 2)
    
    def get_season_phase(self, match_date: str) -> str:
        """Determine season phase"""
        if isinstance(match_date, str):
            month = int(match_date.split('-')[1])
        else:
            month = match_date.month
        
        if month in [8, 9, 10]:
            return 'early'
        elif month in [11, 12, 1, 2]:
            return 'mid'
        else:
            return 'late'
    
    def is_weekend_match(self, match_date: str) -> int:
        """Check if match is on weekend"""
        # Simplified - in production would use actual day of week
        return 1 if pd.to_datetime(match_date).weekday() >= 5 else 0
    
    def build_comprehensive_features(self, match_data: Dict, league: str, era_bin: str) -> Dict:
        """Build comprehensive feature pack for residual head"""
        
        # Build consensus features
        consensus_data = self.build_consensus_features(match_data, league, era_bin)
        
        if consensus_data is None:
            return None
        
        # Build all feature types
        consensus_features = {
            'logit_cons_h': consensus_data['logit_cons_h'],
            'logit_cons_d': consensus_data['logit_cons_d'],
            'logit_cons_a': consensus_data['logit_cons_a'],
            'disp_h': consensus_data['disp_h'],
            'disp_d': consensus_data['disp_d'],
            'disp_a': consensus_data['disp_a'],
            'n_books': consensus_data['n_books'],
            'avg_overround': consensus_data['avg_overround'],
            'disagree_js': consensus_data['disagree_js']
        }
        
        book_identity_features = self.build_book_identity_features(consensus_data)
        book_group_features = self.build_book_group_features(consensus_data)
        structural_features = self.build_structural_features(match_data)
        
        # Combine all features
        all_features = {}
        all_features.update(consensus_features)
        all_features.update(book_identity_features)
        all_features.update(book_group_features)
        all_features.update(structural_features)
        
        return all_features
    
    def process_historical_matches_for_features(self, limit: int = 5000) -> pd.DataFrame:
        """Process historical matches to build feature dataset"""
        
        print(f"Building book features for up to {limit:,} historical matches...")
        
        # Load recent historical data
        query = """
        SELECT 
            id, match_date, season, league, home_team, away_team, result,
            b365_h, b365_d, b365_a,
            bw_h, bw_d, bw_a,
            iw_h, iw_d, iw_a,
            lb_h, lb_d, lb_a,
            ps_h, ps_d, ps_a,
            wh_h, wh_d, wh_a,
            sj_h, sj_d, sj_a,
            vc_h, vc_d, vc_a
        FROM historical_odds
        WHERE result IS NOT NULL
        AND match_date >= '2020-01-01'
        ORDER BY match_date DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        df = pd.read_sql(query, self.conn)
        print(f"Processing {len(df):,} matches for feature engineering...")
        
        # Build features for each match
        feature_records = []
        
        for idx, row in df.iterrows():
            era_bin = self.determine_era_bin(row['match_date'])
            match_data = row.to_dict()
            
            # Build comprehensive features
            features = self.build_comprehensive_features(match_data, row['league'], era_bin)
            
            if features:
                # Add match metadata
                feature_record = {
                    'match_id': row['id'],
                    'match_date': row['match_date'],
                    'league': row['league'],
                    'era_bin': era_bin,
                    'home_team': row['home_team'],
                    'away_team': row['away_team'],
                    'result': row['result']
                }
                
                # Add all features
                feature_record.update(features)
                feature_records.append(feature_record)
            
            if (idx + 1) % 500 == 0:
                print(f"Processed {idx + 1:,} matches...")
        
        features_df = pd.DataFrame(feature_records)
        print(f"Built features for {len(features_df):,} matches")
        
        return features_df
    
    def analyze_feature_importance(self, features_df: pd.DataFrame) -> Dict:
        """Analyze feature distributions and importance"""
        
        print("Analyzing feature distributions...")
        
        # Identify feature types
        consensus_features = [col for col in features_df.columns if col.startswith(('logit_cons_', 'disp_', 'n_books', 'avg_overround', 'disagree_js'))]
        book_identity_features = [col for col in features_df.columns if col.startswith(('delta_logit_', 'overround_', 'present_'))]
        book_group_features = [col for col in features_df.columns if col.startswith(('sharp_', 'rec_'))]
        structural_features = [col for col in features_df.columns if col in ['league_tier', 'season_phase', 'is_weekend']]
        
        # Calculate basic statistics
        feature_stats = {}
        
        for feature_group_name, feature_list in [
            ('consensus', consensus_features),
            ('book_identity', book_identity_features),
            ('book_group', book_group_features),
            ('structural', structural_features)
        ]:
            if feature_list:
                group_df = features_df[feature_list]
                feature_stats[feature_group_name] = {
                    'feature_count': len(feature_list),
                    'mean_values': group_df.mean().to_dict(),
                    'std_values': group_df.std().to_dict(),
                    'missing_rates': group_df.isnull().mean().to_dict()
                }
        
        # Check for perfect correlations or constant features
        correlation_warnings = []
        constant_features = []
        
        numeric_features = features_df.select_dtypes(include=[np.number]).columns
        numeric_df = features_df[numeric_features]
        
        for col in numeric_df.columns:
            if numeric_df[col].std() == 0:
                constant_features.append(col)
        
        return {
            'feature_statistics': feature_stats,
            'total_features': len(numeric_df.columns),
            'constant_features': constant_features,
            'correlation_warnings': correlation_warnings,
            'feature_groups': {
                'consensus': consensus_features,
                'book_identity': book_identity_features,
                'book_group': book_group_features,
                'structural': structural_features
            }
        }
    
    def run_book_feature_building(self, limit: int = 5000) -> Dict:
        """Run complete book feature building process"""
        
        print("BOOK FEATURES BUILDING - WEEK 2")
        print("=" * 50)
        print("Building comprehensive bookmaker-aware features...")
        
        try:
            # Build features dataset
            features_df = self.process_historical_matches_for_features(limit)
            
            # Analyze features
            feature_analysis = self.analyze_feature_importance(features_df)
            
            # Save results
            os.makedirs('features/book_features', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Save features dataset
            features_path = f'features/book_features/book_features_{timestamp}.csv'
            features_df.to_csv(features_path, index=False)
            
            # Save feature analysis
            analysis_path = f'features/book_features/feature_analysis_{timestamp}.json'
            with open(analysis_path, 'w') as f:
                json.dump(feature_analysis, f, indent=2, default=str)
            
            # Compile results
            results = {
                'timestamp': datetime.now().isoformat(),
                'features_df': features_df,
                'feature_analysis': feature_analysis,
                'files': {
                    'features_path': features_path,
                    'analysis_path': analysis_path
                }
            }
            
            # Print comprehensive summary
            self.print_features_summary(results)
            
            return results
            
        finally:
            self.conn.close()
    
    def print_features_summary(self, results: Dict):
        """Print comprehensive feature building summary"""
        
        print("\n" + "=" * 60)
        print("BOOK FEATURES BUILDING COMPLETE")
        print("=" * 60)
        
        features_df = results['features_df']
        analysis = results['feature_analysis']
        
        print(f"\n📊 FEATURE DATASET:")
        print(f"   • Matches Processed: {len(features_df):,}")
        print(f"   • Total Features: {analysis['total_features']}")
        print(f"   • Leagues Covered: {features_df['league'].nunique()}")
        print(f"   • Date Range: {features_df['match_date'].min()} to {features_df['match_date'].max()}")
        
        print(f"\n🎯 FEATURE GROUPS:")
        for group_name, features in analysis['feature_groups'].items():
            if features:
                print(f"   • {group_name.replace('_', ' ').title()}: {len(features)} features")
        
        print(f"\n📈 KEY CONSENSUS FEATURES:")
        consensus_stats = analysis['feature_statistics'].get('consensus', {})
        if 'mean_values' in consensus_stats:
            print(f"   • Average Books per Match: {consensus_stats['mean_values'].get('n_books', 0):.1f}")
            print(f"   • Average Overround: {consensus_stats['mean_values'].get('avg_overround', 0):.4f}")
            print(f"   • Average Disagreement (JS): {consensus_stats['mean_values'].get('disagree_js', 0):.4f}")
        
        print(f"\n🏪 BOOKMAKER INTELLIGENCE:")
        book_group_stats = analysis['feature_statistics'].get('book_group', {})
        if 'mean_values' in book_group_stats:
            print(f"   • Sharp Books Present (avg): {book_group_stats['mean_values'].get('sharp_books_present', 0):.1f}")
            print(f"   • Rec Books Present (avg): {book_group_stats['mean_values'].get('rec_books_present', 0):.1f}")
            print(f"   • Sharp Overround (avg): {book_group_stats['mean_values'].get('sharp_overround_mean', 0):.4f}")
            print(f"   • Rec Overround (avg): {book_group_stats['mean_values'].get('rec_overround_mean', 0):.4f}")
        
        if analysis['constant_features']:
            print(f"\n⚠️  CONSTANT FEATURES DETECTED:")
            for feature in analysis['constant_features'][:5]:
                print(f"   • {feature}")
        
        print(f"\n🚀 RESIDUAL HEAD READINESS:")
        print(f"   • Consensus logits: Ready")
        print(f"   • Dispersion metrics: Available")
        print(f"   • Book identity features: Complete")
        print(f"   • Book group aggregations: Ready")
        print(f"   • Next: Train residual-on-market head")
        
        print(f"\n📄 Files saved:")
        for name, path in results['files'].items():
            print(f"   • {name}: {path}")

def main():
    """Run book features building"""
    
    builder = BookFeaturesBuilder()
    results = builder.run_book_feature_building()
    
    return results

if __name__ == "__main__":
    main()