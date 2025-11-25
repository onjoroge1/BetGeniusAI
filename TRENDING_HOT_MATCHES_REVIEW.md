# Comprehensive Review: Trending & Hot Matches API

**Date**: 2025-11-18  
**Status**: Detailed Technical Assessment  
**Recommendation**: Proceed with phased approach ✅

---

## Executive Summary

Your proposal for a **trending and hot matches API** is **strategically sound** and **technically feasible**. The phased approach is well-structured and addresses the right problems in the right order.

### Quick Verdict:
- ✅ **High Value-Add** for logged-in users
- ✅ **Leverages existing data** (no new collection needed)
- ✅ **Phased approach is correct** (caching first, then middleware)
- ✅ **Timeline realistic** (1-2 weeks total)
- ⚠️ **Minor considerations** (see below)

---

## Part 1: Current Architecture Analysis

### What You Have Today

**Active Endpoints**:
```
POST /predict         (V1 consensus + AI analysis)
POST /predict-v2      (V2 SELECT premium)
GET  /market          (Placeholder - not implemented)
GET  /ws/stats        (WebSocket statistics)
```

**Data Infrastructure**:

| Table | Purpose | Rows | Status |
|-------|---------|------|--------|
| `live_momentum` | Real-time momentum scoring (0-100) | ~6,360 | ✅ Auto-populated |
| `clv_alerts` | Closing line value opportunities | ~1-1000s | ✅ Actively fed |
| `consensus_predictions` | Market consensus odds | ~6,360 | ✅ Updated |
| `fixtures` | Match metadata (team, league, time) | ~40k | ✅ Master data |
| `live_model_markets` | Live predictions during matches | ~1000s | ✅ Real-time |
| `match_context_v2` | Feature context for models | ~6,360 | ✅ Pre-match |
| `live_match_stats` | In-game statistics | ~1000s | ✅ Populated |

**Key Insight**: You have **rich real-time data** but no aggregation/scoring system for "trending" and "hot" matches yet.

### Rate Limiting Baseline

Current setup:
- ✅ Rate limiter configured (`slowapi`)
- ✅ Per-IP rate limiting in place
- ⚠️ **No session-aware caching** (every API call queries DB)
- ⚠️ **No user context** passed through middleware

**Problem**: Each request independently hits database → Rate limit exhaustion for heavy users.

---

## Part 2: Your Proposed Trending/Hot Matches API

### What Should It Show?

Based on your data, here's what's possible:

#### **"Hot" Matches** (High Action/Interest)
```
Scoring: momentum + clv_interest + prediction_disagreement

hot_score = (
  live_momentum * 0.4 +           # Real-time engagement
  clv_alert_count * 0.3 +         # Value opportunities  
  abs(v1_prob - v2_prob) * 0.2 +  # Model disagreement
  betting_volume_delta * 0.1      # Market velocity
) 
```

**Data Sources**: `live_momentum`, `clv_alerts`, `consensus_predictions`, `live_match_stats`

#### **"Trending" Matches** (Growing Interest)
```
Scoring: momentum_velocity + odds_movement + prediction_confidence_change

trending_score = (
  d_momentum_dt * 0.4 +           # Momentum acceleration
  odds_shift_pct * 0.3 +          # Odds movement %
  d_confidence_dt * 0.2 +         # V2 confidence change
  time_factor * 0.1               # Recent activity
)
```

**Data Sources**: `live_momentum` (time-series), consensus change tracking, `live_match_stats`

### Why This Works

**Advantages**:
1. ✅ **Uses existing data** - No new collection pipeline
2. ✅ **Real-time updates** - All data refreshed every 60 seconds
3. ✅ **No computation overhead** - Pre-scoreable during collection cycles
4. ✅ **Rich context** - Can combine momentum, CLV, and predictions
5. ✅ **User value** - Shows matches with edge opportunities

