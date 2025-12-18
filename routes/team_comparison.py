"""
Team Comparison API - Head-to-Head Stats for Content Marketing
Provides fascinating matchup data perfect for evergreen blog content.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import os
from sqlalchemy import create_engine, text
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/compare", tags=["Team Comparison"])

DATABASE_URL = os.environ.get("DATABASE_URL")


class TeamComparisonRequest(BaseModel):
    team_a: str
    team_b: str


class MatchRecord(BaseModel):
    date: str
    competition: str
    stage: Optional[str]
    team_a_score: int
    team_b_score: int
    winner: str
    venue: Optional[str]
    was_penalty_shootout: bool
    shootout_result: Optional[str]


class PenaltyStats(BaseModel):
    total_shootouts: int
    wins: int
    losses: int
    win_rate: float
    notable_shootouts: List[str]


class TournamentRecord(BaseModel):
    world_cups_played: int
    world_cup_wins: int
    finals_reached: int
    best_finish: str
    total_wc_matches: int
    wc_win_rate: float


class HeadToHeadStats(BaseModel):
    total_matches: int
    team_a_wins: int
    team_b_wins: int
    draws: int
    team_a_goals: int
    team_b_goals: int
    biggest_team_a_win: Optional[str]
    biggest_team_b_win: Optional[str]
    last_5_matches: List[MatchRecord]
    competitive_matches: int
    friendly_matches: int


class InterestingFacts(BaseModel):
    facts: List[str]
    narratives: List[str]


class TeamComparisonResponse(BaseModel):
    team_a: str
    team_b: str
    head_to_head: HeadToHeadStats
    team_a_penalties: PenaltyStats
    team_b_penalties: PenaltyStats
    team_a_tournament_record: TournamentRecord
    team_b_tournament_record: TournamentRecord
    interesting_facts: InterestingFacts
    generated_at: str


def get_engine():
    if not DATABASE_URL:
        raise HTTPException(status_code=500, detail="Database not configured")
    return create_engine(DATABASE_URL)


def normalize_team_name(name: str) -> str:
    """Normalize team name for fuzzy matching"""
    replacements = {
        "usa": "United States",
        "us": "United States",
        "united states": "United States",
        "england": "England",
        "uk": "England",
        "germany": "Germany",
        "deutschland": "Germany",
        "spain": "Spain",
        "espana": "Spain",
        "france": "France",
        "brazil": "Brazil",
        "brasil": "Brazil",
        "argentina": "Argentina",
        "portugal": "Portugal",
        "netherlands": "Netherlands",
        "holland": "Netherlands",
        "italy": "Italy",
        "italia": "Italy",
        "mexico": "Mexico",
        "japan": "Japan",
        "south korea": "South Korea",
        "korea": "South Korea",
        "morocco": "Morocco",
        "croatia": "Croatia",
        "belgium": "Belgium",
        "senegal": "Senegal",
        "ghana": "Ghana",
        "nigeria": "Nigeria",
        "cameroon": "Cameroon",
        "algeria": "Algeria",
        "egypt": "Egypt",
        "tunisia": "Tunisia",
        "ivory coast": "Ivory Coast",
        "cote d'ivoire": "Ivory Coast",
    }
    lower = name.lower().strip()
    return replacements.get(lower, name.title())


def get_penalty_shootout_stats(engine, team_name: str) -> PenaltyStats:
    """Get penalty shootout history for a team from penalty_shootout_history table"""
    query = text("""
        SELECT 
            team_name,
            opponent_name,
            tournament_name,
            match_date,
            stage,
            result,
            penalties_scored,
            penalties_missed
        FROM penalty_shootout_history
        WHERE team_name ILIKE :team
        ORDER BY match_date DESC
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"team": f"%{team_name}%"})
        rows = result.fetchall()
    
    wins = 0
    losses = 0
    notable = []
    
    for row in rows:
        won = row.result == 'W'
        
        if won:
            wins += 1
        else:
            losses += 1
        
        if row.tournament_name and "World Cup" in row.tournament_name:
            result_str = "Won" if won else "Lost"
            stage = row.stage or "Match"
            year = row.match_date.year if row.match_date else 'N/A'
            notable.append(f"{result_str} vs {row.opponent_name} ({row.tournament_name} {stage}, {year})")
    
    total = wins + losses
    win_rate = round((wins / total * 100), 1) if total > 0 else 0.0
    
    return PenaltyStats(
        total_shootouts=total,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        notable_shootouts=notable[:5]
    )


