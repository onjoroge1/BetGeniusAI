"""
Delta-Logit Residual Trainer
Safe residual formulation with clipping and calibration
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime
import json
import argparse
from typing import Dict, List, Tuple, Optional
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression

class DeltaLogitResidualTrainer:
    """
    Safe residual trainer using delta-logit formulation:
    logit(p_hat) = logit(q_market) + lambda * clip(Delta, [-c, c])
    """
    
    def __init__(self, lambda_param: float = 0.7, clip_value: float = 1.0, 
                 l2_reg: float = 0.001, lr: float = 0.05, epochs: int = 400):
        self.lambda_param = lambda_param
        self.clip_value = clip_value
        self.l2_reg = l2_reg
        self.lr = lr
        self.epochs = epochs
        
        self.W = None
        self.b = None
        self.scaler = None
        self.temperature = 1.0
        self.feature_names = None
        
    def softmax(self, logits: np.ndarray) -> np.ndarray:
        """Numerically stable softmax"""
        exp_logits = np.exp(logits - np.max(logits, axis=1, keepdims=True))
        return exp_logits / np.sum(exp_logits, axis=1, keepdims=True)
    
    def market_to_logits(self, market_probs: np.ndarray) -> np.ndarray:
        """Convert market probabilities to logits with clipping"""
        clipped_probs = np.clip(market_probs, 0.02, 0.98)
        
        # For multiclass, use log-odds relative to last class
        logits = np.zeros_like(clipped_probs)
        for i in range(clipped_probs.shape[1] - 1):
            logits[:, i] = np.log(clipped_probs[:, i] / clipped_probs[:, -1])
        # Last class logit is 0 (reference)
        
        return logits
    
    def logits_to_probs(self, logits: np.ndarray) -> np.ndarray:
        """Convert logits to probabilities"""
        return self.softmax(logits)
    
    def compute_delta_logits(self, X: np.ndarray) -> np.ndarray:
        """Compute delta logits from features"""
        if self.W is None or self.b is None:
            raise ValueError("Model not trained")
        
        # Linear combination
        delta = X @ self.W + self.b
        
        # Clip to prevent extreme corrections
        delta_clipped = np.clip(delta, -self.clip_value, self.clip_value)
        
        return delta_clipped
    
    def forward(self, X: np.ndarray, market_probs: np.ndarray) -> np.ndarray:
        """Forward pass: market + clipped residuals"""
        # Convert market probs to logits
        market_logits = self.market_to_logits(market_probs)
        
        # Compute delta logits
        delta_logits = self.compute_delta_logits(X)
        
        # Combine with scaling
        final_logits = market_logits + self.lambda_param * delta_logits
        
        # Convert back to probabilities
        final_probs = self.logits_to_probs(final_logits)
        
        return final_probs
    
    def compute_loss(self, y_pred: np.ndarray, y_true: np.ndarray, W: np.ndarray) -> float:
        """Compute negative log-likelihood with L2 regularization"""
        # Clip predictions for numerical stability
        y_pred_clipped = np.clip(y_pred, 1e-15, 1 - 1e-15)
        
        # Cross-entropy loss
        ce_loss = -np.mean(np.sum(y_true * np.log(y_pred_clipped), axis=1))
        
        # L2 regularization
        l2_penalty = self.l2_reg * np.sum(W ** 2)
        
        return ce_loss + l2_penalty
    
    def compute_gradients(self, X: np.ndarray, market_probs: np.ndarray, 
                         y_true: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Compute gradients for W and b"""
        batch_size = X.shape[0]
        
        # Forward pass
        y_pred = self.forward(X, market_probs)
        
        # Compute delta logits for gradient calculation
        market_logits = self.market_to_logits(market_probs)
        delta_logits = self.compute_delta_logits(X)
        
        # Gradient of loss w.r.t. final logits
        grad_logits = y_pred - y_true
        
        # Chain rule: gradient w.r.t. delta logits
        grad_delta = self.lambda_param * grad_logits
        
        # Apply clipping gradient (derivative of clip function)
        delta_raw = X @ self.W + self.b
        clip_mask = (delta_raw >= -self.clip_value) & (delta_raw <= self.clip_value)
        grad_delta = grad_delta * clip_mask
        
        # Gradients w.r.t. W and b
        grad_W = (X.T @ grad_delta) / batch_size + 2 * self.l2_reg * self.W
        grad_b = np.mean(grad_delta, axis=0)
        
        return grad_W, grad_b
    
    def fit(self, X: np.ndarray, market_probs: np.ndarray, y: np.ndarray, 
            X_val: Optional[np.ndarray] = None, market_probs_val: Optional[np.ndarray] = None,
            y_val: Optional[np.ndarray] = None, verbose: bool = True) -> Dict:
        """Train the residual model"""
        
        # Scale features
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)
        X_val_scaled = self.scaler.transform(X_val) if X_val is not None else None
        
        # Initialize parameters
        n_features = X_scaled.shape[1]
        n_classes = market_probs.shape[1]
        
        # Initialize W and b (small random values)
        self.W = np.random.normal(0, 0.01, (n_features, n_classes))
        self.b = np.zeros(n_classes)
        
        # Convert labels to one-hot if needed
        if len(y.shape) == 1:
            y_onehot = np.zeros((len(y), n_classes))
            y_onehot[np.arange(len(y)), y] = 1
        else:
            y_onehot = y
        
        if y_val is not None and len(y_val.shape) == 1:
            y_val_onehot = np.zeros((len(y_val), n_classes))
            y_val_onehot[np.arange(len(y_val)), y_val] = 1
        else:
            y_val_onehot = y_val
        
        # Training history
        history = {'train_loss': [], 'val_loss': [], 'val_metrics': []}
        
        # Mini-batch gradient descent
        for epoch in range(self.epochs):
            # Forward pass
            y_pred = self.forward(X_scaled, market_probs)
            
            # Compute loss
            train_loss = self.compute_loss(y_pred, y_onehot, self.W)
            history['train_loss'].append(train_loss)
            
            # Compute gradients
            grad_W, grad_b = self.compute_gradients(X_scaled, market_probs, y_onehot)
            
            # Update parameters
            self.W -= self.lr * grad_W
            self.b -= self.lr * grad_b
            
            # Validation metrics
            if X_val is not None and epoch % 50 == 0:
                val_pred = self.forward(X_val_scaled, market_probs_val)
                val_loss = self.compute_loss(val_pred, y_val_onehot, self.W)
                history['val_loss'].append(val_loss)
                
                val_metrics = self.compute_metrics(val_pred, y_val_onehot, market_probs_val)
                history['val_metrics'].append(val_metrics)
                
                if verbose and epoch % 100 == 0:
                    print(f"Epoch {epoch}: Train Loss={train_loss:.4f}, Val Loss={val_loss:.4f}, "
                          f"Val LogLoss={val_metrics['logloss']:.4f}")
        
        return history
    
    def predict(self, X: np.ndarray, market_probs: np.ndarray) -> np.ndarray:
        """Make predictions"""
        X_scaled = self.scaler.transform(X)
        return self.forward(X_scaled, market_probs)
    
    def calibrate_temperature(self, X: np.ndarray, market_probs: np.ndarray, 
                            y_true: np.ndarray) -> float:
        """Apply temperature scaling for calibration"""
        # Get uncalibrated predictions
        uncalibrated_probs = self.predict(X, market_probs)
        
        # Convert to logits
        uncalibrated_logits = self.market_to_logits(uncalibrated_probs)
        
        # Find optimal temperature
        temperatures = np.logspace(-2, 1, 50)  # 0.01 to 10
        best_temp = 1.0
        best_loss = float('inf')
        
        y_true_labels = np.argmax(y_true, axis=1) if len(y_true.shape) > 1 else y_true
        
        for temp in temperatures:
            calibrated_logits = uncalibrated_logits / temp
            calibrated_probs = self.logits_to_probs(calibrated_logits)
            
            # Compute log loss
            calibrated_probs_clipped = np.clip(calibrated_probs, 1e-15, 1 - 1e-15)
            if len(y_true.shape) > 1:
                loss = -np.mean(np.sum(y_true * np.log(calibrated_probs_clipped), axis=1))
            else:
                loss = -np.mean(np.log(calibrated_probs_clipped[np.arange(len(y_true_labels)), y_true_labels]))
            
            if loss < best_loss:
                best_loss = loss
                best_temp = temp
        
        self.temperature = best_temp
        return best_temp
    
    def predict_calibrated(self, X: np.ndarray, market_probs: np.ndarray) -> np.ndarray:
        """Make calibrated predictions"""
        uncalibrated_probs = self.predict(X, market_probs)
        
        if self.temperature != 1.0:
            uncalibrated_logits = self.market_to_logits(uncalibrated_probs)
            calibrated_logits = uncalibrated_logits / self.temperature
            return self.logits_to_probs(calibrated_logits)
        
        return uncalibrated_probs
    
    def compute_metrics(self, y_pred: np.ndarray, y_true: np.ndarray, 
                       market_probs: np.ndarray) -> Dict:
        """Compute comprehensive metrics"""
        # Handle different y_true formats
        if len(y_true.shape) == 1:
            y_true_labels = y_true
            y_true_onehot = np.zeros((len(y_true), y_pred.shape[1]))
            y_true_onehot[np.arange(len(y_true)), y_true] = 1
        else:
            y_true_onehot = y_true
            y_true_labels = np.argmax(y_true, axis=1)
        
        y_pred_clipped = np.clip(y_pred, 1e-15, 1 - 1e-15)
        market_probs_clipped = np.clip(market_probs, 1e-15, 1 - 1e-15)
        
        # LogLoss
        model_logloss = -np.mean(np.sum(y_true_onehot * np.log(y_pred_clipped), axis=1))
        market_logloss = -np.mean(np.sum(y_true_onehot * np.log(market_probs_clipped), axis=1))
        
        # Brier Score
        model_brier = np.mean(np.sum((y_pred - y_true_onehot) ** 2, axis=1))
        market_brier = np.mean(np.sum((market_probs - y_true_onehot) ** 2, axis=1))
        
        # Accuracy
        model_accuracy = np.mean(np.argmax(y_pred, axis=1) == y_true_labels)
        market_accuracy = np.mean(np.argmax(market_probs, axis=1) == y_true_labels)
        
        # Top-2 accuracy
        model_top2 = np.mean([y_true_labels[i] in np.argsort(y_pred[i])[-2:] for i in range(len(y_true_labels))])
        market_top2 = np.mean([y_true_labels[i] in np.argsort(market_probs[i])[-2:] for i in range(len(y_true_labels))])
        
        # Mean predicted probability of true outcome
        model_p_true = np.mean([y_pred[i, y_true_labels[i]] for i in range(len(y_true_labels))])
        market_p_true = np.mean([market_probs[i, y_true_labels[i]] for i in range(len(y_true_labels))])
        
        return {
            'model_logloss': model_logloss,
            'market_logloss': market_logloss,
            'logloss_improvement': market_logloss - model_logloss,
            'model_brier': model_brier,
            'market_brier': market_brier,
            'brier_improvement': market_brier - model_brier,
            'model_accuracy': model_accuracy,
            'market_accuracy': market_accuracy,
            'model_top2': model_top2,
            'market_top2': market_top2,
            'model_p_true': model_p_true,
            'market_p_true': market_p_true
        }
    
    def save_artifacts(self, outdir: str, feature_names: List[str], timestamp: str):
        """Save model artifacts"""
        os.makedirs(outdir, exist_ok=True)
        
        # Save model parameters
        np.save(os.path.join(outdir, f'W_{timestamp}.npy'), self.W)
        np.save(os.path.join(outdir, f'b_{timestamp}.npy'), self.b)
        np.save(os.path.join(outdir, f'feat_cols_{timestamp}.npy'), feature_names)
        
        # Save configuration
        config = {
            'lambda_param': self.lambda_param,
            'clip_value': self.clip_value,
            'l2_reg': self.l2_reg,
            'temperature': self.temperature,
            'feature_names': feature_names,
            'timestamp': timestamp
        }
        
        with open(os.path.join(outdir, f'config_{timestamp}.json'), 'w') as f:
            json.dump(config, f, indent=2)