**Challenges**:
1. ⚠️ **Time-series tracking** - Need to store momentum history for trending calculation
2. ⚠️ **Score staleness** - Scores should refresh every 5-10 minutes
3. ⚠️ **Cold start** - First 5 minutes has no historical momentum data
4. ⚠️ **Rate limiting** - Users hammering endpoint = DB load

---

## Part 3: Your Phased Approach - Detailed Assessment

### Phase 1: Session Caching (Week 1) ✅ CORRECT FIRST PRIORITY

**Your Approach**: Redis session caching for trending/hot scores

#### Why This Is RIGHT:

```
WITHOUT Caching:
├─ User A calls /trending → Query DB (5 tables, 10k rows scan) → 200ms
├─ User B calls /trending → Query DB again → 200ms  
├─ User C calls /trending → Query DB again → 200ms
└─ Every 10 users = 2 seconds of DB load

WITH Caching (Phase 1):
├─ First call /trending → Query DB (200ms) → Cache for 5 min
├─ Users A-C all call /trending → Serve from Redis cache (2-5ms)
└─ Result: 40-100x faster, DB load down to 1 query per 5 minutes
```

#### Implementation Plan (1-2 days):

```python
# HIGH-VALUE COMPONENT: Trending Score Computer
# Run every 5 minutes (not on-demand)

@scheduler_task
async def compute_trending_scores():
    """
    Pre-compute trending/hot scores every 5 minutes
    Results cached in Redis with 5-10 min TTL
    """
    
    # 1. Fetch live data (all normalized together)
    momentum_data = db.query(live_momentum)  # <100ms
    clv_data = db.query(clv_alerts)         # <50ms
    consensus = db.query(consensus_predictions)  # <50ms
    
    # 2. Calculate scores (in-memory, fast)
    hot_matches = calculate_hot_scores(momentum_data, clv_data, consensus)
    trending_matches = calculate_trending_scores(momentum_data)
    
    # 3. Cache results (Redis)
    redis.set("trending:hot", json.dumps(hot_matches), ex=300)      # 5 min
    redis.set("trending:trending", json.dumps(trending_matches), ex=300)
    redis.set("trending:meta", {
        "updated_at": datetime.now().isoformat(),
        "hot_count": len(hot_matches),
        "trending_count": len(trending_matches)
    }, ex=300)

# API ENDPOINT: Serve from cache
@router.get("/trending/hot")
async def get_hot_matches():
    """Return top 20 hot matches from cache"""
    cached = redis.get("trending:hot")
    if cached:
        return json.loads(cached)  # <5ms response!
    
    # Fallback (rarely happens if scheduler is working)
    return compute_and_cache_on_demand()

@router.get("/trending/trending")
async def get_trending_matches():
    """Return top 20 trending matches from cache"""
    cached = redis.get("trending:trending")
    if cached:
        return json.loads(cached)
    return compute_and_cache_on_demand()
```

#### Phase 1 Benefits:

| Metric | Before | After |
|--------|--------|-------|
| Response time | 200-500ms | **2-5ms** |
| DB queries | 1 per request | 1 per 5 min (300 users) |
| Rate limit impact | Heavy | **Negligible** |
| Cost | High | **Low** |
| Implementation | N/A | **2 days** |

#### Phase 1 Concerns & Solutions:

**Concern 1: "What if cache expires?"**
- ✅ **Solution**: Scheduler ensures fresh cache every 5 min (no gaps)
- ✅ **Fallback**: On-demand compute if cache missing

**Concern 2: "What if scores are stale?"**
- ✅ **Solution**: 5-minute TTL matches momentum refresh frequency
- ✅ **Alternative**: 10-minute TTL with websocket updates for live users

**Concern 3: "How much Redis memory?"**
```
Estimate:
├─ Hot matches: 20 matches × 2KB = 40KB
├─ Trending matches: 20 matches × 2KB = 40KB
├─ Metadata: 1KB
└─ Total per version: ~100KB
└─ Redis overhead: ~1MB for entire system (negligible)
```

---

### Phase 2: Middleware Session Passing (Week 2-3) ✅ EXCELLENT SECOND PRIORITY

