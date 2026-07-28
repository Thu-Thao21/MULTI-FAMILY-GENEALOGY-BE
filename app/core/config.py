from pydantic import BaseSettings

class Settings(BaseSettings):
    MONGODB_URI: str = "mongodb://localhost:27017"
    MONGODB_DB: str = "multi_family_db"

    class Config:
        env_file = ".env"

settings = Settings()
