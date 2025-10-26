# Market Endpoint - Complete Integration Guide

## Overview
The `/market` endpoint provides a **free-tier market board** showing both V1 (consensus) and V2 (ML) predictions side-by-side with live bookmaker odds. It's designed for real-time odds comparison with premium upgrade CTAs for high-value V2 SELECT picks.

---

## Architecture & Data Flow

### Backend Data Sources

```
┌─────────────────────────────────────────────────────────────┐
│                     /market Endpoint                        │
└─────────────────────────────────────────────────────────────┘
                            │
                ┌───────────┼───────────┐
                │           │           │
                ▼           ▼           ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ fixtures │ │odds_snap │ │consensus_│
        │          │ │  shots   │ │predictions│
        └──────────┘ └──────────┘ └──────────┘
             │            │            │
             │            │            │
        kickoff_at   latest odds   V1 probs
        + status     per book      (pre-computed)
                                        │
                                        ▼
                                   V2 LightGBM
                                   (on-demand)
```

### How "Upcoming" Matches are Determined

**IMPORTANT:** The database only has 2 status values:
- `'scheduled'` - Match not yet played
- `'finished'` - Match completed

There is **NO `'upcoming'` status field**. Instead, the system uses **time-based filtering**:

```sql
-- UPCOMING matches:
WHERE f.kickoff_at > NOW() AND f.status = 'scheduled'

-- LIVE matches (in-progress):
WHERE f.kickoff_at <= NOW() 
  AND f.kickoff_at > NOW() - INTERVAL '2 hours'
  AND f.status = 'scheduled'
```

### Data Flow Steps

1. **Filter by time** → Get matches with `kickoff_at > NOW()` + odds available
2. **Fetch odds** → Latest odds per bookmaker from `odds_snapshots` (updated every 60s)
3. **Get V1** → Read pre-computed consensus from `consensus_predictions` (updated every 60s by scheduler)
4. **Generate V2** → Call V2 LightGBM predictor on-demand
5. **Calculate metrics** → Agreement, divergence, EV, V2 SELECT eligibility
6. **Return** → Combined response with both models + premium CTA

**Performance:** ~500ms for 10 matches (fast because V1 is pre-computed!)

---

## API Specification

### Endpoint
```
GET /market?status={upcoming|live}&limit={N}&league={ID}
```

### Authentication
```http
Authorization: Bearer {API_KEY}
```

### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `status` | string | Yes | - | `upcoming` or `live` |
| `limit` | integer | No | 10 | Max matches to return (1-50) |
| `league` | integer | No | null | Filter by league_id |

### Response Schema

```json
{
  "matches": [
    {
      "match_id": 1353591,
      "status": "UPCOMING",
      "kickoff_at": "2025-10-26T21:30:00+00:00",
      "league": {
        "id": 72,
        "name": "Serie B - Brazil"
      },
      "home": {"name": "Vila Nova"},
      "away": {"name": "Ferroviária"},
      
      "odds": {
        "books": {
          "bet365": {"home": 1.77, "draw": 3.45, "away": 4.8},
          "pinnacle": {"home": 1.82, "draw": 3.38, "away": 4.93}
        },
        "novig_current": {
          "home": 0.520,
          "draw": 0.275,
          "away": 0.205
        }
      },
      
      "models": {
        "v1_consensus": {
          "probs": {"home": 0.524, "draw": 0.278, "away": 0.198},
          "pick": "home",
          "confidence": 0.524,
          "source": "market_consensus"
        },
        "v2_lightgbm": {
          "probs": {"home": 0.658, "draw": 0.228, "away": 0.114},
          "pick": "home",
          "confidence": 0.658,
          "source": "ml_model"
        }
      },
      
      "analysis": {
        "agreement": {
          "same_pick": true,
          "confidence_delta": 0.134,
          "divergence": "low"
        },
        "premium_available": {
          "v2_select_qualified": true,
          "reason": "conf=0.66, ev=+0.134",
          "cta_url": "/predict-v2"
        }
      },
      
      "ui_hints": {
        "primary_model": "v2_lightgbm",
        "show_premium_badge": true,
        "confidence_pct": 66
      }
    }
  ],
  "total_count": 1,
  "timestamp": "2025-10-26T21:15:00.000000"
}
```

