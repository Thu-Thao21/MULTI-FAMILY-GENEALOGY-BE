from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional

client: Optional[AsyncIOMotorClient] = None

def connect_mongo(uri: str):
    global client
    client = AsyncIOMotorClient(uri)
    return client


def get_database(db_name: str):
    if not client:
        raise RuntimeError("MongoDB client is not initialized")
    return client[db_name]


def close_mongo():
    global client
    if client:
        client.close()
