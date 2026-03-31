from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import engine


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)

    app = FastAPI(title=settings.APP_NAME)

    app.include_router(api_router)

    @app.get("/")
    def root():
        return {
            "message": "DevSecOps AI Platform API is running",
            "environment": settings.APP_ENV,
        }

    return app