def load_or_generate_data(data_path: Optional[str] = None) -> pd.DataFrame:
    """Load data or generate synthetic dataset for testing"""
    
    if data_path and os.path.exists(data_path):
        print(f"Loading data from {data_path}")
        return pd.read_csv(data_path)
    else:
        print("Generating synthetic dataset for testing...")
        np.random.seed(42)
        
        n_samples = 1000
        
        # Generate synthetic market probabilities
        # Simulate realistic football match probabilities
        home_strength = np.random.normal(0, 0.5, n_samples)
        away_strength = np.random.normal(0, 0.5, n_samples)
        
        # Market probabilities (before normalization)
        raw_h = np.exp(home_strength) * np.random.uniform(0.8, 1.2, n_samples)
        raw_d = np.random.uniform(0.2, 0.4, n_samples)
        raw_a = np.exp(away_strength) * np.random.uniform(0.8, 1.2, n_samples)
        
        # Normalize to probabilities
        total = raw_h + raw_d + raw_a
        pH_mkt = raw_h / total
        pD_mkt = raw_d / total
        pA_mkt = raw_a / total
        
        # Generate features
        feat_elo_diff = home_strength - away_strength + np.random.normal(0, 0.1, n_samples)
        feat_form_diff = np.random.normal(0, 0.3, n_samples)
        feat_rest_diff = np.random.randint(-3, 4, n_samples)
        feat_home_advantage = np.random.uniform(0.1, 0.3, n_samples)
        
        # Dispersion features
        dispH = np.random.exponential(0.01, n_samples)
        dispD = np.random.exponential(0.008, n_samples)
        dispA = np.random.exponential(0.012, n_samples)
        n_books = np.random.choice([3, 4, 5, 6], n_samples, p=[0.1, 0.3, 0.4, 0.2])
        
        # Generate outcomes (with some correlation to features)
        outcome_logits = np.column_stack([
            home_strength + feat_elo_diff * 0.3 + np.random.normal(0, 0.5, n_samples),
            np.random.normal(-0.5, 0.3, n_samples),
            away_strength - feat_elo_diff * 0.3 + np.random.normal(0, 0.5, n_samples)
        ])
        
        outcome_probs = np.exp(outcome_logits) / np.sum(np.exp(outcome_logits), axis=1, keepdims=True)
        y = np.array([np.random.choice(3, p=probs) for probs in outcome_probs])
        
        # Create DataFrame
        data = pd.DataFrame({
            'y': y,
            'pH_mkt': pH_mkt,
            'pD_mkt': pD_mkt,
            'pA_mkt': pA_mkt,
            'feat_elo_diff': feat_elo_diff,
            'feat_form_diff': feat_form_diff,
            'feat_rest_diff': feat_rest_diff,
            'feat_home_advantage': feat_home_advantage,
            'dispH': dispH,
            'dispD': dispD,
            'dispA': dispA,
            'n_books': n_books
        })
        
        return data

