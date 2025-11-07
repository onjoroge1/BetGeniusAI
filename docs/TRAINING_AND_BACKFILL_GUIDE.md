# Training and Backfill Management Guide

## Overview

This guide explains how to manage recurring backfills and model training for the BetGenius AI prediction system.

---

## 📅 **1. RECURRING BACKFILL STRATEGY**

### **What Gets Backfilled:**

1. **match_context** - Team rest days, schedule congestion, derby flags
2. **historical_odds** - Preservation of odds snapshots for CLV analysis

### **When to Backfill:**

✅ **Daily** - For new matches from last 30 days  
✅ **Historical** - One-time backfill for older data (already completed)

### **How to Run:**

#### **Option A: Manual Daily Backfill**
```bash
# Run backfill for recent matches (last 30 days)
python scripts/daily_backfill_cron.py
```

#### **Option B: Automated Daily Backfill (Recommended)**

**Using Replit Scheduled Deployment:**
1. Set deployment target to `scheduled` in deploy config
2. Configure schedule: Daily at 3 AM UTC
3. Command: `python scripts/daily_backfill_cron.py`

**Or using cron (if on VM):**
```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 3 AM UTC)
0 3 * * * cd /home/runner/workspace && python scripts/daily_backfill_cron.py >> /tmp/daily_backfill.log 2>&1
```

### **What It Does:**

1. ✅ Finds matches from last 30 days missing context data
2. ✅ Computes and stores match_context (rest days, congestion)
3. ✅ Preserves historical odds snapshots for CLV tracking
4. ✅ Logs all operations to data_lineage table

### **Monitoring Daily Backfill:**

```bash
# Check logs
tail -f /tmp/daily_backfill.log

# Verify latest backfill
psql $DATABASE_URL -c "
  SELECT MAX(created_at) as last_backfill, COUNT(*) as total
  FROM match_context;
"
```

---

## 🧠 **2. MODEL TRAINING STRATEGY**

### **Training Frequency Recommendations:**

| Scenario | Frequency | Trigger | Command |
|----------|-----------|---------|---------|
| **Production** | Weekly | Auto (if 500+ new matches) | `--auto` |
| **Development** | On-demand | Manual | `--train` |
| **Major Update** | Immediate | After feature changes | `--train` |

### **Training Triggers:**

The system automatically recommends retraining when:

1. ✅ **500+ new matches** since last training
2. ✅ **20%+ improvement** in Phase 2 coverage
3. ✅ **Never trained** before
4. ✅ **Major data backfill** completed

### **Using the Training Management Script:**

#### **Check Training Status:**
```bash
python scripts/manage_training.py --check
```

**Output:**
```
📊 Current Dataset:
   Total matches:      8,809
   Phase 2 coverage:   100.0%

🔧 Last Training:
   Date:               2025-11-07
   Matches used:       8,809
   Model version:      v2-team-plus-plus-20251107-180000
   Accuracy:           54.3%
   LogLoss:            0.985

💡 Recommendation:
   ⏸️  No retraining needed
   Reason: Only 234 new matches (threshold: 500)
```

#### **Run Full Training:**
```bash
# Standard training (5-fold CV on full dataset)
python scripts/manage_training.py --train

# Custom parameters
python scripts/manage_training.py --train --min-matches 5000 --cv-folds 10
```

#### **Auto-Training (Recommended for Cron):**
```bash
# Only trains if needed
python scripts/manage_training.py --auto
```

### **Training Duration:**

| Dataset Size | Feature Building | Training | Total |
|--------------|-----------------|----------|-------|
| 1,000 matches | ~15 min | ~3 min | ~18 min |
| 5,000 matches | ~90 min | ~10 min | ~100 min |
| 8,809 matches | ~150 min | ~15 min | ~165 min |

**Note:** First run is slow due to uncached features. Future optimization will add feature caching.

### **Automated Weekly Training:**

**Using Replit Scheduled Deployment:**
```bash
# Deploy config for weekly training (Sundays at 2 AM)
deployment_target: scheduled
schedule: "0 2 * * 0"  # Cron format
run: ["python", "scripts/manage_training.py", "--auto"]
```

**Or using cron:**
```bash
# Add to crontab (runs Sundays at 2 AM UTC)
0 2 * * 0 cd /home/runner/workspace && python scripts/manage_training.py --auto >> /tmp/training.log 2>&1
```

---

## 📊 **3. MONITORING & VALIDATION**

### **Check Backfill Status:**

