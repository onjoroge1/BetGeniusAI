# BetGenius AI - Frontend Implementation Guide

## 🎯 Overview

This guide shows you how to integrate BetGenius AI betting intelligence into your frontend application, whether you're using React, Vue, Angular, vanilla JavaScript, or mobile (React Native, Flutter).

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [React Implementation](#react-implementation)
3. [Vue Implementation](#vue-implementation)
4. [Vanilla JavaScript](#vanilla-javascript)
5. [React Native (Mobile)](#react-native-mobile)
6. [Flutter (Mobile)](#flutter-mobile)
7. [UI Components](#ui-components)
8. [Real-Time Updates](#real-time-updates)
9. [Best Practices](#best-practices)

---

## 🚀 Quick Start

### API Configuration

```javascript
// config/api.js
export const API_CONFIG = {
  baseURL: process.env.REACT_APP_API_URL || 'http://localhost:8000',
  apiKey: process.env.REACT_APP_API_KEY || 'betgenius_secure_key_2024',
  timeout: 10000,
};

export const apiHeaders = {
  'Authorization': `Bearer ${API_CONFIG.apiKey}`,
  'Content-Type': 'application/json',
};
```

---

## ⚛️ React Implementation

### 1. API Service Layer

```javascript
// services/bettingIntelligence.js
import axios from 'axios';
import { API_CONFIG, apiHeaders } from '../config/api';

const api = axios.create({
  baseURL: API_CONFIG.baseURL,
  headers: apiHeaders,
  timeout: API_CONFIG.timeout,
});

export const bettingIntelligenceService = {
  // Get betting intelligence for a specific match
  getMatchIntel: async (matchId, params = {}) => {
    const { bankroll = 1000, kelly_frac = 0.5, model = 'best' } = params;
    const response = await api.get(`/betting-intelligence/${matchId}`, {
      params: { bankroll, kelly_frac, model }
    });
    return response.data;
  },

  // Get curated betting opportunities
  getOpportunities: async (filters = {}) => {
    const {
      min_edge = 0.02,
      limit = 20,
      offset = 0,
      league_ids = [],
      model = 'best',
      status = 'upcoming',
      sort_by = 'edge'
    } = filters;

    const response = await api.get('/betting-intelligence', {
      params: {
        min_edge,
        limit,
        offset,
        league_ids: league_ids.join(','),
        model,
        status,
        sort_by
      }
    });
    return response.data;
  },

  // Get market board with embedded intel
  getMarketBoard: async (params = {}) => {
    const { status = 'upcoming', limit = 20, league_id } = params;
    const response = await api.get('/market', {
      params: { status, limit, league_id }
    });
    return response.data;
  },
};
```

### 2. Custom Hooks

```javascript
// hooks/useBettingIntel.js
import { useState, useEffect } from 'react';
import { bettingIntelligenceService } from '../services/bettingIntelligence';

export const useBettingIntel = (matchId, options = {}) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchIntel = async () => {
      try {
        setLoading(true);
        const result = await bettingIntelligenceService.getMatchIntel(matchId, options);
        setData(result);
        setError(null);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    if (matchId) {
      fetchIntel();
    }
  }, [matchId, options.bankroll, options.kelly_frac, options.model]);

  return { data, loading, error };
};

// hooks/useOpportunities.js
export const useOpportunities = (filters = {}) => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [totalCount, setTotalCount] = useState(0);

  useEffect(() => {
    const fetchOpportunities = async () => {
      try {
        setLoading(true);
        const result = await bettingIntelligenceService.getOpportunities(filters);
        setOpportunities(result.opportunities || []);
        setTotalCount(result.total_count || 0);
        setError(null);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchOpportunities();
  }, [JSON.stringify(filters)]);

  return { opportunities, totalCount, loading, error };
};
```

### 3. UI Components

```jsx
// components/BettingIntelCard.jsx
import React from 'react';
import { useBettingIntel } from '../hooks/useBettingIntel';

const BettingIntelCard = ({ matchId, bankroll = 1000 }) => {
  const { data, loading, error } = useBettingIntel(matchId, { bankroll });

  if (loading) return <div className="animate-pulse">Loading...</div>;
  if (error) return <div className="text-red-500">Error: {error}</div>;
  if (!data?.betting_intelligence) return null;

  const { betting_intelligence, home, away, league, kickoff_time } = data;
  const { best_bet, kelly_sizing, clv } = betting_intelligence;

  const edgeColor = best_bet.edge >= 0.05 ? 'text-green-600' : 
                    best_bet.edge >= 0.02 ? 'text-blue-600' : 
                    'text-gray-600';

  const recommendationBadge = {
    'STRONG BET': 'bg-green-100 text-green-800',
    'VALUE BET': 'bg-blue-100 text-blue-800',
    'PASS': 'bg-gray-100 text-gray-800'
  }[best_bet.recommendation] || 'bg-gray-100';

  return (
    <div className="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition-shadow">
      {/* Match Header */}
      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-lg font-bold">
            {home.name} vs {away.name}
          </h3>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${recommendationBadge}`}>
            {best_bet.recommendation}
          </span>
        </div>
        <div className="text-sm text-gray-500">
          {league.name} • {new Date(kickoff_time).toLocaleString()}
        </div>
      </div>

      {/* Best Bet */}
      <div className="mb-4 p-4 bg-gray-50 rounded-lg">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Recommended Pick</span>
          <span className="text-xl font-bold uppercase">{best_bet.pick}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600">Expected Edge</span>
          <span className={`text-lg font-bold ${edgeColor}`}>
            {(best_bet.edge * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Kelly Sizing */}
      <div className="mb-4">
        <div className="text-sm font-medium text-gray-700 mb-2">Position Sizing</div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-gray-500">Recommended Stake</div>
            <div className="text-lg font-bold">
              {kelly_sizing.recommended_stake_pct.toFixed(1)}%
            </div>
            <div className="text-sm text-gray-600">
              ${(bankroll * kelly_sizing.recommended_stake_pct / 100).toFixed(0)}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500">Max Stake</div>
            <div className="text-lg font-bold">
              {kelly_sizing.max_stake_pct.toFixed(1)}%
            </div>
          </div>
        </div>
      </div>

      {/* CLV Analysis */}
      <div>
        <div className="text-sm font-medium text-gray-700 mb-2">Closing Line Value</div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <div className="p-2 rounded bg-gray-50">
            <div className="text-xs text-gray-500">Home</div>
            <div className={`text-sm font-bold ${clv.home > 0 ? 'text-green-600' : 'text-red-600'}`}>
              {(clv.home * 100).toFixed(1)}%
            </div>
          </div>
          <div className="p-2 rounded bg-gray-50">
            <div className="text-xs text-gray-500">Draw</div>
            <div className={`text-sm font-bold ${clv.draw > 0 ? 'text-green-600' : 'text-red-600'}`}>
              {(clv.draw * 100).toFixed(1)}%
            </div>
          </div>
          <div className="p-2 rounded bg-gray-50">
            <div className="text-xs text-gray-500">Away</div>
            <div className={`text-sm font-bold ${clv.away > 0 ? 'text-green-600' : 'text-red-600'}`}>
              {(clv.away * 100).toFixed(1)}%
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default BettingIntelCard;
```

```jsx
// components/OpportunitiesList.jsx
import React, { useState } from 'react';
import { useOpportunities } from '../hooks/useOpportunities';

const OpportunitiesList = () => {
  const [filters, setFilters] = useState({
    min_edge: 0.02,
    limit: 20,
    sort_by: 'edge'
  });

  const { opportunities, totalCount, loading, error } = useOpportunities(filters);

  if (loading) return <div>Loading opportunities...</div>;
  if (error) return <div>Error: {error}</div>;

  return (
    <div className="max-w-6xl mx-auto p-6">
      {/* Filters */}
      <div className="mb-6 flex gap-4">
        <select
          value={filters.min_edge}
          onChange={(e) => setFilters({ ...filters, min_edge: parseFloat(e.target.value) })}
          className="px-4 py-2 border rounded-lg"
        >
          <option value="0.01">1%+ Edge</option>
          <option value="0.02">2%+ Edge</option>
          <option value="0.03">3%+ Edge</option>
          <option value="0.05">5%+ Edge</option>
        </select>

        <select
          value={filters.sort_by}
          onChange={(e) => setFilters({ ...filters, sort_by: e.target.value })}
          className="px-4 py-2 border rounded-lg"
        >
          <option value="edge">Sort by Edge</option>
          <option value="kickoff">Sort by Kickoff</option>
          <option value="confidence">Sort by Confidence</option>
        </select>
      </div>

      {/* Count */}
      <div className="mb-4 text-lg font-semibold">
        {totalCount} Opportunities Found
      </div>

      {/* List */}
      <div className="space-y-4">
        {opportunities.map((opp) => (
          <div key={opp.match_id} className="bg-white rounded-lg shadow p-6">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-lg font-bold">
                  {opp.home_team} vs {opp.away_team}
                </h3>
                <p className="text-sm text-gray-500">
                  {opp.league_name} • {new Date(opp.kickoff_time).toLocaleString()}
                </p>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-green-600">
                  {(opp.betting_intelligence.best_bet.edge * 100).toFixed(1)}%
                </div>
                <div className="text-sm text-gray-500">Edge</div>
              </div>
            </div>

            <div className="flex gap-6">
              <div>
                <div className="text-sm text-gray-500">Pick</div>
                <div className="text-lg font-bold uppercase">
                  {opp.betting_intelligence.best_bet.pick}
                </div>
              </div>
              <div>
                <div className="text-sm text-gray-500">Stake</div>
                <div className="text-lg font-bold">
                  {opp.betting_intelligence.kelly_sizing.recommended_stake_pct.toFixed(1)}%
                </div>
              </div>
              <div>
                <div className="text-sm text-gray-500">Recommendation</div>
                <div className="text-lg font-medium">
                  {opp.betting_intelligence.best_bet.recommendation}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default OpportunitiesList;
```

### 4. Complete Page Example

```jsx
// pages/BettingDashboard.jsx
import React, { useState } from 'react';
import BettingIntelCard from '../components/BettingIntelCard';
import OpportunitiesList from '../components/OpportunitiesList';

const BettingDashboard = () => {
  const [bankroll, setBankroll] = useState(1000);
  const [activeTab, setActiveTab] = useState('opportunities');

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <h1 className="text-3xl font-bold text-gray-900">
            BetGenius AI Dashboard
          </h1>
          <div className="mt-4">
            <label className="text-sm font-medium text-gray-700 mr-2">
              Bankroll:
            </label>
            <input
              type="number"
              value={bankroll}
              onChange={(e) => setBankroll(parseFloat(e.target.value) || 1000)}
              className="px-4 py-2 border rounded-lg"
              placeholder="Enter bankroll"
            />
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="max-w-7xl mx-auto px-4 mt-6">
        <div className="border-b border-gray-200">
          <nav className="-mb-px flex space-x-8">
            <button
              onClick={() => setActiveTab('opportunities')}
              className={`${
                activeTab === 'opportunities'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
            >
              Opportunities
            </button>
            <button
              onClick={() => setActiveTab('market')}
              className={`${
                activeTab === 'market'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
            >
              Market Board
            </button>
          </nav>
        </div>
      </div>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {activeTab === 'opportunities' && <OpportunitiesList />}
        {activeTab === 'market' && <div>Market Board Coming Soon</div>}
      </main>
    </div>
  );
};

export default BettingDashboard;
```

---

## 🟢 Vue Implementation

### 1. Composition API Service

```javascript
// services/bettingIntel.js
import { ref } from 'vue';
import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_KEY = import.meta.env.VITE_API_KEY || 'betgenius_secure_key_2024';

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Authorization': `Bearer ${API_KEY}`
  }
});

export function useBettingIntel() {
  const loading = ref(false);
  const error = ref(null);

  const getMatchIntel = async (matchId, params = {}) => {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.get(`/betting-intelligence/${matchId}`, { params });
      return response.data;
    } catch (err) {
      error.value = err.message;
      throw err;
    } finally {
      loading.value = false;
    }
  };

  const getOpportunities = async (filters = {}) => {
    loading.value = true;
    error.value = null;
    try {
      const response = await api.get('/betting-intelligence', { params: filters });
      return response.data;
    } catch (err) {
      error.value = err.message;
      throw err;
    } finally {
      loading.value = false;
    }
  };

  return {
    loading,
    error,
    getMatchIntel,
    getOpportunities
  };
}
```

### 2. Vue Component

```vue
<!-- components/BettingIntelCard.vue -->
<template>
  <div class="betting-intel-card">
    <div v-if="loading">Loading...</div>
    <div v-else-if="error">Error: {{ error }}</div>
    <div v-else-if="intel" class="card">
      <!-- Match Header -->
      <div class="header">
        <h3>{{ intel.home.name }} vs {{ intel.away.name }}</h3>
        <span :class="recommendationClass">
          {{ intel.betting_intelligence.best_bet.recommendation }}
        </span>
      </div>

      <!-- Best Bet -->
      <div class="best-bet">
        <div class="pick">
          <span>Pick:</span>
          <strong>{{ intel.betting_intelligence.best_bet.pick.toUpperCase() }}</strong>
        </div>
        <div class="edge">
          <span>Edge:</span>
          <strong :class="edgeClass">
            {{ (intel.betting_intelligence.best_bet.edge * 100).toFixed(1) }}%
          </strong>
        </div>
      </div>

      <!-- Kelly Sizing -->
      <div class="kelly">
        <div>Recommended: {{ intel.betting_intelligence.kelly_sizing.recommended_stake_pct.toFixed(1) }}%</div>
        <div>Amount: ${{ calculateStake }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import { useBettingIntel } from '../services/bettingIntel';

const props = defineProps({
  matchId: {
    type: Number,
    required: true
  },
  bankroll: {
    type: Number,
    default: 1000
  }
});

const { loading, error, getMatchIntel } = useBettingIntel();
const intel = ref(null);

const recommendationClass = computed(() => {
  const rec = intel.value?.betting_intelligence?.best_bet?.recommendation;
  return {
    'recommendation': true,
    'strong': rec === 'STRONG BET',
    'value': rec === 'VALUE BET',
    'pass': rec === 'PASS'
  };
});

const edgeClass = computed(() => {
  const edge = intel.value?.betting_intelligence?.best_bet?.edge || 0;
  return {
    'edge-high': edge >= 0.05,
    'edge-medium': edge >= 0.02 && edge < 0.05,
    'edge-low': edge < 0.02
  };
});

const calculateStake = computed(() => {
  const pct = intel.value?.betting_intelligence?.kelly_sizing?.recommended_stake_pct || 0;
  return (props.bankroll * pct / 100).toFixed(0);
});

onMounted(async () => {
  intel.value = await getMatchIntel(props.matchId, {
    bankroll: props.bankroll
  });
});
</script>

<style scoped>
.betting-intel-card {
  background: white;
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.recommendation.strong {
  background: #10b981;
  color: white;
}

.recommendation.value {
  background: #3b82f6;
  color: white;
}

.edge-high { color: #10b981; }
.edge-medium { color: #3b82f6; }
.edge-low { color: #6b7280; }
</style>
```

---

## 📱 React Native (Mobile)

```javascript
// services/api.js
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const API_BASE = 'https://your-api.replit.app';  // Production URL
const API_KEY = 'betgenius_secure_key_2024';

const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
  },
  timeout: 10000
});

export const fetchOpportunities = async (filters = {}) => {
  try {
    const response = await api.get('/betting-intelligence', { params: filters });
    // Cache for offline access
    await AsyncStorage.setItem('cached_opportunities', JSON.stringify(response.data));
    return response.data;
  } catch (error) {
    // Try to load cached data
    const cached = await AsyncStorage.getItem('cached_opportunities');
    if (cached) {
      return JSON.parse(cached);
    }
    throw error;
  }
};

// components/BettingCard.js
import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';

export const BettingCard = ({ opportunity, onPress }) => {
  const { home_team, away_team, betting_intelligence } = opportunity;
  const { best_bet, kelly_sizing } = betting_intelligence;

  const edgeColor = best_bet.edge >= 0.05 ? '#10b981' : 
                    best_bet.edge >= 0.02 ? '#3b82f6' : '#6b7280';

  return (
    <TouchableOpacity style={styles.card} onPress={onPress}>
      <View style={styles.header}>
        <Text style={styles.matchTitle}>
          {home_team} vs {away_team}
        </Text>
        <View style={[styles.badge, { backgroundColor: edgeColor }]}>
          <Text style={styles.badgeText}>{best_bet.recommendation}</Text>
        </View>
      </View>

      <View style={styles.stats}>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Pick</Text>
          <Text style={styles.statValue}>{best_bet.pick.toUpperCase()}</Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Edge</Text>
          <Text style={[styles.statValue, { color: edgeColor }]}>
            {(best_bet.edge * 100).toFixed(1)}%
          </Text>
        </View>
        <View style={styles.stat}>
          <Text style={styles.statLabel}>Stake</Text>
          <Text style={styles.statValue}>
            {kelly_sizing.recommended_stake_pct.toFixed(1)}%
          </Text>
        </View>
      </View>
    </TouchableOpacity>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  matchTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    flex: 1,
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  badgeText: {
    color: 'white',
    fontSize: 10,
    fontWeight: '600',
  },
  stats: {
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  stat: {
    alignItems: 'center',
  },
  statLabel: {
    fontSize: 12,
    color: '#6b7280',
    marginBottom: 4,
  },
  statValue: {
    fontSize: 18,
    fontWeight: 'bold',
  },
});
```

---

## 🎨 UI Components Library

### Recommendation Badge

```jsx
const RecommendationBadge = ({ recommendation }) => {
  const colors = {
    'STRONG BET': 'bg-green-500 text-white',
    'VALUE BET': 'bg-blue-500 text-white',
    'PASS': 'bg-gray-400 text-white'
  };

  return (
    <span className={`px-3 py-1 rounded-full text-sm font-semibold ${colors[recommendation]}`}>
      {recommendation}
    </span>
  );
};
```

### Edge Indicator

```jsx
const EdgeIndicator = ({ edge }) => {
  const percentage = (edge * 100).toFixed(1);
  const color = edge >= 0.05 ? 'text-green-600' : 
                edge >= 0.02 ? 'text-blue-600' : 'text-gray-600';

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500">Edge:</span>
      <span className={`text-2xl font-bold ${color}`}>{percentage}%</span>
    </div>
  );
};
```

### Kelly Sizing Display

```jsx
const KellySizing = ({ sizing, bankroll }) => {
  const stake = (bankroll * sizing.recommended_stake_pct / 100).toFixed(0);

  return (
    <div className="p-4 bg-blue-50 rounded-lg">
      <div className="text-sm text-gray-600 mb-2">Position Sizing</div>
      <div className="flex justify-between items-end">
        <div>
          <div className="text-3xl font-bold text-blue-600">
            {sizing.recommended_stake_pct.toFixed(1)}%
          </div>
          <div className="text-sm text-gray-500">of bankroll</div>
        </div>
        <div className="text-right">
          <div className="text-2xl font-bold">${stake}</div>
          <div className="text-xs text-gray-500">recommended stake</div>
        </div>
      </div>
    </div>
  );
};
```

---

## ⚡ Real-Time Updates

### Polling Strategy

```javascript
// hooks/useRealTimeOpportunities.js
import { useState, useEffect, useRef } from 'react';
import { bettingIntelligenceService } from '../services/bettingIntelligence';

export const useRealTimeOpportunities = (filters = {}, pollInterval = 60000) => {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const intervalRef = useRef(null);

  const fetchData = async () => {
    try {
      const data = await bettingIntelligenceService.getOpportunities(filters);
      setOpportunities(data.opportunities || []);
      setLoading(false);
    } catch (err) {
      console.error('Failed to fetch opportunities:', err);
    }
  };

  useEffect(() => {
    // Initial fetch
    fetchData();

    // Set up polling
    intervalRef.current = setInterval(fetchData, pollInterval);

    // Cleanup
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [JSON.stringify(filters), pollInterval]);

  return { opportunities, loading, refresh: fetchData };
};
```

### Usage

```jsx
const LiveDashboard = () => {
  const { opportunities, loading, refresh } = useRealTimeOpportunities({
    min_edge: 0.03,
    status: 'live'
  }, 30000); // Poll every 30 seconds

  return (
    <div>
      <button onClick={refresh}>Refresh Now</button>
      <div>
        {opportunities.map(opp => (
          <BettingCard key={opp.match_id} opportunity={opp} />
        ))}
      </div>
    </div>
  );
};
```

---

## ✅ Best Practices

### 1. Error Handling

```javascript
const ErrorBoundary = ({ error, retry }) => (
  <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
    <h3 className="text-lg font-semibold text-red-800 mb-2">
      Something went wrong
    </h3>
    <p className="text-red-600 mb-4">{error}</p>
    <button
      onClick={retry}
      className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
    >
      Try Again
    </button>
  </div>
);
```

### 2. Loading States

```jsx
const LoadingSkeleton = () => (
  <div className="animate-pulse">
    <div className="h-8 bg-gray-200 rounded w-3/4 mb-4"></div>
    <div className="h-4 bg-gray-200 rounded w-1/2 mb-2"></div>
    <div className="h-4 bg-gray-200 rounded w-2/3"></div>
  </div>
);
```

### 3. Caching Strategy

```javascript
// Simple in-memory cache
const cache = new Map();
const CACHE_DURATION = 60000; // 1 minute

export const fetchWithCache = async (key, fetchFn) => {
  const cached = cache.get(key);
  if (cached && Date.now() - cached.timestamp < CACHE_DURATION) {
    return cached.data;
  }

  const data = await fetchFn();
  cache.set(key, { data, timestamp: Date.now() });
  return data;
};
```

### 4. Responsive Design

```css
/* Mobile-first approach */
.betting-card {
  padding: 1rem;
}

@media (min-width: 768px) {
  .betting-card {
    padding: 1.5rem;
  }
}

@media (min-width: 1024px) {
  .betting-card {
    padding: 2rem;
  }
}
```

---

## 🎯 Quick Start Templates

### Minimal Implementation (5 minutes)

```jsx
import { useState, useEffect } from 'react';

function QuickBettingApp() {
  const [opps, setOpps] = useState([]);

  useEffect(() => {
    fetch('http://localhost:8000/betting-intelligence?min_edge=0.03', {
      headers: { 'Authorization': 'Bearer betgenius_secure_key_2024' }
    })
      .then(res => res.json())
      .then(data => setOpps(data.opportunities || []));
  }, []);

  return (
    <div>
      {opps.map(o => (
        <div key={o.match_id}>
          <h3>{o.home_team} vs {o.away_team}</h3>
          <p>Pick: {o.betting_intelligence.best_bet.pick}</p>
          <p>Edge: {(o.betting_intelligence.best_bet.edge * 100).toFixed(1)}%</p>
        </div>
      ))}
    </div>
  );
}
```

---

## 📚 Additional Resources

- **API Documentation**: See `BETTING_INTELLIGENCE_API.md`
- **Test Commands**: See `CURL_TEST_STATEMENTS.md`
- **Implementation Summary**: See `BETTING_INTEL_IMPLEMENTATION_SUMMARY.md`

---

**Need Help?** Check the API documentation or test endpoints with the curl statements provided.
