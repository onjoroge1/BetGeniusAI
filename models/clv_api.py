#!/usr/bin/env python3

import asyncio
import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
import json
from fastapi import HTTPException
from pydantic import BaseModel

class CLVOpportunity(BaseModel):
    match_id: int
    outcome: str
    best_odds: float
    best_bookmaker: int
    market_odds: float
    clv_percentage: float
    confidence_level: str
    time_to_kickoff_hours: float
    recommendation: str
    created_at: datetime

class CLVAnalysis(BaseModel):
    match_id: int
    home_team: str
    away_team: str
    league_id: int
    opportunities: List[CLVOpportunity]
    market_summary: Dict
    timing_analysis: Dict
    overall_recommendation: str

class CLVMonitorAPI:
    """Real-time CLV monitoring API for frontend integration"""
    
    def __init__(self):
        self.database_url = os.environ.get('DATABASE_URL')
        self.clv_threshold_positive = 2.0  # Positive CLV threshold for betting
        self.clv_threshold_alert = 3.0     # High CLV alert threshold
        self.movement_threshold = 5.0      # Significant movement threshold
        
        # Premium bookmakers from analysis
        self.premium_bookmakers = [148, 894, 710, 6, 748]
        self.sharp_bookmakers = [937, 468, 176, 215]  # Pinnacle-style sharp books
    
    async def get_match_clv_analysis(self, match_id: int) -> CLVAnalysis:
        """Get comprehensive CLV analysis for a specific match"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Get match details
                cursor.execute("""
                    SELECT tm.home_team, tm.away_team, tm.league_id
                    FROM training_matches tm
                    WHERE tm.match_id = %s
                    LIMIT 1
                """, (match_id,))
                
                match_info = cursor.fetchone()
                if not match_info:
                    raise HTTPException(status_code=404, detail="Match not found")
                
                home_team, away_team, league_id = match_info
                
                # Get current odds for this match
                cursor.execute("""
                    SELECT 
                        os.outcome,
                        os.book_id,
                        os.odds_decimal,
                        os.implied_prob,
                        os.secs_to_kickoff,
                        os.created_at
                    FROM odds_snapshots os
                    WHERE os.match_id = %s
                      AND os.created_at > NOW() - INTERVAL '24 hours'
                    ORDER BY os.created_at DESC
                """, (match_id,))
                
                odds_data = cursor.fetchall()
                
                if not odds_data:
                    raise HTTPException(status_code=404, detail="No recent odds data for this match")
                
                # Analyze CLV opportunities by outcome
                opportunities = []
                market_summary = {}
                
                # Group odds by outcome
                odds_by_outcome = {}
                for outcome, book_id, odds_decimal, implied_prob, secs_to_kickoff, created_at in odds_data:
                    if outcome not in odds_by_outcome:
                        odds_by_outcome[outcome] = []
                    
                    odds_by_outcome[outcome].append({
                        'book_id': book_id,
                        'odds': odds_decimal,
                        'implied_prob': implied_prob,
                        'secs_to_kickoff': secs_to_kickoff,
                        'created_at': created_at
                    })
                
                # Calculate CLV for each outcome
                for outcome, odds_list in odds_by_outcome.items():
                    if len(odds_list) >= 2:
                        # Find best odds (highest) and market consensus
                        best_odds_entry = max(odds_list, key=lambda x: x['odds'])
                        
                        # Calculate market consensus (excluding outliers)
                        odds_values = [entry['odds'] for entry in odds_list]
                        sorted_odds = sorted(odds_values)
                        
                        # Use median for market consensus (more robust than mean)
                        market_odds = sorted_odds[len(sorted_odds) // 2]
                        
                        # Calculate CLV
                        clv_percentage = (best_odds_entry['odds'] - market_odds) / market_odds * 100
                        
                        # Determine confidence level based on bookmaker and sample size
                        confidence_level = self._determine_confidence(
                            best_odds_entry['book_id'], 
                            len(odds_list), 
                            clv_percentage
                        )
                        
                        # Generate recommendation
                        recommendation = self._generate_recommendation(
                            clv_percentage, 
                            best_odds_entry['secs_to_kickoff'],
                            confidence_level
                        )
                        
                        # Create CLV opportunity
                        opportunity = CLVOpportunity(
                            match_id=match_id,
                            outcome=outcome,
                            best_odds=best_odds_entry['odds'],
                            best_bookmaker=best_odds_entry['book_id'],
                            market_odds=market_odds,
                            clv_percentage=clv_percentage,
                            confidence_level=confidence_level,
                            time_to_kickoff_hours=best_odds_entry['secs_to_kickoff'] / 3600,
                            recommendation=recommendation,
                            created_at=best_odds_entry['created_at']
                        )
                        
                        opportunities.append(opportunity)
                        
                        # Build market summary
                        market_summary[outcome] = {
                            'best_odds': best_odds_entry['odds'],
                            'market_odds': market_odds,
                            'worst_odds': min(odds_values),
                            'bookmaker_count': len(odds_list),
                            'clv_percentage': clv_percentage
                        }
                
                # Timing analysis
                timing_analysis = self._analyze_timing(odds_data)
                
                # Overall recommendation
                overall_recommendation = self._generate_overall_recommendation(opportunities)
                
                return CLVAnalysis(
                    match_id=match_id,
                    home_team=home_team,
                    away_team=away_team,
                    league_id=league_id,
                    opportunities=opportunities,
                    market_summary=market_summary,
                    timing_analysis=timing_analysis,
                    overall_recommendation=overall_recommendation
                )
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"CLV analysis error: {str(e)}")
    
    async def get_live_clv_alerts(self, league_ids: Optional[List[int]] = None) -> List[CLVOpportunity]:
        """Get live CLV alerts for active matches"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Build league filter
                league_filter = ""
                params = []
                if league_ids:
                    league_filter = "AND tm.league_id = ANY(%s)"
                    params.append(league_ids)
                
                # Get matches with recent odds and positive CLV
                cursor.execute(f"""
                    WITH recent_odds AS (
                        SELECT 
                            os.match_id,
                            os.outcome,
                            os.book_id,
                            os.odds_decimal,
                            os.secs_to_kickoff,
                            os.created_at,
                            ROW_NUMBER() OVER (
                                PARTITION BY os.match_id, os.outcome, os.book_id 
                                ORDER BY os.created_at DESC
                            ) as rn
                        FROM odds_snapshots os
                        WHERE os.created_at > NOW() - INTERVAL '24 hours'
                          AND os.secs_to_kickoff > 3600  -- At least 1 hour to kickoff
                          {league_filter}
                    ),
                    clv_calculations AS (
                        SELECT 
                            ro.match_id,
                            ro.outcome,
                            ro.book_id,
                            ro.odds_decimal,
                            ro.secs_to_kickoff,
                            ro.created_at,
                            AVG(ro.odds_decimal) OVER (
                                PARTITION BY ro.match_id, ro.outcome
                            ) as market_odds,
                            MAX(ro.odds_decimal) OVER (
                                PARTITION BY ro.match_id, ro.outcome
                            ) as best_odds
                        FROM recent_odds ro
                        WHERE ro.rn = 1
                    )
                    SELECT 
                        cc.match_id,
                        cc.outcome,
                        cc.book_id,
                        cc.odds_decimal,
                        cc.market_odds,
                        cc.best_odds,
                        (cc.best_odds - cc.market_odds) / cc.market_odds * 100 as clv_pct,
                        cc.secs_to_kickoff,
                        cc.created_at
                    FROM clv_calculations cc
                    WHERE cc.odds_decimal = cc.best_odds  -- Only best odds entries
                      AND (cc.best_odds - cc.market_odds) / cc.market_odds * 100 >= %s
                    ORDER BY clv_pct DESC
                    LIMIT 20
                """, params + [self.clv_threshold_positive])
                
                alerts = cursor.fetchall()
                
                clv_opportunities = []
                for alert in alerts:
                    (match_id, outcome, book_id, odds_decimal, market_odds, 
                     best_odds, clv_pct, secs_to_kickoff, created_at) = alert
                    
                    confidence_level = self._determine_confidence(book_id, 5, clv_pct)
                    recommendation = self._generate_recommendation(clv_pct, secs_to_kickoff, confidence_level)
                    
                    opportunity = CLVOpportunity(
                        match_id=match_id,
                        outcome=outcome,
                        best_odds=odds_decimal,
                        best_bookmaker=book_id,
                        market_odds=market_odds,
                        clv_percentage=clv_pct,
                        confidence_level=confidence_level,
                        time_to_kickoff_hours=secs_to_kickoff / 3600,
                        recommendation=recommendation,
                        created_at=created_at
                    )
                    
                    clv_opportunities.append(opportunity)
                
                return clv_opportunities
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Live CLV alerts error: {str(e)}")
    
    async def get_clv_dashboard_data(self) -> Dict:
        """Get comprehensive dashboard data for CLV monitoring"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                
                # Active matches with CLV opportunities
                cursor.execute("""
                    SELECT COUNT(DISTINCT match_id) 
                    FROM odds_snapshots 
                    WHERE created_at > NOW() - INTERVAL '4 hours'
                      AND secs_to_kickoff > 3600
                """)
                active_matches = cursor.fetchone()[0]
                
                # CLV opportunities in last hour
                live_alerts = await self.get_live_clv_alerts()
                positive_clv_count = len([alert for alert in live_alerts if alert.clv_percentage > 0])
                
                # Top bookmakers by CLV
                cursor.execute("""
                    SELECT 
                        book_id,
                        COUNT(*) as odds_count,
                        AVG(odds_decimal) as avg_odds,
                        COUNT(DISTINCT match_id) as matches
                    FROM odds_snapshots
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                    GROUP BY book_id
                    ORDER BY AVG(odds_decimal) DESC
                    LIMIT 10
                """)
                top_bookmakers = cursor.fetchall()
                
                # Recent movements
                cursor.execute("""
                    WITH movement_data AS (
                        SELECT 
                            match_id,
                            outcome,
                            book_id,
                            odds_decimal,
                            created_at,
                            LAG(odds_decimal) OVER (
                                PARTITION BY match_id, outcome, book_id 
                                ORDER BY created_at
                            ) as prev_odds
                        FROM odds_snapshots
                        WHERE created_at > NOW() - INTERVAL '6 hours'
                    )
                    SELECT COUNT(*)
                    FROM movement_data
                    WHERE prev_odds IS NOT NULL
                      AND ABS((odds_decimal - prev_odds) / prev_odds * 100) >= %s
                """, (self.movement_threshold,))
                
                significant_movements = cursor.fetchone()[0]
                
                dashboard_data = {
                    'summary': {
                        'active_matches': active_matches,
                        'positive_clv_opportunities': positive_clv_count,
                        'significant_movements_6h': significant_movements,
                        'bookmakers_tracked': len(top_bookmakers)
                    },
                    'live_alerts': [alert.dict() for alert in live_alerts[:10]],
                    'top_bookmakers': [
                        {
                            'book_id': book_id,
                            'odds_count': odds_count,
                            'avg_odds': float(avg_odds),
                            'matches': matches,
                            'is_premium': book_id in self.premium_bookmakers
                        }
                        for book_id, odds_count, avg_odds, matches in top_bookmakers
                    ],
                    'last_updated': datetime.now().isoformat()
                }
                
                return dashboard_data
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Dashboard data error: {str(e)}")
    
    def _determine_confidence(self, book_id: int, sample_size: int, clv_pct: float) -> str:
        """Determine confidence level for CLV opportunity"""
        if book_id in self.sharp_bookmakers:
            confidence_boost = 1
        elif book_id in self.premium_bookmakers:
            confidence_boost = 0.5
        else:
            confidence_boost = 0
        
        base_confidence = min(sample_size / 10, 1.0)  # Max confidence at 10+ bookmakers
        clv_confidence = min(abs(clv_pct) / 10, 1.0)  # Max confidence at 10%+ CLV
        
        total_confidence = (base_confidence + clv_confidence + confidence_boost) / 3
        
        if total_confidence >= 0.8:
            return "High"
        elif total_confidence >= 0.5:
            return "Medium" 
        else:
            return "Low"
    
    def _generate_recommendation(self, clv_pct: float, secs_to_kickoff: int, confidence: str) -> str:
        """Generate betting recommendation based on CLV and timing"""
        hours_to_kickoff = secs_to_kickoff / 3600
        
        if clv_pct >= self.clv_threshold_alert and confidence == "High":
            return "STRONG BET - High CLV with high confidence"
        elif clv_pct >= self.clv_threshold_positive and confidence in ["High", "Medium"]:
            if hours_to_kickoff > 48:
                return "BET - Good CLV with early timing"
            elif hours_to_kickoff > 24:
                return "BET - Positive CLV in optimal window"
            else:
                return "CONSIDER - Positive CLV but close to kickoff"
        elif clv_pct >= 0 and clv_pct < self.clv_threshold_positive:
            return "MONITOR - Slight positive CLV, watch for improvement"
        else:
            return "AVOID - Negative CLV"
    
    def _generate_overall_recommendation(self, opportunities: List[CLVOpportunity]) -> str:
        """Generate overall match recommendation"""
        if not opportunities:
            return "NO DATA - Insufficient odds data for analysis"
        
        strong_bets = [opp for opp in opportunities if "STRONG BET" in opp.recommendation]
        good_bets = [opp for opp in opportunities if opp.recommendation.startswith("BET")]
        
        if strong_bets:
            return f"RECOMMENDED - {len(strong_bets)} strong CLV opportunities detected"
        elif good_bets:
            return f"CONSIDER - {len(good_bets)} positive CLV opportunities available"
        else:
            return "MONITOR - No significant CLV opportunities currently"
    
    def _analyze_timing(self, odds_data: List) -> Dict:
        """Analyze timing patterns in odds data"""
        if not odds_data:
            return {}
        
        latest_time = max(entry[5] for entry in odds_data)  # created_at
        earliest_time = min(entry[5] for entry in odds_data)
        
        time_span_hours = (latest_time - earliest_time).total_seconds() / 3600
        avg_secs_to_kickoff = sum(entry[4] for entry in odds_data) / len(odds_data)
        
        return {
            'data_span_hours': round(time_span_hours, 2),
            'avg_hours_to_kickoff': round(avg_secs_to_kickoff / 3600, 2),
            'total_odds_points': len(odds_data),
            'timing_recommendation': self._get_timing_recommendation(avg_secs_to_kickoff)
        }
    
    def _get_timing_recommendation(self, secs_to_kickoff: float) -> str:
        """Get timing-based recommendation"""
        hours = secs_to_kickoff / 3600
        
        if hours > 72:
            return "EARLY - Excellent timing for CLV capture"
        elif hours > 48:
            return "OPTIMAL - Good timing window for betting"
        elif hours > 24:
            return "LATE - Consider quick execution"
        else:
            return "CLOSING - Limited time for CLV opportunities"