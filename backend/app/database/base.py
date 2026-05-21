from sqlalchemy.orm import declarative_base


Base = declarative_base()

# Import models so SQLAlchemy metadata includes every table before create_all().
# Order matters for FK targets: users/projects must exist before tables that
# reference them.
from backend.app.models import (  # noqa: E402,F401
    user,
    project,
    workflow,
    artifact,
    repository_analysis,
    task,
)