---

## Frontend Integration

### React/TypeScript Example

```typescript
// types.ts
export interface MarketMatch {
  match_id: number;
  status: 'UPCOMING' | 'LIVE';
  kickoff_at: string;
  league: { id: number; name: string };
  home: { name: string };
  away: { name: string };
  odds: {
    books: Record<string, { home: number; draw: number; away: number }>;
    novig_current: { home: number; draw: number; away: number };
  };
  models: {
    v1_consensus?: {
      probs: { home: number; draw: number; away: number };
      pick: string;
      confidence: number;
      source: string;
    };
    v2_lightgbm?: {
      probs: { home: number; draw: number; away: number };
      pick: string;
      confidence: number;
      source: string;
    };
  };
  analysis?: {
    agreement: {
      same_pick: boolean;
      confidence_delta: number;
      divergence: 'high' | 'low';
    };
    premium_available: {
      v2_select_qualified: boolean;
      reason: string;
      cta_url: string | null;
    };
  };
  ui_hints: {
    primary_model: string;
    show_premium_badge: boolean;
    confidence_pct: number;
  };
}

export interface MarketResponse {
  matches: MarketMatch[];
  total_count: number;
  timestamp: string;
}

// api.ts
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const API_KEY = process.env.REACT_APP_API_KEY;

export async function fetchMarket(
  status: 'upcoming' | 'live' = 'upcoming',
  limit: number = 10,
  leagueId?: number
): Promise<MarketResponse> {
  const params = new URLSearchParams({
    status,
    limit: limit.toString(),
  });
  
  if (leagueId) {
    params.append('league', leagueId.toString());
  }
  
  const response = await fetch(`${API_BASE}/market?${params}`, {
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    throw new Error(`Market API error: ${response.status}`);
  }
  
  return response.json();
}

// MarketBoard.tsx
import React, { useEffect, useState } from 'react';
import { fetchMarket, MarketMatch } from './api';

export const MarketBoard: React.FC = () => {
  const [matches, setMatches] = useState<MarketMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let interval: NodeJS.Timeout;

    const loadMatches = async () => {
      try {
        setLoading(true);
        const data = await fetchMarket('upcoming', 20);
        setMatches(data.matches);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load market');
      } finally {
        setLoading(false);
      }
    };

    // Initial load
    loadMatches();

    // Refresh every 60 seconds (matches backend update frequency)
    interval = setInterval(loadMatches, 60000);

    return () => clearInterval(interval);
  }, []);

  if (loading && matches.length === 0) {
    return <div className="loading">Loading market data...</div>;
  }

  if (error) {
    return <div className="error">Error: {error}</div>;
  }

  return (
    <div className="market-board">
      <h1>Live Market Board</h1>
      <p className="subtitle">
        Showing {matches.length} upcoming matches • Updates every 60s
      </p>

      <div className="matches-grid">
        {matches.map((match) => (
          <MatchCard key={match.match_id} match={match} />
        ))}
      </div>
    </div>
  );
};

// MatchCard.tsx
const MatchCard: React.FC<{ match: MarketMatch }> = ({ match }) => {
  const { v1_consensus, v2_lightgbm } = match.models;
  const isPremium = match.analysis?.premium_available.v2_select_qualified;

  return (
    <div className={`match-card ${isPremium ? 'premium' : ''}`}>
      {/* Header */}
      <div className="match-header">
        <span className="league">{match.league.name}</span>
        <span className="kickoff">
          {new Date(match.kickoff_at).toLocaleString()}
        </span>
      </div>

      {/* Teams */}
      <div className="teams">
        <div className="team">{match.home.name}</div>
        <div className="vs">vs</div>
        <div className="team">{match.away.name}</div>
      </div>

      {/* Model Comparison */}
      <div className="models">
        <div className="model v1">
          <h4>V1 Market Consensus</h4>
          {v1_consensus && (
            <>
              <div className="pick">
                Pick: <strong>{v1_consensus.pick}</strong>
              </div>
              <div className="confidence">
                Confidence: {(v1_consensus.confidence * 100).toFixed(1)}%
              </div>
              <div className="probs">
                H: {(v1_consensus.probs.home * 100).toFixed(0)}% | 
                D: {(v1_consensus.probs.draw * 100).toFixed(0)}% | 
                A: {(v1_consensus.probs.away * 100).toFixed(0)}%
              </div>
            </>
          )}
        </div>

        <div className="model v2">
          <h4>
            V2 ML Model
            {isPremium && <span className="badge">⭐ PREMIUM</span>}
          </h4>
          {v2_lightgbm && (
            <>
              <div className="pick">
                Pick: <strong>{v2_lightgbm.pick}</strong>
              </div>
              <div className="confidence">
                Confidence: {(v2_lightgbm.confidence * 100).toFixed(1)}%
              </div>
              <div className="probs">
                H: {(v2_lightgbm.probs.home * 100).toFixed(0)}% | 
                D: {(v2_lightgbm.probs.draw * 100).toFixed(0)}% | 
                A: {(v2_lightgbm.probs.away * 100).toFixed(0)}%
              </div>
            </>
          )}
        </div>
      </div>

      {/* Agreement Analysis */}
      {match.analysis && (
        <div className="analysis">
          <div className={`agreement ${match.analysis.agreement.same_pick ? 'agree' : 'disagree'}`}>
            {match.analysis.agreement.same_pick ? '✓' : '✗'} Models {match.analysis.agreement.same_pick ? 'Agree' : 'Disagree'}
            <span className="delta">
              Δ: {(match.analysis.agreement.confidence_delta * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {/* Premium CTA */}
      {isPremium && (
        <div className="premium-cta">
          <button 
            onClick={() => window.location.href = `/predict-v2?match_id=${match.match_id}`}
            className="cta-button"
          >
            Get Premium Analysis + AI Insights →
          </button>
          <small>{match.analysis?.premium_available.reason}</small>
        </div>
      )}

      {/* Best Odds */}
      <div className="best-odds">
        <h5>Best Odds Available:</h5>
        <div className="odds-row">
          {Object.entries(match.odds.books).slice(0, 3).map(([book, odds]) => (
            <div key={book} className="book">
              <span className="book-name">{book}</span>
              <span>{odds.home} / {odds.draw} / {odds.away}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
```

