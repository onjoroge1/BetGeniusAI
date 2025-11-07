# Backfill Monitor - Auto-Restart Script

## Overview

The `monitor_and_restart_backfill.py` script automatically monitors and restarts the match_context backfill process to ensure complete data coverage without manual intervention.

## Features

✅ **Automatic Restart** - Restarts when process completes or crashes  
✅ **Stall Detection** - Detects when backfill stops making progress  
✅ **Progress Tracking** - Real-time monitoring of backfilled match count  
✅ **Auto-Complete** - Stops automatically when all matches are backfilled  

## Usage

### Basic Usage (Recommended)

```bash
# Run with default settings (5 min stall timeout, 60s checks)
python scripts/monitor_and_restart_backfill.py
```

### Advanced Usage

```bash
# Custom stall timeout (10 minutes)
python scripts/monitor_and_restart_backfill.py --stall-timeout 600

# Faster progress checks (every 30 seconds)
python scripts/monitor_and_restart_backfill.py --check-interval 30

# Both options combined
python scripts/monitor_and_restart_backfill.py --stall-timeout 600 --check-interval 30
```

### Run in Background (Recommended for long backfills)

```bash
# Run in background with nohup
nohup python scripts/monitor_and_restart_backfill.py > /tmp/backfill_monitor.log 2>&1 &

# Check progress
tail -f /tmp/backfill_monitor.log

# Check if running
ps aux | grep monitor_and_restart_backfill
```

## How It Works

1. **Initial Check** - Counts matches already backfilled and remaining
2. **Start Backfill** - Launches `backfill_match_context.py`
3. **Monitor Loop** - Every 60 seconds:
   - Checks if process is running
   - Checks if progress is being made
   - Counts remaining matches
4. **Auto-Restart Triggers**:
   - Process exits (completed batch of 5000)
   - Process crashes
   - No progress for 5+ minutes (stalled)
5. **Auto-Complete** - Stops when remaining matches = 0

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--stall-timeout` | 300 | Seconds without progress before restart |
| `--check-interval` | 60 | Seconds between progress checks |

## Example Output

```
======================================================================
  BACKFILL MONITOR - Auto-Restart Enabled
======================================================================
Stall timeout:   300s (5.0 minutes)
Check interval:  60s
======================================================================

📊 Initial Status:
   Backfilled:  905 matches
   Remaining:   7,904 matches
   Total:       8,809 matches

🚀 Starting backfill process...
   Process started (PID: 12345, Restart #1)
   Progress: +100 matches (total: 1005) (remaining: 7,804)
   Progress: +250 matches (total: 1255) (remaining: 7,554)
   ...
   ⚠️  Process stopped (remaining: 2,904 matches)
   Restarting in 5 seconds...
🚀 Starting backfill process...
   Process started (PID: 12456, Restart #2)
   ...
======================================================================
✅ BACKFILL COMPLETE - All matches processed!
======================================================================
Total restarts:  3
Final count:     8,809 matches
======================================================================
```

## Stopping the Monitor

```bash
# If running in foreground
Ctrl+C

# If running in background
pkill -f monitor_and_restart_backfill
```

## Troubleshooting

### Monitor keeps restarting immediately
- Check database connectivity
- Review `/tmp/backfill_monitor.log` for errors

### "No progress" but matches are being processed
- Increase `--stall-timeout` to 600 or more
- Backfill may be processing very slowly

### Database connection errors
- Verify `DATABASE_URL` environment variable is set
- Check database is accessible

## Best Practices

1. **Run overnight** for complete backfill (6-8 hours estimated)
2. **Use nohup** to prevent interruption if terminal disconnects
3. **Monitor logs** periodically to check progress
4. **Default settings** work well for most cases
