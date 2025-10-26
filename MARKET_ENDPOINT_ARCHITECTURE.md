# `/market` Endpoint & `/predict-v2` Architecture Analysis

## 🎯 **Question 1: Does `/predict-v2` Call OpenAI?**

### **Current `/predict` Flow**

```python
@app.post("/predict")
async def predict_match(request):
    # Step 1: Collect match data from API-Football
    match_data = get_enhanced_data_collector().collect_comprehensive_match_data(match_id)
    
    # Step 2: Generate V1 consensus prediction
    prediction_result = await get_consensus_prediction_from_db(match_id)
    
    # Step 3: Enhanced AI analysis (if requested)
    if request.include_analysis:
        analyzer = get_enhanced_ai_analyzer()  # Uses OpenAI GPT-4o
        ai_result = analyzer.analyze_match_comprehensive(match_data, prediction_result)
    
    # Step 4: Return comprehensive response
    return response
```

**Key Insight**: OpenAI is called in Step 3, **only if `include_analysis=True`**

---

### **Recommendation for `/predict-v2`**

**✅ YES, call OpenAI for `/predict-v2`!** Here's why:

#### **1. Premium Value Proposition**
```
Free Tier (/market):
- V2 predictions only
- No AI analysis
- JSON probabilities
→ Good for data consumers / automated betting

Premium Tier (/predict-v2):
- V2 SELECT (high-confidence)
- OpenAI GPT-4o analysis
- Detailed reasoning, betting intel
→ Great for human bettors who need context
```

#### **2. API Structure**

| Endpoint | Model | OpenAI | Format | Tier |
|----------|-------|--------|--------|------|
| `/predict` | V1 consensus | ✅ Optional | Full analysis | Free (legacy) |
| `/predict-v2` | V2 select | ✅ **YES** | Full analysis | **Premium** |
| `/market` | V2 full | ❌ No | Odds + predictions | Free |

#### **3. Implementation**

**NO NEW API NEEDED!** Reuse existing OpenAI analyzer:

```python
@app.post("/predict-v2")
async def predict_v2_select(
    request: PredictionRequest,
    api_key: str = Depends(verify_premium_api_key)  # Premium only
):
    # Step 1: Get match data (same as V1)
    match_data = get_enhanced_data_collector().collect_comprehensive_match_data(match_id)
    
    # Step 2: Generate V2 prediction
    v2_result = get_v2_lgbm_predictor().predict(match_id)
    
    # Step 3: Check if this qualifies for V2 SELECT
    allocator = get_allocator()
    model_type, premium_lock, metadata = allocator.allocate_model(
        v2_probs=v2_result['probabilities'],
        market_probs=get_market_consensus(match_id),
        league_name=match_data['league']['name']
    )
    
    if model_type != 'v2_select':
        raise HTTPException(
            status_code=403,
            detail="This match doesn't qualify for V2 Select (confidence too low)"
        )
    
    # Step 4: Call OpenAI (SAME ANALYZER, just with V2 predictions)
    if request.include_analysis:
        analyzer = get_enhanced_ai_analyzer()
        ai_result = analyzer.analyze_match_comprehensive(
            match_data, 
            v2_result  # ← V2 predictions instead of V1
        )
    
    # Step 5: Return response (same structure as /predict)
    return build_comprehensive_response(match_data, v2_result, ai_result)
```

**Key Points**:
- ✅ Reuse existing `EnhancedAIAnalyzer`
- ✅ Same OpenAI API key (already configured)
- ✅ Same response format (frontend compatible)
- ✅ Just feed V2 predictions instead of V1

---

## 🎯 **Question 2: Does `/market` Use Real-Time Data?**

### **Current Odds Infrastructure**

#### **Tables & Systems**:
```sql
-- Real-time odds collection
CREATE TABLE odds_snapshots (
    match_id VARCHAR,
    bookmaker VARCHAR,
    ts_snapshot TIMESTAMPTZ,
    home_odds FLOAT,
    draw_odds FLOAT,
    away_odds FLOAT
);

-- Pre-computed consensus (refreshed every 30s - 5min)
CREATE TABLE consensus_predictions (
    match_id VARCHAR PRIMARY KEY,
    time_bucket VARCHAR,  -- '30m_before', '1h_before', etc.
    prob_home FLOAT,
    prob_draw FLOAT,
    prob_away FLOAT,
    confidence FLOAT,
    updated_at TIMESTAMPTZ
);

-- CLV tracking (post-match analysis)
CREATE TABLE clv_alerts (
    match_id VARCHAR,
    alert_type VARCHAR,
    ev_close FLOAT,
    created_at TIMESTAMPTZ
);
```

#### **Collection Systems**:
1. **Automated Collector** (`models/automated_collector.py`)
   - Runs daily for completed matches
   - Backfills historical data
   - For **training**, not real-time

2. **Enhanced Real Data Collector** (`models/enhanced_real_data_collector.py`)
   - Real-time match data from API-Football
   - Injuries, form, news
   - Used by `/predict` endpoint

