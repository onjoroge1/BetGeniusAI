"""
Live AI Analysis System
Intelligently triggers OpenAI analysis for live matches based on:
- Time intervals (every 3-5 minutes)
- Significant odds movements (>5% change)
- Key match events (goals, red cards)
"""

import os
import psycopg2
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import json
from openai import OpenAI

from models.odds_velocity import OddsVelocityCalculator

logger = logging.getLogger(__name__)


class LiveAIAnalyzer:
    """Generates AI analysis for live matches with intelligent triggers"""

    # Circuit breaker: stop calling OpenAI after repeated failures
    _circuit_open = False
    _circuit_open_until = None
    _consecutive_failures = 0
    _MAX_FAILURES = 3  # Open circuit after 3 consecutive failures
    _CIRCUIT_COOLDOWN_MINUTES = 30  # Wait 30 min before retrying

    def __init__(self, db_url: str):
        self.db_url = db_url
        api_key = os.environ.get('OPENAI_API_KEY')
        self.openai_client = OpenAI(api_key=api_key) if api_key else None
        self.velocity_calculator = OddsVelocityCalculator(db_url)

        # Trigger thresholds
        self.time_interval_minutes = 4  # Analyze every 4 minutes
        self.odds_movement_threshold = 5  # 5% odds change triggers analysis

        if not api_key:
            logger.warning("OPENAI_API_KEY not set — AI analysis disabled")
            LiveAIAnalyzer._circuit_open = True
            LiveAIAnalyzer._circuit_open_until = datetime.max
    
    def should_trigger_analysis(self, match_id: int) -> Tuple[bool, str]:
        """
        Determine if AI analysis should be triggered for this match
        Returns: (should_trigger, trigger_reason)
        """
        # Circuit breaker check — stop hammering OpenAI when quota is exhausted
        if LiveAIAnalyzer._circuit_open:
            if LiveAIAnalyzer._circuit_open_until and datetime.now() < LiveAIAnalyzer._circuit_open_until:
                return False, f"circuit_open (retry after {LiveAIAnalyzer._circuit_open_until.strftime('%H:%M')})"
            else:
                # Cooldown expired — half-open, allow one attempt
                logger.info("🔌 AI circuit breaker: cooldown expired, allowing retry")
                LiveAIAnalyzer._circuit_open = False
                LiveAIAnalyzer._consecutive_failures = 0

        if not self.openai_client:
            return False, "openai_client_not_configured"

        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Check 1: Time-based trigger (every N minutes)
                cursor.execute("""
                    SELECT generated_at
                    FROM live_ai_analysis
                    WHERE match_id = %s
                    ORDER BY generated_at DESC
                    LIMIT 1
                """, (match_id,))
                
                last_analysis = cursor.fetchone()
                
                if last_analysis:
                    time_since_last = datetime.now() - last_analysis[0].replace(tzinfo=None)
                    if time_since_last < timedelta(minutes=self.time_interval_minutes):
                        return False, f"Too soon (last: {time_since_last.seconds//60}m ago)"
                else:
                    # No previous analysis - trigger for first time
                    return True, "first_analysis"
                
                # Check 2: Significant odds movement
                velocity_data = self.velocity_calculator.get_odds_velocity(match_id, lookback_minutes=5)
                
                if velocity_data.get('has_significant_movement'):
                    return True, f"odds_movement_{velocity_data.get('market_sentiment', 'unknown')}"
                
                # Check 3: Recent significant events (goals, red cards)
                cursor.execute("""
                    SELECT event_type, minute, team, player_name
                    FROM match_events
                    WHERE match_id = %s
                        AND event_type IN ('goal', 'red_card')
                        AND timestamp > NOW() - INTERVAL '5 minutes'
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (match_id,))
                
                recent_event = cursor.fetchone()
                
                if recent_event:
                    event_type, minute, team, player = recent_event
                    return True, f"event_{event_type}_{team}_{minute}min"
                
                # Check 4: Time-based fallback (been longer than interval)
                if not last_analysis or time_since_last >= timedelta(minutes=self.time_interval_minutes):
                    return True, "time_interval"
                
                return False, "no_trigger"
                
        except Exception as e:
            logger.error(f"Error checking analysis triggers: {e}")
            return False, f"error_{str(e)}"
    
    def get_match_context(self, match_id: int) -> Dict:
        """Gather all relevant data for AI analysis"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Get match info
                cursor.execute("""
                    SELECT 
                        f.home_team,
                        f.away_team,
                        f.league_name,
                        f.kickoff_at
                    FROM fixtures f
                    WHERE f.match_id = %s
                """, (match_id,))
                
                match_row = cursor.fetchone()
                if not match_row:
                    return {}
                
                home_team, away_team, league, kickoff = match_row
                
                # Get latest live statistics
                cursor.execute("""
                    SELECT 
                        minute, period,
                        home_score, away_score,
                        home_possession, away_possession,
                        home_shots_total, away_shots_total,
                        home_shots_on_target, away_shots_on_target,
                        home_corners, away_corners,
                        home_yellow_cards, away_yellow_cards,
                        home_red_cards, away_red_cards
                    FROM live_match_stats
                    WHERE match_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (match_id,))
                
                stats_row = cursor.fetchone()
                
                stats = {}
                if stats_row:
                    stats = {
                        'minute': stats_row[0],
                        'period': stats_row[1],
                        'score': {'home': stats_row[2], 'away': stats_row[3]},
                        'possession': {'home': stats_row[4], 'away': stats_row[5]},
                        'shots': {
                            'home': {'total': stats_row[6], 'on_target': stats_row[8]},
                            'away': {'total': stats_row[7], 'on_target': stats_row[9]}
                        },
                        'corners': {'home': stats_row[10], 'away': stats_row[11]},
                        'cards': {
                            'home': {'yellow': stats_row[12], 'red': stats_row[14]},
                            'away': {'yellow': stats_row[13], 'red': stats_row[15]}
                        }
                    }
                
                # Get recent events
                cursor.execute("""
                    SELECT minute, event_type, team, player_name, detail
                    FROM match_events
                    WHERE match_id = %s
                    ORDER BY minute DESC
                    LIMIT 10
                """, (match_id,))
                
                events = []
                for row in cursor.fetchall():
                    events.append({
                        'minute': row[0],
                        'type': row[1],
                        'team': row[2],
                        'player': row[3],
                        'detail': row[4]
                    })
                
                # Get odds velocity
                velocity_data = self.velocity_calculator.get_odds_velocity(match_id)
                
                return {
                    'match_id': match_id,
                    'home_team': home_team,
                    'away_team': away_team,
                    'league': league,
                    'kickoff': kickoff.isoformat() if kickoff else None,
                    'live_stats': stats,
                    'recent_events': events,
                    'odds_velocity': velocity_data
                }
                
        except Exception as e:
            logger.error(f"Error gathering match context: {e}")
            return {}
    
    def generate_ai_analysis(self, match_context: Dict, trigger_reason: str) -> Dict:
        """
        Generate AI analysis using OpenAI GPT-4o
        Returns structured betting insights
        """
        try:
            home_team = match_context.get('home_team', 'Home')
            away_team = match_context.get('away_team', 'Away')
            stats = match_context.get('live_stats', {})
            events = match_context.get('recent_events', [])
            velocity = match_context.get('odds_velocity', {})
            
            # Build concise prompt
            prompt = f"""Analyze this LIVE match for betting insights:

{home_team} vs {away_team}
League: {match_context.get('league', 'Unknown')}

LIVE STATUS:
- Score: {stats.get('score', {}).get('home', 0)}-{stats.get('score', {}).get('away', 0)}
- Minute: {stats.get('minute', '?')}'
- Period: {stats.get('period', 'Unknown')}

STATISTICS:
- Possession: {home_team} {stats.get('possession', {}).get('home', '?')}% - {stats.get('possession', {}).get('away', '?')}% {away_team}
- Shots (on target): {home_team} {stats.get('shots', {}).get('home', {}).get('total', 0)} ({stats.get('shots', {}).get('home', {}).get('on_target', 0)}) - {stats.get('shots', {}).get('away', {}).get('total', 0)} ({stats.get('shots', {}).get('away', {}).get('on_target', 0)}) {away_team}
- Corners: {stats.get('corners', {}).get('home', 0)} - {stats.get('corners', {}).get('away', 0)}
- Cards: {home_team} Y{stats.get('cards', {}).get('home', {}).get('yellow', 0)} R{stats.get('cards', {}).get('home', {}).get('red', 0)} | {away_team} Y{stats.get('cards', {}).get('away', {}).get('yellow', 0)} R{stats.get('cards', {}).get('away', {}).get('red', 0)}

RECENT EVENTS:
{self._format_events(events[:5])}

ODDS MOVEMENT (last 15 min):
- Market sentiment: {velocity.get('market_sentiment', 'unknown')}
- Significant movement: {"YES" if velocity.get('has_significant_movement') else "NO"}

Trigger: {trigger_reason}

Provide CONCISE analysis (3-4 sentences max):
1. Current momentum and game flow
2. Key betting angles RIGHT NOW
3. Which outcome is gaining/losing value based on stats and odds movement

Format as JSON:
{{
  "momentum_assessment": "brief description",
  "key_observations": ["observation 1", "observation 2", "observation 3"],
  "betting_angles": [
    {{"market": "market_name", "reasoning": "why", "confidence": "high/medium/low"}}
  ],
  "value_shift": "which outcome is gaining/losing value"
}}"""

            # Call OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert sports betting analyst providing real-time insights. Be concise and actionable."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=500,
                response_format={"type": "json_object"}
            )
            
            ai_content = response.choices[0].message.content
            tokens_used = response.usage.total_tokens
            
            # Parse JSON response
            analysis_data = json.loads(ai_content)

            # Success — reset circuit breaker
            LiveAIAnalyzer._consecutive_failures = 0
            LiveAIAnalyzer._circuit_open = False

            return {
                'success': True,
                'analysis': analysis_data,
                'raw_content': ai_content,
                'tokens_used': tokens_used
            }
            
        except Exception as e:
            # Circuit breaker: track consecutive failures
            error_str = str(e)
            is_quota_error = '429' in error_str or 'insufficient_quota' in error_str or 'rate_limit' in error_str.lower()

            LiveAIAnalyzer._consecutive_failures += 1

            if is_quota_error or LiveAIAnalyzer._consecutive_failures >= LiveAIAnalyzer._MAX_FAILURES:
                LiveAIAnalyzer._circuit_open = True
                cooldown = LiveAIAnalyzer._CIRCUIT_COOLDOWN_MINUTES
                LiveAIAnalyzer._circuit_open_until = datetime.now() + timedelta(minutes=cooldown)
                logger.warning(
                    f"🔴 AI circuit breaker OPEN — {LiveAIAnalyzer._consecutive_failures} failures. "
                    f"No OpenAI calls for {cooldown} min (until {LiveAIAnalyzer._circuit_open_until.strftime('%H:%M')}). "
                    f"Error: {error_str[:100]}"
                )
            else:
                logger.error(f"Error generating AI analysis: {e}", exc_info=True)

            return {
                'success': False,
                'error': str(e),
                'analysis': {},
                'tokens_used': 0
            }
    
    def _format_events(self, events: List[Dict]) -> str:
        """Format events for AI prompt"""
        if not events:
            return "No recent events"
        
        formatted = []
        for e in events:
            formatted.append(
                f"{e.get('minute')}' - {e.get('type')} ({e.get('team')}) - {e.get('player', 'Unknown')}"
            )
        
        return "\n".join(formatted)
    
    def store_ai_analysis(
        self,
        match_id: int,
        trigger_reason: str,
        match_context: Dict,
        ai_result: Dict
    ):
        """Store AI analysis in database"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                stats = match_context.get('live_stats', {})
                
                cursor.execute("""
                    INSERT INTO live_ai_analysis (
                        match_id, minute, analysis_type, trigger_reason,
                        home_score, away_score,
                        odds_snapshot, statistics_snapshot,
                        ai_insights, key_observations, betting_angles,
                        momentum_assessment, tokens_used
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    match_id,
                    stats.get('minute'),
                    'live_update',
                    trigger_reason,
                    stats.get('score', {}).get('home', 0),
                    stats.get('score', {}).get('away', 0),
                    json.dumps(match_context.get('odds_velocity', {})),
                    json.dumps(stats),
                    ai_result.get('raw_content', ''),
                    json.dumps(ai_result.get('analysis', {}).get('key_observations', [])),
                    json.dumps(ai_result.get('analysis', {}).get('betting_angles', [])),
                    ai_result.get('analysis', {}).get('momentum_assessment', ''),
                    ai_result.get('tokens_used', 0)
                ))
                
                conn.commit()
                logger.info(f"✅ Stored AI analysis for match {match_id} (trigger: {trigger_reason})")
                
        except Exception as e:
            logger.error(f"Error storing AI analysis: {e}")
    
    def analyze_live_match(self, match_id: int) -> Optional[Dict]:
        """
        Main method: Check triggers and generate analysis if needed
        Returns analysis if generated, None if skipped
        """
        try:
            # Check if we should trigger analysis
            should_trigger, trigger_reason = self.should_trigger_analysis(match_id)
            
            if not should_trigger:
                logger.debug(f"Skipping analysis for match {match_id}: {trigger_reason}")
                return None
            
            logger.info(f"🤖 Triggering AI analysis for match {match_id}: {trigger_reason}")
            
            # Gather match context
            match_context = self.get_match_context(match_id)
            
            if not match_context:
                logger.warning(f"No context for match {match_id}")
                return None
            
            # Generate AI analysis
            ai_result = self.generate_ai_analysis(match_context, trigger_reason)
            
            if not ai_result.get('success'):
                logger.error(f"AI analysis failed: {ai_result.get('error')}")
                return None
            
            # Store in database
            self.store_ai_analysis(match_id, trigger_reason, match_context, ai_result)
            
            return {
                'match_id': match_id,
                'trigger_reason': trigger_reason,
                'analysis': ai_result.get('analysis', {}),
                'generated_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error analyzing live match {match_id}: {e}", exc_info=True)
            return None
    
    def analyze_all_live_matches(self):
        """Analyze all currently live matches"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # Get live matches
                cursor.execute("""
                    SELECT DISTINCT match_id
                    FROM fixtures
                    WHERE kickoff_at <= NOW()
                        AND kickoff_at > NOW() - INTERVAL '2 hours'
                        AND status = 'scheduled'
                """)
                
                match_ids = [row[0] for row in cursor.fetchall()]
                
                logger.info(f"🤖 Checking {len(match_ids)} live matches for AI analysis")
                
                analyses_generated = 0
                for match_id in match_ids:
                    result = self.analyze_live_match(match_id)
                    if result:
                        analyses_generated += 1
                
                logger.info(f"✅ Generated {analyses_generated} AI analyses")
                
        except Exception as e:
            logger.error(f"Error analyzing live matches: {e}", exc_info=True)


# Standalone function for scheduler
def analyze_live_matches():
    """Wrapper function for scheduler"""
    db_url = os.environ.get('DATABASE_URL')
    analyzer = LiveAIAnalyzer(db_url)
    analyzer.analyze_all_live_matches()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    analyze_live_matches()