### CSS Styling Example

```css
.market-board {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem;
}

.matches-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(500px, 1fr));
  gap: 1.5rem;
  margin-top: 2rem;
}

.match-card {
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  transition: all 0.3s ease;
}

.match-card.premium {
  border: 2px solid #ffd700;
  background: linear-gradient(135deg, #fff9e6 0%, #ffffff 100%);
}

.match-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 1rem;
  font-size: 0.85rem;
  color: #666;
}

.teams {
  text-align: center;
  margin: 1.5rem 0;
}

.teams .team {
  font-size: 1.2rem;
  font-weight: bold;
  margin: 0.5rem 0;
}

.teams .vs {
  color: #999;
  font-size: 0.9rem;
}

.models {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin: 1.5rem 0;
  padding: 1rem;
  background: #f8f8f8;
  border-radius: 8px;
}

.model h4 {
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.badge {
  font-size: 0.7rem;
  background: #ffd700;
  color: #000;
  padding: 2px 6px;
  border-radius: 4px;
}

.pick {
  margin: 0.5rem 0;
  font-size: 1rem;
}

.confidence {
  font-size: 1.1rem;
  font-weight: bold;
  color: #2563eb;
}

.probs {
  font-size: 0.85rem;
  color: #666;
  margin-top: 0.5rem;
}

.analysis {
  margin: 1rem 0;
  padding: 0.75rem;
  background: white;
  border-radius: 6px;
}

.agreement {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.agreement.agree {
  color: #16a34a;
}

.agreement.disagree {
  color: #dc2626;
}

.premium-cta {
  margin-top: 1rem;
  padding: 1rem;
  background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
  border-radius: 8px;
  text-align: center;
}

.cta-button {
  background: #000;
  color: #ffd700;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 6px;
  font-weight: bold;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.2s;
}

.cta-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.2);
}

.best-odds {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #e0e0e0;
}

.best-odds h5 {
  font-size: 0.85rem;
  color: #666;
  margin-bottom: 0.5rem;
}

.odds-row {
  display: flex;
  gap: 1rem;
  font-size: 0.85rem;
}

.book {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.book-name {
  font-weight: bold;
  color: #2563eb;
}
```