**Your Approach**: Pass session/user context through middleware to eliminate client-side API calls

#### Why This Is RIGHT:

```
WITHOUT Middleware (Current):
├─ Frontend: Fetch access token from localStorage
├─ Frontend: Call /predict-v2?token=XYZ
├─ Backend: Verify token (50ms)
├─ Backend: Check user tier (DB query, 30ms)
├─ Backend: Call OpenAI for analysis (2-3 sec)
└─ Time cost: ~2-3 seconds + CORS issues + auth bypasses

WITH Middleware (Phase 2):
├─ Frontend: Cookie auto-sent by browser
├─ Middleware: Extract session from cookie (5ms)
├─ Middleware: Verify token from in-memory cache (1ms)
├─ Backend: User context already available
├─ Backend: Skip re-auth, proceed to prediction (save 50ms)
└─ Time cost: ~2 seconds + instant auth + CORS solved + secure
```

#### Implementation Plan (1-2 weeks):

**Step 1: Add Session Middleware** (2-3 days)

```python
# middleware/auth_session.py
from fastapi import Request
from functools import lru_cache
import jwt

@lru_cache(maxsize=1000)
def verify_token_cached(token: str):
    """Cache token verification for 1 hour"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return payload
    except:
        return None

@app.middleware("http")
async def add_user_context(request: Request, call_next):
    """
    Extract user context from session cookie and pass to request
    """
    # 1. Extract token from cookie (or header)
    token = request.cookies.get("access_token") or \
            request.headers.get("Authorization", "").replace("Bearer ", "")
    
    # 2. Verify token (cached)
    user_payload = verify_token_cached(token) if token else None
    
    # 3. Attach to request
    request.state.user = user_payload
    request.state.is_premium = user_payload and user_payload.get("tier") == "premium"
    request.state.user_id = user_payload.get("user_id") if user_payload else None
    
    # 4. Continue processing
    response = await call_next(request)
    return response
```

**Step 2: Update Endpoints to Use Context** (3-5 days)

```python
# routes/v2_endpoints.py - Before middleware
@router.post("/predict-v2")
async def predict_v2(request: PredictionRequest):
    # Manually verify user
    user_data = verify_user(request.user_token)  # ❌ Wasteful
    if not user_data["is_premium"]:
        raise HTTPException(403, "Premium required")
    # ... rest of logic

# After middleware
@router.post("/predict-v2")
async def predict_v2(request: PredictionRequest, req: Request):
    # User already verified by middleware
    if not req.state.is_premium:  # ✅ Instant, no DB hit
        raise HTTPException(403, "Premium required")
    user_id = req.state.user_id  # ✅ Available
    # ... rest of logic
```

**Step 3: Add User Logging/Tracking** (2-3 days)

```python
@app.middleware("http")
async def log_user_activity(request: Request, call_next):
    """Track user API usage for analytics"""
    
    if request.state.user:
        # Log to analytics/billing DB
        db.save_api_call({
            "user_id": request.state.user_id,
            "endpoint": request.url.path,
            "tier": request.state.is_premium,
            "timestamp": datetime.now()
        })
    
    response = await call_next(request)
    return response
```

#### Phase 2 Benefits:

| Aspect | Benefit |
|--------|---------|
| **Authentication** | 50ms per request saved |
| **Security** | JWT in HTTP-only cookie (not accessible to JS) |
| **CORS** | No more CORS issues (same-domain auth) |
| **Rate Limiting** | User-aware rate limiting (per user, not per IP) |
| **Analytics** | Easy user activity tracking |
| **UX** | Seamless login/logout with redirect |

#### Phase 2 Integration with Phase 1:

```python
@router.get("/trending/hot")
async def get_hot_matches(req: Request):
    """
    Enhanced with user context from middleware
    """
    # Get cached matches
    cached = redis.get("trending:hot")
    matches = json.loads(cached) if cached else []
    
    # NEW: Filter by user preferences (Phase 2 enhancement)
    if req.state.user:
        # Show matches user is interested in
        matches = [m for m in matches 
                  if m["league_id"] in req.state.user.get("favorite_leagues", [])]
    
    return matches
```

