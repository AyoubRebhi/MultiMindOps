"""Durable execution worker package.

* ``handlers``          — phase → coroutine registry that does the actual work.
* ``execution_worker``  — the polling loop that claims jobs and runs handlers.

Both are importable without side effects so the API process can embed the
worker (in-process mode) or a standalone process can run it
(``python -m backend.app.workers.execution_worker``).
"""
