"""Pebble Index 01 -> new Claude session per recording.

Receives Index 01 webhook deliveries (protocol v1, see INDEX_WEBHOOK_API.md in
coredevices/mobileapp), verifies the HMAC signature, and fires a Claude Code
scheduled task's API trigger with the transcript. Each fire starts a new Claude
session that reads the recording and decides what to do with it.
"""

import hashlib
import hmac
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests
from flask import Flask, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pebble-router")

SIGNING_SECRET = os.environ.get("INDEX_WEBHOOK_SECRET", "").encode()
ROUTER_TOKEN = os.environ.get("ROUTER_TOKEN", "")  # optional extra header auth
FIRE_URL = os.environ.get("ROUTINE_FIRE_URL", "")  # https://api.anthropic.com/v1/claude_code/routines/<id>/fire
FIRE_TOKEN = os.environ.get("ROUTINE_TOKEN", "")
FIRE_BETA = os.environ.get("ROUTINE_BETA", "experimental-cc-routine-2026-04-01")
MAX_SKEW_SECONDS = 300

app = Flask(__name__)

_seen: dict[str, float] = {}
_seen_lock = threading.Lock()
SEEN_TTL = 24 * 3600  # the app retries for ~10 minutes; keep IDs well past that


# ---------- webhook verification ----------

def _verify(raw_body: bytes) -> tuple[bool, str]:
    h = request.headers
    if h.get("X-Index-Webhook-Version") != "1":
        return False, "unsupported webhook version"
    if ROUTER_TOKEN and h.get("Authorization") != f"Bearer {ROUTER_TOKEN}":
        return False, "bad token"
    if not SIGNING_SECRET:
        return True, "unsigned (INDEX_WEBHOOK_SECRET not set)"
    try:
        ts = int(h.get("X-Index-Timestamp", ""))
    except ValueError:
        return False, "invalid timestamp"
    if abs(time.time() - ts) > MAX_SKEW_SECONDS:
        return False, "expired request"
    prefix = (
        f"v1\n{ts}\n{h.get('X-Index-Delivery', '')}\n"
        f"{h.get('X-Index-Trigger', '')}\n{1 if h.get('X-Index-Test') == 'true' else 0}\n"
    )
    expected = hmac.new(SIGNING_SECRET, prefix.encode() + raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, h.get("X-Index-Signature", "")):
        return False, "invalid signature"
    return True, "ok"


def _was_fired(delivery_id: str) -> bool:
    now = time.time()
    with _seen_lock:
        for k in [k for k, t in _seen.items() if now - t > SEEN_TTL]:
            del _seen[k]
        return delivery_id in _seen


def _mark_fired(delivery_id: str) -> None:
    with _seen_lock:
        _seen[delivery_id] = time.time()


# ---------- fire the Claude session ----------

GESTURES = {"single-click-hold": "Hold & talk", "double-click-hold": "Double click & hold"}


def _fire_text(transcript: str, recorded_at: str, trigger: str, delivery_id: str) -> str:
    try:
        when = datetime.fromtimestamp(int(recorded_at) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        when = "unknown"
    return (
        "Source: Pebble Index 01 ring voice recording\n"
        f"Recorded at (UTC): {when}\n"
        f"Gesture: {GESTURES.get(trigger, trigger or 'unknown')}\n"
        f"Delivery ID: {delivery_id}\n\n"
        f"Transcript:\n{transcript}"
    )


def fire_session(text: str) -> requests.Response:
    return requests.post(
        FIRE_URL,
        headers={
            "Authorization": f"Bearer {FIRE_TOKEN}",
            "anthropic-beta": FIRE_BETA,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={"text": text},
        timeout=30,
    )


@app.post("/index-webhook")
def index_webhook():
    raw = request.get_data(cache=True)
    ok, why = _verify(raw)
    if not ok:
        log.warning("rejected: %s", why)
        return why, 401 if why in ("invalid signature", "bad token", "expired request") else 400

    delivery_id = request.headers.get("X-Index-Delivery", "")
    trigger = request.headers.get("X-Index-Trigger", "")
    if request.headers.get("X-Index-Test") == "true":
        log.info("test event received (%s); session firing %s", why,
                 "configured" if FIRE_URL and FIRE_TOKEN else "NOT configured")
        return "test ok", 200
    if delivery_id and _was_fired(delivery_id):
        return "already received", 200

    transcript = (request.form.get("transcription") or "").strip()
    if not transcript:
        # Audio-only payloads carry nothing to send; set the ring to "Transcription only" or "Both".
        log.info("delivery=%s has no transcription; ignored", delivery_id)
        return "no transcription in payload", 200

    if not (FIRE_URL and FIRE_TOKEN):
        log.error("delivery=%s: ROUTINE_FIRE_URL / ROUTINE_TOKEN not set", delivery_id)
        return "session target not configured", 503  # the ring app retries

    text = _fire_text(transcript, request.form.get("recordedAt", ""), trigger, delivery_id)
    try:
        r = fire_session(text)
    except requests.RequestException as e:
        log.error("delivery=%s fire failed: %s", delivery_id, e)
        return "could not reach Claude", 502

    if r.ok:
        if delivery_id:
            _mark_fired(delivery_id)
        session_url = (r.json() or {}).get("claude_code_session_url", "")
        log.info("delivery=%s -> new session %s", delivery_id, session_url)
        return "session started", 200

    log.error("delivery=%s fire returned %s: %s", delivery_id, r.status_code, r.text[:300])
    # Any 5xx makes the ring app retry (every minute, up to 10 times), so a bad token or
    # the 30-fires-per-hour limit doesn't lose the recording.
    return f"Claude returned {r.status_code}", 503


@app.get("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
