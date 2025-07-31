"""
Deep Learning Prototype for Football Prediction
Prototype implementation of neural network approaches
"""

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import json
from typing import Dict, List, Tuple, Any

class FootballMatchDataset(Dataset):
    """Custom dataset for football match data"""
    
    def __init__(self, features: np.ndarray, targets: np.ndarray):
        self.features = torch.FloatTensor(features)
        self.targets = torch.FloatTensor(targets)
    
    def __len__(self):
        return len(self.features)
    
    def __getitem__(self, idx):
        return self.features[idx], self.targets[idx]

class AttentionFootballNet(nn.Module):
    """Neural network with attention mechanism for football prediction"""
    
    def __init__(self, input_dim: int, hidden_dims: List[int] = [256, 128, 64], 
                 attention_dim: int = 64, dropout_rate: float = 0.3):
        super(AttentionFootballNet, self).__init__()
        
        # Feature embedding layers
        layers = []
        prev_dim = input_dim
        
        for hidden_dim in hidden_dims:
            layers.extend([
                nn.Linear(prev_dim, hidden_dim),
                nn.BatchNorm1d(hidden_dim),
                nn.ReLU(),
                nn.Dropout(dropout_rate)
            ])
            prev_dim = hidden_dim
        
        self.feature_layers = nn.Sequential(*layers)
        
        # Attention mechanism
        self.attention = nn.MultiheadAttention(
            embed_dim=prev_dim,
            num_heads=8,
            dropout=dropout_rate,
            batch_first=True
        )
        
        # Output layers
        self.output_layers = nn.Sequential(
            nn.Linear(prev_dim, 32),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(32, 3),  # Home, Draw, Away
            nn.Softmax(dim=1)
        )
        
        # Uncertainty estimation
        self.uncertainty_head = nn.Sequential(
            nn.Linear(prev_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid()
        )
    
    def forward(self, x):
        # Feature extraction
        features = self.feature_layers(x)
        
        # Reshape for attention (batch, seq_len=1, features)
        features_reshaped = features.unsqueeze(1)
        
        # Self-attention
        attended_features, attention_weights = self.attention(
            features_reshaped, features_reshaped, features_reshaped
        )
        
        # Squeeze back to (batch, features)
        attended_features = attended_features.squeeze(1)
        
        # Predictions
        probabilities = self.output_layers(attended_features)
        uncertainty = self.uncertainty_head(attended_features)
        
        return probabilities, uncertainty, attention_weights

class LSTMFootballNet(nn.Module):
    """LSTM network for sequence-based football prediction"""
    
    def __init__(self, input_dim: int, hidden_dim: int = 128, 
                 num_layers: int = 2, dropout_rate: float = 0.3):
        super(LSTMFootballNet, self).__init__()
        
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        
        # LSTM layers
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            dropout=dropout_rate,
            batch_first=True,
            bidirectional=True
        )
        
        # Output layers
        self.output_layers = nn.Sequential(
            nn.Linear(hidden_dim * 2, 64),  # *2 for bidirectional
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(dropout_rate),
            nn.Linear(32, 3),
            nn.Softmax(dim=1)
        )
    
    def forward(self, x):
        # LSTM expects (batch, seq_len, features)
        # For single match, seq_len = 1
        if len(x.shape) == 2:
            x = x.unsqueeze(1)
        
        lstm_out, (hidden, cell) = self.lstm(x)
        
        # Take the last output
        last_output = lstm_out[:, -1, :]
        
        # Predictions
        probabilities = self.output_layers(last_output)
        
        return probabilities

class EnsembleFootballNet(nn.Module):
    """Ensemble of different neural network architectures"""
    
    def __init__(self, input_dim: int):
        super(EnsembleFootballNet, self).__init__()
        
        # Different network architectures
        self.attention_net = AttentionFootballNet(input_dim)
        self.lstm_net = LSTMFootballNet(input_dim)
        
        # Simple feedforward network
        self.feedforward_net = nn.Sequential(
            nn.Linear(input_dim, 256),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, 3),
            nn.Softmax(dim=1)
        )
        
        # Ensemble weights
        self.ensemble_weights = nn.Parameter(torch.ones(3) / 3)
    
    def forward(self, x):
        # Get predictions from each network
        att_probs, uncertainty, attention_weights = self.attention_net(x)
        lstm_probs = self.lstm_net(x)
        ff_probs = self.feedforward_net(x)
        
        # Weighted ensemble
        weights = torch.softmax(self.ensemble_weights, dim=0)
        ensemble_probs = (weights[0] * att_probs + 
                         weights[1] * lstm_probs + 
                         weights[2] * ff_probs)
        
        return ensemble_probs, uncertainty, {
            'attention_weights': attention_weights,
            'ensemble_weights': weights,
            'individual_predictions': {
                'attention': att_probs,
                'lstm': lstm_probs,
                'feedforward': ff_probs
            }
        }

