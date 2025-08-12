# Enhanced Betting Markets Implementation

## Answers to Your Key Questions

### 1. T-72h Odds in Model Accuracy

**Current Implementation**: We use T-24h consensus but acknowledge T-72h is optimal.

**Evidence from Code**:
```python
# From data_snapshot.py
snapshot_time_hours: int = 24  # Currently T-24h, not T-72h

# From consensus_builder.py  
time_buckets = {
    '48h': {'min_hours': 36, 'max_hours': 60},  # Closest to T-72h
    '24h': {'min_hours': 18, 'max_hours': 30},  # Current default
}
```

**Answer**: No, we're currently using T-24h odds for accuracy measurement, not T-72h. We should update this.

### 2. Adding CLV, Spread, and Moneyline

**Current Markets**: We only support match result (1X2) markets.

**Implementation Needed**:

#### A. Closing Line Value (CLV)
```python
def calculate_clv(opening_odds, closing_odds, bet_outcome):
    """Calculate Closing Line Value - key metric for sharp bettors"""
    opening_prob = 1 / opening_odds
    closing_prob = 1 / closing_odds
    
    # CLV = (Closing Probability - Opening Probability) / Opening Probability
    clv = (closing_prob - opening_prob) / opening_prob
    
    return {
        'clv_percentage': clv * 100,
        'clv_category': 'positive' if clv > 0 else 'negative',
        'market_movement': 'sharpened' if clv > 0 else 'weakened'
    }
```

#### B. Spread (Asian Handicap)
```python
def get_spread_markets():
    """Implement Asian Handicap predictions"""
    
    markets = {
        'asian_handicap': {
            'home_-0.5': prob_calculation,
            'home_-1.0': prob_calculation,
            'away_+0.5': prob_calculation,
            'away_+1.0': prob_calculation
        }
    }
    
    return markets
```

#### C. Moneyline (Already Implemented)
Our current 1X2 market IS the moneyline for soccer. In US terms:
- Home Win = Moneyline Home
- Away Win = Moneyline Away  
- Draw = Specific to soccer

### 3. Adding Player Odds Over/Under

**Current Status**: Not implemented.

**Implementation Strategy**:

#### A. Player Props Data Structure
```python
player_markets = {
    'goals': {
        'player_id': 12345,
        'player_name': 'Mo Salah',
        'market_type': 'anytime_goalscorer',
        'odds': 2.50,
        'probability': 0.40
    },
    'assists': {
        'player_id': 12345, 
        'market_type': 'assists_over_0.5',
        'odds': 3.00,
        'probability': 0.33
    },
    'shots': {
        'player_id': 12345,
        'market_type': 'shots_over_2.5', 
        'odds': 1.80,
        'probability': 0.55
    }
}
```

#### B. Player Performance Prediction Model
```python
class PlayerPerformancePredictor:
    def predict_player_props(self, player_id, match_context):
        """Predict individual player performance"""
        
        # Historical player data
        player_stats = self.get_player_history(player_id)
        
        # Match context factors
        opposition_defense = self.get_opposition_strength()
        venue_factor = self.get_venue_impact()
        recent_form = self.get_player_form()
        
        # Position-specific models
        if player_stats['position'] == 'Forward':
            return self.predict_forward_props(player_id, match_context)
        elif player_stats['position'] == 'Midfielder':
            return self.predict_midfielder_props(player_id, match_context)
```

## Implementation Roadmap

### Phase 1: Enhanced Timing (Immediate)
1. **Update to T-72h optimal timing**
   ```python
   # Update data_snapshot.py
   snapshot_time_hours: int = 72  # Change from 24 to 72
   ```

2. **Add timing metadata to predictions**
   ```python
   prediction_metadata = {
       'timing_window': 'T-72h',
       'market_efficiency': 'optimal',
       'accuracy_expectation': 'maximum'
   }
   ```

### Phase 2: Additional Markets (Short-term)
1. **CLV Calculation**
   - Track opening vs closing odds
   - Calculate CLV for all bets
   - Display CLV in prediction response

2. **Spread Markets**
   - Add Asian Handicap predictions
   - Implement spread probability calculations
   - Integrate with current consensus model

3. **Enhanced Total Goals**
   - Current: Basic over/under 2.5
   - Add: Multiple totals (1.5, 2.5, 3.5, 4.5)
   - Add: Team-specific totals

### Phase 3: Player Props (Medium-term)
1. **Data Collection**
   - Player statistics API integration
   - Position-specific performance metrics
   - Injury status and availability

2. **Player Models**
   - Individual player performance prediction
   - Position-specific algorithms
   - Match context integration

3. **Market Integration**
   - Player prop odds collection
   - Probability calculations
   - Value bet identification

## Updated API Response Structure

```json
{
  "match_info": {...},
  "predictions": {
    "match_result": {
      "home_win": 0.44,
      "draw": 0.272, 
      "away_win": 0.287
    },
    "spread_markets": {
      "asian_handicap": {
        "home_-0.5": 0.396,
        "away_+0.5": 0.503
      }
    },
    "total_goals": {
      "over_1.5": 0.75,
      "over_2.5": 0.60,
      "over_3.5": 0.35
    },
    "player_props": {
      "mo_salah": {
        "anytime_goalscorer": 0.40,
        "shots_over_2.5": 0.55
      }
    }
  },
  "clv_analysis": {
    "market_movement": "Odds shortened from 2.20 to 1.95",
    "clv_percentage": -11.36,
    "sharp_money_indicator": "positive"
  }
}
```

## The Odds API Market Coverage

**Currently Available**:
- Match Result (1X2) ✅ 
- Total Goals (Over/Under) ✅
- Asian Handicap ✅
- Both Teams to Score ✅

**Requires Additional Setup**:
- Player Props (Limited availability)
- CLV tracking (Custom implementation needed)
- Enhanced spreads (Multiple handicap lines)

## Immediate Action Items

1. **Update timing to T-72h** for optimal accuracy
2. **Implement CLV tracking** for bet value assessment  
3. **Expand total goals markets** beyond just 2.5
4. **Add spread probability calculations** for Asian Handicap
5. **Research player props data availability** via The Odds API

The foundation is solid - we just need to expand the markets and optimize the timing alignment.