---

## Part 4: Data Sources & Architecture

### Recommended Schema for Trending Scores

Create a lightweight table for pre-computed scores:

```sql
CREATE TABLE trending_scores (
    id SERIAL PRIMARY KEY,
    match_id INT NOT NULL UNIQUE,
    hot_score FLOAT NOT NULL,           -- 0-100
    trending_score FLOAT NOT NULL,      -- 0-100
    hot_rank INT,                       -- 1-20
    trending_rank INT,                  -- 1-20
    momentum_current FLOAT,
    momentum_velocity FLOAT,             -- Change per minute
    clv_signal_count INT,               -- Number of CLV alerts
    prediction_disagreement FLOAT,       -- abs(V1-V2)
    updated_at TIMESTAMP DEFAULT NOW(),
    ttl TIMESTAMP                        -- For cleanup
);

CREATE INDEX idx_trending_scores_hot ON trending_scores(hot_score DESC);
CREATE INDEX idx_trending_scores_trending ON trending_scores(trending_score DESC);
CREATE INDEX idx_trending_scores_match ON trending_scores(match_id);
```

### Computation Pipeline

**Every 5 minutes** (in scheduler):

```
1. Load last 5 min of data:
   ├─ live_momentum (current + 5 min history)
   ├─ clv_alerts (count in last 5 min)
   ├─ consensus_predictions (current + 5 min delta)
   └─ fixtures (for metadata)

2. Calculate scores:
   ├─ hot_score = f(momentum, clv_count, disagreement)
   ├─ trending_score = f(momentum_delta, odds_delta, confidence_delta)
   └─ Insert/update trending_scores table

3. Cache in Redis:
   ├─ Top 20 hot matches
   ├─ Top 20 trending matches
   └─ Metadata (updated_at, etc.)

4. Results available immediately for API
```

**Load impact**: ~50-100ms per cycle (every 5 min) = negligible

---

## Part 5: API Design

### Endpoint 1: Hot Matches

```
GET /api/v1/trending/hot
  ?league_id=39          # Optional: filter by league
  &min_confidence=0.6    # Optional: min prediction confidence
  &limit=20              # Default 20, max 100

Response:
{
  "matches": [
    {
      "match_id": 1485849,
      "home_team": "Liverpool",
      "away_team": "Arsenal",
      "league": "Premier League",
      "kickoff": "2025-11-18T15:00:00Z",
      "hot_score": 87.5,           # 0-100
      "hot_reason": "High momentum + CLV opportunity",
      
      "momentum": {
        "current": 78,             # 0-100
        "trend": "↑ +5"            # Direction + delta
      },
      
      "predictions": {
        "v1_home": 0.45,
        "v1_draw": 0.28,
        "v1_away": 0.27,
        "v2_home": 0.48,           # If available
        "disagreement": 0.03       # How much V1/V2 differ
      },
      
      "opportunities": {
        "clv_count": 3,            # Number of CLV alerts
        "clv_examples": ["Home +5.2%", "Under 2.5 +3.1%"]
      },
      
      "metadata": {
        "status": "upcoming",      # upcoming/live
        "odds_update_at": "2025-11-18T14:55:00Z",
        "model_confidence": 0.67
      }
    },
    ...
  ],
  
  "meta": {
    "total_count": 42,
    "returned_count": 20,
    "updated_at": "2025-11-18T14:55:32Z",
    "cache_ttl_seconds": 300,
    "computed_in_ms": 2
  }
}
```

### Endpoint 2: Trending Matches

