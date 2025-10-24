# Global Historical Odds Collection Strategy

## 📊 API Comparison Matrix

| Feature | SportsData.io | The Odds API | API-Football |
|---------|--------------|--------------|--------------|
| **League Coverage** | 500+ leagues | ~15 major leagues | 1,100+ leagues |
| **Historical Depth** | Decades (varies) | June 2020 → present | 2006+ (detailed from 2016+) |
| **World Cup** | ✅ Yes | ❌ Limited | ✅ Full coverage + qualifiers |
| **International Matches** | ✅ Tournaments only | ❌ Limited | ✅ Full (6 confederations) |
| **Odds Granularity** | Multiple bookmakers | 10-min intervals (5-min from 2022) | Multiple bookmakers |
| **In-game Stats** | ✅ Yes | ❌ No | ✅ Yes (shots, cards, etc.) |
| **Update Frequency** | Real-time | Snapshots | 15 seconds |
| **Historical Access** | Via Historical API (>30 days) | Paid plans only | Standard API |
| **Cost** | Custom pricing | 10 quota/region/market | Free tier available |

---

## 🎯 Recommended Collection Architecture

### **Phase 1: API-Football (PRIMARY SOURCE)**
**Why:** Best coverage (1,100+ leagues), strong World Cup/international support, existing integration

**Target Leagues:**
- ✅ **Already have**: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie
- 🆕 **Add World Cup**: FIFA World Cup (all editions)
- 🆕 **Add International**: 
  - UEFA Euro Championship
  - Copa America
  - Africa Cup of Nations
  - Asian Cup
  - CONCACAF Gold Cup
  - Confederations Cup
- 🆕 **Add Regional Leagues**:
  - Portugal Primeira Liga
  - Belgium Pro League
  - Turkey Super Lig
  - Russia Premier League
  - Brazil Serie A
  - Argentina Primera División
  - Mexico Liga MX
  - MLS
  - Chinese Super League
  - Japanese J-League
  - Saudi Pro League
  - Australian A-League

**Endpoint Strategy:**
```python
# 1. Get historical fixtures with results
GET /v3/fixtures?league={league_id}&season={year}

# 2. Get odds for each fixture
GET /v3/odds?fixture={fixture_id}

# 3. Get match statistics
GET /v3/fixtures/statistics?fixture={fixture_id}
```

**Data Collection:**
- Go back **5-10 years** for each league (2015-2024)
- Collect: fixtures, odds, match stats (shots, cards, corners)
- Estimated: **50,000-100,000 matches**

---

### **Phase 2: SportsData.io (DEPTH ENRICHMENT)**
**Why:** Deep historical data (decades), 500+ league coverage, good for rare competitions

**Use Cases:**
1. **Historical depth beyond API-Football's range** (pre-2006 data)
2. **Lesser-known leagues** not in API-Football
3. **US sports betting perspective** (DraftKings, FanDuel odds)
4. **Verify/cross-reference** odds accuracy

**Implementation:**
```python
# Historical API for old data
GET /v4/soccer/historical/scores/date/{date}?key={api_key}

# Pre-Game Odds by Date
GET /v4/soccer/odds/pregame/{competition}/{date}?key={api_key}
```

**Target:**
- **1990-2006**: Fill gaps for major European leagues
- **Obscure leagues**: Nordic, Baltic, Central American
- **Historical World Cups**: 1990, 1994, 1998, 2002, 2006

---

### **Phase 3: The Odds API (VALIDATION & RECENT DATA)**
**Why:** High-frequency snapshots (5-min intervals), good for recent data validation

**Use Cases:**
1. **2020-2024 odds validation** (cross-check API-Football)
2. **Closing line capture** (precise pre-kickoff odds)
3. **Line movement analysis** (10-min/5-min snapshots)

**Implementation:**
```python
# Historical snapshot at specific time
GET /v4/historical/sports/soccer_epl/odds?apiKey={key}&date=2022-10-18T02:00:00Z
```

**Target:**
- **Major leagues only**: EPL, La Liga, Bundesliga, Serie A, Ligue 1
- **2020-2024**: Full historical snapshots
- **Use for CLV analysis**: Line movement patterns

---

## 🏗️ Implementation Plan

### **Step 1: Schema Validation**
Current `historical_odds` table structure:
```sql
- fixture_id (int)
- home_team, away_team (varchar)
- league (varchar)
- season (int)
- kickoff (timestamptz)
- home_score, away_score (int)
- outcome (varchar) -- H/D/A
- odds_home, odds_draw, odds_away (numeric)
- bookmaker (varchar)
- shots_home, shots_away (int)
- corners_home, corners_away (int)
- yellows_home, yellows_away (int)
- reds_home, reds_away (int)
```