```bash
# Match context coverage
psql $DATABASE_URL -c "
  SELECT 
    COUNT(mc.*) as backfilled,
    COUNT(tm.*) as total_matches,
    COUNT(mc.*) * 100.0 / COUNT(tm.*) as coverage_pct
  FROM training_matches tm
  LEFT JOIN match_context mc ON tm.match_id = mc.match_id
  WHERE tm.match_date >= '2020-01-01';
"

# Recent backfill activity
psql $DATABASE_URL -c "
  SELECT 
    DATE(created_at) as date,
    COUNT(*) as matches_backfilled
  FROM match_context
  WHERE created_at >= NOW() - INTERVAL '7 days'
  GROUP BY DATE(created_at)
  ORDER BY date DESC;
"
```

### **Check Training Status:**

```bash
# Training metadata
cat models/artifacts/training_metadata.json

# Model performance tracking
psql $DATABASE_URL -c "
  SELECT 
    model_name,
    created_at,
    metrics
  FROM model_versions
  ORDER BY created_at DESC
  LIMIT 5;
"
```

---

## 🎯 **4. RECOMMENDED SETUP (Production)**

### **Daily Backfill (3 AM UTC):**
```bash
# Replit Scheduled Deployment
deployment_target: scheduled
schedule: "0 3 * * *"
run: ["python", "scripts/daily_backfill_cron.py"]
```

### **Weekly Auto-Training (Sundays 2 AM UTC):**
```bash
# Replit Scheduled Deployment
deployment_target: scheduled
schedule: "0 2 * * 0"
run: ["python", "scripts/manage_training.py", "--auto"]
```

### **Manual Training (After Major Updates):**
```bash
# After Phase 3 features or major data quality improvements
python scripts/manage_training.py --train
```

---

## ⚙️ **5. CONFIGURATION**

### **Training Manager Settings:**

Edit `scripts/manage_training.py`:

```python
# Thresholds
self.min_matches_for_retrain = 500   # Retrain after 500 new matches
self.min_total_matches = 3000        # Minimum dataset size
```

### **Backfill Settings:**

Edit `scripts/daily_backfill_cron.py`:

```python
# Lookback windows
matches = self.get_recent_matches_needing_context(days=30)  # Last 30 days
self.preserve_historical_odds(days=7)                       # Last 7 days
```

---

## 🔧 **6. TROUBLESHOOTING**

### **Training Stuck or Very Slow:**

**Problem:** Feature building takes 2+ hours  
**Solution:** Feature caching (planned optimization)

```bash
# For now: Train on subset for quick validation
python scripts/manage_training.py --train --min-matches 1000
```

### **Backfill Keeps Failing:**

**Problem:** Database connection issues  
**Solution:** Use the auto-restart monitor

```bash
# Use the auto-restart backfill monitor
python scripts/monitor_and_restart_backfill.py
```

### **Training Fails with Out of Memory:**

**Problem:** Dataset too large for available RAM  
**Solution:** Reduce batch size or use incremental training

```python
# Edit train_v2_team_plus_plus.py
# Reduce limit in load_matches_with_phase2_context():
backfiller.run(limit=3000)  # Instead of 5000
```

---

## 📈 **7. EXPECTED PERFORMANCE METRICS**

### **Phase 1 (46 features):**
- Accuracy: 50-52%
- LogLoss: ~1.00
- Brier Score: ~0.24

### **Phase 2 (50 features) - Current:**
- Accuracy: 53-55% (expected)
- LogLoss: ~0.97
- Brier Score: ~0.23

### **Phase 3 (70+ features) - Planned:**
- Accuracy: 57-58% (target)
- LogLoss: ~0.93
- Brier Score: ~0.21

---

## 🚀 **Quick Reference Commands**

```bash
# Check if training needed
python scripts/manage_training.py --check

# Run full training
python scripts/manage_training.py --train

# Auto-train (only if needed)
python scripts/manage_training.py --auto

# Daily backfill
python scripts/daily_backfill_cron.py

# Monitor backfill progress
python scripts/monitor_and_restart_backfill.py

# View logs
tail -f /tmp/training.log
tail -f /tmp/daily_backfill.log
tail -f /tmp/backfill_monitor.log
```

---

## 📝 **Summary**

**Recurring Backfill:**
- ✅ Run **daily** via scheduled deployment (3 AM UTC)
- ✅ Covers match_context and historical_odds
- ✅ Automatic retry with monitor script if needed

**Model Training:**
- ✅ Run **weekly** via scheduled deployment (Sundays 2 AM UTC)
- ✅ Auto-trains only when 500+ new matches available
- ✅ Tracks performance and versions automatically
- ✅ Manual training after major updates

**Best Practice:** Set up both as scheduled deployments and monitor logs weekly!
