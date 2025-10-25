#!/usr/bin/env python3
"""
LightGBM Training Launcher
Runs training in background and monitors progress
"""
import subprocess
import os
import sys
import time
from pathlib import Path

def main():
    print("="*70)
    print("LIGHTGBM TRAINING LAUNCHER")
    print("="*70)
    
    # Set LD_LIBRARY_PATH
    try:
        result = subprocess.run(
            ["gcc", "-print-file-name=libgomp.so"],
            capture_output=True,
            text=True,
            check=True
        )
        libgomp_path = result.stdout.strip()
        lib_dir = str(Path(libgomp_path).parent)
        
        current_ld_path = os.environ.get('LD_LIBRARY_PATH', '')
        if current_ld_path:
            os.environ['LD_LIBRARY_PATH'] = f"{lib_dir}:{current_ld_path}"
        else:
            os.environ['LD_LIBRARY_PATH'] = lib_dir
        
        print(f"✅ Set LD_LIBRARY_PATH: {lib_dir}")
    except Exception as e:
        print(f"⚠️  Warning: Could not set LD_LIBRARY_PATH: {e}")
    
    # Choose training mode
    print("\nTraining Options:")
    print("1. Fast single-split (10-15 min, test accuracy only)")
    print("2. Full 5-fold CV (30-40 min, production-ready)")
    
    choice = input("\nChoose [1/2] (default: 1): ").strip() or "1"
    
    if choice == "1":
        script = "training/train_lgbm_single_split.py"
        log_file = "lgbm_fast_training.log"
        duration = "10-15 minutes"
    else:
        script = "training/train_lgbm_historical_36k.py"
        log_file = "lgbm_training.log"
        duration = "30-40 minutes"
    
    print(f"\n{'='*70}")
    print(f"Starting training: {script}")
    print(f"Log file: {log_file}")
    print(f"Expected duration: {duration}")
    print(f"{'='*70}\n")
    
    # Start training in background
    with open(log_file, 'w') as log:
        process = subprocess.Popen(
            [sys.executable, "-u", script],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy()
        )
    
    pid = process.pid
    print(f"✅ Training started (PID: {pid})")
    print(f"📝 Writing logs to: {log_file}")
    print(f"\nMonitoring progress (Ctrl+C to stop monitoring, training continues)...\n")
    
    # Monitor the log file
    try:
        time.sleep(2)  # Give it a moment to start
        
        # Tail the log file
        tail_process = subprocess.Popen(
            ["tail", "-f", log_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            for line in tail_process.stdout:
                print(line, end='')
                
        except KeyboardInterrupt:
            print("\n\n" + "="*70)
            print("⏸️  Stopped monitoring (training still running in background)")
            print(f"PID: {pid}")
            print(f"\nTo resume monitoring: tail -f {log_file}")
            print(f"To check if running: ps aux | grep {pid}")
            print(f"To stop training: kill {pid}")
            print("="*70)
            tail_process.terminate()
            
    except Exception as e:
        print(f"\n⚠️  Monitoring error: {e}")
        print(f"Training still running (PID: {pid})")
        print(f"Monitor manually: tail -f {log_file}")
    
    # Check if process is still running
    poll = process.poll()
    if poll is None:
        print(f"\n✅ Training process still running (PID: {pid})")
    elif poll == 0:
        print(f"\n✅ Training completed successfully!")
        print(f"\nNext steps:")
        print(f"  python analysis/promotion_gate_checker.py")
    else:
        print(f"\n❌ Training process exited with code {poll}")
        print(f"Check logs: cat {log_file}")

if __name__ == "__main__":
    main()
