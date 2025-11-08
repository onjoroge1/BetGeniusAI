# Ensemble Model Roadmap (V3)

## 🎯 Overview

This document maps the path from current V2 model to the final V3 ensemble system.

---

## 📍 Current Position: Phase 2 Foundation (60% Complete)

### What We Have ✅
- **V1 Production**: Weighted consensus (54.3% accuracy) on `/predict`
- **V2 Foundation**: LightGBM with 50 features on `/predict-v2`
  - Clean data pipeline (real odds only)
  - Anti-leakage infrastructure (TimeSeriesSplit + embargo)
  - 1,236 clean matches with 100% extraction success
  - **Current accuracy: 49.5%** (below 53-55% target)

### What We Need ⚠️
- Fix sanity check leakage (random label: 43.1% → 33%)
- Add drift features (opening → latest odds)
- Backfill to 3,000-5,000 matches
- Tune hyperparameters
- Reach 53-55% accuracy consistently

---

## 🗺️ Three-Phase Roadmap

```
┌─────────────────────────────────────────────────────────────┐
│  PHASE 1: V1 Consensus Model          ✅ COMPLETE          │
├─────────────────────────────────────────────────────────────┤
│  Endpoint: /predict                                         │
│  Accuracy: 54.3% (3-way), 62.4% (2-way)                    │
│  Method: Weighted consensus of market + statistical models │
│  Status: Production deployed, serving predictions          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  PHASE 2: V2 LightGBM + Context        ⚠️ IN PROGRESS      │
├─────────────────────────────────────────────────────────────┤
│  Endpoint: /predict-v2                                      │
│  Target: 53-55% accuracy                                    │
│  Current: 49.5% accuracy (needs +3.5pp to +5.5pp)          │
│  Method: Single LightGBM model with 50 features            │
│  Status: Foundation complete, needs data + tuning          │
│                                                             │
│  ✅ Completed (60%):                                        │
│    • Clean data pipeline                                   │
│    • Anti-leakage infrastructure                           │
│    • 50 feature engineering                                │
│    • 1,236 clean training matches                          │
│                                                             │
│  ⏳ In Progress (30%):                                      │
│    • Fix sanity check leakage                              │
│    • Add drift features (opening odds)                     │
│    • Backfill to 3,000-5,000 matches                       │
│    • Hyperparameter tuning                                 │
│                                                             │
│  🔒 Blocked (10%):                                          │
│    • Production deployment (needs 53-55% first)            │
│    • CLV validation in wild                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  PHASE 3: V3 Ensemble Stack            ❌ NOT STARTED       │
├─────────────────────────────────────────────────────────────┤
│  Endpoint: /predict-v3  ← YES, this is V3!                 │
│  Target: 57-58% accuracy                                    │
│  Method: Stacked ensemble of 5+ diverse models             │
│  Status: Waiting for Phase 2 completion                    │
│                                                             │
│  Prerequisites (must complete first):                       │
│    □ Phase 2 hitting 53-55% consistently                   │
│    □ Dataset >= 5,000 clean matches                        │
│    □ Positive CLV across 5+ leagues                        │
│    □ V2 production-validated                               │
│                                                             │
│  Components to build:                                       │
│    □ Base Model 1: LightGBM-Home/Away (V2 optimized)       │
│    □ Base Model 2: LightGBM-Draw (class weighted)          │
│    □ Base Model 3: XGBoost (alternative boosting)          │
│    □ Base Model 4: CatBoost (categorical specialist)       │
│    □ Base Model 5: Neural Network (MLP 2-3 layers)         │
│    □ Meta-Learner: Ridge/Logistic stacking                 │
│    □ Confidence Weighting: Model agreement scoring         │
│    □ Market Blending: Deviation-aware mixing               │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Detailed Task Breakdown

### PHASE 2 COMPLETION (Estimated: 4-8 weeks)

#### Week 1-2: Critical Fixes 🔴
- [ ] **Fix random-label sanity check**
  - Permute labels independently before CV
  - Add row-permutation test
  - Target: 33% ± 2% accuracy on random labels
  
- [ ] **Create opening odds view**
  ```sql
  CREATE MATERIALIZED VIEW odds_real_opening AS ...
  ```
  
- [ ] **Add drift features to V2FeatureBuilder**
  - `prob_drift_home`, `prob_drift_draw`, `prob_drift_away`
  - `drift_magnitude`, `drift_direction`
  - Expected gain: +0.5-1.0pp accuracy

- [ ] **Validate market baseline**
  - Investigate 45.3% (should be 48-52%)
  - Check odds distribution
  - Verify normalization logic

#### Week 2-4: Data Expansion 🟡
- [ ] **Backfill 1,764 matches** (1,236 → 3,000)
  - Use The Odds API or API-Football
  - Target: 500-1,000 matches/week
  - Retrain every +500 matches
  
- [ ] **Track accuracy improvement curve**
  - Log OOF metrics per training run
  - Plot accuracy vs dataset size
  - Validate diminishing returns

#### Week 4-6: Model Optimization 🟢
- [ ] **Hyperparameter tuning**
  - Grid search: `num_leaves` [31, 63, 127]
  - Grid search: `min_data_in_leaf` [50, 100, 200]
  - Grid search: `feature_fraction` [0.7, 0.8, 0.9]
  - Grid search: `lambda_l1/l2` [0.0, 0.5, 1.0]
  - Expected gain: +1.0-2.0pp accuracy

- [ ] **Class balancing**
  - Up-weight draws (underfit class)
  - Sample weights or `class_weight` parameter
  - Expected gain: +0.5-1.0pp accuracy

- [ ] **Per-league calibration**
  - Isotonic regression post-training
  - Separate calibrators per league tier
  - Improve Brier score by ~0.01-0.02

- [ ] **Add meta-features**
  - League tier (1-5 rating)
  - Derby flag (rivalry matches)
  - Odds regime (favorite/coin-flip/long-shot)
  - Expected gain: +0.5pp accuracy

#### Week 6-8: Validation & Deployment 🔵
- [ ] **CLV analysis on OOF predictions**
  - Calculate expected value per league
  - Track closing line value
  - Target: +2% EV on aggregate

- [ ] **Production deployment**
  - Update `/predict-v2` endpoint
  - Shadow testing vs V1
  - Gradual traffic ramp (10% → 50% → 100%)

- [ ] **Monitor in wild**
  - Real-world accuracy tracking
  - Kelly sizing validation
  - Sharpe ratio on live bets

### Phase 2 Success Criteria ✅
Before proceeding to Phase 3, must achieve:
- ✅ OOF Accuracy: **53-55%** (3-way)
- ✅ LogLoss: **< 1.00**
- ✅ Brier Score: **< 0.22**
- ✅ Dataset: **>= 5,000 matches**
- ✅ Sanity Random: **33% ± 2%**
- ✅ Sanity Market: **48-52%**
- ✅ CLV: **Positive across 5+ leagues**

---

### PHASE 3 ENSEMBLE (Estimated: 8-12 weeks after Phase 2)

#### Month 1: Base Model Development
- [ ] **LightGBM-1: Home/Away Specialist**
  - Optimize for favorites
  - Tune on home wins + away wins
  - Target: 60% 2-way accuracy on favorites

- [ ] **LightGBM-2: Draw Specialist**
  - Heavy class weights for draws
  - Feature selection for draw patterns
  - Target: 35% draw precision

- [ ] **XGBoost Model**
  - Alternative boosting algorithm
  - Different regularization approach
  - Diversity via different architecture

- [ ] **CatBoost Model**
  - Specialized categorical encoding
  - Handles league/team embeddings
  - Complement LightGBM weaknesses

- [ ] **Neural Network (MLP)**
  - 2-3 hidden layers (128-64-32 units)
  - Batch normalization + dropout
  - Learn non-linear feature interactions
  - Target: 51-53% accuracy (diversity > accuracy)

#### Month 2: Meta-Learning Layer
- [ ] **Stacked Generalization**
  - Collect OOF predictions from all 5 base models
  - Train Ridge/Logistic meta-model
  - 5-fold CV on OOF predictions

- [ ] **Confidence Weighting**
  - Calculate model agreement score
  - Weight by individual calibration quality
  - Reduce weight when models disagree

- [ ] **Market-Relative Blending**
  - Blend more when models align against market
  - Reduce ensemble weight when market-aligned
  - Capture value opportunities

#### Month 3: Advanced Features & Polish
- [ ] **Model Agreement Features**
  - Entropy of base predictions
  - Standard deviation across models
  - Unanimous vote flag

- [ ] **Market Deviation Features**
  - Magnitude: `|p_ensemble - p_market|`
  - Direction: `sign(p_ensemble - p_market)`
  - Conviction: `deviation * model_agreement`

- [ ] **Odds Movement Signals**
  - Drift velocity: `(p_latest - p_opening) / hours`
  - Acceleration: Change in drift rate
  - Reversal flags

- [ ] **External Data (if available)**
  - Weather conditions (temperature, rain, wind)
  - Referee statistics (cards, penalties)
  - Venue-specific factors

- [ ] **Deep Learning Embeddings**
  - Team embeddings (learned representations)
  - League embeddings
  - Seasonal patterns

#### Endpoint Design: `/predict-v3`

```python
@app.post("/predict-v3")
async def predict_v3(match_id: int, include_base_models: bool = False):
    """
    V3 Ensemble Prediction Endpoint
    
    Returns stacked ensemble predictions with confidence scoring.
    """
    # Get base model predictions
    lgbm_1 = predict_lgbm_home_away(match_id)
    lgbm_2 = predict_lgbm_draw(match_id)
    xgb = predict_xgboost(match_id)
    catboost = predict_catboost(match_id)
    mlp = predict_neural_net(match_id)
    
    # Calculate model agreement (confidence)
    base_predictions = [lgbm_1, lgbm_2, xgb, catboost, mlp]
    confidence = calculate_model_agreement(base_predictions)
    
    # Meta-model stacking
    ensemble_pred = meta_model.predict_proba([
        lgbm_1, lgbm_2, xgb, catboost, mlp,
        confidence, market_deviation, odds_drift
    ])
    
    # Market-relative blending
    final_pred = blend_with_market(
        ensemble_pred, 
        market_odds,
        weight=confidence
    )
    
    response = {
        "match_id": match_id,
        "predictions": {
            "ensemble": {
                "home": final_pred[0],
                "draw": final_pred[1],
                "away": final_pred[2],
                "confidence": confidence  # 0-100 score
            }
        },
        "model_version": "v3.0.0",
        "accuracy_oof": "57.2%",
        "expected_value": calculate_ev(final_pred, market_odds)
    }
    
    # Optionally include base model breakdown
    if include_base_models:
        response["base_models"] = {
            "lgbm_home_away": lgbm_1,
            "lgbm_draw": lgbm_2,
            "xgboost": xgb,
            "catboost": catboost,
            "neural_net": mlp
        }
    
    return response
