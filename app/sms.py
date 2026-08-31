"""SMS delivery via Vonage (https://vonage.com), alongside email, for
Warning/Emergency alerts. Kept alongside email_alerts.py rather than
replacing it -- SMS only fires if Vonage credentials are actually present
and working; email always fires regardless.

API contract per Vonage's own documentation (developer.vonage.com/api/sms):
POST https://rest.nexmo.com/sms/json, form-encoded
{api_key, api_secret, to, from, text}. Missing key/secret disables sending
entirely -- the alert is still recorded with "sms" in its channels list
only when it actually sends; see services.py::_create_alert.
"""
from __future__ import annotations

import logging

import httpx

from .config import get_settings

logger = logging.getLogger("floodwatch.sms")


async def send_sms(to: str, message: str) -> bool:
    settings = get_settings()
    if not (settings.vonage_api_key and settings.vonage_api_secret):
        return False

    to_number = to.lstrip("+")  # Vonage wants numbers without a leading "+"

    data = {
        "api_key": settings.vonage_api_key,
        "api_secret": settings.vonage_api_secret,
        "to": to_number,
        "from": settings.vonage_from,
        "text": message,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("https://rest.nexmo.com/sms/json", data=data)
        body = resp.json()
        first = (body.get("messages") or [{}])[0]
        ok = resp.status_code == 200 and first.get("status") == "0"
        if ok:
            logger.info("[SMS] sent to %s (message-id=%s)", to, first.get("message-id"))
        else:
            logger.warning(
                "[SMS] to %s failed: status=%s error=%s",
                to, first.get("status"), first.get("error-text"),
            )
        return ok
    except Exception as exc:
        logger.warning("[SMS] to %s raised %s: %s", to, type(exc).__name__, exc)
        return False