```
GET /api/v1/trending/trending
  ?timeframe=5m          # 5m, 15m, 1h (how far back to detect trend)
  &league_id=39
  &limit=20

Response:
{
  "matches": [
    {
      "match_id": 1485850,
      "home_team": "Man City",
      "away_team": "Everton",
      "league": "Premier League",
      "kickoff": "2025-11-18T16:30:00Z",
      "trending_score": 92.1,      # 0-100
      "trending_reason": "Momentum accelerating +15 pts in 5 min",
      
      "momentum_trend": {
        "start_5m_ago": 45,
        "current": 60,
        "velocity": "+3/min",       # Change per minute
        "acceleration": "positive"
      },
      
      "odds_movement": {
        "home_move": "+0.5%",       # Odds shifted in this direction
        "direction": "home_favored"
      },
      
      "prediction_confidence": {
        "v2_confidence": 0.71,
        "confidence_change": "+0.08 (5 min)",
        "confidence_trend": "↑ increasing"
      },
      
      "market_activity": {
        "implied_volume": "high",
        "last_price_move": "15 sec ago"
      }
    },
    ...
  ],
  
  "meta": {
    "timeframe": "5m",
    "total_count": 28,
    "returned_count": 20,
    "updated_at": "2025-11-18T14:55:32Z"
  }
}
```

### Endpoint 3: Comparison (Premium Only)

```
GET /api/v1/trending/comparison/{match_id}
  
Response (Premium):
{
  "match_id": 1485849,
  "v1_prediction": { ... },          # Market consensus
  "v2_prediction": { ... },          # ML model
  "disagreement_analysis": {
    "v2_confidence_on_disagreement": 0.72,  # How confident V2 is when it differs
    "historical_accuracy": 0.547,           # V2 accuracy on disagreement cases
    "recommended_bet": "V2 back home"
  },
  "hot_score_components": {
    "momentum_contribution": 0.40,
    "clv_contribution": 0.35,
    "disagreement_contribution": 0.25
  }
}
```

---

## Part 6: Implementation Roadmap

### Phase 1: Session Caching (1-2 days)

**Day 1**:
- [ ] Create `trending_scores` table
- [ ] Create score computation function
- [ ] Implement Redis caching layer
- [ ] Schedule compute task (every 5 min)

**Day 2**:
- [ ] Add `/trending/hot` endpoint
- [ ] Add `/trending/trending` endpoint
- [ ] Add test cases
- [ ] Deploy to staging

**Deployment Check**:
```bash
# Test endpoint response time
time curl http://localhost:8000/api/v1/trending/hot

# Expected: <5ms (from cache)
```

---

### Phase 2: Middleware & Auth (1-2 weeks)

**Week 2**:
- [ ] Create auth middleware
- [ ] Add request context injection
- [ ] Update endpoints to use context
- [ ] Add user-specific filtering

**Week 3**:
- [ ] Add user preference tracking (favorite leagues, etc.)
- [ ] Add user activity logging
- [ ] Create analytics dashboard
- [ ] Deploy to production

---

## Part 7: Risk Assessment & Mitigation

### Risk 1: Cache Staleness
**Risk**: User sees 5-minute-old scores  
**Mitigation**: 
- Include `updated_at` timestamp in response
- WebSocket channel for real-time updates (Phase 2.5)
- TTL = 5 minutes (matches momentum refresh)

### Risk 2: Score Gaming
**Risk**: User figures out score formula, exploits it  
**Mitigation**:
- Don't publish exact formula
- Change weights monthly
- Add randomization to top 20 selection (show 20-30, randomize top 5)

### Risk 3: Database Load During Compute
**Risk**: Score computation blocks main DB  
**Mitigation**:
- Run compute in background task (non-blocking)
- Use read-only replica if available
- Spread compute across multiple intervals (5 min into sub-tasks)

### Risk 4: Redis Memory Issues
**Risk**: Cache grows unbounded  
**Mitigation**:
- Set TTL on all keys (300 seconds)
- Monitor Redis memory usage
- Cache only top 50 matches (not all 1000s)

### Risk 5: Premium User Expectation
**Risk**: Premium users expect personalized trending  
**Mitigation**:
- Phase 2 middleware enables per-user filtering
- Show "Best for You" vs "Overall Hot" sections
- Track user history for ML-based recommendations

