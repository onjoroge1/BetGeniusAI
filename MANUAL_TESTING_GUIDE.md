# Manual Scheduler Testing Guide

## Problem Solved ✅

**Issue**: Scheduler only ran at 02:00-02:30 UTC, making testing difficult during development.

**Solution**: Added manual collection trigger that bypasses timing restrictions for testing.

## Manual Collection Methods

### Method 1: API Endpoint (Recommended)
```bash
curl -X POST "http://localhost:8000/admin/trigger-collection" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

**Response**:
```json
{
  "status": "success",
  "message": "Manual collection cycle triggered successfully",
  "note": "Collection running in background - check logs for progress",
  "timing": "Bypasses normal 02:00-02:30 UTC restriction for testing"
}
```

### Method 2: Python Script
```bash
python trigger_manual_collection.py
```

### Method 3: Test Script
```bash
python test_manual_collection.py
```

## What This Enables

### ✅ Development Testing
- Test scheduler functionality anytime during development
- No need to wait for 02:00 UTC window
- Immediate feedback on collection issues

### ✅ System Validation
- Verify league map integration works
- Test dual-table population strategy  
- Confirm data collection across all 6 configured leagues

### ✅ Debugging Support
- Trigger collection when investigating issues
- Test fixes immediately after implementation
- Avoid multi-day debugging cycles

## Scheduler Behavior

### Automatic Collection (Production)
- **Timing**: Only during 02:00-02:30 UTC window
- **Frequency**: Once daily
- **Trigger**: Automatic scheduler loop
- **Purpose**: Regular production data collection

### Manual Collection (Testing)
- **Timing**: Available 24/7 for testing
- **Frequency**: On-demand via API call
- **Trigger**: Manual API request with `force=True`
- **Purpose**: Development and testing

## Monitoring Collection Progress

**Watch Server Logs For**:
```
INFO:utils.scheduler:🔧 MANUAL collection cycle triggered
INFO:models.automated_collector:🔄 Starting ENHANCED dual collection cycle...
INFO:models.automated_collector:📋 Phase A: Completed matches → training_matches
INFO:models.automated_collector:📋 Phase B: Upcoming matches → odds_snapshots
```

**Collection Completion**:
```
INFO:utils.scheduler:🔧 MANUAL collection completed: X new matches
```

## Security Note

Manual collection still requires:
- ✅ Valid API authentication
- ✅ Admin endpoint access
- ✅ Proper authorization headers

## Usage Examples

### Quick Test
```bash
# Start server, then trigger collection
curl -X POST "http://localhost:8000/admin/trigger-collection" \
  -H "Authorization: Bearer betgenius_secure_key_2024"
```

### Development Workflow
1. Make scheduler changes
2. Restart server  
3. Trigger manual collection
4. Verify results in logs
5. Iterate as needed

---

**Result**: No more waiting for daily collection windows during development!