**Add columns for source tracking:**
```sql
ALTER TABLE historical_odds ADD COLUMN IF NOT EXISTS data_source varchar;  -- 'api-football', 'sportsdata', 'odds-api'
ALTER TABLE historical_odds ADD COLUMN IF NOT EXISTS odds_timestamp timestamptz;  -- When odds were captured
ALTER TABLE historical_odds ADD COLUMN IF NOT EXISTS is_closing_line boolean DEFAULT false;
```

---

### **Step 2: API-Football Bulk Collection Script**

```python
# jobs/collect_historical_apifootball.py

import requests
import psycopg2
from datetime import datetime
import time

API_KEY = os.getenv('RAPIDAPI_KEY')
BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

HEADERS = {
    "X-RapidAPI-Key": API_KEY,
    "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
}

# Target leagues with their API-Football IDs
LEAGUES = {
    # World Cups
    1: "FIFA World Cup",
    15: "FIFA World Cup Qualification - UEFA",
    16: "FIFA World Cup Qualification - CAF",
    # European
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    88: "Eredivisie",
    94: "Primeira Liga",
    # International tournaments
    4: "UEFA Euro Championship",
    9: "Copa America",
    6: "Africa Cup of Nations",
    # Americas
    71: "Brazil Serie A",
    128: "Argentina Primera División",
    262: "Liga MX",
    253: "MLS",
    # More...
}

def collect_league_history(league_id, league_name, start_year=2015, end_year=2024):
    """Collect all fixtures + odds + stats for a league across multiple seasons"""
    
    for season in range(start_year, end_year + 1):
        print(f"\n{'='*60}")
        print(f"Collecting {league_name} - Season {season}")
        print('='*60)
        
        # 1. Get fixtures
        fixtures = get_fixtures(league_id, season)
        print(f"  Found {len(fixtures)} fixtures")
        
        for fixture in fixtures:
            fixture_id = fixture['fixture']['id']
            
            # Skip if not finished
            if fixture['fixture']['status']['short'] not in ['FT', 'AET', 'PEN']:
                continue
            
            # 2. Get odds
            odds = get_odds(fixture_id)
            
            # 3. Get statistics
            stats = get_statistics(fixture_id)
            
            # 4. Insert into database
            insert_historical_match(fixture, odds, stats)
            
            time.sleep(0.1)  # Rate limiting

def get_fixtures(league_id, season):
    """Get all fixtures for a league/season"""
    response = requests.get(
        f"{BASE_URL}/fixtures",
        headers=HEADERS,
        params={"league": league_id, "season": season}
    )
    return response.json()['response']

def get_odds(fixture_id):
    """Get odds for a fixture"""
    response = requests.get(
        f"{BASE_URL}/odds",
        headers=HEADERS,
        params={"fixture": fixture_id, "bet": 1}  # bet=1 is match winner (H/D/A)
    )
    return response.json()['response']

def get_statistics(fixture_id):
    """Get match statistics"""
    response = requests.get(
        f"{BASE_URL}/fixtures/statistics",
        headers=HEADERS,
        params={"fixture": fixture_id}
    )
    return response.json()['response']

def insert_historical_match(fixture, odds, stats):
    """Insert into historical_odds table"""
    
    # Extract data
    home_team = fixture['teams']['home']['name']
    away_team = fixture['teams']['away']['name']
    home_score = fixture['goals']['home']
    away_score = fixture['goals']['away']
    kickoff = fixture['fixture']['date']
    
    # Determine outcome
    if home_score > away_score:
        outcome = 'H'
    elif home_score < away_score:
        outcome = 'A'
    else:
        outcome = 'D'
    
    # Extract odds (average from multiple bookmakers)
    odds_home, odds_draw, odds_away = extract_average_odds(odds)
    
    # Extract stats
    shots_home, shots_away = extract_stat(stats, 'Total Shots')
    corners_home, corners_away = extract_stat(stats, 'Corner Kicks')
    yellows_home, yellows_away = extract_stat(stats, 'Yellow Cards')
    reds_home, reds_away = extract_stat(stats, 'Red Cards')
    
    # Insert
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO historical_odds (
            fixture_id, home_team, away_team, league, season, kickoff,
            home_score, away_score, outcome,
            odds_home, odds_draw, odds_away, bookmaker,
            shots_home, shots_away, corners_home, corners_away,
            yellows_home, yellows_away, reds_home, reds_away,
            data_source, is_closing_line
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (fixture_id, bookmaker) DO NOTHING
    """, (
        fixture['fixture']['id'], home_team, away_team,
        fixture['league']['name'], fixture['league']['season'],
        kickoff, home_score, away_score, outcome,
        odds_home, odds_draw, odds_away, 'consensus',
        shots_home, shots_away, corners_home, corners_away,
        yellows_home, yellows_away, reds_home, reds_away,
        'api-football', True
    ))
    
    conn.commit()
    cur.close()
    conn.close()

# Run collection
if __name__ == "__main__":
    for league_id, league_name in LEAGUES.items():
        collect_league_history(league_id, league_name, 2015, 2024)
```

