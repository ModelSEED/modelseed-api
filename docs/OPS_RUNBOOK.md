# ModelSEED API — Operations Runbook

Quick reference for anyone who needs to check, restart, or troubleshoot the ModelSEED API on poplar.

## I just got paged — what do I do?

1. **Is the API responding?** `curl -s http://poplar.cels.anl.gov:3004/api/health`
   - Returns `{"status":"ok",...}` → API is fine; the issue is somewhere else (frontend, nginx, jobs). Skip to step 4.
   - No response, connection refused, or 5xx → API is down. Continue.
2. **Is the container up?** `ssh poplar` then `docker ps --filter name=modelseed`
   - `modelseed-api-api-1` shows `Up (healthy)` → port mapping or network issue. See "Connection refused but container shows as running".
   - Container is missing or `Exited` → restart: `cd /scratch/modelseed && docker compose -f modelseed-api/docker-compose.yml up -d`
   - Container is `(unhealthy)` or restarting in a loop → check logs (next step) before restarting again.
3. **Read the last 50 lines of logs:** `docker logs --tail 50 modelseed-api-api-1`. Match against "Common issues" below.
4. **Are jobs stuck?** Check the worker: `docker ps --filter name=celery_modelseed` and `docker logs --tail 50 celery_modelseed`. See "Celery worker operations" below.
5. **Still stuck?** Page Jose (jplfaria) or Chris Henry via your team's usual channel.

## Access

```
ssh <your-username>@poplar.cels.anl.gov
cd /scratch/modelseed
```

All repos and Docker files live under `/scratch/modelseed/`. The directory has group ownership (`HenryLab`, mode 770) so any team member can manage the service.


## Check if the service is running

```bash
# Quick health check (from anywhere with network access)
curl -s http://poplar.cels.anl.gov:3004/api/health

# Expected: {"status":"ok","version":"0.1.0"}
# If no response or connection refused → service is down

# Note: the container listens on 8000 internally; the host publishes it
# on 3004. External traffic uses :3004; anything `docker exec`'d into
# the container uses :8000.
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
cd /scratch/modelseed
docker compose -f modelseed-api/docker-compose.yml restart api
```

### Restart after code changes

```bash
cd /scratch/modelseed
docker compose -f modelseed-api/docker-compose.yml build --no-cache api
docker compose -f modelseed-api/docker-compose.yml up -d
```

**Important:** Do NOT use `docker compose up --build` — it may use cached layers and miss dependency changes. Always use `build --no-cache` when dependencies have changed.

### Full reset (nuclear option)

