"""SMS delivery via Twilio (https://twilio.com) for Warning/Emergency alerts.

Twilio, not Termii: a trial account needs no business verification — you
verify your own phone number as a recipient and send real SMS to it for
free using trial credit. See SMS_SETUP.md.

API contract (Twilio's REST API, form-encoded, HTTP Basic Auth):
POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json
"""
from __future__ import annotations

import logging

import httpx

from .config import get_settings

logger = logging.getLogger("floodwatch.sms")


async def send_sms(to: str, message: str) -> bool:
    settings = get_settings()
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number):
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    data = {"To": to, "From": settings.twilio_from_number, "Body": message}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                data=data,
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
        ok = resp.status_code in (200, 201)
        if ok:
            sid = resp.json().get("sid")
            logger.info("[SMS] sent to %s (sid=%s)", to, sid)
        else:
            logger.warning("[SMS] to %s failed: HTTP %s %s", to, resp.status_code, resp.text)
        return ok
    except Exception as exc:
        logger.warning("[SMS] to %s raised %s: %s", to, type(exc).__name__, exc)
        return False
