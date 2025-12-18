# World Cup 2026 - Data Collection Recommendations

## Current Data Status

### Historical Data Collected
| Tournament | Matches | Seasons | Shootouts |
|------------|---------|---------|-----------|
| FIFA World Cup | 256 | 4 (2010-2022) | 15 |
| UEFA Euro | 477 | 5 (2008-2024) | 18 |
| Africa Cup of Nations | 366 | 5 (2015-2023) | 19 |
| Copa America | 144 | 5 (2015-2024) | 15 |
| WC Qualifiers - UEFA | 728 | 3 | 0 |
| WC Qualifiers - CAF | 540 | 3 | 3 |
| WC Qualifiers - AFC | 456 | 2 | 0 |
| WC Qualifiers - CONMEBOL | 179 | 2 | 0 |
| WC Qualifiers - CONCACAF | 230 | 2 | 0 |
| **TOTAL** | **3,376** | - | **70** |

### API Data Availability
Based on API-Football coverage:

| Competition | Available Seasons |
|-------------|-------------------|
| FIFA World Cup | 2010, 2014, 2018, 2022, 2026 |
| UEFA Euro | 2008, 2012, 2016, 2020, 2024 |
| AFCON | 2015, 2017, 2019, 2021, 2023, 2025 |
| Copa America | 2015, 2016, 2019, 2021, 2024 |
| WC Qualifiers - UEFA | 2018, 2020, 2024 |
| WC Qualifiers - CAF | 2018, 2022, 2023 |
| WC Qualifiers - CONMEBOL | 2018, 2022, 2026 |

**Note**: Data before 2008 is not available in API-Football.

---

## Recommended Data Collection Strategy

### Phase 1: Historical Backfill (COMPLETED)
- World Cups 2010-2022: 256 matches
- Euros 2008-2024: 477 matches
- Continental tournaments: 510 matches
- WC Qualifiers: 2,133 matches

### Phase 2: Real-Time Qualifier Collection (NOW - June 2026)

**Daily Collection Schedule (04:00 UTC):**
```
Leagues to collect:
- WC Qualifiers - UEFA (ID 32) - 2024-2025 season
- WC Qualifiers - CAF (ID 29) - 2024-2025 season
- WC Qualifiers - CONMEBOL (ID 34) - 2026 season
- WC Qualifiers - CONCACAF (ID 31) - 2024-2025 season
- WC Qualifiers - AFC (ID 30) - 2024-2025 season
```

**Expected matches before WC 2026:**
- ~800 additional qualifier matches
- ~50-100 international friendlies (optional)

### Phase 3: Tournament Mode (June-July 2026)

**High-Frequency Collection:**
- Match odds: Every 5 minutes (vs 60 min normal)
- Live match data: Real-time via WebSocket
- Post-match stats: Within 1 hour of final whistle
- Model recalibration: After Matchday 2

---

## Data Gaps and Limitations

### What We DON'T Have (API Limitations)
1. **World Cups before 2010** - Not available in API-Football
2. **Venue country data** - API returns "World" for international matches
3. **Player caps at time of match** - Only current caps available
4. **Squad announcements** - Must be collected manually
5. **Travel distances** - Must be calculated from venue coordinates
6. **Manager tenure** - Not available in API

### How to Address Gaps

| Gap | Solution | Priority |
|-----|----------|----------|
| Pre-2010 World Cups | Manual data entry from historical sources | Low |
| Venue country | Use league.country + host nation mapping | Done |
| Player caps | Track incrementally from collected matches | Medium |
| Squad data | Collect from API-Football squad endpoint | High |
| Travel distances | Calculate from city coordinates | Medium |
| Manager tenure | Manual tracking or web scraping | Low |

---

## Additional Data Sources to Consider

### For Enhanced WC Model

1. **ELO Ratings (External)**
   - Source: eloratings.net
   - Updates: After each match
   - Value: Objective team strength measure

2. **FIFA Rankings**
   - Source: FIFA official
   - Updates: Monthly
   - Value: Official rankings, affects seeding

3. **Player Market Values (Transfermarkt)**
   - Value: Proxy for squad quality
   - Limitation: Requires web scraping

4. **Weather Data**
   - Source: OpenWeatherMap API
   - Value: Heat stress, altitude effects
   - Cost: Free tier sufficient

5. **Betting Volume (if available)**
   - Source: The Odds API (limited)
   - Value: Market sentiment indicator

---

## Collection Frequency Recommendations

| Data Type | Current | Recommended for WC | Notes |
|-----------|---------|-------------------|-------|
| Qualifier odds | 60 min | 30 min during matches | More granular drift data |
| Match results | Daily | 4x daily | Faster model updates |
| Player injuries | 60 min | 30 min near matchday | Squad availability |
| Squad data | Manual | Weekly | Track call-ups |
| Friendly matches | Not collected | Optional | Low weight in model |

---

## Training Data Requirements

### Minimum for WC Model Training
- **Matches**: 500+ (currently: 3,376) ✅
- **Penalty shootouts**: 50+ (currently: 70) ✅
- **Knockout matches**: 100+ (currently: ~200) ✅
- **Group stage matches**: 300+ (currently: ~1,000) ✅

### Recommended Training Split
- Training: 70% (pre-2022 tournaments)
- Validation: 15% (2022 WC + 2024 Euro)
- Test: 15% (2024-2025 qualifiers)

---

## Next Steps

1. **Immediate**: Enable daily qualifier collection in scheduler ✅
2. **January 2025**: Build national team ELO calculator
3. **Q1 2025**: Add squad tracking for 32 WC teams
4. **Q2 2025**: Train WC-specific model with separate heads
5. **Q1 2026**: Deploy tournament mode with high-frequency collection
6. **June 2026**: Activate WC model for live predictions

---

## API Quota Considerations

### Current Usage
- RapidAPI Football: ~300 calls/day for qualifiers
- The Odds API: 5M monthly (plenty of headroom)

### WC 2026 Tournament Mode
- Expect 5-10x normal API usage during tournament
- Reserve 100K+ calls for tournament period
- Enable caching for frequently accessed data
