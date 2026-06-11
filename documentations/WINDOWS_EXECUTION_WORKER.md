# Windows Deployment Note — Execution Worker

> Documentation only. This note does **not** change runtime logic — it records the
> supported worker topology when the platform runs on Windows.

The durable-job **execution worker** drains the `execution_jobs` queue (Docker
builds, corrector re-analysis, and — later — `terraform` execution). It can run
two ways:

| Topology | API process | Worker | When to use |
| --- | --- | --- | --- |
| In-process (default) | `EXECUTION_WORKER_ENABLED=true` | runs inside the API's asyncio loop | local dev, single-container |
| Standalone (recommended on Windows) | `EXECUTION_WORKER_ENABLED=false` | dedicated `python -m backend.app.workers.execution_worker` process, started with `EXECUTION_WORKER_ENABLED=true` | long Docker/terraform jobs, production |

- Default flag: `EXECUTION_WORKER_ENABLED` defaults to `True`
  ([config.py](../backend/app/core/config.py)); the API lifespan starts the
  in-process worker when it is true
  ([app_factory.py](../backend/app/core/app_factory.py#L150)).

## Why prefer a standalone worker on Windows

`loop.add_signal_handler(SIGINT/SIGTERM, …)` raises `NotImplementedError` on
Windows, so the in-process worker's **graceful shutdown is degraded** there
([execution_worker.py](../backend/app/workers/execution_worker.py#L303-L309)).
A long Docker build sharing the API's event loop can therefore be cut off
without draining on restart. Running the worker as its own process isolates
those long-running subprocesses from the HTTP server and from uvicorn reloads.

## Recommended Windows setup

Run two processes:

```powershell
# 1. Worker process — owns execution. Keep the worker enabled here.
$env:EXECUTION_WORKER_ENABLED = "true"
python -m backend.app.workers.execution_worker

# 2. API process — serves HTTP only; disable its in-process worker so the
#    queue is not drained twice.
$env:EXECUTION_WORKER_ENABLED = "false"
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Notes:
- Live Docker build-log streaming over the WebSocket is in-memory per process.
  With a standalone worker, **DB log replay** still works; cross-process *live*
  streaming would require a shared broker (not enabled by default).
- Per-project mutual exclusion is enforced by the database (partial unique index)
  plus `JobService.claim_next_job`, so running the worker separately from the API
  is safe and does not double-execute a project.
