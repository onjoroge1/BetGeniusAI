# 📸 Visual Fix Guide - .replit File

## Current State ❌

**Your `.replit` file (lines 31-42):**
```toml
[deployment]
run = ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-server-header"]
deploymentTarget = "autoscale"

[[ports]]
localPort = 5000    ← Line 36 ❌ WRONG (first port - deployment uses this)
externalPort = 80

[[ports]]
localPort = 8000    ← Line 40 ✅ CORRECT (but second - ignored)
externalPort = 8000

[[ports]]
localPort = 35667
... 7 more port blocks ...
```

**Problem:** Autoscale forwards **port 5000** (first block), but your app runs on **port 8000**.

---

## Fixed State ✅

**Your `.replit` file should look like:**
```toml
[deployment]
run = ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-server-header"]
deploymentTarget = "autoscale"

[[ports]]
localPort = 8000
externalPort = 80

[agent]
expertMode = true
```

**Result:** Autoscale forwards **port 8000** (only port), your app runs on **port 8000**. ✅

---

## How to Fix (Visual)

### Step 1: Select and Delete
**In `.replit` editor, select these lines (35-71):**
```
[[ports]]           ← Start selecting here
localPort = 5000
externalPort = 80

[[ports]]
localPort = 8000
externalPort = 8000

[[ports]]
localPort = 35667
externalPort = 5000

... (6 more blocks) ...

[[ports]]
localPort = 46667
externalPort = 3000   ← End selecting here
```

**Press DELETE**

### Step 2: Add Single Block
**Type this in the empty space:**
```toml
[[ports]]
localPort = 8000
externalPort = 80
```

### Step 3: Save
**Press Ctrl+S (or Cmd+S on Mac)**

---

## Verification Commands

**Copy-paste these into Shell:**
```bash
# Test 1: Count port blocks (should be 1)
grep -n '^\[\[ports\]\]' .replit | wc -l

# Test 2: Find port 8000 (should show one line)
grep -n 'localPort.*8000' .replit

# Test 3: Find port 5000 (should show nothing)
grep -n 'localPort.*5000' .replit || echo "✅ Port 5000 removed successfully"

# Test 4: View the port section
sed -n '31,42p' .replit
```

**Expected output:**
```
1                                          ← Only 1 port block
40:localPort = 8000                       ← Found port 8000
✅ Port 5000 removed successfully          ← No port 5000

[deployment]
run = ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-server-header"]
deploymentTarget = "autoscale"

[[ports]]
localPort = 8000
externalPort = 80

[agent]
expertMode = true
```

---

## After Fixing - Deploy!

**1. Click "Deploy" button**

**2. Select "Autoscale"**

**3. Watch for success logs:**
```
✅ Uvicorn running on http://0.0.0.0:8000
✅ Starting BetGenius AI Backend - port opening... (deployment=True, bg_enabled=False)
✅ Application startup complete.
✅ 🚫 DEPLOYMENT MODE: Background tasks DISABLED (API-only mode)
```

**4. Test endpoints:**
```bash
curl https://your-deployment.replit.app/healthz
# {"ok":true}

curl https://your-deployment.replit.app/
# {"message":"BetGenius AI Backend","status":"running","docs":"/docs"}
```

---

## What NOT to See ❌

**Bad logs (means .replit not fixed):**
```
❌ forwarding local port 5000 to external port 80
❌ deployment=True, type=unknown, bg_enabled=True
❌ ✅ Background scheduler started
```

**If you see these:** .replit file still has port 5000 first. Re-do the fix.

---

## Success Checklist

After fixing `.replit`:
- [ ] Only 1 `[[ports]]` block exists
- [ ] It says `localPort = 8000`
- [ ] It says `externalPort = 80`
- [ ] No port 5000 anywhere
- [ ] File saved (Ctrl+S)

After deploying:
- [ ] Logs show port 8000
- [ ] Logs show `bg_enabled=False`
- [ ] No "Background scheduler started" message
- [ ] `/healthz` endpoint returns `{"ok":true}`

---

## You're 30 Seconds from Success! 🎯

1. Open `.replit`
2. Delete lines 35-71 (all the port blocks)
3. Add one block: `localPort=8000, externalPort=80`
4. Save
5. Deploy
6. Success! 🚀
