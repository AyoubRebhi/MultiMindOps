"""Repository Installation phase.

Installs the AI-generated GitHub Actions pipelines (``bootstrap.yml`` +
``deploy.yml``) INTO the user's repository — the last step that turns generated
artifacts into a reviewable change set the user can merge.

Safety is the governing principle (see :mod:`installation_service`):

* the workflows are pushed onto a DEDICATED installation branch
  (``multiminds/devops-pipelines``) — NEVER ``main`` / ``master`` / ``develop``;
* only the two ``.github/workflows/*.yml`` files are ever staged — no other
  file in the repository is read, modified, or deleted;
* no force-push, ever — reruns add a fast-forward commit or no-op;
* a Pull Request is opened best-effort and degrades to a skip if it cannot be.
"""
