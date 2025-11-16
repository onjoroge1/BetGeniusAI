#!/usr/bin/env python3
"""
BetGenius AI - V2 Model Training (Standalone Script)

This script trains the V2 LightGBM model with clean, leak-resistant features.
Run this manually to retrain the model with updated data.

Usage:
    python scripts/train_v2_standalone.py [--use-transformed] [--max-samples N]

Options:
    --use-transformed    Use transformed context features (2 features: rest_advantage, congestion_ratio)
                        Default: Use raw context features (4 features)
    --max-samples N      Limit training to N samples (for faster testing)
    --skip-sanity       Skip sanity checks (not recommended)
    
Examples:
    # Train with raw context features
    python scripts/train_v2_standalone.py
    
    # Train with transformed features (leak-resistant)
    python scripts/train_v2_standalone.py --use-transformed
    
    # Quick test run with 500 samples
    python scripts/train_v2_standalone.py --max-samples 500

Output:
    - models/v2_lgbm_production.txt (trained model)
    - models/v2_training_metadata.json (metrics + sanity checks)
"""

import os
import sys
import argparse
import logging
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training.train_v2_transformed import main as train_transformed
from training.train_v2 import main as train_raw

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Train BetGenius AI V2 Model (Standalone)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--use-transformed',
        action='store_true',
        help='Use transformed context features (rest_advantage, congestion_ratio)'
    )
    
    parser.add_argument(
        '--max-samples',
        type=int,
        default=None,
        help='Limit training to N samples (for testing)'
    )
    
    parser.add_argument(
        '--skip-sanity',
        action='store_true',
        help='Skip sanity checks (not recommended for production)'
    )
    
    return parser.parse_args()


def main():
    """Main training entry point"""
    args = parse_args()
    
    # Print banner
    print("=" * 80)
    print("  BETGENIUS AI - V2 MODEL TRAINING")
    print("=" * 80)
    print(f"Started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()
    print("Configuration:")
    print(f"  - Features: {'Transformed (2 context)' if args.use_transformed else 'Raw (4 context)'}")
    print(f"  - Max samples: {args.max_samples or 'All available'}")
    print(f"  - Sanity checks: {'Disabled ⚠️' if args.skip_sanity else 'Enabled ✅'}")
    print("=" * 80)
    print()
    
    # Set environment variables
    if args.use_transformed:
        os.environ['V2_USE_TRANSFORMED'] = '1'
        logger.info("Using transformed context features")
    else:
        os.environ.pop('V2_USE_TRANSFORMED', None)
        logger.info("Using raw context features")
    
    if args.max_samples:
        os.environ['V2_MAX_SAMPLES'] = str(args.max_samples)
        logger.info(f"Limiting to {args.max_samples} samples")
    
    if args.skip_sanity:
        os.environ['V2_SKIP_SANITY'] = '1'
        logger.warning("⚠️  Sanity checks disabled - USE WITH CAUTION")
    
    # Verify database connection
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        logger.error("❌ DATABASE_URL environment variable not set")
        logger.error("Please set DATABASE_URL to your PostgreSQL connection string")
        sys.exit(1)
    
    logger.info("✅ Database connection verified")
    
    # Run training
    try:
        if args.use_transformed:
            logger.info("Starting V2.3 training (transformed features)...")
            train_transformed()
        else:
            logger.info("Starting V2 training (raw features)...")
            train_raw()
        
        print()
        print("=" * 80)
        print("✅ TRAINING COMPLETED SUCCESSFULLY")
        print("=" * 80)
        print()
        print("Output files:")
        print("  - models/v2_lgbm_production.txt (trained model)")
        print("  - models/v2_training_metadata.json (metrics)")
        print()
        print("Next steps:")
        print("  1. Review sanity checks in the output above")
        print("  2. Check random-label accuracy (<0.40 = clean)")
        print("  3. Deploy model if all checks pass")
        print("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Training failed: {e}")
        print()
        print("=" * 80)
        print("❌ TRAINING FAILED")
        print("=" * 80)
        print()
        print(f"Error: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Check database connection (DATABASE_URL)")
        print("  2. Verify match_context_v2 table exists and is populated")
        print("  3. Check logs above for specific errors")
        print("=" * 80)
        sys.exit(1)


if __name__ == "__main__":
    main()