3. **Background Scheduler** (`utils/scheduler.py`)
   - Scheduled jobs (every 30s - 6h)
   - Populates `consensus_predictions`
   - Collects odds snapshots

---

### **Answer: YES, `/market` MUST Use Real-Time Data**

#### **Why**:
```
/market Purpose:
1. Show LIVE odds from multiple bookmakers
2. Update every 10-30 seconds
3. Calculate EV vs CURRENT market (not historical)
4. Show live scores during matches
5. Display real-time prediction confidence
```

#### **But We DON'T Need New Infrastructure!**

**Reuse Existing Systems**:

```python
@app.get("/market")
async def get_market_data(
    status: str = Query("upcoming", regex="^(upcoming|live)$"),
    league: Optional[str] = None,
    limit: int = 100
):
    """
    Market data endpoint with real-time odds + predictions
    
    Data Flow:
    1. Get fixtures (upcoming or live)
    2. Get latest odds from odds_snapshots
    3. Get V2 predictions (cached or compute)
    4. Apply model allocation logic
    5. Return UI-ready format
    """
    
    # Step 1: Get fixtures
    fixtures = get_fixtures_by_status(status, league, limit)
    
    # Step 2: For each fixture, build market data
    matches = []
    for fixture in fixtures:
        # Get real-time odds (from odds_snapshots)
        current_odds = get_latest_odds_snapshot(fixture.match_id)
        
        # Get market consensus (from consensus_predictions or compute)
        market_probs = get_market_consensus(fixture.match_id)
        
        # Get V2 prediction (compute or cache)
        v2_probs = get_v2_prediction(fixture.match_id, market_probs)
        
        # Apply allocation logic
        allocator = get_allocator()
        model_type, premium_lock, metadata = allocator.allocate_model(
            v2_probs=v2_probs,
            market_probs=market_probs,
            league_name=fixture.league_name
        )
        
        # Build match object
        match = {
            'match_id': fixture.match_id,
            'status': status.upper(),
            'kickoff_at': fixture.kickoff_at,
            'odds': {
                'books': current_odds,  # Real-time from odds_snapshots
                'novig_current': market_probs  # Computed from current odds
            },
            'model': {
                'v2_probs': v2_probs,
                'conf_v2': metadata['conf_v2'],
                'ev_live': metadata['ev_live']
            },
            'prediction': {
                'type': model_type,
                'premium_lock': premium_lock,
                'confidence_pct': int(metadata['conf_v2'] * 100)
            }
        }
        matches.append(match)
    
    return {'matches': matches, 'total_count': len(matches)}
```

---

### **Should It Hook to CLV?**

**NO - Different Use Cases!**

| System | Purpose | Timing | Data |
|--------|---------|--------|------|
| **CLV** | Post-match analysis | After game ends | Opening vs Closing odds |
| **/market** | Pre-match betting | Before/during game | Current odds vs V2 model |

**But We Can Reuse Infrastructure**:

```
CLV System:                      /market Endpoint:
─────────────                    ─────────────────
✅ odds_snapshots table    →     ✅ Reuse for current odds
✅ Bookmaker integration    →     ✅ Reuse for live odds
✅ Consensus computation    →     ✅ Reuse for market probs
❌ Closing line capture     →     ❌ Not needed (future odds)
❌ CLV calculation          →     ❌ Not needed (EV instead)
```

**What We Add**:
```python
# New function: Get latest odds for upcoming/live matches
def get_latest_odds_snapshot(match_id: str) -> Dict:
    """
    Get most recent odds from odds_snapshots
    Returns: {bookmaker: {home, draw, away}}
    """
    query = """
        SELECT DISTINCT ON (bookmaker)
            bookmaker,
            home_odds,
            draw_odds,
            away_odds,
            ts_snapshot
        FROM odds_snapshots
        WHERE match_id = %s
          AND ts_snapshot <= NOW()
        ORDER BY bookmaker, ts_snapshot DESC
    """
    # Returns latest odds per bookmaker
    # Perfect for /market display

# New function: Calculate EV vs live market
def calculate_ev_live(v2_probs: Dict, market_probs: Dict) -> float:
    """
    Expected value vs current market (NOT closing line)
    """
    conf_v2 = max(v2_probs.values())
    conf_market = max(market_probs.values())
    return conf_v2 - conf_market  # Positive = model sees value NOW
```

---

## 📊 **Comprehensive Comparison**

### **Endpoint Architecture**

| Endpoint | Data Source | Real-Time? | OpenAI? | Purpose |
|----------|-------------|------------|---------|---------|
| `/predict` | API-Football + odds | ✅ Yes | ✅ Optional | V1 full analysis |
| `/predict-v2` | API-Football + odds | ✅ Yes | ✅ **YES** | V2 SELECT analysis |
| `/market` | odds_snapshots + V2 | ✅ Yes | ❌ No | Odds board + picks |

### **Data Flow**