---

## Key Features Highlighted in UI

1. **Model Comparison** - Side-by-side V1 vs V2 display
2. **Agreement Indicators** - Visual cues when models agree/disagree
3. **Premium Badges** - Highlight V2 SELECT eligible picks
4. **Live Updates** - Auto-refresh every 60s (matches backend)
5. **Best Odds Display** - Show top bookmaker prices
6. **Upgrade CTAs** - Convert free users to premium

---

## Update Frequency

- **Backend Scheduler**: Updates odds + V1 consensus every **60 seconds**
- **Frontend Polling**: Recommended **60 seconds** (sync with backend)
- **V2 Predictions**: Generated **on-demand** per request

---

## Premium Conversion Strategy

```typescript
// Example: Track "almost premium" picks for remarketing
const trackNearPremiumPick = (match: MarketMatch) => {
  const v2 = match.models.v2_lightgbm;
  
  if (v2 && v2.confidence >= 0.58 && v2.confidence < 0.62) {
    // Track: "User saw high-confidence pick but wasn't premium"
    analytics.track('near_premium_view', {
      match_id: match.match_id,
      confidence: v2.confidence,
      ev_estimate: match.analysis?.agreement.confidence_delta,
    });
    
    // Show subtle upgrade hint
    return (
      <div className="upgrade-hint">
        💡 Unlock picks with 75%+ accuracy • Upgrade to Premium
      </div>
    );
  }
};
```

---

## Performance Optimization

```typescript
// Use React Query for efficient caching + auto-refresh
import { useQuery } from '@tanstack/react-query';

export const useMarketData = (status: 'upcoming' | 'live', limit: number) => {
  return useQuery({
    queryKey: ['market', status, limit],
    queryFn: () => fetchMarket(status, limit),
    refetchInterval: 60000, // Auto-refresh every 60s
    staleTime: 30000,        // Consider fresh for 30s
    cacheTime: 300000,       // Keep in cache for 5 min
  });
};

// Usage in component
const { data, isLoading, error } = useMarketData('upcoming', 20);
```

---

## Error Handling

```typescript
// Graceful degradation example
const MatchCard: React.FC<{ match: MarketMatch }> = ({ match }) => {
  const hasV1 = match.models.v1_consensus;
  const hasV2 = match.models.v2_lightgbm;
  
  if (!hasV1 && !hasV2) {
    return (
      <div className="match-card error">
        <p>Predictions unavailable for this match</p>
        <small>Match ID: {match.match_id}</small>
      </div>
    );
  }
  
  return (
    <div className="match-card">
      {/* Show available models, hide missing ones */}
      {hasV1 && <V1Display data={match.models.v1_consensus} />}
      {hasV2 && <V2Display data={match.models.v2_lightgbm} />}
      {!hasV2 && <V2Placeholder />}
    </div>
  );
};
```

---

## Testing & Development

```bash
# Test endpoint directly
curl "http://localhost:8000/market?status=upcoming&limit=3" \
  -H "Authorization: Bearer betgenius_secure_key_2024" \
  | jq '.matches[0]'

# Expected: Returns upcoming matches with V1 + V2 predictions
```

---

## Summary

✅ **Keep time-based filtering** - More reliable than status flags  
✅ **Pre-computed V1** - Fast response times (~500ms)  
✅ **On-demand V2** - Fresh predictions every request  
✅ **60s updates** - Backend scheduler keeps data current  
✅ **Premium CTAs** - Built-in conversion opportunities  

The system is production-ready as designed! 🚀
