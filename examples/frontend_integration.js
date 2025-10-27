/**
 * Frontend Integration Examples for BetGenius AI V2
 * 
 * This file demonstrates how to integrate /predict-v2 endpoint
 * into a React/JavaScript frontend application
 */

// ============================================
// 1. API Service Layer (Recommended Pattern)
// ============================================

class BetGeniusAPI {
  constructor(apiKey, baseUrl = 'http://localhost:8000') {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl;
  }

  /**
   * Fetch upcoming matches with V1 and V2 predictions
   * @returns {Promise<Array>} Array of match objects with predictions
   */
  async getMarket() {
    try {
      const response = await fetch(`${this.baseUrl}/market`, {
        method: 'GET',
        headers: {
          'X-API-Key': this.apiKey,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to fetch market:', error);
      throw error;
    }
  }

  /**
   * Get V2 SELECT prediction for a specific match (Premium)
   * @param {number} matchId - The match ID
   * @returns {Promise<Object>} V2 prediction object
   */
  async getPredictionV2(matchId) {
    try {
      const response = await fetch(
        `${this.baseUrl}/predict-v2?match_id=${matchId}`,
        {
          method: 'GET',
          headers: {
            'X-API-Key': this.apiKey,
            'Content-Type': 'application/json',
          },
        }
      );

      // Handle 404 (no V2 prediction available)
      if (response.status === 404) {
        return {
          available: false,
          reason: 'below_quality_threshold',
        };
      }

      // Handle 429 (rate limit)
      if (response.status === 429) {
        const data = await response.json();
        throw new Error(`Rate limit exceeded: ${data.error}`);
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      return {
        available: true,
        ...data,
      };
    } catch (error) {
      console.error('Failed to fetch V2 prediction:', error);
      throw error;
    }
  }

  /**
   * Get V1 prediction for a specific match (Free tier)
   * @param {number} matchId - The match ID
   * @returns {Promise<Object>} V1 prediction object
   */
  async getPredictionV1(matchId) {
    try {
      const response = await fetch(
        `${this.baseUrl}/predict?match_id=${matchId}`,
        {
          method: 'GET',
          headers: {
            'X-API-Key': this.apiKey,
            'Content-Type': 'application/json',
          },
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to fetch V1 prediction:', error);
      throw error;
    }
  }
}

// ============================================
// 2. React Component Examples
// ============================================

// Example 1: Match Card Component (V1 vs V2 Comparison)
function MatchCard({ match, api, isPremiumUser }) {
  const [v2Prediction, setV2Prediction] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);

  // Load V2 prediction on mount (if premium user)
  React.useEffect(() => {
    if (isPremiumUser && match.match_id) {
      loadV2Prediction();
    }
  }, [match.match_id, isPremiumUser]);

  const loadV2Prediction = async () => {
    setLoading(true);
    setError(null);

    try {
      const prediction = await api.getPredictionV2(match.match_id);
      setV2Prediction(prediction);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="match-card">
      {/* Match Header */}
      <div className="match-header">
        <div className="team">
          {match.home_team_logo && (
            <img src={match.home_team_logo} alt={match.home_team} />
          )}
          <span>{match.home_team}</span>
        </div>
        <div className="vs">vs</div>
        <div className="team">
          <span>{match.away_team}</span>
          {match.away_team_logo && (
            <img src={match.away_team_logo} alt={match.away_team} />
          )}
        </div>
      </div>

      {/* Kickoff Time */}
      <div className="kickoff">
        ⏰ {new Date(match.kickoff_at).toLocaleString()}
      </div>

      {/* V1 Prediction (Free - Always shown) */}
      {match.v1_prediction && (
        <div className="prediction v1">
          <div className="label">🥈 Consensus Prediction</div>
          <div className="outcome">
            {match.v1_prediction.predicted_outcome}
          </div>
          <div className="probabilities">
            <span>H: {(match.v1_prediction.home_prob * 100).toFixed(1)}%</span>
            <span>D: {(match.v1_prediction.draw_prob * 100).toFixed(1)}%</span>
            <span>A: {(match.v1_prediction.away_prob * 100).toFixed(1)}%</span>
          </div>
        </div>
      )}

      {/* V2 Prediction (Premium - Conditional) */}
      {isPremiumUser && (
        <div className="prediction v2">
          <div className="label">🥇 V2 SELECT (Premium)</div>

          {loading && <div className="loading">Loading V2...</div>}

          {error && <div className="error">Error: {error}</div>}

          {v2Prediction && v2Prediction.available && (
            <>
              <div className="outcome">
                {v2Prediction.prediction.predicted_outcome}
              </div>
              <div className="metrics">
                <div className="metric">
                  <span className="label">Confidence</span>
                  <span className="value confidence-badge">
                    {(v2Prediction.prediction.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="metric">
                  <span className="label">Expected Value</span>
                  <span className="value ev-badge">
                    {(v2Prediction.prediction.expected_value * 100).toFixed(2)}%
                  </span>
                </div>
              </div>
              <div className="probabilities">
                <span>
                  H: {(v2Prediction.prediction.probabilities.home * 100).toFixed(1)}%
                </span>
                <span>
                  D: {(v2Prediction.prediction.probabilities.draw * 100).toFixed(1)}%
                </span>
                <span>
                  A: {(v2Prediction.prediction.probabilities.away * 100).toFixed(1)}%
                </span>
              </div>

              {/* AI Analysis */}
              {v2Prediction.ai_analysis && (
                <div className="ai-analysis">
                  <div className="ai-label">🤖 AI Analysis</div>
                  <p>{v2Prediction.ai_analysis.summary}</p>
                </div>
              )}
            </>
          )}

          {v2Prediction && !v2Prediction.available && (
            <div className="unavailable">
              ⚠️ No V2 prediction available
              <br />
              <small>(Below quality threshold: Conf &lt; 62% or EV ≤ 0)</small>
            </div>
          )}
        </div>
      )}

      {/* Premium Upgrade CTA (for free users) */}
      {!isPremiumUser && (
        <div className="premium-cta">
          <div className="cta-badge">🔒 Premium Feature</div>
          <p>Unlock V2 SELECT predictions with 70% accuracy</p>
          <button className="upgrade-btn">Upgrade Now</button>
        </div>
      )}

      {/* Best Odds */}
      {match.best_odds && (
        <div className="best-odds">
          <div className="label">📊 Best Odds</div>
          <div className="odds-grid">
            <span>H: {match.best_odds.home?.toFixed(2)}</span>
            <span>D: {match.best_odds.draw?.toFixed(2)}</span>
            <span>A: {match.best_odds.away?.toFixed(2)}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// Example 2: Market Board Component (List of Matches)
function MarketBoard() {
  const [matches, setMatches] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  const api = new BetGeniusAPI('your_api_key_here');
  const isPremiumUser = true; // Check user subscription status

  React.useEffect(() => {
    loadMarket();
  }, []);

  const loadMarket = async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await api.getMarket();
      setMatches(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div className="loading">Loading matches...</div>;
  if (error) return <div className="error">Error: {error}</div>;

  return (
    <div className="market-board">
      <div className="header">
        <h1>⚽ Upcoming Matches</h1>
        <button onClick={loadMarket} className="refresh-btn">
          🔄 Refresh
        </button>
      </div>

      <div className="matches-grid">
        {matches.map((match) => (
          <MatchCard
            key={match.match_id}
            match={match}
            api={api}
            isPremiumUser={isPremiumUser}
          />
        ))}
      </div>

      {matches.length === 0 && (
        <div className="empty-state">No upcoming matches available</div>
      )}
    </div>
  );
}

// Example 3: Single Match Detail View
function MatchDetailView({ matchId }) {
  const [v1Data, setV1Data] = React.useState(null);
  const [v2Data, setV2Data] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  const api = new BetGeniusAPI('your_api_key_here');

  React.useEffect(() => {
    loadPredictions();
  }, [matchId]);

  const loadPredictions = async () => {
    setLoading(true);

    try {
      // Load both V1 and V2 in parallel
      const [v1, v2] = await Promise.all([
        api.getPredictionV1(matchId),
        api.getPredictionV2(matchId),
      ]);

      setV1Data(v1);
      setV2Data(v2);
    } catch (error) {
      console.error('Failed to load predictions:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) return <div>Loading predictions...</div>;

  return (
    <div className="match-detail">
      <h2>Match Analysis</h2>

      {/* V1 Section */}
      <div className="prediction-section">
        <h3>🥈 V1 Consensus Prediction</h3>
        {v1Data && (
          <div className="prediction-content">
            <div className="outcome-large">
              {v1Data.prediction.predicted_outcome}
            </div>
            <ProbabilityChart data={v1Data.prediction.probabilities} />
          </div>
        )}
      </div>

      {/* V2 Section */}
      <div className="prediction-section premium">
        <h3>🥇 V2 SELECT Prediction</h3>
        {v2Data && v2Data.available ? (
          <div className="prediction-content">
            <div className="outcome-large">
              {v2Data.prediction.predicted_outcome}
            </div>
            <div className="quality-metrics">
              <div className="metric-card">
                <div className="metric-value">
                  {(v2Data.prediction.confidence * 100).toFixed(1)}%
                </div>
                <div className="metric-label">Confidence</div>
              </div>
              <div className="metric-card">
                <div className="metric-value">
                  {(v2Data.prediction.expected_value * 100).toFixed(2)}%
                </div>
                <div className="metric-label">Expected Value</div>
              </div>
            </div>
            <ProbabilityChart data={v2Data.prediction.probabilities} />

            {/* AI Analysis */}
            {v2Data.ai_analysis && (
              <div className="ai-section">
                <h4>🤖 AI Analysis</h4>
                <div className="ai-content">
                  <p className="summary">{v2Data.ai_analysis.summary}</p>
                  <div className="insights">
                    {v2Data.ai_analysis.key_factors?.map((factor, i) => (
                      <div key={i} className="insight-item">
                        • {factor}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="unavailable-message">
            <p>⚠️ No V2 prediction meets quality criteria</p>
            <small>Confidence must be ≥62% and EV &gt; 0</small>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================
// 3. Helper Components
// ============================================

function ProbabilityChart({ data }) {
  const { home, draw, away } = data;

  return (
    <div className="probability-chart">
      <div className="bar-container">
        <div
          className="bar home"
          style={{ width: `${home * 100}%` }}
          title={`Home: ${(home * 100).toFixed(1)}%`}
        >
          <span className="bar-label">H: {(home * 100).toFixed(1)}%</span>
        </div>
      </div>
      <div className="bar-container">
        <div
          className="bar draw"
          style={{ width: `${draw * 100}%` }}
          title={`Draw: ${(draw * 100).toFixed(1)}%`}
        >
          <span className="bar-label">D: {(draw * 100).toFixed(1)}%</span>
        </div>
      </div>
      <div className="bar-container">
        <div
          className="bar away"
          style={{ width: `${away * 100}%` }}
          title={`Away: ${(away * 100).toFixed(1)}%`}
        >
          <span className="bar-label">A: {(away * 100).toFixed(1)}%</span>
        </div>
      </div>
    </div>
  );
}

// ============================================
// 4. Error Handling & Retry Logic
// ============================================

class APIClientWithRetry extends BetGeniusAPI {
  async fetchWithRetry(url, options, maxRetries = 3, delay = 1000) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        const response = await fetch(url, options);

        // Don't retry on client errors (4xx)
        if (response.status >= 400 && response.status < 500) {
          return response;
        }

        // Retry on server errors (5xx)
        if (response.status >= 500) {
          if (attempt === maxRetries) {
            throw new Error(`Server error after ${maxRetries} attempts`);
          }
          await this.sleep(delay * attempt); // Exponential backoff
          continue;
        }

        return response;
      } catch (error) {
        if (attempt === maxRetries) throw error;
        await this.sleep(delay * attempt);
      }
    }
  }

  sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

// ============================================
// 5. Example Usage
// ============================================

// Initialize API client
const api = new BetGeniusAPI('your_api_key_here');

// Example: Fetch market and display
async function example() {
  try {
    // Get all matches
    const matches = await api.getMarket();
    console.log(`Found ${matches.length} upcoming matches`);

    // Get V2 prediction for first match
    if (matches.length > 0) {
      const match = matches[0];
      const v2Prediction = await api.getPredictionV2(match.match_id);

      if (v2Prediction.available) {
        console.log('V2 Prediction:', v2Prediction.prediction);
      } else {
        console.log('V2 prediction not available for this match');
      }
    }
  } catch (error) {
    console.error('Error:', error);
  }
}

// Export for use in your app
export { BetGeniusAPI, APIClientWithRetry, MatchCard, MarketBoard, MatchDetailView };
