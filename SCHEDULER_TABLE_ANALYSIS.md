# Scheduler Data Dumping Analysis

## 📋 Investigation Results: Which Table Gets The Data?

### 1. Primary Target Table: `training_matches` ✅

**Evidence from Database:**
```sql
-- Latest records in training_matches
SELECT * FROM training_matches ORDER BY collected_at DESC LIMIT 3;
```

**Results:**
- **Match 1208604**: Leganes vs Sevilla (La Liga, Nov 9 2024) - Home Win 1-0
- **Match 1208610**: Villarreal vs Alaves (La Liga, Nov 9 2024) - Home Win 3-0  
- **Match 1208602**: Real Betis vs Celta Vigo (La Liga, Nov 10 2024) - Draw 2-2

**Key Finding**: Scheduler dumps completed match data with outcomes into `training_matches` table.

### 2. Secondary Tables Analysis:

#### `odds_consensus` - Contains T-72h Data ✅
```sql
SELECT * FROM odds_consensus LIMIT 3;
```

**Results:**
- **Match 1038121**: 72-hour horizon, consensus probabilities (65.4% H, 20.4% D, 14.2% A)
- **Match 1223620**: 72-hour horizon, consensus probabilities (43.7% H, 34.2% D, 22.1% A)
- **Match 878238**: 72-hour horizon, consensus probabilities (60.0% H, 22.3% D, 17.7% A)

**Key Finding**: `odds_consensus` contains processed odds at specific horizons (T-72h shown).

#### `odds_snapshots` - EMPTY ❌
```sql
SELECT * FROM odds_snapshots LIMIT 3;
-- Returns: No rows (empty table)
```

**Key Finding**: Real-time odds snapshots are not being collected.

### 3. Model Usage Analysis:

#### Current Model Uses `consensus_predictions` NOT Raw Odds Tables

**From `predictor_consensus.py`:**
```python
# Line 112-116: Model queries consensus_predictions table
consensus_query = """
SELECT 
    consensus_h, consensus_d, consensus_a,
    dispersion_h, dispersion_d, dispersion_a,
    n_books, consensus_method, created_at
FROM consensus_predictions
WHERE match_id = %s AND time_bucket = %s
"""
```

#### Time Bucket Logic:
```python
# Line 61-72: Time bucket selection
if hours_to_kickoff >= 24:
    return '24h'
elif hours_to_kickoff >= 12:
    return '12h'  
elif hours_to_kickoff >= 6:
    return '6h'
```

### 4. Data Flow Discovery:

#### Scheduler Data Flow:
```
Scheduler → training_matches (completed matches for training)
```

#### Prediction Data Flow:
```
Live Prediction → consensus_predictions (processed probabilities by time bucket)
```

#### Missing Data Flow:
```
Missing: odds_snapshots (real-time odds at T-48h/T-24h intervals)
```

### 5. Current Status Summary:

#### ✅ What's Working:
- **Scheduler**: Dumps completed match data into `training_matches`
- **Consensus System**: Uses `consensus_predictions` for live predictions
- **T-72h Data**: Available in `odds_consensus` table

#### ❌ What's Missing:
- **Real-time T-48h/T-24h snapshots**: `odds_snapshots` table is empty
- **Systematic odds collection**: No periodic T-48h/T-24h collection running
- **Integration**: Model doesn't use `odds_consensus` T-72h data

### 6. Critical Gap Identified:

The model is designed to use 48h/24h odds from `odds_snapshots` but:
1. **Scheduler doesn't populate `odds_snapshots`** - only dumps to `training_matches`
2. **`odds_snapshots` is completely empty** - 0 records
3. **Model falls back to `consensus_predictions`** - limited data (10 records)

### 7. Horizon Data Available:

#### From `odds_consensus`:
- **T-72h data available**: All 3 sample records show `horizon_hours: 72`
- **Processed probabilities**: Already calculated consensus from multiple bookmakers
- **Recent data**: Created July 30, 2025

### 8. Architecture Problem:

```
DESIGNED FLOW (not working):
API Call → odds_snapshots (T-48h/T-24h) → consensus_builder → predictions

ACTUAL FLOW (limited):  
API Call → consensus_predictions (only 10 records) → predictions
```

### 9. Solution Required:

#### Option 1: Fix Scheduler to Populate `odds_snapshots`
```python
# Add to scheduler: collect live odds at T-48h/T-24h intervals
# Store raw bookmaker odds with timing metadata
```

#### Option 2: Use Available `odds_consensus` Data  
```python
# Modify model to use odds_consensus (T-72h) instead of missing odds_snapshots
# Better data quality, more records available
```

#### Option 3: Real-time Collection Enhancement
```python
# Enhance live prediction to populate odds_snapshots during API calls
# Store timing-aware odds for future model training
```

## Bottom Line:

**Scheduler Target**: `training_matches` (completed matches for ML training)
**Model Source**: Tries `odds_snapshots` (empty) → Falls back to `consensus_predictions` (10 records)  
**Available but Unused**: `odds_consensus` (T-72h processed data, better quality)

The gap is that systematic T-48h/T-24h odds collection is missing, and the model should be updated to use the available T-72h `odds_consensus` data.