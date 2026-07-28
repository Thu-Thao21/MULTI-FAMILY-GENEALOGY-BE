from typing import Any
from app.core.config import settings
from app.db.mongodb import get_database

# Dependency helper that returns a Motor database instance
def get_db() -> Any:
    return get_database(settings.MONGODB_DB)