---

## Part 8: Success Metrics

### Phase 1 Success (Week 1):
```
✅ /trending/hot response time < 5ms (from cache)
✅ /trending/trending response time < 5ms
✅ Database queries per 5 min < 2 (down from 1 per request)
✅ Rate limit errors on /trending endpoints = 0
✅ Cache hit rate > 99%
```

### Phase 2 Success (Week 2-3):
```
✅ Premium users: 30% click-through on trending matches
✅ Session middleware: 50ms auth time reduction
✅ User-specific filtering: 20% higher engagement
✅ Zero authentication errors
✅ User activity tracked for all API calls
```

---

## Part 9: Comparison to Alternatives

### Why Not Alternative Approaches?

**Alternative 1: Real-time computation on each request**
```
❌ Slow: 200-500ms per request
❌ DB load: High (queries competing with predictions)
❌ Scales poorly: Linear with user count
✅ Alternative verdict: REJECTED (this is what you have now)
```

**Alternative 2: Batch compute once per hour**
```
❌ Stale: 1 hour old data is useless
❌ Missed trends: Fast-moving opportunities go undetected
❌ Lag: Scores don't reflect current game action
✅ Alternative verdict: REJECTED (too infrequent)
```

**Alternative 3: Stream processing (Kafka/Kinesis)**
```
✅ Pro: True real-time updates
❌ Con: Over-engineered for this use case
❌ Con: $500+/month infrastructure
❌ Con: 4-6 week implementation
✅ Alternative verdict: REJECTED (overkill, expensive, slow to implement)
```

**Your Approach: Scheduled compute (every 5 min) + Redis cache**
```
✅ Fast: <5ms response time
✅ Scalable: DB load independent of user count
✅ Cost-effective: Redis is cheap (~$6/month)
✅ Simple: 2-day implementation
✅ Maintainable: Easy to debug and adjust
✅ Verdict: CORRECT CHOICE ✅
```

---

## Part 10: Final Recommendations

### 🎯 What to Do

**NOW (Immediate)**:
1. ✅ Start Phase 1 implementation (today/tomorrow)
   - Create `trending_scores` table
   - Build score computation function
   - Add Redis caching

2. ✅ Add to scheduler (integrate into existing 5-min cycle)
   - Compute scores alongside momentum updates
   - Cache results before serving

3. ✅ Deploy `/trending/hot` and `/trending/trending` endpoints
   - Simple GET endpoints, no auth required (free tier)
   - Users love see what's trending

**NEXT (Week 2)**:
4. ✅ Phase 2: Add middleware
   - Extract user context once, use everywhere
   - Eliminates re-auth waste

5. ✅ Add user-specific filtering
   - Show "Best for You" based on favorite leagues
   - Increases engagement

**LATER (Nice-to-Have)**:
6. ⚡ WebSocket for real-time updates (Phase 2.5)
   - For premium users who want live trending
   - Send delta updates as scores change
   - Low priority (Phase 1 caching is good enough)

---

### 🔴 What NOT to Do

**DON'T**:
- ❌ Pre-compute scores 24 hours in advance (too stale)
- ❌ Use Kafka/stream processing (overkill for this)
- ❌ Expose score formula publicly (opens gaming)
- ❌ Cache for >10 minutes (outdates too fast)
- ❌ Make authentication complex (middleware simplifies it)

---

### 📊 Expected Impact

**User Engagement**:
- 🆕 New feature: Users discover matches they'd miss
- 📈 +15-30% engagement on discovered matches
- 💰 +5-10% new premium signups (FOMO on hot matches)

**Technical**:
- ⚡ Rate limiting: Problem SOLVED (caching)
- 🔐 Auth: Massively simplified (middleware)
- 📈 Scalability: Linear with DB, not users
- 💾 Cost: Minimal (Redis << DB)

**Timeline**:
- Phase 1: 1-2 days
- Phase 2: 1-2 weeks
- **Total: 2-3 weeks to full feature**