---

### **Step 3: SportsData.io Historical Enrichment**

```python
# jobs/collect_historical_sportsdata.py

SPORTSDATA_API_KEY = "0505bf4274254c299533d72f14a4f236"
BASE_URL = "https://api.sportsdata.io/v4/soccer"

HEADERS = {
    "Ocp-Apim-Subscription-Key": SPORTSDATA_API_KEY
}

def collect_historical_world_cups():
    """Collect historical World Cup data (1990-2006)"""
    
    # Competition ID for FIFA World Cup
    competition_id = 3  # Example - verify actual ID
    
    for year in [1990, 1994, 1998, 2002, 2006]:
        # Get competition details for that season
        response = requests.get(
            f"{BASE_URL}/scores/json/CompetitionDetails/{competition_id}",
            headers=HEADERS,
            params={"season": f"{year}"}
        )
        
        games = response.json()['Games']
        
        for game in games:
            # Get historical odds
            odds_response = requests.get(
                f"{BASE_URL}/historical/odds/json/GameOddsByGameId/{game['GameId']}",
                headers=HEADERS
            )
            
            # Insert into database
            insert_sportsdata_match(game, odds_response.json())
```

---

### **Step 4: The Odds API Validation**

```python
# jobs/validate_odds_theoddsapi.py

from datetime import datetime, timedelta

ODDS_API_KEY = os.getenv('ODDS_API_KEY')
BASE_URL = "https://api.the-odds-api.com/v4/historical"

def validate_recent_odds(league='soccer_epl', start_date='2020-06-06'):
    """Cross-validate odds from The Odds API"""
    
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.now()
    
    while current_date < end_date:
        timestamp = current_date.strftime('%Y-%m-%dT12:00:00Z')
        
        response = requests.get(
            f"{BASE_URL}/sports/{league}/odds",
            params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu",
                "markets": "h2h",
                "date": timestamp
            }
        )
        
        # Compare with existing data
        validate_against_database(response.json())
        
        current_date += timedelta(days=1)
```

---

## 📈 Expected Results

### **Coverage Projection:**

| Data Source | Matches Added | Leagues | Years | Est. API Calls |
|-------------|---------------|---------|-------|----------------|
| **API-Football (Phase 1)** | 80,000 | 50+ | 2015-2024 | 100,000 |
| **SportsData.io (Phase 2)** | 5,000 | 10+ | 1990-2006 | 10,000 |
| **The Odds API (Phase 3)** | 15,000 | 5 | 2020-2024 | 50,000 |
| **TOTAL** | **100,000** | **60+** | **1990-2024** | **160,000** |

### **Final historical_odds Table:**
- **Current**: 14,527 matches (6 leagues, 1993-2024)
- **After Phase 1**: ~95,000 matches (50+ leagues, 2015-2024)
- **After Phase 2**: ~100,000 matches (+World Cups 1990-2006)
- **After Phase 3**: Validated + enhanced with line movement data

---

## 🚀 Execution Timeline

### **Week 1-2: API-Football Collection**
- Configure script for 30 top leagues
- Run overnight collections (rate-limited)
- Verify data quality

### **Week 3: SportsData.io Enrichment**
- Historical World Cups
- Pre-2006 major league data
- Lesser-known leagues

### **Week 4: The Odds API Validation**
- 2020-2024 cross-validation
- Identify odds discrepancies
- Enrich closing line data

### **Ongoing:**
- Run `compute_historical_features_fast.py` weekly
- Rebuild training matrix with new leagues
- Monitor feature extraction performance

---

## 💰 Cost Estimation

| API | Plan | Estimated Cost |
|-----|------|----------------|
| **API-Football** | Standard (~500 req/day limit) | $0-30/month (may need higher tier) |
| **SportsData.io** | Custom (contact sales) | TBD - likely $50-200/month |
| **The Odds API** | Paid (10 quota/call) | ~$50/month for validation |

**Total**: ~$100-300/month during collection phase, ~$50/month maintenance

---

## ✅ Next Steps

1. **Immediate**: Set up SportsData.io API key in secrets
2. **This Week**: Write `collect_historical_apifootball.py` script
3. **Test**: Run on 1-2 leagues first (verify data quality)
4. **Scale**: Expand to all 50+ target leagues
5. **Monitor**: Track feature extraction performance as data grows

---

## 🎯 Success Metrics

- ✅ **100,000+ matches** in `historical_odds` table
- ✅ **60+ leagues** including World Cup
- ✅ **1990-2024** comprehensive coverage
- ✅ **Feature extraction** completes in <2 minutes for all matches
- ✅ **Training matrix** grows to 2,000-5,000 samples
- ✅ **LightGBM hit rate** reaches 58-62% at scale

---

**The pipeline is ready. The APIs are identified. Time to build the global historical database!** 🌍⚽
