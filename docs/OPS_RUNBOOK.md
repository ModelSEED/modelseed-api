# ModelSEED API — Operations Runbook

Quick reference for anyone who needs to check, restart, or troubleshoot the ModelSEED API on poplar.

## Access

```
ssh <your-username>@poplar.cels.anl.gov
cd /scratch/jplfaria/repos
```

All repos and Docker files live under `/scratch/jplfaria/repos/`. The service runs as a Docker container.


## Check if the service is running

```bash
# Quick health check (from anywhere with network access)
curl -s http://poplar.cels.anl.gov:8000/api/health

# Expected: {"status":"ok","version":"0.1.0"}
# If no response or connection refused → service is down
```

```bash
# On poplar: check container status
docker ps --filter name=modelseed

# Should show modelseed-api-api-1 with status "Up" and "(healthy)"
# If status shows "(unhealthy)" or container is missing → restart needed
```


## Restart the service

### Quick restart (no code changes)

```bash
cd /scratch/jplfaria/repos
docker compose -f modelseed-api/docker-compose.yml restart api
```

### Restart after code changes

```bash
cd /scratch/jplfaria/repos
docker compose -f modelseed-api/docker-compose.yml build --no-cache api
docker compose -f modelseed-api/docker-compose.yml up -d
```

**Important:** Do NOT use `docker compose up --build` — it may use cached layers and miss dependency changes. Always use `build --no-cache` when dependencies have changed.

### Full reset (nuclear option)

If the container is in a bad state (won't stop, zombie process, etc.):

```bash
cd /scratch/jplfaria/repos
docker compose -f modelseed-api/docker-compose.yml down
docker rmi $(docker images --filter reference='*modelseed*' -q) 2>/dev/null
docker compose -f modelseed-api/docker-compose.yml build --no-cache api
docker compose -f modelseed-api/docker-compose.yml up -d
```


## Auto-recovery

The service is configured with:

- **`restart: unless-stopped`** — Docker automatically restarts the container if it crashes or if the host reboots (as long as Docker daemon starts on boot)
- **Health check** — Docker pings `/api/health` every 60 seconds. After 3 consecutive failures, the container is marked unhealthy and Docker restarts it

This means most transient failures (OOM, unhandled exception, network blip) will self-heal within ~3 minutes without human intervention.

### What auto-recovery does NOT handle

- Docker daemon itself crashing or not starting after reboot
- Disk full (container can't write job state or logs)
- Port 8000 already in use by another process
- Code bugs that cause the health endpoint itself to fail (infinite restart loop)
- Network-level issues (firewall, DNS) blocking external access while container is healthy internally


## View logs

```bash
# Last 100 lines
docker logs --tail 100 modelseed-api-api-1

# Follow live
docker logs -f modelseed-api-api-1

# Since a specific time
docker logs --since 2h modelseed-api-api-1
```


## Common issues

### Container keeps restarting

```bash
# Check why it's dying
docker logs --tail 50 modelseed-api-api-1

# Common causes:
# - "ModuleNotFoundError" → dependency repo missing or not cloned to correct branch
# - "FileNotFoundError: Template file not found" → ModelSEEDTemplates not cloned
# - "Address already in use" → another process on port 8000
```

### "Connection refused" but container shows as running

```bash
# Check if uvicorn is actually listening
docker exec modelseed-api-api-1 ss -tlnp | grep 8000

# Check if firewall is blocking
curl -s http://localhost:8000/api/health  # from poplar itself
```

### Health check shows "unhealthy" but API works in browser

The health check runs *inside* the container (`localhost:8000`). If the API responds to external requests but the health check fails, the issue is inside the container:

```bash
docker exec modelseed-api-api-1 python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read())"
```

### Updating code

```bash
cd /scratch/jplfaria/repos/modelseed-api
git pull

# If only modelseed-api code changed:
docker compose -f docker-compose.yml build --no-cache api && docker compose -f docker-compose.yml up -d

# If dependency repos changed too (ModelSEEDpy, KBUtilLib, etc.):
cd /scratch/jplfaria/repos
cd ModelSEEDpy && git pull && cd ..
cd KBUtilLib && git pull && cd ..
# ... etc for any changed repo
docker compose -f modelseed-api/docker-compose.yml build --no-cache api
docker compose -f modelseed-api/docker-compose.yml up -d
```


## Verify after restart

```bash
# 1. Health check
curl -s http://poplar.cels.anl.gov:8000/api/health

# 2. Biochem search (no auth needed)
curl -s "http://poplar.cels.anl.gov:8000/api/biochem/search?query=glucose&type=compounds" | head -c 200

# 3. Demo page loads
curl -s -o /dev/null -w "%{http_code}" http://poplar.cels.anl.gov:8000/demo/
# Expected: 200
```

Or open http://poplar.cels.anl.gov:8000/demo/ in a browser.


## Architecture summary

```
User → poplar:8000 → Docker container (modelseed-api-api-1)
                        └── uvicorn → FastAPI app
                              ├── /api/health     (always up if container is running)
                              ├── /api/biochem/*  (no auth, reads ModelSEEDDatabase)
                              ├── /api/models/*   (needs PATRIC token)
                              ├── /api/jobs/*     (dispatches to subprocess scripts)
                              └── /demo/          (static HTML dashboard)
```

The container is self-contained — all Python dependencies and data repos are baked into the Docker image. The only external dependency is the PATRIC Workspace Service (for workspace-mode operations).


## Key files on poplar

| Path | What |
|------|------|
| `/scratch/jplfaria/repos/modelseed-api/` | This repo |
| `/scratch/jplfaria/repos/ModelSEEDpy/` | Modeling engine (cshenry fork) |
| `/scratch/jplfaria/repos/KBUtilLib/` | KBase utility library |
| `/scratch/jplfaria/repos/cobrakbase/` | KBase/cobra bridge |
| `/scratch/jplfaria/repos/ModelSEEDDatabase/` | Biochemistry data (dev branch) |
| `/scratch/jplfaria/repos/ModelSEEDTemplates/` | Model templates v7.0 |
| `/scratch/jplfaria/repos/cb_annotation_ontology_api/` | Annotation ontology |


## Contacts

- **Source code**: https://github.com/ModelSEED/modelseed-api
- **Swagger docs**: http://poplar.cels.anl.gov:8000/docs
- **Flower (job monitoring)**: http://poplar.cels.anl.gov:5555/ (when Celery mode is enabled)