class DeepLearningPrototype:
    """Prototype implementation of deep learning approaches"""
    
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.scaler = StandardScaler()
        print(f"Using device: {self.device}")
    
    def generate_synthetic_data(self, n_samples: int = 5000, n_features: int = 50) -> Tuple[np.ndarray, np.ndarray]:
        """Generate synthetic football data for prototyping"""
        
        np.random.seed(42)
        
        # Generate realistic football features
        features = np.random.randn(n_samples, n_features)
        
        # Add some realistic patterns
        # Home advantage
        features[:, 0] = np.random.normal(0.3, 0.2, n_samples)  # Home team strength bonus
        
        # Team quality difference
        features[:, 1] = np.random.normal(0, 0.5, n_samples)   # Quality difference
        
        # Recent form
        features[:, 2:7] = np.random.beta(2, 2, (n_samples, 5))  # Recent match results
        
        # Injury count
        features[:, 7] = np.random.poisson(1.5, n_samples)      # Home team injuries
        features[:, 8] = np.random.poisson(1.5, n_samples)      # Away team injuries
        
        # Generate target probabilities with realistic patterns
        home_bias = 0.1 + features[:, 0] * 0.3  # Home advantage effect
        quality_effect = features[:, 1] * 0.2   # Quality difference effect
        form_effect = (features[:, 2:7].mean(axis=1) - 0.5) * 0.15  # Form effect
        injury_effect = -(features[:, 7] - features[:, 8]) * 0.02   # Injury effect
        
        # Base probabilities
        home_prob = 0.45 + home_bias + quality_effect + form_effect + injury_effect
        away_prob = 0.30 - home_bias - quality_effect - form_effect - injury_effect
        draw_prob = 0.25 + np.random.normal(0, 0.05, n_samples)
        
        # Normalize probabilities
        total_prob = home_prob + draw_prob + away_prob
        targets = np.column_stack([
            home_prob / total_prob,
            draw_prob / total_prob,
            away_prob / total_prob
        ])
        
        # Ensure probabilities are valid
        targets = np.clip(targets, 0.05, 0.9)
        targets = targets / targets.sum(axis=1, keepdims=True)
        
        return features, targets
    
    def train_model(self, model: nn.Module, train_loader: DataLoader, 
                   val_loader: DataLoader, num_epochs: int = 100) -> Dict[str, List[float]]:
        """Train a neural network model"""
        
        model = model.to(self.device)
        optimizer = optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-5)
        scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
        criterion = nn.KLDivLoss(reduction='batchmean')  # Good for probability distributions
        
        train_losses = []
        val_losses = []
        
        for epoch in range(num_epochs):
            # Training
            model.train()
            train_loss = 0.0
            for features, targets in train_loader:
                features, targets = features.to(self.device), targets.to(self.device)
                
                optimizer.zero_grad()
                
                if isinstance(model, EnsembleFootballNet):
                    outputs, uncertainty, metadata = model(features)
                    loss = criterion(torch.log(outputs), targets)
                    # Add uncertainty regularization
                    uncertainty_loss = torch.mean(uncertainty)
                    loss = loss + 0.01 * uncertainty_loss
                elif isinstance(model, AttentionFootballNet):
                    outputs, uncertainty, attention_weights = model(features)
                    loss = criterion(torch.log(outputs), targets)
                    uncertainty_loss = torch.mean(uncertainty)
                    loss = loss + 0.01 * uncertainty_loss
                else:
                    outputs = model(features)
                    loss = criterion(torch.log(outputs), targets)
                
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                optimizer.step()
                
                train_loss += loss.item()
            
            # Validation
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for features, targets in val_loader:
                    features, targets = features.to(self.device), targets.to(self.device)
                    
                    if isinstance(model, EnsembleFootballNet):
                        outputs, _, _ = model(features)
                    elif isinstance(model, AttentionFootballNet):
                        outputs, _, _ = model(features)
                    else:
                        outputs = model(features)
                    
                    loss = criterion(torch.log(outputs), targets)
                    val_loss += loss.item()
            
            avg_train_loss = train_loss / len(train_loader)
            avg_val_loss = val_loss / len(val_loader)
            
            train_losses.append(avg_train_loss)
            val_losses.append(avg_val_loss)
            
            scheduler.step(avg_val_loss)
            
            if epoch % 20 == 0:
                print(f"Epoch {epoch}: Train Loss: {avg_train_loss:.4f}, Val Loss: {avg_val_loss:.4f}")
        
        return {'train_losses': train_losses, 'val_losses': val_losses}
    
    def evaluate_model(self, model: nn.Module, test_loader: DataLoader) -> Dict[str, float]:
        """Evaluate model performance"""
        
        model.eval()
        all_predictions = []
        all_targets = []
        
        with torch.no_grad():
            for features, targets in test_loader:
                features, targets = features.to(self.device), targets.to(self.device)
                
                if isinstance(model, EnsembleFootballNet):
                    outputs, _, _ = model(features)
                elif isinstance(model, AttentionFootballNet):
                    outputs, _, _ = model(features)
                else:
                    outputs = model(features)
                
                all_predictions.append(outputs.cpu().numpy())
                all_targets.append(targets.cpu().numpy())
        
        predictions = np.vstack(all_predictions)
        targets = np.vstack(all_targets)
        
        # Calculate metrics
        logloss = -np.mean(np.sum(targets * np.log(np.clip(predictions, 1e-15, 1-1e-15)), axis=1))
        brier_score = np.mean(np.sum((predictions - targets)**2, axis=1))
        
        # Accuracy (highest probability prediction)
        pred_classes = np.argmax(predictions, axis=1)
        true_classes = np.argmax(targets, axis=1)
        accuracy = np.mean(pred_classes == true_classes)
        
        return {
            'logloss': logloss,
            'brier_score': brier_score,
            'accuracy': accuracy
        }
    
    def run_prototype_experiment(self) -> Dict[str, Any]:
        """Run complete prototype experiment"""
        
        print("DEEP LEARNING PROTOTYPE EXPERIMENT")
        print("=" * 40)
        
        # Generate data
        print("Generating synthetic data...")
        features, targets = self.generate_synthetic_data(n_samples=5000, n_features=50)
        
        # Normalize features
        features = self.scaler.fit_transform(features)
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            features, targets, test_size=0.2, random_state=42
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_train, y_train, test_size=0.2, random_state=42
        )
        
        # Create datasets
        train_dataset = FootballMatchDataset(X_train, y_train)
        val_dataset = FootballMatchDataset(X_val, y_val)
        test_dataset = FootballMatchDataset(X_test, y_test)
        
        # Create data loaders
        train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=64, shuffle=False)
        test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)
        
        # Initialize models
        input_dim = features.shape[1]
        models = {
            'attention_net': AttentionFootballNet(input_dim),
            'lstm_net': LSTMFootballNet(input_dim),
            'ensemble_net': EnsembleFootballNet(input_dim)
        }
        
        results = {}
        
        # Train and evaluate each model
        for model_name, model in models.items():
            print(f"\nTraining {model_name}...")
            
            # Train model
            training_history = self.train_model(model, train_loader, val_loader, num_epochs=100)
            
            # Evaluate model
            test_metrics = self.evaluate_model(model, test_loader)
            
            results[model_name] = {
                'training_history': training_history,
                'test_metrics': test_metrics
            }
            
            print(f"{model_name} Results:")
            print(f"  LogLoss: {test_metrics['logloss']:.6f}")
            print(f"  Accuracy: {test_metrics['accuracy']:.3f}")
            print(f"  Brier Score: {test_metrics['brier_score']:.6f}")
        
        # Compare with baseline
        baseline_metrics = {
            'simple_consensus': {
                'logloss': 0.963475,
                'accuracy': 0.543,
                'brier_score': 0.572791
            }
        }
        
        results['baseline'] = baseline_metrics
        
        return results

def main():
    """Run the deep learning prototype"""
    
    prototype = DeepLearningPrototype()
    results = prototype.run_prototype_experiment()
    
    print("\n" + "=" * 60)
    print("PROTOTYPE RESULTS SUMMARY")
    print("=" * 60)
    
    # Compare all models
    for model_name, model_results in results.items():
        if model_name == 'baseline':
            print(f"\nBASELINE - Simple Consensus:")
            metrics = model_results['simple_consensus']
        else:
            print(f"\n{model_name.upper()}:")
            metrics = model_results['test_metrics']
        
        print(f"  LogLoss: {metrics['logloss']:.6f}")
        print(f"  Accuracy: {metrics['accuracy']:.1%}")
        print(f"  Brier Score: {metrics['brier_score']:.6f}")
    
    # Save results
    with open('deep_learning_prototype_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n📄 Results saved: deep_learning_prototype_results.json")
    
    return results

if __name__ == "__main__":
    main()