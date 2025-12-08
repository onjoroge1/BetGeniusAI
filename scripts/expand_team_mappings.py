#!/usr/bin/env python3
"""
Automated Team Name Mapping Expansion Script

This script automatically expands team_name_mapping by:
1. Finding all unmapped teams in historical_odds
2. Using fuzzy matching to find corresponding teams in training_matches/fixtures
3. Adding verified mappings to the database
4. Optionally running the backfill to populate historical_features

Features:
- Multi-strategy matching (exact, normalized, fuzzy, word-based)
- Confidence scoring for each match
- Bulk insert with conflict handling
- Progress logging and statistics
"""

import os
import sys
import re
import logging
import psycopg2
from psycopg2.extras import execute_values
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Optional
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get('DATABASE_URL')

TEAM_NAME_ALIASES = {
    # England
    'Man United': 'Manchester United',
    'Man City': 'Manchester City',
    'Tottenham': 'Tottenham Hotspur',
    'Newcastle': 'Newcastle United',
    'Wolves': 'Wolverhampton Wanderers',
    'West Ham': 'West Ham United',
    'Brighton': 'Brighton & Hove Albion',
    'Sheffield Utd': 'Sheffield United',
    'Nott\'m Forest': 'Nottingham Forest',
    'Nottingham': 'Nottingham Forest',
    'Leeds': 'Leeds United',
    'Leicester': 'Leicester City',
    'Burnley': 'Burnley FC',
    'Southampton': 'Southampton FC',
    'Everton': 'Everton FC',
    'Fulham': 'Fulham FC',
    'Norwich': 'Norwich City',
    'Watford': 'Watford FC',
    'West Brom': 'West Bromwich Albion',
    'Bournemouth': 'AFC Bournemouth',
    'Huddersfield': 'Huddersfield Town',
    'Swansea': 'Swansea City',
    'Stoke': 'Stoke City',
    'Hull': 'Hull City',
    'Cardiff': 'Cardiff City',
    'QPR': 'Queens Park Rangers',
    'Sunderland': 'Sunderland AFC',
    'Middlesbrough': 'Middlesbrough FC',
    'Ipswich': 'Ipswich Town',
    # Italy
    'Inter': 'Inter Milan',
    'Internazionale': 'Inter Milan',
    'AC Milan': 'Milan',
    'Roma': 'AS Roma',
    'Lazio': 'SS Lazio',
    'Napoli': 'SSC Napoli',
    'Juventus': 'Juventus FC',
    'Chievo': 'Chievo Verona',
    'Parma': 'Parma Calcio 1913',
    'Palermo': 'Palermo FC',
    'Catania': 'Catania FC',
    'Genoa': 'Genoa CFC',
    'Sampdoria': 'UC Sampdoria',
    'Torino': 'Torino FC',
    'Udinese': 'Udinese Calcio',
    'Verona': 'Hellas Verona',
    'Bologna': 'Bologna FC 1909',
    'Cagliari': 'Cagliari Calcio',
    'Sassuolo': 'US Sassuolo',
    'Spezia': 'Spezia Calcio',
    'Salernitana': 'US Salernitana 1919',
    'Empoli': 'Empoli FC',
    'Monza': 'AC Monza',
    'Frosinone': 'Frosinone Calcio',
    'Lecce': 'US Lecce',
    'Cremonese': 'US Cremonese',
    'Cosenza': 'Cosenza Calcio',
    'Cittadella': 'AS Cittadella',
    'Pisa': 'Pisa SC',
    'Ascoli': 'Ascoli Calcio 1898',
    'Perugia': 'AC Perugia Calcio',
    'Reggina': 'Reggina 1914',
    'Brescia': 'Brescia Calcio',
    'Bari': 'SSC Bari',
    'Benevento': 'Benevento Calcio',
    'Modena': 'Modena FC',
    'Venezia': 'Venezia FC',
    'Ternana': 'Ternana Calcio',
    'SPAL': 'SPAL 2013',
    'Crotone': 'FC Crotone',
    # Spain
    'Atletico': 'Atletico Madrid',
    'Athletic': 'Athletic Bilbao',
    'Real': 'Real Madrid',
    'Barcelona': 'FC Barcelona',
    'Sociedad': 'Real Sociedad',
    'Betis': 'Real Betis',
    'Celta': 'Celta Vigo',
    'Mallorca': 'RCD Mallorca',
    'Villarreal': 'Villarreal CF',
    'Sevilla': 'Sevilla FC',
    'Valencia': 'Valencia CF',
    'Getafe': 'Getafe CF',
    'Osasuna': 'CA Osasuna',
    'Alaves': 'Deportivo Alaves',
    'Eibar': 'SD Eibar',
    'Levante': 'Levante UD',
    'Granada': 'Granada CF',
    'Valladolid': 'Real Valladolid',
    'Cadiz': 'Cadiz CF',
    'Elche': 'Elche CF',
    'Rayo Vallecano': 'Rayo Vallecano',
    'Almeria': 'UD Almeria',
    'Leganes': 'CD Leganes',
    'Girona': 'Girona FC',
    'Tenerife': 'CD Tenerife',
    'Sp Gijon': 'Sporting Gijon',
    'Santander': 'Racing Santander',
    'Cartagena': 'FC Cartagena',
    'Alcorcon': 'AD Alcorcon',
    'Lugo': 'CD Lugo',
    'Ponferradina': 'SD Ponferradina',
    'Huesca': 'SD Huesca',
    'Zaragoza': 'Real Zaragoza',
    'Las Palmas': 'UD Las Palmas',
    'Malaga': 'Malaga CF',
    'Mirandes': 'CD Mirandes',
    'Burgos': 'Burgos CF',
    'Oviedo': 'Real Oviedo',
    'Albacete': 'Albacete Balompie',
    'Eibar': 'SD Eibar',
    # Germany
    'Bayern': 'Bayern Munich',
    'Bayern München': 'Bayern Munich',
    'Dortmund': 'Borussia Dortmund',
    'Leverkusen': 'Bayer Leverkusen',
    'M\'gladbach': 'Borussia Monchengladbach',
    'Mgladbach': 'Borussia Monchengladbach',
    'Frankfurt': 'Eintracht Frankfurt',
    'Mainz': 'Mainz 05',
    'Freiburg': 'SC Freiburg',
    'Leipzig': 'RB Leipzig',
    'Koln': 'FC Koln',
    'Wolfsburg': 'VfL Wolfsburg',
    'Hoffenheim': 'TSG Hoffenheim',
    'Union Berlin': 'Union Berlin',
    'Hertha': 'Hertha Berlin',
    'Augsburg': 'FC Augsburg',
    'Bremen': 'Werder Bremen',
    'Dusseldorf': 'Fortuna Dusseldorf',
    'Schalke': 'Schalke 04',
    'Stuttgart': 'VfB Stuttgart',
    'Bochum': 'VfL Bochum',
    'Heidenheim': 'FC Heidenheim',
    'Darmstadt': 'SV Darmstadt 98',
    'Paderborn': 'SC Paderborn',
    'Karlsruhe': 'Karlsruher SC',
    'Regensburg': 'SSV Jahn Regensburg',
    'Sandhausen': 'SV Sandhausen',
    'Braunschweig': 'Eintracht Braunschweig',
    'Erzgebirge Aue': 'Erzgebirge Aue',
    'Nurnberg': 'FC Nurnberg',
    'Ingolstadt': 'FC Ingolstadt',
    'Greuther Furth': 'SpVgg Greuther Furth',
    'Kaiserslautern': 'Kaiserslautern',
    'Hannover': 'Hannover 96',
    'Magdeburg': 'FC Magdeburg',
    'Kiel': 'Holstein Kiel',
    'Hamburg': 'Hamburger SV',
    'St Pauli': 'FC St. Pauli',
    'Elversberg': 'SV Elversberg',
    'Wehen': 'SV Wehen Wiesbaden',
    'Rostock': 'Hansa Rostock',
    # France
    'PSG': 'Paris Saint-Germain',
    'Paris SG': 'Paris Saint-Germain',
    'Paris Saint Germain': 'Paris Saint-Germain',
    'Lyon': 'Olympique Lyon',
    'Marseille': 'Olympique Marseille',
    'Monaco': 'AS Monaco',
    'Lille': 'LOSC Lille',
    'Lens': 'RC Lens',
    'Nice': 'OGC Nice',
    'Rennes': 'Stade Rennais',
    'Reims': 'Stade de Reims',
    'Nantes': 'FC Nantes',
    'Montpellier': 'Montpellier HSC',
    'Bordeaux': 'Girondins Bordeaux',
    'Nancy': 'AS Nancy',
    'Caen': 'SM Caen',
    'Valenciennes': 'Valenciennes FC',
    'Sochaux': 'FC Sochaux',
    'Toulouse': 'Toulouse FC',
    'Strasbourg': 'RC Strasbourg',
    'Lorient': 'FC Lorient',
    'Brest': 'Stade Brest',
    'Angers': 'Angers SCO',
    'Metz': 'FC Metz',
    'Dijon': 'Dijon FCO',
    'Nimes': 'Nimes Olympique',
    'Amiens': 'Amiens SC',
    'Guingamp': 'EA Guingamp',
    'Auxerre': 'AJ Auxerre',
    'Troyes': 'ES Troyes',
    'Ajaccio': 'AC Ajaccio',
    'Le Havre': 'Le Havre AC',
    'Clermont': 'Clermont Foot',
    # Netherlands
    'Ajax': 'Ajax Amsterdam',
    'PSV': 'PSV Eindhoven',
    'Feyenoord': 'Feyenoord Rotterdam',
    'Az Alkmaar': 'AZ Alkmaar',
    'AZ': 'AZ Alkmaar',
    'Twente': 'FC Twente',
    'Utrecht': 'FC Utrecht',
    'Vitesse': 'Vitesse Arnhem',
    'Waalwijk': 'RKC Waalwijk',
    'Willem II': 'Willem II',
    'Heerenveen': 'SC Heerenveen',
    'Groningen': 'FC Groningen',
    'Heracles': 'Heracles Almelo',
    'Sparta Rotterdam': 'Sparta Rotterdam',
    'NEC Nijmegen': 'NEC Nijmegen',
    'Emmen': 'FC Emmen',
    'Fortuna Sittard': 'Fortuna Sittard',
    'Cambuur': 'SC Cambuur',
    'Volendam': 'FC Volendam',
    'Excelsior': 'Excelsior Rotterdam',
    'Den Haag': 'ADO Den Haag',
    'Zwolle': 'PEC Zwolle',
    # Belgium
    'Brugge': 'Club Brugge',
    'Club Bruges': 'Club Brugge',
    'Anderlecht': 'RSC Anderlecht',
    'Gent': 'KAA Gent',
    'Genk': 'KRC Genk',
    'Standard': 'Standard Liege',
    'Antwerp': 'Royal Antwerp',
    'St Truiden': 'St. Truiden',
    'Cercle Brugge': 'Cercle Brugge',
    'Kortrijk': 'KV Kortrijk',
    'Eupen': 'AS Eupen',
    'Waregem': 'SV Zulte Waregem',
    'Oostende': 'KV Oostende',
    'Oud-Heverlee Leuven': 'OH Leuven',
    'Charleroi': 'Sporting Charleroi',
    'Mechelen': 'KV Mechelen',
    'Westerlo': 'KVC Westerlo',
    'Seraing': 'RFC Seraing',
    'Beerschot': 'Beerschot VA',
    # Portugal
    'Porto': 'FC Porto',
    'Benfica': 'SL Benfica',
    'Sporting': 'Sporting CP',
    'Sp Lisbon': 'Sporting CP',
    'Braga': 'SC Braga',
    'Guimaraes': 'Vitoria Guimaraes',
    'Boavista': 'Boavista FC',
    'Maritimo': 'CS Maritimo',
    'Portimonense': 'Portimonense SC',
    'Santa Clara': 'CD Santa Clara',
    'Belenenses': 'Belenenses SAD',
    'Pacos Ferreira': 'FC Pacos de Ferreira',
    'Rio Ave': 'Rio Ave FC',
    'Gil Vicente': 'Gil Vicente FC',
    'Famalicao': 'FC Famalicao',
    'Arouca': 'FC Arouca',
    'Vizela': 'FC Vizela',
    'Estoril': 'Estoril Praia',
    'Casa Pia': 'Casa Pia AC',
    'Moreirense': 'Moreirense FC',
    'Chaves': 'GD Chaves',
    # Turkey
    'Galatasaray': 'Galatasaray SK',
    'Fenerbahce': 'Fenerbahce SK',
    'Besiktas': 'Besiktas JK',
    'Trabzonspor': 'Trabzonspor',
    'Buyuksehyr': 'Istanbul Basaksehir',
    'Gaziantep': 'Gaziantep FK',
    'Sivasspor': 'Sivasspor',
    'Ankaragucu': 'Ankaragucu',
    'Hatayspor': 'Hatayspor',
    'Karagumruk': 'Fatih Karagumruk',
    'Yeni Malatyaspor': 'Yeni Malatyaspor',
    'Ad. Demirspor': 'Adana Demirspor',
    'Kayserispor': 'Kayserispor',
    'Konyaspor': 'Konyaspor',
    'Alanyaspor': 'Alanyaspor',
    'Kasimpasa': 'Kasimpasa',
    'Giresunspor': 'Giresunspor',
    'Rizespor': 'Caykur Rizespor',
    'Antalyaspor': 'Antalyaspor',
    'Goztepe': 'Goztepe',
    'Altay': 'Altay SK',
    'Istanbulspor': 'Istanbulspor',
    'Umraniyespor': 'Umraniyespor',
    'Pendikspor': 'Pendikspor',
    'Eyupspor': 'Eyupspor',
    'Bodrum': 'Bodrum FK',
    # Scotland
    'St Gilloise': 'Union Saint-Gilloise',
    'Celtic': 'Celtic FC',
    'Rangers': 'Rangers FC',
    'Aberdeen': 'Aberdeen FC',
    'Hearts': 'Heart of Midlothian',
    'Hibernian': 'Hibernian FC',
    'Dundee United': 'Dundee United',
    'Kilmarnock': 'Kilmarnock FC',
    'St Johnstone': 'St. Johnstone',
    'St Mirren': 'St. Mirren',
    'Livingston': 'Livingston FC',
    'Ross County': 'Ross County',
    'Motherwell': 'Motherwell FC',
    'Partick': 'Partick Thistle',
    'Queen of Sth': "Queen of the South",
    'Dunfermline': 'Dunfermline Athletic',
    'Falkirk': 'Falkirk FC',
    'Inverness CT': 'Inverness CT',
    'Airdrieonians': 'Airdrieonians FC',
    'Arbroath': 'Arbroath FC',
    'Greenock Morton': 'Greenock Morton',
    'Hamilton': 'Hamilton Academical',
    # Additional specific mappings for problematic teams
    'Cittadella': 'Cittadella',
    'Kortrijk': 'Kortrijk',
    'Gaziantep': 'Gaziantep FK',
    'Eupen': 'Eupen',
    'Chievo': 'Chievo Verona',
    'Maritimo': 'Maritimo',
    'Sandhausen': 'Sandhausen',
    'Oostende': 'Oostende',
    'Willem II': 'Willem II Tilburg',
    'Sochaux': 'Sochaux',
    'Perugia': 'Perugia',
    'Pacos Ferreira': 'Pacos de Ferreira',
    'FC Emmen': 'Emmen',
    'Fuenlabrada': 'Fuenlabrada',
    'Blackburn': 'Blackburn Rovers',
    'Middlesbrough': 'Middlesbrough',
    'Vizela': 'Vizela',
    'Beerschot VA': 'Beerschot',
    'Hansa Rostock': 'Hansa Rostock',
    'Cosenza': 'Cosenza',
    'Ascoli': 'Ascoli',
    'Cartagena': 'Cartagena',
    'Regensburg': 'Jahn Regensburg',
    'Boavista': 'Boavista',
}

