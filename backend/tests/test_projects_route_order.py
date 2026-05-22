"""Guards against the route-collision regression where ``/{project_id}`` ate
``/me/identity``.

We don't need a running app — the APIRouter's ``routes`` list reflects
declaration order, which is what FastAPI uses to dispatch. The contract this
test enforces is: any STATIC path under ``/api/projects/me/...`` (and other
known static prefixes) must be declared BEFORE the first dynamic route that
takes ``{project_id}`` as its first path parameter.
"""

from __future__ import annotations

import pytest

from backend.app.api.routes.projects import router


# Routes attached to an APIRouter with a prefix store the FULL path on the
# route object — so /me/identity registered on a router with prefix
# /api/projects becomes /api/projects/me/identity. We strip the prefix at
# read time to keep the assertions readable.
_PREFIX = "/api/projects"


def _route_records():
    """Return (idx, method, relative_path) tuples in declaration order.

    FastAPI dispatches per (method, path). Two routes with different methods
    can never collide regardless of order, so the ordering rule we enforce
    is scoped to a single HTTP method.
    """
    records = []
    for idx, route in enumerate(router.routes):
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue
        rel = path[len(_PREFIX):] if path.startswith(_PREFIX) else path
        if not rel:
            rel = "/"
        for method in methods:
            records.append((idx, method.upper(), rel))
    return records


def test_get_me_identity_precedes_dynamic_get_project_id():
    """GET /me/identity must come before GET /{project_id}.

    This is the exact regression we fixed — a literal "me" was being matched
    against the dynamic ``{project_id}`` segment.
    """
    records = _route_records()
    static_idx = next(
        (i for i, m, p in records if m == "GET" and p == "/me/identity"),
        None,
    )
    dynamic_idx = next(
        (i for i, m, p in records if m == "GET" and p == "/{project_id}"),
        None,
    )
    assert static_idx is not None, (
        f"GET /me/identity is missing. Records: {records}"
    )
    assert dynamic_idx is not None, "GET /{project_id} is missing"
    assert static_idx < dynamic_idx, (
        f"GET /me/identity (idx={static_idx}) must precede "
        f"GET /{{project_id}} (idx={dynamic_idx}) — FastAPI matches in "
        f"declaration order and the dynamic route would capture 'me'."
    )


def test_no_top_level_static_get_after_dynamic_get_route():
    """Future-proofing: no new TOP-LEVEL static GET path may land below the
    first dynamic GET ``/{project_id}*`` route.

    Per-method scope — a POST below a GET is fine because the dispatch
    tables are independent. Project-scoped sub-paths (``/{project_id}/...``)
    are also fine; only literal-top-level paths are at risk of being shadowed.
    """
    records = _route_records()
    get_records = [(i, p) for i, m, p in records if m == "GET"]
    first_dynamic = next(
        (i for i, p in get_records if p.startswith("/{project_id}")),
        None,
    )
    if first_dynamic is None:
        pytest.skip("no dynamic GET /{project_id} route registered")

    offenders = []
    for idx, p in get_records:
        if idx <= first_dynamic:
            continue
        if p.startswith("/{") or p == "/":
            continue
        offenders.append((idx, p))

    assert not offenders, (
        "Static GET route(s) declared AFTER the dynamic /{project_id} "
        f"block — move them above: {offenders}"
    )
