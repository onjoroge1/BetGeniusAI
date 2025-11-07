# Quick Start - Auto-Restart Backfill

## ⚡ Run Now (Recommended)

```bash
# Start monitoring in background (runs until complete)
nohup python scripts/monitor_and_restart_backfill.py > /tmp/backfill_monitor.log 2>&1 &

# Check progress anytime
tail -20 /tmp/backfill_monitor.log
```

## 📊 Check Status

```bash
# Live progress
tail -f /tmp/backfill_monitor.log

# Database status
psql $DATABASE_URL -c "SELECT COUNT(*) as backfilled FROM match_context;"
psql $DATABASE_URL -c "
  SELECT 
    COUNT(mc.*) as backfilled,
    COUNT(tm.*) - COUNT(mc.*) as remaining
  FROM training_matches tm
  LEFT JOIN match_context mc ON tm.match_id = mc.match_id
  WHERE tm.match_date >= '2020-01-01' AND tm.outcome IS NOT NULL;
"
```

## 🛑 Stop Monitoring

```bash
# Stop the monitor
pkill -f monitor_and_restart_backfill

# Verify stopped
ps aux | grep monitor_and_restart
```

## 📝 What It Does

1. ✅ Automatically restarts backfill when it completes (every 5000 matches)
2. ✅ Detects and restarts if process crashes
3. ✅ Detects and restarts if stalled (no progress for 5 minutes)
4. ✅ Stops automatically when all matches are backfilled
5. ✅ Tracks progress in real-time

## ⏱️ Expected Duration

- **Total matches:** ~8,000 remaining
- **Processing rate:** ~50-70 matches/minute
- **Estimated time:** 2-3 hours for complete backfill

## 💡 Pro Tips

- Run overnight for best results
- Check logs every 30 minutes to verify progress
- Don't stop the monitor manually unless necessary
- The script will auto-complete when done!