def main():
    parser = argparse.ArgumentParser(description='Delta-Logit Residual Trainer')
    parser.add_argument('--data', type=str, help='Path to training data CSV')
    parser.add_argument('--val_ratio', type=float, default=0.2, help='Validation split ratio')
    parser.add_argument('--lambda', type=float, default=0.7, dest='lambda_param', help='Lambda scaling parameter')
    parser.add_argument('--clip', type=float, default=1.0, help='Clipping value for delta logits')
    parser.add_argument('--l2', type=float, default=0.001, help='L2 regularization')
    parser.add_argument('--lr', type=float, default=0.05, help='Learning rate')
    parser.add_argument('--epochs', type=int, default=400, help='Number of training epochs')
    parser.add_argument('--calibrate', action='store_true', help='Apply temperature scaling')
    parser.add_argument('--outdir', type=str, default='./residual_artifacts', help='Output directory')
    
    args = parser.parse_args()
    
    print("DELTA-LOGIT RESIDUAL TRAINER")
    print("=" * 40)
    print(f"Lambda: {args.lambda_param}, Clip: {args.clip}, L2: {args.l2}")
    print(f"Learning rate: {args.lr}, Epochs: {args.epochs}")
    
    # Load data
    df = load_or_generate_data(args.data)
    print(f"Loaded dataset with {len(df)} samples")
    
    # Extract features and targets
    market_cols = ['pH_mkt', 'pD_mkt', 'pA_mkt']
    feature_cols = [col for col in df.columns if col.startswith('feat_')] + \
                   [col for col in ['dispH', 'dispD', 'dispA', 'n_books'] if col in df.columns]
    
    print(f"Using {len(feature_cols)} features: {feature_cols}")
    
    X = df[feature_cols].values
    market_probs = df[market_cols].values
    y = df['y'].values
    
    # Train/validation split
    X_train, X_val, market_train, market_val, y_train, y_val = train_test_split(
        X, market_probs, y, test_size=args.val_ratio, random_state=42, stratify=y
    )
    
    print(f"Training set: {len(X_train)}, Validation set: {len(X_val)}")
    
    # Initialize and train model
    trainer = DeltaLogitResidualTrainer(
        lambda_param=args.lambda_param,
        clip_value=args.clip,
        l2_reg=args.l2,
        lr=args.lr,
        epochs=args.epochs
    )
    
    print("\nTraining residual model...")
    history = trainer.fit(X_train, market_train, y_train, X_val, market_val, y_val)
    
    # Compute final metrics
    final_pred = trainer.predict(X_val, market_val)
    final_metrics = trainer.compute_metrics(final_pred, y_val, market_val)
    
    print(f"\nFinal Validation Metrics:")
    print(f"Model LogLoss: {final_metrics['model_logloss']:.4f}")
    print(f"Market LogLoss: {final_metrics['market_logloss']:.4f}")
    print(f"LogLoss Improvement: {final_metrics['logloss_improvement']:.4f}")
    print(f"Model Brier: {final_metrics['model_brier']:.4f}")
    print(f"Brier Improvement: {final_metrics['brier_improvement']:.4f}")
    print(f"Model Accuracy: {final_metrics['model_accuracy']:.3f}")
    print(f"Model Top-2: {final_metrics['model_top2']:.3f}")
    
    # Apply calibration if requested
    if args.calibrate:
        print("\nApplying temperature calibration...")
        temperature = trainer.calibrate_temperature(X_val, market_val, y_val)
        print(f"Optimal temperature: {temperature:.3f}")
        
        # Recompute metrics with calibration
        calibrated_pred = trainer.predict_calibrated(X_val, market_val)
        calibrated_metrics = trainer.compute_metrics(calibrated_pred, y_val, market_val)
        
        print(f"Calibrated LogLoss: {calibrated_metrics['model_logloss']:.4f}")
        print(f"Calibrated Improvement: {calibrated_metrics['logloss_improvement']:.4f}")
        
        final_metrics['calibrated_logloss'] = calibrated_metrics['model_logloss']
        final_metrics['calibrated_improvement'] = calibrated_metrics['logloss_improvement']
        final_metrics['temperature'] = temperature
    
    # Save artifacts
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    trainer.save_artifacts(args.outdir, feature_cols, timestamp)
    
    # Save metrics
    metrics_path = os.path.join(args.outdir, f'metrics_{timestamp}.json')
    with open(metrics_path, 'w') as f:
        json.dump(final_metrics, f, indent=2, default=str)
    
    print(f"\nArtifacts saved to {args.outdir}")
    print(f"Metrics saved to {metrics_path}")
    
    return final_metrics

if __name__ == "__main__":
    main()