def normalize_team_name(name: str) -> str:
    """Normalize team name for matching"""
    if not name:
        return ""
    
    name = name.lower().strip()
    
    name = re.sub(r'\bfc\b', '', name)
    name = re.sub(r'\bsc\b', '', name)
    name = re.sub(r'\bsk\b', '', name)
    name = re.sub(r'\bcf\b', '', name)
    name = re.sub(r'\bafc\b', '', name)
    name = re.sub(r'\bud\b', '', name)
    name = re.sub(r'\bcd\b', '', name)
    name = re.sub(r'\brcd\b', '', name)
    name = re.sub(r'\bas\b', '', name)
    name = re.sub(r'\bss\b', '', name)
    name = re.sub(r'\bssc\b', '', name)
    name = re.sub(r'\brsc\b', '', name)
    name = re.sub(r'\bkaa\b', '', name)
    name = re.sub(r'\bkrc\b', '', name)
    name = re.sub(r'\blogc\b', '', name)
    name = re.sub(r'\brc\b', '', name)
    name = re.sub(r'\brb\b', '', name)
    name = re.sub(r'\bhsc\b', '', name)
    name = re.sub(r'\b1\.\s*\b', '', name)
    name = re.sub(r'\b18\d{2}\b', '', name)
    name = re.sub(r'\b19\d{2}\b', '', name)
    name = re.sub(r'\b20\d{2}\b', '', name)
    name = re.sub(r'\b0\d\b', '', name)
    
    name = name.replace("ü", "u").replace("ö", "o").replace("ä", "a")
    name = name.replace("é", "e").replace("è", "e").replace("ê", "e")
    name = name.replace("á", "a").replace("à", "a").replace("â", "a")
    name = name.replace("ó", "o").replace("ò", "o").replace("ô", "o")
    name = name.replace("ú", "u").replace("ù", "u").replace("û", "u")
    name = name.replace("í", "i").replace("ì", "i").replace("î", "i")
    name = name.replace("ñ", "n").replace("ç", "c")
    name = name.replace("ø", "o").replace("å", "a").replace("æ", "ae")
    
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def get_key_words(name: str) -> set:
    """Extract key identifying words from team name"""
    norm = normalize_team_name(name)
    words = set(norm.split())
    
    stop_words = {'united', 'city', 'town', 'rovers', 'wanderers', 'athletic', 
                  'real', 'sporting', 'racing', 'royal', 'olympic', 'olympique'}
    
    key_words = words - stop_words
    return key_words if key_words else words

