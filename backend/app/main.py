from fastapi import FastAPI

from backend.app.api.routes.tasks import router as task_router
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import engine
from backend.app.api.routes.health import router as health_router 

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME)

app.include_router(task_router)
app.include_router(health_router)


@app.get("/")
def root():
    return {
        "message": "DevSecOps AI Platform API is running",
        "environment": settings.APP_ENV,
    }