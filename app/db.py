"""Async MongoDB access layer (pymongo AsyncMongoClient)."""
from __future__ import annotations

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from .config import get_settings

_client: AsyncMongoClient | None = None
_db: AsyncDatabase | None = None


async def connect() -> AsyncDatabase:
    """Open the shared client and ensure indexes exist."""
    global _client, _db
    if _db is not None:
        return _db
    settings = get_settings()
    _client = AsyncMongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
    _db = _client.get_database(settings.database_name)
    await _client.admin.command("ping")
    await ensure_indexes(_db)
    return _db


async def disconnect() -> None:
    global _client, _db
    if _client is not None:
        await _client.close()
    _client = None
    _db = None


def get_database() -> AsyncDatabase:
    if _db is None:
        raise RuntimeError("Database not connected. Call connect() first.")
    return _db


async def ensure_indexes(db: AsyncDatabase) -> None:
    await db.sites.create_index([("site_id", ASCENDING)], unique=True)
    await db.stations.create_index([("station_id", ASCENDING)], unique=True)
    await db.stations.create_index([("site_id", ASCENDING)])
    await db.readings.create_index([("station_id", ASCENDING), ("ts", DESCENDING)])
    await db.readings.create_index([("site_id", ASCENDING), ("ts", DESCENDING)])
    await db.readings.create_index([("ts", DESCENDING)])
    await db.alerts.create_index([("ts", DESCENDING)])
    await db.alerts.create_index([("site_id", ASCENDING), ("ts", DESCENDING)])
    await db.alerts.create_index([("alert_id", ASCENDING)], unique=True)
    # Subscribers moved from phone (SMS) to email -- drop the old unique
    # index if it's still there from before, so a second email-only
    # subscriber doesn't collide as a "duplicate" missing phone value.
    try:
        await db.subscribers.drop_index("phone_1")
    except Exception:
        pass  # already gone, or never existed on this database
    await db.subscribers.create_index([("email", ASCENDING)], unique=True)


# Collection accessors -------------------------------------------------------
def sites():
    return get_database().sites


def stations():
    return get_database().stations


def readings():
    return get_database().readings


def alerts():
    return get_database().alerts


def subscribers():
    return get_database().subscribers
