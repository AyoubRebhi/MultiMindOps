from sqlalchemy.orm import declarative_base


Base = declarative_base()

# Import models so SQLAlchemy metadata includes every table before create_all().
from backend.app.models import repository_analysis, task  # noqa: E402,F401
