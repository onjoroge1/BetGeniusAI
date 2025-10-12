# Autoscale Deployment Fix Instructions

**Date**: October 12, 2025  
**Status**: ⚠️ Manual `.replit` configuration required

---

## Issues Fixed Automatically ✅

### 1. Startup Delay (FIXED)
**Problem**: Background scheduler started on app startup, delaying port opening  
**Solution**: Deferred background tasks to start 2 seconds AFTER port opens  
**Result**: Port 8000 opens immediately, scheduler starts after

**Verification in logs:**
```
INFO:     Application startup complete.     ← Port opens FIRST
INFO:     127.0.0.1:44998 - "GET / HTTP/1.1" 200 OK  
INFO:main:Port opened - now starting background scheduler...
INFO:main:✅ Background scheduler started (deferred)
```

---

## Manual Fix Required ⚠️

### 2. Port Configuration in `.replit`

**Problem**: Your `.replit` file has the WRONG port as the first entry:

```toml
# CURRENT (WRONG - First port is 5000, but app runs on 8000)
[[ports]]
localPort = 5000
externalPort = 80       ← First port (Autoscale uses this!)

[[ports]]
localPort = 8000
externalPort = 8000     ← Your app actually runs here
```

**Autoscale Requirement**: 
- Only ONE port should be configured
- The FIRST port must map to external port 80
- Your app runs on port 8000, so it must be: `8000 → 80`

**Required Fix**:

1. Open the `.replit` file in the editor
2. **Delete all port entries** (lines 35-66)
3. **Replace with this single entry**:

```toml
[[ports]]
localPort = 8000
externalPort = 80
```

**Complete `.replit` file should look like this:**

```toml
modules = ["python-3.11", "python3", "postgresql-16"]

[nix]
channel = "stable-24_05"
packages = ["cairo", "ffmpeg-full", "freetype", "gcc", "ghostscript", "glibcLocales", "gobject-introspection", "gtk3", "libxcrypt", "libyaml", "ocl-icd", "opencl-headers", "pkg-config", "qhull", "tcl", "tk", "xsimd"]

[workflows]
runButton = "Project"

[[workflows.workflow]]
name = "Project"
mode = "parallel"
author = "agent"

[[workflows.workflow.tasks]]
task = "workflow.run"
args = "BetGenius AI Server"

[[workflows.workflow]]
name = "BetGenius AI Server"
author = "agent"

[workflows.workflow.metadata]
outputType = "console"

[[workflows.workflow.tasks]]
task = "shell.exec"
args = "export LD_LIBRARY_PATH=\"$(gcc -print-file-name=libgomp.so | xargs dirname):$LD_LIBRARY_PATH\" && python main.py"
waitForPort = 8000

[deployment]
run = ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
deploymentTarget = "autoscale"

[[ports]]
localPort = 8000
externalPort = 80

[agent]
expertMode = true
```

---

## Deployment Configuration Verification ✅

Your deployment config is already correct:

```toml
[deployment]
run = ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
deploymentTarget = "autoscale"
```

✅ Listens on `0.0.0.0` (all interfaces)  
✅ Port `8000` (matches port forwarding)  
✅ Deployment target: `autoscale`  

---

## Summary of Changes

| Issue | Status | Action |
|-------|--------|--------|
| Background scheduler delays port opening | ✅ FIXED | Deferred to start after port opens |
| Port 8000 → 80 mapping | ⚠️ MANUAL | Edit `.replit` to have ONLY `8000 → 80` |
| Multiple port entries | ⚠️ MANUAL | Remove all ports except `8000 → 80` |
| Server binds to 0.0.0.0 | ✅ OK | Already configured correctly |

---

## After Manual Fix

Once you update the `.replit` file:

1. **Save the file**
2. **Restart the workspace** (or just the workflow)
3. **Redeploy to Autoscale**

Your deployment should now succeed with:
- ✅ Port opens immediately (< 1 second)
- ✅ Correct port mapping: `8000 → 80`
- ✅ Background tasks start after port is ready
- ✅ No conflicting port entries

---

## Technical Details

### Why Port 80?

According to Replit Autoscale documentation:

> "By default, Replit binds the first port you open to external port 80, which allows access without a port address in the URL (e.g., customdomain.com/ instead of customdomain.com:3000/)"

> "For Autoscale Deployments, only a single external port is supported... remove all externalPort entries for ports except for the specific port you intend for internet interaction."

### Why Defer Background Tasks?

Autoscale health checks require the port to open quickly. Background activities (automated match collection, CLV monitoring) were starting during app initialization, delaying port availability. By deferring these tasks to start 2 seconds after port opens, the health check passes immediately.

---

## Verification Commands

After fixing, verify with:

```bash
# Check port is open
curl http://localhost:8000/

# Check deployment config
cat .replit | grep -A 2 "ports"

# Should show:
# [[ports]]
# localPort = 8000
# externalPort = 80
```

---

## Need Help?

If deployment still fails after this fix, check:
1. `.replit` has ONLY one `[[ports]]` entry
2. That entry maps `8000 → 80`
3. No other port entries exist
4. Deployment config uses `--port 8000`