```
Real-Time Odds Collection (Every 30s):
┌─────────────────────────────────────────┐
│   The Odds API / API-Football          │
│   (21+ bookmakers)                      │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│   odds_snapshots table                  │
│   (ts_snapshot, bookmaker, odds)        │
└────────────────┬────────────────────────┘
                 │
      ┌──────────┴──────────┐
      │                     │
      ▼                     ▼
┌─────────────┐      ┌──────────────┐
│   /predict  │      │   /market    │
│   /predict-v2│      │              │
│  (analysis)  │      │  (odds board)│
└─────────────┘      └──────────────┘
      │                     │
      ▼                     ▼
┌─────────────┐      ┌──────────────┐
│   OpenAI    │      │  Pure JSON   │
│  Analysis   │      │  (no AI)     │
└─────────────┘      └──────────────┘
```

---

## ✅ **Implementation Recommendations**

### **1. `/predict-v2` Implementation**

**Priority**: HIGH  
**Effort**: LOW (reuse existing code)  
**Impact**: HIGH (premium product)

```python
# New endpoint (95% code reuse)
@app.post("/predict-v2")
async def predict_v2_select(request: PredictionRequest):
    # 1. Get match data (SAME as /predict)
    match_data = get_enhanced_data_collector().collect_comprehensive_match_data(match_id)
    
    # 2. Generate V2 prediction (NEW)
    v2_predictor = get_v2_lgbm_predictor()
    v2_result = v2_predictor.predict(match_id, match_data)
    
    # 3. Verify V2 SELECT eligibility (NEW)
    if v2_result['conf_v2'] < 0.62 or v2_result['ev_live'] <= 0:
        raise HTTPException(403, "Not eligible for V2 Select")
    
    # 4. Call OpenAI (REUSE from /predict)
    if request.include_analysis:
        analyzer = get_enhanced_ai_analyzer()
        ai_result = analyzer.analyze_match_comprehensive(match_data, v2_result)
    
    # 5. Return response (SAME format as /predict)
    return build_response(match_data, v2_result, ai_result)
```

**Benefits**:
- ✅ Reuse 95% of `/predict` code
- ✅ Same OpenAI analyzer (no new API)
- ✅ Same response format (frontend compatible)
- ✅ Premium value (AI analysis + high-confidence)

---

### **2. `/market` Implementation**

**Priority**: HIGH  
**Effort**: MEDIUM (new endpoint, reuse infrastructure)  
**Impact**: HIGH (product differentiation)

```python
@app.get("/market")
async def get_market_data(
    status: str = "upcoming",
    league: Optional[str] = None
):
    # 1. Get fixtures (NEW query)
    fixtures = get_fixtures_by_status(status, league)
    
    # 2. For each fixture:
    matches = []
    for fixture in fixtures:
        # Get real-time odds (REUSE odds_snapshots)
        current_odds = get_latest_odds_snapshot(fixture.match_id)
        
        # Get market consensus (REUSE consensus logic)
        market_probs = compute_market_consensus(current_odds)
        
        # Get V2 prediction (NEW)
        v2_probs = get_v2_prediction(fixture.match_id, market_probs)
        
        # Allocate model (NEW)
        model_type, lock = allocate_model(v2_probs, market_probs)
        
        # Build response (NEW format)
        matches.append({
            'match_id': fixture.match_id,
            'odds': current_odds,  # Real-time
            'model': v2_probs,
            'prediction': {
                'type': model_type,
                'premium_lock': lock
            }
        })
    
    return {'matches': matches}
```

**Benefits**:
- ✅ Real-time odds from existing infrastructure
- ✅ No new data collection needed
- ✅ Clean separation (odds board vs analysis)
- ✅ Fast (no OpenAI calls)

---

## 🎯 **Final Answers**

### **Question 1: Does `/predict-v2` call OpenAI?**

**✅ YES**

- **Reuse existing OpenAI analyzer** (no new API)
- **Same comprehensive analysis** format
- **Premium value proposition** (high-confidence + AI reasoning)
- **95% code reuse** from `/predict`

### **Question 2: Does `/market` use real-time data?**

**✅ YES**

- **Real-time odds** from `odds_snapshots` table
- **Real-time predictions** from V2 model
- **Real-time EV** calculations
- **NOT hooked to CLV** (different use case)
- **Reuses existing infrastructure** (no new collectors)

---

## 📋 **Implementation Checklist**

### **Phase 1: V2 Predictor Service**
- [ ] Load V2 LightGBM model
- [ ] Create prediction service
- [ ] Add caching layer

### **Phase 2: `/predict-v2` Endpoint**
- [ ] Clone `/predict` endpoint
- [ ] Replace V1 with V2 predictions
- [ ] Add V2 SELECT eligibility check
- [ ] Reuse OpenAI analyzer
- [ ] Test with sample matches

### **Phase 3: `/market` Endpoint**
- [ ] Create market response schemas
- [ ] Query fixtures by status
- [ ] Get latest odds from `odds_snapshots`
- [ ] Compute V2 predictions
- [ ] Apply model allocation
- [ ] Return UI-ready format

### **Phase 4: Caching & Performance**
- [ ] Cache V2 predictions (5-10s TTL)
- [ ] Cache market data (10s TTL)
- [ ] Add Redis for high traffic

---

**Ready to implement?** Let me know which phase to start with!