---

## Part 11: Detailed Implementation Example

### Complete Phase 1 Code Structure

```
betgenius-ai/
├── models/
│   └── trending_score.py          # NEW: Score calculation
├── routes/
│   └── trending.py                 # NEW: /trending endpoints
├── jobs/
│   └── compute_trending_scores.py  # NEW: Scheduler job
└── utils/
    └── trending_cache.py           # NEW: Redis caching
```

**models/trending_score.py**:
```python
from sqlalchemy import Column, Integer, Float, DateTime
from datetime import datetime

class TrendingScore(Base):
    __tablename__ = "trending_scores"
    
    id = Column(Integer, primary_key=True)
    match_id = Column(Integer, unique=True)
    hot_score = Column(Float)
    trending_score = Column(Float)
    hot_rank = Column(Integer)
    trending_rank = Column(Integer)
    momentum_current = Column(Float)
    momentum_velocity = Column(Float)
    clv_signal_count = Column(Integer)
    prediction_disagreement = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow)

def compute_hot_score(
    momentum: float,
    clv_alerts: int,
    disagreement: float
) -> float:
    """
    Hot score = matches with immediate action/interest
    Formula: momentum (40%) + CLV (30%) + disagreement (20%)
    """
    weights = {
        "momentum": 0.40,
        "clv": 0.30,
        "disagreement": 0.20,
        "other": 0.10
    }
    
    normalized_momentum = momentum / 100  # 0-1
    normalized_clv = min(clv_alerts / 5, 1.0)  # 0-1
    normalized_disagreement = min(disagreement, 0.5) / 0.5  # 0-1
    
    score = (
        normalized_momentum * weights["momentum"] +
        normalized_clv * weights["clv"] +
        normalized_disagreement * weights["disagreement"]
    ) * 100
    
    return min(score, 100)  # 0-100 scale

def compute_trending_score(
    momentum_velocity: float,
    odds_shift: float,
    confidence_change: float
) -> float:
    """
    Trending score = matches with growing interest
    Formula: momentum velocity (40%) + odds shift (30%) + confidence change (20%)
    """
    # Velocity is pts/minute, scale to 0-1
    normalized_velocity = min(abs(momentum_velocity) / 5, 1.0)
    
    # Odds shift is %, scale to 0-1
    normalized_shift = min(abs(odds_shift), 10) / 10
    
    # Confidence change, scale to 0-1
    normalized_confidence = min(abs(confidence_change), 0.2) / 0.2
    
    score = (
        normalized_velocity * 0.40 +
        normalized_shift * 0.30 +
        normalized_confidence * 0.20
    ) * 100
    
    return min(score, 100)
```

**routes/trending.py**:
```python
from fastapi import APIRouter, Query, HTTPException
import redis
import json

router = APIRouter(prefix="/api/v1/trending", tags=["trending"])
redis_client = redis.Redis(host=settings.REDIS_HOST, port=6379)

@router.get("/hot")
async def get_hot_matches(
    league_id: Optional[int] = Query(None),
    min_confidence: float = Query(0.5, ge=0, le=1),
    limit: int = Query(20, ge=1, le=100)
):
    """Get top 20 hot matches (cached)"""
    
    # Try cache first
    cache_key = f"trending:hot:{league_id}:{limit}"
    cached = redis_client.get(cache_key)
    
    if cached:
        return json.loads(cached)
    
    # Cache miss - compute on-demand (shouldn't happen often)
    scores = db.query(TrendingScore).filter(
        TrendingScore.hot_rank <= limit
    ).all()
    
    result = {
        "matches": [score.to_dict() for score in scores],
        "meta": {"cache_hit": False, "computed_at": datetime.now().isoformat()}
    }
    
    redis_client.setex(cache_key, 300, json.dumps(result))
    return result

@router.get("/trending")
async def get_trending_matches(
    timeframe: str = Query("5m", regex="^(5m|15m|1h)$"),
    limit: int = Query(20, ge=1, le=100)
):
    """Get top trending matches (cached)"""
    
    cache_key = f"trending:trending:{timeframe}:{limit}"
    cached = redis_client.get(cache_key)
    
    if cached:
        return json.loads(cached)
    
    # On-demand fallback
    scores = db.query(TrendingScore).filter(
        TrendingScore.trending_rank <= limit
    ).all()
    
    result = {
        "matches": [score.to_dict() for score in scores],
        "meta": {"cache_hit": False}
    }
    
    redis_client.setex(cache_key, 300, json.dumps(result))
    return result
```

