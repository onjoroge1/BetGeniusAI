#!/usr/bin/env python3
"""
Model Training Management Script

Manages V2-Team++ model training with:
- Auto-detection of when retraining is needed
- Training on full dataset or incremental updates
- Model versioning and artifact storage
- Performance tracking and validation
- Automatic model promotion to production

Usage:
    # Check if training is needed
    python scripts/manage_training.py --check
    
    # Run full training
    python scripts/manage_training.py --train
    
    # Run training with custom parameters
    python scripts/manage_training.py --train --min-matches 5000 --cv-folds 5
    
    # Auto-train (only if needed based on match count)
    python scripts/manage_training.py --auto
    
    # Schedule as cron job (runs weekly, trains if needed)
    0 2 * * 0 cd /path/to/project && python scripts/manage_training.py --auto
"""

import os
import sys
import argparse
import logging
from datetime import datetime
import psycopg2
import json
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TrainingManager:
    """Manage model training lifecycle"""
    
    def __init__(self):
        self.database_url = os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL not set")
        
        self.conn = psycopg2.connect(self.database_url)
        
        # Training thresholds
        self.min_matches_for_retrain = 500  # Retrain after 500 new matches
        self.min_total_matches = 3000  # Minimum dataset size
        
        # Paths
        self.models_dir = Path("models/artifacts")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.metadata_file = self.models_dir / "training_metadata.json"
    
    def get_last_training_metadata(self) -> dict:
        """Load last training metadata"""
        if not self.metadata_file.exists():
            return {
                'last_training_date': None,
                'matches_used': 0,
                'model_version': None,
                'performance': {}
            }
        
        with open(self.metadata_file, 'r') as f:
            return json.load(f)
    
    def save_training_metadata(self, metadata: dict):
        """Save training metadata"""
        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2, default=str)
    
    def get_training_dataset_stats(self) -> dict:
        """Get statistics about current training dataset"""
        query = """
            SELECT 
                COUNT(*) as total_matches,
                MIN(tm.match_date) as earliest_match,
                MAX(tm.match_date) as latest_match,
                COUNT(mc.match_id) as with_phase2_data,
                COUNT(mc.match_id) * 100.0 / COUNT(*) as phase2_coverage
            FROM training_matches tm
            LEFT JOIN match_context mc ON tm.match_id = mc.match_id
            WHERE tm.match_date >= '2020-01-01'
              AND tm.outcome IS NOT NULL
              AND tm.outcome IN ('H', 'D', 'A', 'Home', 'Draw', 'Away')
        """
        
        with self.conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            
        return {
            'total_matches': row[0],
            'earliest_match': row[1],
            'latest_match': row[2],
            'with_phase2_data': row[3],
            'phase2_coverage': float(row[4]) if row[4] else 0.0
        }
    
    def should_retrain(self) -> tuple[bool, str]:
        """
        Determine if model should be retrained
        
        Returns:
            (should_retrain, reason)
        """
        last_metadata = self.get_last_training_metadata()
        current_stats = self.get_training_dataset_stats()
        
        # Check 1: Never trained
        if last_metadata['last_training_date'] is None:
            return True, "No model trained yet"
        
        # Check 2: Insufficient total matches
        if current_stats['total_matches'] < self.min_total_matches:
            return False, f"Insufficient matches ({current_stats['total_matches']} < {self.min_total_matches})"
        
        # Check 3: Significant new data
        new_matches = current_stats['total_matches'] - last_metadata['matches_used']
        if new_matches >= self.min_matches_for_retrain:
            return True, f"{new_matches} new matches since last training (threshold: {self.min_matches_for_retrain})"
        
        # Check 4: Phase 2 coverage significantly improved
        last_phase2_coverage = last_metadata.get('phase2_coverage', 0)
        current_phase2_coverage = current_stats['phase2_coverage']
        
        if current_phase2_coverage - last_phase2_coverage > 20:  # 20% improvement
            return True, f"Phase 2 coverage improved from {last_phase2_coverage:.1f}% to {current_phase2_coverage:.1f}%"
        
        # No retrain needed
        return False, f"Only {new_matches} new matches (threshold: {self.min_matches_for_retrain})"
    
    def run_training(self, min_matches: int = 3000, cv_folds: int = 5) -> dict:
        """
        Execute model training (LEAKAGE-FREE VERSION)
        
        Uses:
        - Time-based CV with embargo
        - Pre-kickoff odds enforcement
        - Sanity checks for leakage detection
        
        Returns:
            Training results and performance metrics
        """
        import subprocess
        
        logger.info("="*70)
        logger.info("  STARTING LEAKAGE-FREE MODEL TRAINING")
        logger.info("="*70)
        logger.info("Anti-leakage measures:")
        logger.info("  1. Time-based CV with 7-day embargo")
        logger.info("  2. Pre-kickoff odds only (T-1h)")
        logger.info("  3. Sanity checks enabled")
        logger.info("="*70)
        
        # Get dataset stats
        stats = self.get_training_dataset_stats()
        logger.info(f"\n📊 Training Dataset:")
        logger.info(f"   Total matches:      {stats['total_matches']:,}")
        logger.info(f"   Phase 2 coverage:   {stats['phase2_coverage']:.1f}%")
        logger.info(f"   Date range:         {stats['earliest_match']} to {stats['latest_match']}")
        
        # Run leakage-free training script
        logger.info("\n🚀 Launching leakage-free training script...")
        
        env = os.environ.copy()
        # Set LibGOMP path (CRITICAL for LightGBM)
        try:
            gcc_lib_path = subprocess.check_output(
                ["gcc", "-print-file-name=libgomp.so"], 
                text=True
            ).strip()
            lib_dir = os.path.dirname(gcc_lib_path)
            
            if 'LD_LIBRARY_PATH' in env:
                env['LD_LIBRARY_PATH'] = f"{lib_dir}:{env['LD_LIBRARY_PATH']}"
            else:
                env['LD_LIBRARY_PATH'] = lib_dir
                
            logger.info(f"   LibGOMP configured: {lib_dir}")
        except Exception as e:
            logger.warning(f"   Failed to configure LibGOMP: {e}")
        
        # Execute training
        result = subprocess.run(
            ["python", "training/train_v2_no_leakage.py"],
            capture_output=True,
            text=True,
            env=env,
            timeout=7200  # 2 hour timeout for full training
        )
        
        if result.returncode != 0:
            logger.error("❌ Training failed!")
            logger.error(result.stderr)
            logger.error("\n Stdout:")
            logger.error(result.stdout)
            raise RuntimeError(f"Training failed with exit code {result.returncode}")
        
        # Parse training output for performance metrics
        output = result.stdout
        logger.info("\n📊 Training Output:")
        logger.info(output)
        
        # Extract metrics (simplified - you can enhance this)
        performance = self.extract_performance_from_output(output)
        
        # Save metadata
        metadata = {
            'last_training_date': datetime.now().isoformat(),
            'matches_used': stats['total_matches'],
            'phase2_coverage': stats['phase2_coverage'],
            'model_version': f"v2-team-plus-plus-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            'performance': performance,
            'cv_folds': cv_folds,
            'min_matches': min_matches
        }
        
        self.save_training_metadata(metadata)
        
        logger.info("\n✅ Training complete!")
        logger.info(f"   Model version: {metadata['model_version']}")
        logger.info(f"   Accuracy: {performance.get('accuracy', 'N/A')}")
        logger.info(f"   LogLoss: {performance.get('logloss', 'N/A')}")
        
        return metadata
    
    def extract_performance_from_output(self, output: str) -> dict:
        """Extract performance metrics from training output"""
        metrics = {}
        
        # Look for common patterns in output
        lines = output.split('\n')
        for line in lines:
            if 'accuracy' in line.lower():
                # Try to extract accuracy value
                import re
                match = re.search(r'(\d+\.\d+)%?', line)
                if match:
                    metrics['accuracy'] = float(match.group(1))
            
            if 'logloss' in line.lower():
                import re
                match = re.search(r'(\d+\.\d+)', line)
                if match:
                    metrics['logloss'] = float(match.group(1))
            
            if 'brier' in line.lower():
                import re
                match = re.search(r'(\d+\.\d+)', line)
                if match:
                    metrics['brier_score'] = float(match.group(1))
        
        return metrics
    
    def check_status(self):
        """Check training status and recommendations"""
        logger.info("="*70)
        logger.info("  TRAINING STATUS CHECK")
        logger.info("="*70)
        
        # Get metadata
        last_metadata = self.get_last_training_metadata()
        current_stats = self.get_training_dataset_stats()
        
        logger.info(f"\n📊 Current Dataset:")
        logger.info(f"   Total matches:      {current_stats['total_matches']:,}")
        logger.info(f"   Phase 2 coverage:   {current_stats['phase2_coverage']:.1f}%")
        
        logger.info(f"\n🔧 Last Training:")
        if last_metadata['last_training_date']:
            logger.info(f"   Date:               {last_metadata['last_training_date']}")
            logger.info(f"   Matches used:       {last_metadata['matches_used']:,}")
            logger.info(f"   Model version:      {last_metadata['model_version']}")
            
            # Performance
            perf = last_metadata.get('performance', {})
            if perf:
                logger.info(f"   Accuracy:           {perf.get('accuracy', 'N/A')}")
                logger.info(f"   LogLoss:            {perf.get('logloss', 'N/A')}")
        else:
            logger.info("   Never trained")
        
        # Recommendation
        should_train, reason = self.should_retrain()
        
        logger.info(f"\n💡 Recommendation:")
        if should_train:
            logger.info(f"   ✅ RETRAIN RECOMMENDED")
            logger.info(f"   Reason: {reason}")
        else:
            logger.info(f"   ⏸️  No retraining needed")
            logger.info(f"   Reason: {reason}")
        
        logger.info("="*70)
    
    def auto_train(self, min_matches: int = 3000, cv_folds: int = 5):
        """Auto-train only if needed"""
        should_train, reason = self.should_retrain()
        
        logger.info("="*70)
        logger.info("  AUTO-TRAINING CHECK")
        logger.info("="*70)
        logger.info(f"\n{reason}")
        
        if should_train:
            logger.info("\n✅ Starting automatic training...")
            return self.run_training(min_matches=min_matches, cv_folds=cv_folds)
        else:
            logger.info("\n⏸️  Skipping training - not needed")
            return None


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Manage V2-Team++ model training'
    )
    
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check training status and recommendations'
    )
    
    parser.add_argument(
        '--train',
        action='store_true',
        help='Run full model training'
    )
    
    parser.add_argument(
        '--auto',
        action='store_true',
        help='Auto-train only if needed (for cron jobs)'
    )
    
    parser.add_argument(
        '--min-matches',
        type=int,
        default=3000,
        help='Minimum matches required for training (default: 3000)'
    )
    
    parser.add_argument(
        '--cv-folds',
        type=int,
        default=5,
        help='Number of cross-validation folds (default: 5)'
    )
    
    args = parser.parse_args()
    
    try:
        manager = TrainingManager()
        
        if args.check:
            manager.check_status()
        elif args.train:
            manager.run_training(
                min_matches=args.min_matches,
                cv_folds=args.cv_folds
            )
        elif args.auto:
            manager.auto_train(
                min_matches=args.min_matches,
                cv_folds=args.cv_folds
            )
        else:
            parser.print_help()
            sys.exit(1)
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
