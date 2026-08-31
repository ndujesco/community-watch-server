"""Email delivery for Warning/Emergency alerts, via the user's own
email-composer service (https://email-composer-phi.vercel.app), a small
Next.js + nodemailer app that sends through Gmail. Replaces SMS entirely —
see the project README for why (Termii needed business verification that
couldn't be completed; Twilio's trial blocks all custom message content;
rather than keep fighting SMS providers, alerts go by email instead).

API contract (read directly from that project's source,
src/app/api/send-email/route.ts): POST {url}/api/send-email, JSON body
{to, subject, body}, where body is an HTML string. A missing/unreachable
service just fails the send silently from the caller's perspective — the
alert is still recorded with "email" in its channels list either way.
"""
from __future__ import annotations

import logging

import httpx

from .config import get_settings

logger = logging.getLogger("floodwatch.email")


async def send_alert_email(to: str, subject: str, html_body: str) -> bool:
    settings = get_settings()
    url = f"{settings.email_composer_url.rstrip('/')}/api/send-email"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url, json={"to": to, "subject": subject, "body": html_body}
            )
        ok = resp.status_code == 200
        if ok:
            logger.info("[EMAIL] sent to %s", to)
        else:
            logger.warning("[EMAIL] to %s failed: HTTP %s %s", to, resp.status_code, resp.text)
        return ok
    except Exception as exc:
        logger.warning("[EMAIL] to %s raised %s: %s", to, type(exc).__name__, exc)
        return False
