"""Helpers to turn MongoDB documents into JSON-serialisable dicts."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def jsonify(doc: Any) -> Any:
    """Recursively convert Mongo documents into JSON-safe structures.

    * ObjectId -> str (under ``id``; the raw ``_id`` is dropped)
    * datetime -> ISO 8601 string with trailing Z
    """
    if isinstance(doc, list):
        return [jsonify(d) for d in doc]
    if isinstance(doc, dict):
        out: dict[str, Any] = {}
        for key, value in doc.items():
            if key == "_id":
                out["id"] = str(value)
                continue
            out[key] = jsonify(value)
        return out
    if isinstance(doc, datetime):
        # Stored as naive UTC; emit ISO 8601 with explicit Z so the browser
        # parses it as UTC rather than local time.
        if doc.tzinfo is None:
            return doc.isoformat() + "Z"
        return doc.isoformat()
    return doc
