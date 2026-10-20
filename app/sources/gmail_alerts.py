"""Gmail'e gelen LinkedIn / Kariyer.net ilan alarmı e-postalarını IMAP ile okur."""
from __future__ import annotations

import email
import imaplib
import logging
import re
import ssl
from datetime import datetime, timedelta
from email.header import decode_header, make_header

import certifi
import httpx

from app.config import env
from app.models import Job
from app.sources import kariyernet

log = logging.getLogger(__name__)

SENDERS = ["linkedin.com", "kariyer.net"]
LINK_RE = re.compile(r"https?://[^\s\"'<>]+")


def _body(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    out = []
    for p in parts:
        if p.get_content_type() in ("text/html", "text/plain"):
            payload = p.get_payload(decode=True)
            if payload:
                out.append(payload.decode(p.get_content_charset() or "utf-8", errors="ignore"))
    return "\n".join(out)


def fetch(client: httpx.Client, lookback_days: int) -> list[Job]:
    address = env("GMAIL_ADDRESS", required=False)
    password = env("GMAIL_APP_PASSWORD", required=False)
    if not address or not password:
        log.info("Gmail bilgileri yok; e-posta alarmları atlanıyor.")
        return []

    ctx = ssl.create_default_context(cafile=certifi.where())
    since = (datetime.now() - timedelta(days=lookback_days)).strftime("%d-%b-%Y")
    jobs: dict[str, Job] = {}

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", ssl_context=ctx)
        imap.login(address, password.replace(" ", ""))
        imap.select("INBOX", readonly=True)
    except Exception as e:  # noqa: BLE001
        log.warning("Gmail'e bağlanılamadı: %s", e)
        return []

    try:
        for sender in SENDERS:
            _, data = imap.search(None, f'(FROM "{sender}" SINCE {since})')
            for num in data[0].split():
                _, msg_data = imap.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                subject = str(make_header(decode_header(msg.get("Subject", ""))))
                body = _body(msg)
                links = set(LINK_RE.findall(body))

                if "linkedin" in sender:
                    for jid in set(re.findall(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", body)):
                        jobs[f"li{jid}"] = Job("LinkedIn", jid, "", "", "",
                                               f"https://www.linkedin.com/jobs/view/{jid}")
                else:
                    resolved = 0
                    for link in links:
                        job = kariyernet.job_from_url(link)
                        # Takip (yönlendirme) linklerini çözmeyi dene
                        if job is None and "kariyer" in link and resolved < 20:
                            try:
                                resolved += 1
                                job = kariyernet.job_from_url(str(client.head(link).url))
                            except httpx.HTTPError:
                                pass
                        if job:
                            jobs[f"kn{job.native_id}"] = job
                log.debug("E-posta işlendi: %s", subject)
    finally:
        imap.logout()

    log.info("Gmail alarmları: %d ilan bulundu", len(jobs))
    return list(jobs.values())
