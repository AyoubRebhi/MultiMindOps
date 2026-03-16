from pydantic import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./devsecops.db"

    class Config:
        env_file = ".env"


settings = Settings()