def fuzzy_match_score(name1: str, name2: str) -> float:
    """Calculate fuzzy match score between two team names"""
    norm1 = normalize_team_name(name1)
    norm2 = normalize_team_name(name2)
    
    if norm1 == norm2:
        return 1.0
    
    ratio = SequenceMatcher(None, norm1, norm2).ratio()
    
    words1 = get_key_words(name1)
    words2 = get_key_words(name2)
    
    if words1 and words2:
        common = words1 & words2
        word_score = len(common) / max(len(words1), len(words2))
        ratio = max(ratio, word_score)
    
    return ratio

def get_unmapped_teams(conn) -> List[Dict]:
    """Get all teams from historical_odds that don't have mappings"""
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT ho.home_team as team_name, ho.league, 
               COUNT(*) as match_count
        FROM historical_odds ho
        LEFT JOIN team_name_mapping tnm ON ho.home_team = tnm.historical_name
        WHERE tnm.historical_name IS NULL
          AND ho.home_shots IS NOT NULL
        GROUP BY ho.home_team, ho.league
        
        UNION
        
        SELECT DISTINCT ho.away_team as team_name, ho.league,
               COUNT(*) as match_count
        FROM historical_odds ho
        LEFT JOIN team_name_mapping tnm ON ho.away_team = tnm.historical_name
        WHERE tnm.historical_name IS NULL
          AND ho.home_shots IS NOT NULL
        GROUP BY ho.away_team, ho.league
        
        ORDER BY match_count DESC
    """)
    
    teams = []
    for row in cursor.fetchall():
        teams.append({
            'name': row[0],
            'league': row[1],
            'match_count': row[2]
        })
    
    cursor.close()
    return teams

def get_api_football_teams(conn, league_id: int) -> List[Dict]:
    """Get teams from training_matches/fixtures for a specific league"""
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT home_team as team_name, home_team_id as team_id
        FROM training_matches
        WHERE league_id = %s AND home_team IS NOT NULL
        
        UNION
        
        SELECT DISTINCT away_team as team_name, away_team_id as team_id
        FROM training_matches
        WHERE league_id = %s AND away_team IS NOT NULL
        
        UNION
        
        SELECT DISTINCT home_team as team_name, home_team_id as team_id
        FROM fixtures
        WHERE league_id = %s AND home_team IS NOT NULL
        
        UNION
        
        SELECT DISTINCT away_team as team_name, away_team_id as team_id
        FROM fixtures
        WHERE league_id = %s AND away_team IS NOT NULL
    """, (league_id, league_id, league_id, league_id))
    
    teams = []
    for row in cursor.fetchall():
        if row[0] and row[1]:
            teams.append({
                'name': row[0],
                'team_id': row[1]
            })
    
    cursor.close()
    return teams

