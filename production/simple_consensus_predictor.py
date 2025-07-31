
class SimpleWeightedConsensusPredictor:
    """Production-ready simple weighted consensus predictor"""
    
    def __init__(self):
        # Quality weights from 31-year bookmaker analysis
        self.weights = {
            'pinnacle': 0.35,
            'bet365': 0.25, 
            'betway': 0.22,
            'william_hill': 0.18
        }
    
    def predict_match(self, bookmaker_odds):
        """
        Predict match outcome using weighted consensus
        
        Args:
            bookmaker_odds: dict with format:
                {
                    'pinnacle': {'home': 2.10, 'draw': 3.40, 'away': 3.20},
                    'bet365': {'home': 2.05, 'draw': 3.30, 'away': 3.15},
                    # ... other bookmakers
                }
        
        Returns:
            {
                'probabilities': {'home': 0.45, 'draw': 0.30, 'away': 0.25},
                'confidence': 0.85,
                'prediction': 'home',
                'quality_score': 0.92
            }
        """
        
        # Convert odds to probabilities for each bookmaker
        book_probs = {}
        total_weight = 0
        
        for book, odds in bookmaker_odds.items():
            if book.lower().replace(' ', '_') in self.weights:
                # Convert decimal odds to probabilities
                prob_home = 1.0 / odds['home']
                prob_draw = 1.0 / odds['draw'] 
                prob_away = 1.0 / odds['away']
                
                # Normalize probabilities
                total_prob = prob_home + prob_draw + prob_away
                prob_home /= total_prob
                prob_draw /= total_prob
                prob_away /= total_prob
                
                weight = self.weights[book.lower().replace(' ', '_')]
                book_probs[book] = {
                    'home': prob_home,
                    'draw': prob_draw, 
                    'away': prob_away,
                    'weight': weight
                }
                total_weight += weight
        
        if not book_probs:
            return None
            
        # Compute weighted average probabilities
        weighted_home = sum(bp['home'] * bp['weight'] for bp in book_probs.values()) / total_weight
        weighted_draw = sum(bp['draw'] * bp['weight'] for bp in book_probs.values()) / total_weight  
        weighted_away = sum(bp['away'] * bp['weight'] for bp in book_probs.values()) / total_weight
        
        # Normalize final probabilities
        total_final = weighted_home + weighted_draw + weighted_away
        final_probs = {
            'home': weighted_home / total_final,
            'draw': weighted_draw / total_final,
            'away': weighted_away / total_final
        }
        
        # Determine prediction and confidence
        max_prob = max(final_probs.values())
        prediction = max(final_probs, key=final_probs.get)
        
        # Confidence based on max probability and market consensus
        confidence = min(max_prob * 1.2, 1.0)
        
        # Quality score based on bookmaker coverage
        quality_score = total_weight / sum(self.weights.values())
        
        return {
            'probabilities': final_probs,
            'confidence': confidence,
            'prediction': prediction,
            'quality_score': quality_score,
            'bookmaker_count': len(book_probs),
            'total_weight': total_weight
        }
