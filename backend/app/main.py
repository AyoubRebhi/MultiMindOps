from fastapi import FastAPI

from .api.routes.tasks import router as tasks_router
from .database import base
from .database.session import engine


# Ensure all database tables are created on startup.
base.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MultiMindOps API")

app.include_router(tasks_router)


@app.get("/")
def root() -> dict:
    return {"status": "ok"}
