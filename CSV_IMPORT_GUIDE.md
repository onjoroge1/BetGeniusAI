# CSV Import Guide - Historical Odds Data

## ✅ What We Built

A simple Python script that imports football-data.co.uk CSV files directly into your `historical_odds` table.

---

## 📁 Script Location

`jobs/import_csv_historical_odds_simple.py`

---

## 🚀 How to Use

### Step 1: Place CSV Files in a Directory

```bash
# Example structure:
attached_assets/
  ├── SC1_2020-21.csv
  ├── E0_Premier_League_2019-20.csv
  ├── SP1_La_Liga_2018-19.csv
  └── ...
```

### Step 2: Run the Import Script

```bash
python jobs/import_csv_historical_odds_simple.py attached_assets/
```

That's it! The script will:
- Find all `.csv` files in the directory
- Parse each file
- Extract match data, odds from multiple bookmakers, and match statistics
- Insert into `historical_odds` table
- Show progress for each file

---

## 📊 What Gets Imported

### Match Data
- Date, teams, league, season
- Final score and result (H/D/A)

### Bookmaker Odds (H/D/A for each)
- **Bet365** (B365)
- **Bet&Win** (BW)
- **Interwetten** (IW)
- **Pinnacle** (PS)
- **William Hill** (WH)
- **VC Bet** (VC)
- **Market Average** (Avg)
- **Market Maximum** (Max)

### Match Statistics
- Shots (total and on target)
- Corners
- Fouls
- Yellow cards
- Red cards

---

## 🌍 Where to Get More CSV Files

### **football-data.co.uk** (FREE - Best Source)
- **URL**: https://www.football-data.co.uk/data.php
- **Coverage**: 20+ European leagues
- **History**: Back to ~1994
- **Format**: CSV (one file per league per season)
- **Bookmakers**: 6-8 bookmakers per match

**Download Instructions:**
1. Visit https://www.football-data.co.uk/data.php
2. Click on your desired league (e.g., "English Premier League")
3. Download CSVs for each season
4. Place all CSVs in a folder
5. Run the import script!

**Example Leagues Available:**
- E0: Premier League
- E1: Championship
- SP1: La Liga
- I1: Serie A
- D1: Bundesliga
- F1: Ligue 1
- N1: Eredivisie
- And many more!

### **Kaggle Datasets** (FREE - Large Datasets)

**Option 1: Club Football 2000-2025**
- **URL**: https://www.kaggle.com/datasets/adamgbor/club-football-match-data-2000-2025
- **Coverage**: 27 leagues, 2000-2025
- Download, extract CSVs, and import!

**Option 2: European Soccer Database (SQLite)**
- **URL**: https://www.kaggle.com/hugomathien/soccer
- 25,000+ matches with odds
- Can export to CSV or import directly

---

## 💡 Pro Tips

### Import Multiple Seasons at Once

```bash
# Download all Premier League seasons from football-data.co.uk
mkdir -p data/premier_league
cd data/premier_league
# Download E0 (Premier League) CSVs for 2015-2024
# Then:
python jobs/import_csv_historical_odds_simple.py data/premier_league/
```

### Check What's Already in Database

```bash
python -c "
import psycopg2, os
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute('SELECT COUNT(*), MIN(match_date), MAX(match_date) FROM historical_odds')
print(f'Matches: {cur.fetchone()}')
cur.close()
conn.close()
"
```

### Avoid Duplicates

The script will insert duplicates if you run it multiple times on the same files. To avoid:
1. Keep track of which files you've imported
2. Or clear the table first: `DELETE FROM historical_odds WHERE league = 'SC1'`
3. Or add a unique constraint (see below)

### Add Unique Constraint (Optional)

```sql
ALTER TABLE historical_odds 
ADD CONSTRAINT unique_match 
UNIQUE (match_date, home_team, away_team);
```

Then update the import script to use `ON CONFLICT DO NOTHING` or `DO UPDATE SET...`

---

## 📈 Expected Results

### Small League (e.g., Scottish Championship - SC1)
- **1 season**: ~140 matches
- **10 seasons**: ~1,400 matches
- **Import time**: 1-2 minutes per season

### Big League (e.g., Premier League - E0)
- **1 season**: ~380 matches
- **10 seasons**: ~3,800 matches
- **Import time**: 3-5 minutes per season

### Full Collection Goal
- **50+ leagues** × **10 seasons** = **50,000-100,000 matches**
- **Total import time**: 2-4 hours
- **Database size**: ~500MB-1GB

---

## 🔄 Integration with Feature Pipeline

After importing historical data, run the feature extraction pipeline:

```bash
# Extract historical features from new matches
python jobs/compute_historical_features_fast.py

# Rebuild training matrix
python datasets/build_training_matrix.py

# Check new feature count
python -c "
import pandas as pd
df = pd.read_parquet('artifacts/datasets/v2_tabular.parquet')
print(f'Training matrix: {df.shape}')
"
```

---

## ✅ Success Metrics

- ✅ **135 matches** imported (from your first CSV)
- ✅ Script working perfectly
- ✅ Ready to scale to thousands of matches

**Next Steps:**
1. Download more CSVs from football-data.co.uk
2. Import all leagues you care about
3. Rerun feature extraction pipeline
4. Watch your training matrix grow!

---

## 🎯 Recommended Collection Strategy

### Phase 1: Major European Leagues (2015-2024)
- Premier League (E0)
- La Liga (SP1)
- Serie A (I1)
- Bundesliga (D1)
- Ligue 1 (F1)
- **Expected**: ~20,000 matches

### Phase 2: Additional Top Leagues (2015-2024)
- Eredivisie (N1)
- Primeira Liga (P1)
- Championship (E1)
- **Expected**: +10,000 matches

### Phase 3: Historical Depth (2000-2014)
- Same leagues, earlier seasons
- **Expected**: +30,000 matches

**Total**: 60,000+ matches with full odds and statistics! 🚀

---

Your import script is ready and working. Just download more CSVs and keep running it!