```

### Phase 3 Success Criteria ✅
- ✅ OOF Accuracy: **57-58%** (3-way)
- ✅ LogLoss: **< 0.92**
- ✅ Brier Score: **< 0.18**
- ✅ Expected Value: **+5% across all leagues**
- ✅ Sharpe Ratio: **> 1.5** on hypothetical Kelly betting
- ✅ Model Agreement: **> 0.7** on high-confidence predictions
- ✅ Production Stable: **30 days** without critical bugs

---

## 🎯 Milestone Timeline

```
NOW (Nov 2025)
│
├─ Week 1-2: Critical Fixes
│  ├─ Fix sanity checks
│  ├─ Add drift features
│  └─ Validate market baseline
│
├─ Week 2-4: Data Expansion
│  ├─ Backfill to 3,000 matches
│  └─ Retrain periodically
│
├─ Week 4-6: Model Optimization
│  ├─ Hyperparameter tuning
│  ├─ Class balancing
│  └─ Per-league calibration
│
├─ Week 6-8: V2 Production
│  ├─ CLV validation
│  ├─ Deploy /predict-v2
│  └─ Monitor in wild
│
▼
Phase 2 COMPLETE (Jan 2026)
├─ 53-55% accuracy achieved
├─ 5,000+ clean matches
└─ Positive CLV validated
│
├─ Month 1: Base Models
│  ├─ LightGBM variants
│  ├─ XGBoost
│  ├─ CatBoost
│  └─ Neural Network
│
├─ Month 2: Meta-Learning
│  ├─ Stacked generalization
│  ├─ Confidence weighting
│  └─ Market blending
│
├─ Month 3: Advanced Features
│  ├─ Model agreement
│  ├─ Odds movement
│  └─ External data
│
▼
Phase 3 COMPLETE (Apr 2026)
├─ 57-58% accuracy achieved
├─ /predict-v3 deployed
└─ Production-validated ensemble
```

---

## 📊 Expected Accuracy Progression

| Phase | Model | Matches | Accuracy | LogLoss | Status |
|-------|-------|---------|----------|---------|--------|
| **V1** | Consensus | 40,769 | 54.3% | 0.987 | ✅ Production |
| **V2 (Current)** | LightGBM | 1,236 | 49.5% | 1.013 | ⚠️ In Progress |
| **V2 (Target)** | LightGBM | 5,000 | 53-55% | <1.00 | ⏳ Pending |
| **V3 (Ensemble)** | Stack | 5,000+ | 57-58% | <0.92 | ❌ Future |

**Improvement Curve:**
- 1,236 → 3,000 matches: +2.5pp → **52%**
- 3,000 → 5,000 matches: +2.0pp → **54%**
- Hyperparameter tuning: +1.0pp → **55%**
- Ensemble stacking: +2-3pp → **57-58%**

---

## 🚀 Action Items (Priority Order)

### This Week
1. 🔴 **Fix sanity check leakage** (critical for validation)
2. 🔴 **Create opening odds view** (quick SQL)
3. 🔴 **Add drift features** (update V2FeatureBuilder)

### Next 2 Weeks
4. 🟡 **Start backfilling** (500-1,000 matches/week)
5. 🟡 **Validate market baseline** (investigate 45.3%)
6. 🟡 **Retrain at 2,000 matches** (measure improvement)

### Next Month
7. 🟢 **Hyperparameter tuning** (grid search)
8. 🟢 **Class balancing** (up-weight draws)
9. 🟢 **Reach 3,000 matches** (75% to Phase 2 target)

### Next Quarter
10. 🔵 **Deploy V2 to production** (`/predict-v2`)
11. 🔵 **CLV validation** (track closing line value)
12. 🔵 **Begin Phase 3 design** (ensemble architecture)

---

## ✅ Yes, V3 = `/predict-v3` Endpoint!

**Endpoint Evolution:**
- `/predict` = V1 Consensus (54.3%, production)
- `/predict-v2` = V2 LightGBM (targeting 53-55%)
- `/predict-v3` = V3 Ensemble (targeting 57-58%)

**Each endpoint coexists** - users can choose:
- V1 for stable, proven predictions
- V2 for improved accuracy (once validated)
- V3 for maximum performance (future premium tier)

---

## 💭 Strategic Considerations

### Why Not Skip to V3 Now?
1. **Foundation required**: Ensemble only as good as base models
2. **Data insufficient**: 1,236 matches too small for stable 5-model stack
3. **Risk management**: Need to validate V2 works before complexity
4. **Learning opportunity**: V2 tuning informs V3 architecture

### Why Sequential Phases?
1. **Incremental validation**: Catch issues early
2. **Resource efficiency**: Don't waste time on bad foundations
3. **User trust**: Gradual accuracy improvements build confidence
4. **Technical debt**: Clean V2 → easier V3 integration

### What If V2 Plateaus at 52%?
- Still deploy (52% > 54.3% V1? No, so keep as SELECT premium)
- Investigate architectural limits
- Consider alternative approaches (neural nets, transformers)
- Re-evaluate Phase 3 ensemble value proposition

---

**Bottom Line:** You're 60% through Phase 2, with a clear 4-8 week path to completion. Phase 3 (V3 ensemble) is a well-defined 3-month project that starts **after** V2 hits 53-55%. Stay focused on the current phase! 🎯