def get_tournament_record(engine, team_name: str) -> TournamentRecord:
    """Get World Cup tournament record for a team from international_matches table"""
    query = text("""
        SELECT 
            home_team_name,
            away_team_name,
            home_goals,
            away_goals,
            tournament_stage,
            tournament_name,
            match_date,
            penalty_shootout,
            penalty_home,
            penalty_away,
            outcome
        FROM international_matches
        WHERE (home_team_name ILIKE :team OR away_team_name ILIKE :team)
          AND tournament_id = 1
        ORDER BY match_date DESC
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"team": f"%{team_name}%"})
        rows = result.fetchall()
    
    if not rows:
        return TournamentRecord(
            world_cups_played=0,
            world_cup_wins=0,
            finals_reached=0,
            best_finish="Never qualified",
            total_wc_matches=0,
            wc_win_rate=0.0
        )
    
    total_matches = len(rows)
    wins = 0
    finals = 0
    wc_wins = 0
    best_stage = "Group Stage"
    years_played = set()
    
    stage_rank = {
        "Final": 5,
        "Semi-finals": 4,
        "Semi-final": 4,
        "Quarter-finals": 3,
        "Quarter-final": 3,
        "Round of 16": 2,
        "Group": 1
    }
    best_rank = 0
    
    for row in rows:
        is_home = team_name.lower() in row.home_team_name.lower()
        team_score = row.home_goals if is_home else row.away_goals
        opp_score = row.away_goals if is_home else row.home_goals
        
        if row.match_date:
            years_played.add(row.match_date.year)
        
        if team_score > opp_score:
            wins += 1
        elif team_score == opp_score and row.penalty_shootout:
            team_pens = row.penalty_home if is_home else row.penalty_away
            opp_pens = row.penalty_away if is_home else row.penalty_home
            if team_pens and opp_pens and team_pens > opp_pens:
                wins += 1
        
        stage = row.tournament_stage or ""
        for stage_name, rank in stage_rank.items():
            if stage_name.lower() in stage.lower() and rank > best_rank:
                best_rank = rank
                best_stage = stage_name
        
        if "final" in stage.lower() and "semi" not in stage.lower() and "quarter" not in stage.lower():
            finals += 1
            if team_score > opp_score:
                wc_wins += 1
            elif team_score == opp_score and row.penalty_shootout:
                team_pens = row.penalty_home if is_home else row.penalty_away
                opp_pens = row.penalty_away if is_home else row.penalty_home
                if team_pens and opp_pens and team_pens > opp_pens:
                    wc_wins += 1
    
    win_rate = round((wins / total_matches * 100), 1) if total_matches > 0 else 0.0
    
    return TournamentRecord(
        world_cups_played=len(years_played),
        world_cup_wins=wc_wins,
        finals_reached=finals,
        best_finish=best_stage,
        total_wc_matches=total_matches,
        wc_win_rate=win_rate
    )


def get_head_to_head(engine, team_a: str, team_b: str) -> HeadToHeadStats:
    """Get head-to-head statistics between two teams from international_matches"""
    query = text("""
        SELECT 
            home_team_name,
            away_team_name,
            home_goals,
            away_goals,
            match_date,
            tournament_name,
            tournament_stage,
            penalty_shootout,
            penalty_home,
            penalty_away
        FROM international_matches
        WHERE (
            (home_team_name ILIKE :team_a AND away_team_name ILIKE :team_b) OR
            (home_team_name ILIKE :team_b AND away_team_name ILIKE :team_a)
        )
        ORDER BY match_date DESC
    """)
    
    with engine.connect() as conn:
        result = conn.execute(query, {"team_a": f"%{team_a}%", "team_b": f"%{team_b}%"})
        rows = result.fetchall()
    
    if not rows:
        return HeadToHeadStats(
            total_matches=0,
            team_a_wins=0,
            team_b_wins=0,
            draws=0,
            team_a_goals=0,
            team_b_goals=0,
            biggest_team_a_win=None,
            biggest_team_b_win=None,
            last_5_matches=[],
            competitive_matches=0,
            friendly_matches=0
        )
    
    team_a_wins = 0
    team_b_wins = 0
    draws = 0
    team_a_goals = 0
    team_b_goals = 0
    biggest_a_margin = 0
    biggest_b_margin = 0
    biggest_a_win = None
    biggest_b_win = None
    competitive = 0
    friendly = 0
    last_5 = []
    
    for row in rows:
        a_is_home = team_a.lower() in row.home_team_name.lower()
        
        a_score = row.home_goals if a_is_home else row.away_goals
        b_score = row.away_goals if a_is_home else row.home_goals
        
        team_a_goals += a_score
        team_b_goals += b_score
        
        tournament = row.tournament_name or ""
        is_competitive = any(x in tournament.lower() for x in ["world cup", "euro", "copa", "nations", "qualifier", "afcon"])
        if is_competitive:
            competitive += 1
        else:
            friendly += 1
        
        was_shootout = bool(row.penalty_shootout)
        shootout_result = None
        
        if a_score > b_score:
            team_a_wins += 1
            winner = team_a
            margin = a_score - b_score
            if margin > biggest_a_margin:
                biggest_a_margin = margin
                year = row.match_date.year if row.match_date else 'N/A'
                biggest_a_win = f"{a_score}-{b_score} ({row.tournament_name}, {year})"
        elif b_score > a_score:
            team_b_wins += 1
            winner = team_b
            margin = b_score - a_score
            if margin > biggest_b_margin:
                biggest_b_margin = margin
                year = row.match_date.year if row.match_date else 'N/A'
                biggest_b_win = f"{b_score}-{a_score} ({row.tournament_name}, {year})"
        else:
            if row.penalty_shootout and row.penalty_home and row.penalty_away:
                a_pens = row.penalty_home if a_is_home else row.penalty_away
                b_pens = row.penalty_away if a_is_home else row.penalty_home
                shootout_result = f"{a_pens}-{b_pens}"
                if a_pens > b_pens:
                    team_a_wins += 1
                    winner = f"{team_a} (pens)"
                else:
                    team_b_wins += 1
                    winner = f"{team_b} (pens)"
            else:
                draws += 1
                winner = "Draw"
        
        if len(last_5) < 5:
            last_5.append(MatchRecord(
                date=row.match_date.strftime("%Y-%m-%d") if row.match_date else "Unknown",
                competition=row.tournament_name or "Unknown",
                stage=row.tournament_stage,
                team_a_score=a_score,
                team_b_score=b_score,
                winner=winner,
                venue="Neutral",
                was_penalty_shootout=was_shootout,
                shootout_result=shootout_result
            ))
    
    return HeadToHeadStats(
        total_matches=len(rows),
        team_a_wins=team_a_wins,
        team_b_wins=team_b_wins,
        draws=draws,
        team_a_goals=team_a_goals,
        team_b_goals=team_b_goals,
        biggest_team_a_win=biggest_a_win,
        biggest_team_b_win=biggest_b_win,
        last_5_matches=last_5,
        competitive_matches=competitive,
        friendly_matches=friendly
    )


def generate_interesting_facts(
    team_a: str,
    team_b: str,
    h2h: HeadToHeadStats,
    pen_a: PenaltyStats,
    pen_b: PenaltyStats,
    tourn_a: TournamentRecord,
    tourn_b: TournamentRecord
) -> InterestingFacts:
    """Generate compelling facts and narratives for blog content"""
    facts = []
    narratives = []
    
    if h2h.total_matches > 0:
        facts.append(f"{team_a} and {team_b} have met {h2h.total_matches} times in international football")
        
        if h2h.team_a_wins > h2h.team_b_wins:
            facts.append(f"{team_a} leads the all-time series {h2h.team_a_wins}-{h2h.team_b_wins}-{h2h.draws}")
        elif h2h.team_b_wins > h2h.team_a_wins:
            facts.append(f"{team_b} leads the all-time series {h2h.team_b_wins}-{h2h.team_a_wins}-{h2h.draws}")
        else:
            facts.append(f"The all-time series is perfectly even: {h2h.team_a_wins}-{h2h.team_b_wins}-{h2h.draws}")
        
        avg_goals = (h2h.team_a_goals + h2h.team_b_goals) / h2h.total_matches
        facts.append(f"Their matches average {avg_goals:.1f} goals per game")
    
    if pen_a.total_shootouts > 0:
        if pen_a.win_rate >= 70:
            facts.append(f"{team_a} are penalty shootout specialists with a {pen_a.win_rate}% win rate ({pen_a.wins}/{pen_a.total_shootouts})")
        elif pen_a.win_rate <= 30:
            facts.append(f"{team_a} have historically struggled in shootouts with just a {pen_a.win_rate}% win rate ({pen_a.wins}/{pen_a.total_shootouts})")
    
    if pen_b.total_shootouts > 0:
        if pen_b.win_rate >= 70:
            facts.append(f"{team_b} are penalty shootout specialists with a {pen_b.win_rate}% win rate ({pen_b.wins}/{pen_b.total_shootouts})")
        elif pen_b.win_rate <= 30:
            facts.append(f"{team_b} have historically struggled in shootouts with just a {pen_b.win_rate}% win rate ({pen_b.wins}/{pen_b.total_shootouts})")
    
    if pen_a.total_shootouts > 0 and pen_b.total_shootouts > 0:
        diff = abs(pen_a.win_rate - pen_b.win_rate)
        if diff >= 40:
            better = team_a if pen_a.win_rate > pen_b.win_rate else team_b
            worse = team_b if pen_a.win_rate > pen_b.win_rate else team_a
            better_rate = max(pen_a.win_rate, pen_b.win_rate)
            worse_rate = min(pen_a.win_rate, pen_b.win_rate)
            narratives.append(f"In a penalty shootout scenario, {better} would be heavy favorites with their {better_rate}% win rate compared to {worse}'s {worse_rate}%")
    
    if tourn_a.world_cup_wins > 0 and tourn_b.world_cup_wins > 0:
        total = tourn_a.world_cup_wins + tourn_b.world_cup_wins
        facts.append(f"Between them, these nations have won {total} World Cups ({team_a}: {tourn_a.world_cup_wins}, {team_b}: {tourn_b.world_cup_wins})")
    elif tourn_a.world_cup_wins > 0:
        facts.append(f"{team_a} have won {tourn_a.world_cup_wins} World Cup(s) while {team_b} are still searching for their first")
    elif tourn_b.world_cup_wins > 0:
        facts.append(f"{team_b} have won {tourn_b.world_cup_wins} World Cup(s) while {team_a} are still searching for their first")
    
    if tourn_a.wc_win_rate > 0 and tourn_b.wc_win_rate > 0:
        if abs(tourn_a.wc_win_rate - tourn_b.wc_win_rate) >= 10:
            better = team_a if tourn_a.wc_win_rate > tourn_b.wc_win_rate else team_b
            better_rate = max(tourn_a.wc_win_rate, tourn_b.wc_win_rate)
            facts.append(f"{better} have the superior World Cup win rate at {better_rate}%")
    
    if h2h.competitive_matches > h2h.friendly_matches and h2h.total_matches > 0:
        pct = round(h2h.competitive_matches / h2h.total_matches * 100)
        narratives.append(f"This is a true competitive rivalry - {pct}% of their meetings have been in competitive fixtures")
    
    if h2h.last_5_matches:
        shootout_count = sum(1 for m in h2h.last_5_matches if m.was_penalty_shootout)
        if shootout_count >= 2:
            narratives.append(f"Drama follows this fixture - {shootout_count} of their last 5 meetings went to penalty shootouts")
    
    close_games = [m for m in h2h.last_5_matches if abs(m.team_a_score - m.team_b_score) <= 1 or m.was_penalty_shootout]
    if len(close_games) >= 4:
        narratives.append("Expect a tight game - their recent meetings have been decided by fine margins")
    
    return InterestingFacts(facts=facts, narratives=narratives)


@router.get("/teams", response_model=TeamComparisonResponse)
async def compare_teams(
    team_a: str = Query(..., description="First team name (e.g., Argentina)"),
    team_b: str = Query(..., description="Second team name (e.g., France)")
):
    """
    Compare two national teams with head-to-head stats, penalty records,
    tournament history, and interesting facts for blog content.
    
    Example: /api/v1/compare/teams?team_a=Argentina&team_b=France
    """
    engine = get_engine()
    
    team_a_norm = normalize_team_name(team_a)
    team_b_norm = normalize_team_name(team_b)
    
    h2h = get_head_to_head(engine, team_a_norm, team_b_norm)
    pen_a = get_penalty_shootout_stats(engine, team_a_norm)
    pen_b = get_penalty_shootout_stats(engine, team_b_norm)
    tourn_a = get_tournament_record(engine, team_a_norm)
    tourn_b = get_tournament_record(engine, team_b_norm)
    
    facts = generate_interesting_facts(team_a_norm, team_b_norm, h2h, pen_a, pen_b, tourn_a, tourn_b)
    
    return TeamComparisonResponse(
        team_a=team_a_norm,
        team_b=team_b_norm,
        head_to_head=h2h,
        team_a_penalties=pen_a,
        team_b_penalties=pen_b,
        team_a_tournament_record=tourn_a,
        team_b_tournament_record=tourn_b,
        interesting_facts=facts,
        generated_at=datetime.utcnow().isoformat()
    )


@router.get("/popular-matchups")
async def get_popular_matchups():
    """Get a list of popular team matchups for content inspiration"""
    matchups = [
        {"team_a": "Argentina", "team_b": "France", "context": "2022 World Cup Final rivals"},
        {"team_a": "Brazil", "team_b": "Germany", "context": "Historic rivalry, 7-1 never forget"},
        {"team_a": "England", "team_b": "Germany", "context": "Classic European rivalry"},
        {"team_a": "Argentina", "team_b": "Brazil", "context": "South American Superclasico"},
        {"team_a": "Spain", "team_b": "Italy", "context": "Euro powerhouses"},
        {"team_a": "Netherlands", "team_b": "Germany", "context": "Fierce neighbors rivalry"},
        {"team_a": "Mexico", "team_b": "United States", "context": "CONCACAF rivalry"},
        {"team_a": "Nigeria", "team_b": "Cameroon", "context": "African giants clash"},
        {"team_a": "Japan", "team_b": "South Korea", "context": "Asian rivals"},
        {"team_a": "Morocco", "team_b": "Algeria", "context": "North African derby"},
    ]
    return {"matchups": matchups, "total": len(matchups)}


@router.get("/team/{team_name}/penalty-history")
async def get_team_penalty_history(team_name: str):
    """
    Get detailed penalty shootout history for a single team.
    Perfect for "Team X's Penalty Curse" type blog posts.
    """
    engine = get_engine()
    team_norm = normalize_team_name(team_name)
    stats = get_penalty_shootout_stats(engine, team_norm)
    
    return {
        "team": team_norm,
        "penalty_stats": stats,
        "blog_angle": _get_penalty_blog_angle(team_norm, stats),
        "generated_at": datetime.utcnow().isoformat()
    }


def _get_penalty_blog_angle(team: str, stats: PenaltyStats) -> str:
    """Suggest a blog angle based on penalty stats"""
    if stats.total_shootouts == 0:
        return f"{team}'s Uncharted Territory: A Team Without Shootout Experience"
    elif stats.win_rate >= 80:
        return f"{team}'s Penalty Masterclass: The Secrets Behind Their {stats.win_rate}% Win Rate"
    elif stats.win_rate >= 60:
        return f"Cool Under Pressure: How {team} Excel in Penalty Shootouts"
    elif stats.win_rate <= 25:
        return f"The {team} Penalty Curse: Breaking Down Their {stats.win_rate}% Win Rate"
    elif stats.win_rate <= 40:
        return f"When Nerves Strike: Why {team} Struggle From the Spot"
    else:
        return f"{team} in Shootouts: A Mixed Record That Could Go Either Way"