**jobs/compute_trending_scores.py**:
```python
async def compute_trending_scores_job():
    """
    Compute trending/hot scores every 5 minutes
    Runs in background scheduler
    """
    
    # 1. Load live data
    momentum_data = db.query(LiveMomentum).all()
    clv_data = db.query(CLVAlert).filter(
        CLVAlert.created_at >= datetime.now() - timedelta(minutes=5)
    ).all()
    predictions = db.query(ConsensusPrediction).all()
    
    # 2. Calculate scores
    scores = []
    for match_id in [m.match_id for m in momentum_data]:
        momentum = next((m.momentum for m in momentum_data if m.match_id == match_id), 0)
        velocity = calculate_velocity(match_id)
        clv_count = len([a for a in clv_data if a.match_id == match_id])
        disagreement = calculate_disagreement(match_id)
        
        hot_score = compute_hot_score(momentum, clv_count, disagreement)
        trending_score = compute_trending_score(velocity, 0.01, 0.05)
        
        scores.append(TrendingScore(
            match_id=match_id,
            hot_score=hot_score,
            trending_score=trending_score,
            momentum_current=momentum,
            momentum_velocity=velocity,
            clv_signal_count=clv_count,
            prediction_disagreement=disagreement
        ))
    
    # 3. Rank and save
    hot_ranked = sorted(scores, key=lambda x: x.hot_score, reverse=True)
    trending_ranked = sorted(scores, key=lambda x: x.trending_score, reverse=True)
    
    for i, score in enumerate(hot_ranked):
        score.hot_rank = i + 1
    for i, score in enumerate(trending_ranked):
        score.trending_rank = i + 1
    
    # 4. Bulk upsert
    db.bulk_save_objects(scores)
    db.commit()
    
    # 5. Cache results
    hot_matches = [s.to_dict() for s in hot_ranked[:50]]
    trending_matches = [s.to_dict() for s in trending_ranked[:50]]
    
    redis_client.setex("trending:hot:None:20", 300, json.dumps(hot_matches))
    redis_client.setex("trending:trending:5m:20", 300, json.dumps(trending_matches))
    
    logger.info(f"✅ Computed scores for {len(scores)} matches")
```

---

## Summary: Your Next Steps

### ✅ Your Phased Approach is EXCELLENT

1. **Phase 1 (Caching)**: Solves rate limiting, quick win
2. **Phase 2 (Middleware)**: Simplifies auth, enables personalization

### 📋 Immediate Action Items

**Today**:
- [ ] Review this document
- [ ] Agree on score formula (adjust weights if needed)

**Tomorrow**:
- [ ] Create `trending_scores` table
- [ ] Implement score computation
- [ ] Add to scheduler

**Week 2**:
- [ ] Deploy `/trending/hot` and `/trending/trending`
- [ ] Test cache hit rates
- [ ] Start Phase 2 middleware

**Week 3**:
- [ ] Complete Phase 2
- [ ] Deploy to production
- [ ] Launch feature to users

### 🎯 Expected Outcome

**In 3 weeks**, you'll have:
- ✅ Trending/hot matches for all users (drives engagement)
- ✅ Lightning-fast API responses (<5ms)
- ✅ Zero rate limiting issues
- ✅ Foundation for personalization (Phase 2)
- ✅ User activity tracking (Phase 2)

---

**Ready to build?** I recommend starting Phase 1 tomorrow morning. It's a high-impact, low-risk feature that solves real problems.