def get_all_api_football_teams(conn) -> List[Dict]:
    """Get ALL teams from training_matches/fixtures across all leagues (for fallback)"""
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT home_team as team_name, home_team_id as team_id, league_id
        FROM training_matches
        WHERE home_team IS NOT NULL AND home_team_id IS NOT NULL
        
        UNION
        
        SELECT DISTINCT away_team as team_name, away_team_id as team_id, league_id
        FROM training_matches
        WHERE away_team IS NOT NULL AND away_team_id IS NOT NULL
        
        UNION
        
        SELECT DISTINCT home_team as team_name, home_team_id as team_id, league_id
        FROM fixtures
        WHERE home_team IS NOT NULL AND home_team_id IS NOT NULL
        
        UNION
        
        SELECT DISTINCT away_team as team_name, away_team_id as team_id, league_id
        FROM fixtures
        WHERE away_team IS NOT NULL AND away_team_id IS NOT NULL
    """)
    
    teams = []
    for row in cursor.fetchall():
        if row[0] and row[1]:
            teams.append({
                'name': row[0],
                'team_id': row[1],
                'league_id': row[2]
            })
    
    cursor.close()
    return teams

def get_league_mapping(conn) -> Dict[str, int]:
    """Get historical league code to API-Football league ID mapping"""
    cursor = conn.cursor()
    cursor.execute("SELECT historical_code, api_football_league_id FROM league_code_mapping")
    mapping = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.close()
    return mapping

def find_best_match(historical_name: str, api_teams: List[Dict], 
                    threshold: float = 0.6) -> Optional[Dict]:
    """Find the best matching API-Football team for a historical team name"""
    
    if historical_name in TEAM_NAME_ALIASES:
        alias = TEAM_NAME_ALIASES[historical_name]
        for team in api_teams:
            if normalize_team_name(team['name']) == normalize_team_name(alias):
                return {
                    'api_name': team['name'],
                    'team_id': team['team_id'],
                    'score': 1.0,
                    'match_type': 'alias'
                }
    
    norm_historical = normalize_team_name(historical_name)
    for team in api_teams:
        if normalize_team_name(team['name']) == norm_historical:
            return {
                'api_name': team['name'],
                'team_id': team['team_id'],
                'score': 1.0,
                'match_type': 'exact'
            }
    
    best_match = None
    best_score = 0.0
    
    for team in api_teams:
        score = fuzzy_match_score(historical_name, team['name'])
        if score > best_score:
            best_score = score
            best_match = team
    
    if best_match and best_score >= threshold:
        return {
            'api_name': best_match['name'],
            'team_id': best_match['team_id'],
            'score': best_score,
            'match_type': 'fuzzy'
        }
    
    return None

def insert_mappings(conn, mappings: List[Dict]) -> int:
    """Insert new team mappings into database"""
    if not mappings:
        return 0
    
    cursor = conn.cursor()
    
    values = [
        (m['historical_name'], m['league_code'], m['team_id'], m['api_name'], m['score'])
        for m in mappings
    ]
    
    execute_values(
        cursor,
        """INSERT INTO team_name_mapping (historical_name, historical_league, api_football_team_id, api_football_name, confidence)
           VALUES %s
           ON CONFLICT (historical_name, historical_league) DO NOTHING""",
        values
    )
    
    inserted = cursor.rowcount
    conn.commit()
    cursor.close()
    
    return inserted

def expand_mappings(threshold: float = 0.65, dry_run: bool = False) -> Dict:
    """Main function to expand team mappings"""
    
    logger.info("=" * 60)
    logger.info("AUTOMATED TEAM MAPPING EXPANSION")
    logger.info("=" * 60)
    
    conn = psycopg2.connect(DATABASE_URL)
    
    unmapped_teams = get_unmapped_teams(conn)
    logger.info(f"Found {len(unmapped_teams)} unmapped teams in historical_odds")
    
    league_mapping = get_league_mapping(conn)
    logger.info(f"Loaded {len(league_mapping)} league mappings")
    
    all_api_teams = get_all_api_football_teams(conn)
    logger.info(f"Loaded {len(all_api_teams)} teams from API-Football data (cross-league fallback)")
    
    api_teams_cache = {}
    
    new_mappings = []
    failed_matches = []
    seen_historical_names = set()
    
    stats = {
        'total_unmapped': len(unmapped_teams),
        'exact_matches': 0,
        'alias_matches': 0,
        'fuzzy_matches': 0,
        'cross_league_matches': 0,
        'failed_matches': 0,
        'by_league': defaultdict(lambda: {'found': 0, 'failed': 0})
    }
    
    for i, team in enumerate(unmapped_teams):
        historical_name = team['name']
        league_code = team['league']
        
        if historical_name in seen_historical_names:
            continue
        seen_historical_names.add(historical_name)
        
        api_league_id = league_mapping.get(league_code)
        
        match = None
        
        if api_league_id:
            if api_league_id not in api_teams_cache:
                api_teams_cache[api_league_id] = get_api_football_teams(conn, api_league_id)
            
            api_teams = api_teams_cache[api_league_id]
            
            if api_teams:
                match = find_best_match(historical_name, api_teams, threshold)
        
        if not match:
            match = find_best_match(historical_name, all_api_teams, threshold)
            if match:
                match['match_type'] = 'cross_league'
        
        if match:
            new_mappings.append({
                'historical_name': historical_name,
                'api_name': match['api_name'],
                'team_id': match['team_id'],
                'league_code': league_code,
                'score': match['score'],
                'match_type': match['match_type']
            })
            
            if match['match_type'] == 'exact':
                stats['exact_matches'] += 1
            elif match['match_type'] == 'alias':
                stats['alias_matches'] += 1
            elif match['match_type'] == 'cross_league':
                stats['cross_league_matches'] += 1
            else:
                stats['fuzzy_matches'] += 1
            
            stats['by_league'][league_code]['found'] += 1
        else:
            stats['failed_matches'] += 1
            stats['by_league'][league_code]['failed'] += 1
            failed_matches.append({
                'name': historical_name,
                'league': league_code,
                'reason': 'no_match_found'
            })
        
        if (i + 1) % 50 == 0:
            logger.info(f"  Processed {i+1}/{len(unmapped_teams)} teams...")
    
    unique_unmapped = len(seen_historical_names)
    
    logger.info("\n" + "=" * 60)
    logger.info("MATCHING RESULTS")
    logger.info("=" * 60)
    logger.info(f"Total unmapped teams (unique): {unique_unmapped}")
    logger.info(f"Exact matches: {stats['exact_matches']}")
    logger.info(f"Alias matches: {stats['alias_matches']}")
    logger.info(f"Fuzzy matches: {stats['fuzzy_matches']}")
    logger.info(f"Cross-league matches: {stats['cross_league_matches']}")
    logger.info(f"Failed matches: {stats['failed_matches']}")
    logger.info(f"Success rate: {(len(new_mappings)/max(unique_unmapped,1))*100:.1f}%")
    
    logger.info("\nBy League:")
    for league, counts in sorted(stats['by_league'].items()):
        logger.info(f"  {league}: {counts['found']} found, {counts['failed']} failed")
    
    if dry_run:
        logger.info("\n[DRY RUN] Would insert these mappings:")
        for m in new_mappings[:20]:
            logger.info(f"  {m['historical_name']} -> {m['api_name']} ({m['match_type']}, {m['score']:.2f})")
        if len(new_mappings) > 20:
            logger.info(f"  ... and {len(new_mappings)-20} more")
    else:
        inserted = insert_mappings(conn, new_mappings)
        logger.info(f"\n✅ Inserted {inserted} new team mappings")
    
    if failed_matches:
        logger.info(f"\nFailed matches (top 20):")
        for fm in failed_matches[:20]:
            logger.info(f"  {fm['name']} ({fm['league']}): {fm['reason']}")
    
    conn.close()
    
    return {
        'stats': stats,
        'new_mappings': new_mappings,
        'failed_matches': failed_matches
    }

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Expand team name mappings')
    parser.add_argument('--threshold', type=float, default=0.65,
                        help='Fuzzy match threshold (0-1, default 0.65)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    
    args = parser.parse_args()
    
    result = expand_mappings(threshold=args.threshold, dry_run=args.dry_run)
    
    logger.info("\n" + "=" * 60)
    logger.info("EXPANSION COMPLETE")
    logger.info("=" * 60)