If the container is in a bad state (won't stop, zombie process, etc.):

```bash
cd /scratch/modelseed
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
- Host port 3004 already in use by another process
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
# - "Address already in use" → another process on host port 3004 (or 8000 inside container)
```

### "Connection refused" but container shows as running

```bash
# Check if uvicorn is actually listening (inside the container, port 8000)
docker exec modelseed-api-api-1 ss -tlnp | grep 8000

# Check the host-side mapping is in place (port 3004 on poplar)
ss -tlnp | grep 3004

# From poplar itself, hit the host-published port
curl -s http://localhost:3004/api/health
```

If `:8000` is listening inside but `:3004` is not on the host, the Docker port publish is broken — restart the container.

### Health check shows "unhealthy" but API works in browser

The health check runs *inside* the container (`localhost:8000`). If the API responds to external requests but the health check fails, the issue is inside the container:

```bash
docker exec modelseed-api-api-1 python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').read())"
```

### Updating code

```bash
cd /scratch/modelseed/modelseed-api
git pull

# If only modelseed-api code changed:
docker compose -f docker-compose.yml build --no-cache api && docker compose -f docker-compose.yml up -d

# If dependency repos changed too (ModelSEEDpy, KBUtilLib, etc.):
cd /scratch/modelseed
cd ModelSEEDpy && git pull && cd ..
cd KBUtilLib && git pull && cd ..
# ... etc for any changed repo
docker compose -f modelseed-api/docker-compose.yml build --no-cache api
docker compose -f modelseed-api/docker-compose.yml up -d
```


## Celery worker operations

The API container dispatches long-running jobs (reconstruct, gapfill, FBA, merge) to a separate worker container called `celery_modelseed`. Both containers are defined in the same `docker-compose.yml` and join the external `bioseed_network` so they can reach the shared `bioseed_redis` broker on DB 10, queue `modelseed`.

The deployed compose sets `MODELSEED_USE_CELERY=true` for both services. Subprocess mode is dev-only.

### Check the worker

```bash
# Worker status
docker ps --filter name=celery_modelseed

# Should show: Up <time> with no restart loops
docker logs --tail 100 celery_modelseed

# Healthy startup ends with lines like:
#   celery@modelseed@<hostname> ready.
#   [tasks] modelseed_api.jobs.tasks.reconstruct (etc.)
```

### Worker concurrency and limits

| Setting | Value | Where |
|---------|-------|-------|
| Concurrency | 2 | `celery_app.py` `main()` `--concurrency=2` |
| Prefetch | 1 | `worker_prefetch_multiplier=1` (one task per slot, no hoarding) |
| Task hard limit | 4 hours | `task_time_limit=3600 * 4` |
| `acks_late` | true | tasks ack only after completion |
| `reject_on_worker_lost` | true | crashed worker re-queues mid-task |
| `stop_grace_period` | 15 min | docker waits before SIGKILL on `down`/`restart` |

Two slots × 4-hour ceiling means at most two long jobs at once; further jobs queue in Redis.

### Restart the worker (the safe way)

`reconstruct + gapfill` runs ~6–10 min; FBA ~10 s. The 15-minute stop grace lets in-flight tasks finish before SIGKILL, and `acks_late` re-queues anything still running when the timeout hits. So:

```bash
cd /scratch/modelseed
docker compose -f modelseed-api/docker-compose.yml restart worker
```

Do **not** `docker kill celery_modelseed` — that bypasses the grace period and can leave half-done state in the model workspace (worth re-running but worth knowing).

### Inspect the queue

```bash
# Queue depth (number of pending tasks)
docker exec bioseed_redis redis-cli -n 10 LLEN modelseed

# Peek at the next task without removing it
docker exec bioseed_redis redis-cli -n 10 LINDEX modelseed 0

# Inspect via Celery instead of Redis
docker exec celery_modelseed celery -A modelseed_api.jobs.celery_app inspect active
docker exec celery_modelseed celery -A modelseed_api.jobs.celery_app inspect reserved
docker exec celery_modelseed celery -A modelseed_api.jobs.celery_app inspect stats
```

### Drain stuck tasks

If the queue fills with tasks that should not run (e.g. accidental flood, bad client), purge it:

```bash
# DESTRUCTIVE: removes all queued tasks but does not affect ones already running
docker exec celery_modelseed celery -A modelseed_api.jobs.celery_app purge -Q modelseed -f
```

If a task is wedged inside a worker and won't finish, restart the worker container — the grace period gives it 15 min to finish, then SIGKILL fires. With `acks_late`, the task re-queues and retries on next worker startup, so make sure you've fixed the underlying bug or the next worker will get stuck on the same task.

### Flower (live monitoring)

http://poplar.cels.anl.gov:5555/ — runs as part of the bioseed scheduler stack, not in this compose. Shows live task list, history, worker heartbeat, and per-task tracebacks. If Flower is down but the worker is fine, the issue is on the bioseed side; if both are down, check `bioseed_redis`.

### Job state versus Celery state

The API serves job status from JSON files in `/tmp/modelseed-jobs/` (mounted as the `modelseed-jobs` Docker volume, shared between `api` and `worker` containers). Celery's own result backend is also Redis, but the API does NOT read from it. The bridge is in `celery_app.py` — `task_prerun`, `task_postrun`, and `task_failure` signals call into `JobStore` to keep the JSON files in sync.

If a job shows as "running" forever in the API but Celery says it succeeded, suspect the signal bridge: check `docker logs celery_modelseed` for exceptions in the bridge handlers, and check the JSON file directly:

```bash
docker exec modelseed-api-api-1 ls /tmp/modelseed-jobs/
docker exec modelseed-api-api-1 cat /tmp/modelseed-jobs/<job-id>.json
```

## Disk, logs, and persisted state

### Where things live

| Path (on poplar host) | What | Volatility |
|---|---|---|
| `/scratch/modelseed/` | All source + dependency repos | Persistent, group `HenryLab` |
| Docker volume `modelseed-api_modelseed-jobs` | Job state JSON files | Persistent across restarts; lost if volume is `rm`'d |
| Docker container logs | uvicorn + Celery stdout/stderr | Capped by Docker's default rotation if configured at daemon level; otherwise grows until container is removed |
| `bioseed_redis` (separate container, owned by bioseed scheduler stack) | Celery queue, task results | Persistent per Redis policy; not our concern |
| PATRIC workspace | All models, gapfills, FBA results | Authoritative storage — owned by PATRIC, not us |

### Things to monitor

```bash
# Disk usage on /scratch
df -h /scratch

# Docker disk usage (images, containers, volumes, build cache)
docker system df

# Job store size (grows over time; each job is a small JSON file)
docker exec modelseed-api-api-1 du -sh /tmp/modelseed-jobs/
```

### Cleanup

If `/scratch` gets tight, the safe wins are old Docker images and the build cache:

```bash
# Remove dangling images + unused build cache (does not touch running containers or named volumes)
docker system prune -a --volumes=false
```

Do NOT prune the `modelseed-api_modelseed-jobs` volume — it holds the job-status JSON files the API serves to the frontend. Old job records can be removed file-by-file inside the container if needed; there is no automated retention policy yet.

## Verify after restart

```bash
# 1. Health check
curl -s http://poplar.cels.anl.gov:3004/api/health

# 2. Biochem search (no auth needed)
curl -s "http://poplar.cels.anl.gov:3004/api/biochem/search?query=glucose&type=compounds" | head -c 200

# 3. Demo page loads
curl -s -o /dev/null -w "%{http_code}" http://poplar.cels.anl.gov:3004/demo/
# Expected: 200
```

Or open http://poplar.cels.anl.gov:3004/demo/ in a browser.


## Architecture summary

```
User → poplar:3004 → Docker container (modelseed-api-api-1, listening :8000 internally)
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
| `/scratch/modelseed/modelseed-api/` | This repo |
| `/scratch/modelseed/ModelSEEDpy/` | Modeling engine (cshenry fork) |
| `/scratch/modelseed/KBUtilLib/` | KBase utility library |
| `/scratch/modelseed/cobrakbase/` | KBase/cobra bridge |
| `/scratch/modelseed/ModelSEEDDatabase/` | Biochemistry data (dev branch) |
| `/scratch/modelseed/ModelSEEDTemplates/` | Model templates v7.0 |
| `/scratch/modelseed/cb_annotation_ontology_api/` | Annotation ontology |


## Contacts

- **Source code**: https://github.com/ModelSEED/modelseed-api
- **Swagger docs**: http://poplar.cels.anl.gov:3004/docs
- **Flower (job monitoring)**: http://poplar.cels.anl.gov:5555/
