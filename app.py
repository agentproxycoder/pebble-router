"""Pebble Index 01 -> Claude context router.

Receives Index 01 webhook deliveries (protocol v1, see INDEX_WEBHOOK_API.md in
coredevices/mobileapp), verifies the HMAC signature, asks Claude which route the
spoken prompt belongs to, and forwards it to that route's destination webhook.
"""

import hashlib
import hmac
import json
import logging
import os
import threading
import time

import anthropic
import requests
from flask import Flask, request

from routes import ROUTES, TRIGGER_OVERRIDES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pebble-router")

SIGNING_SECRET = os.environ.get("INDEX_WEBHOOK_SECRET", "").encode()
BEARER_TOKEN = os.environ.get("ROUTER_TOKEN", "")  # optional extra header auth
MAX_SKEW_SECONDS = 300
MODEL = os.environ.get("ROUTER_MODEL", "claude-opus-5-5")

app = Flask(__name__)
client = anthropic.Anthropic()

_seen: dict[str, float] = {}
_seen_lock = threading.Lock()


# ---------- webhook verification ----------

def _verify(raw_body: bytes) -> tuple[bool, str]:
    h = request.headers
    if h.get("X-Index-Webhook-Version") != "1":
        return False, "unsupported webhook version"
    if BEARER_TOKEN and h.get("Authorization") != f"Bearer {BEARER_TOKEN}":
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


def _already_seen(delivery_id: str) -> bool:
    now = time.time()
    with _seen_lock:
        for k in [k for k, t in _seen.items() if now - t > 2 * MAX_SKEW_SECONDS]:
            del _seen[k]
        if delivery_id in _seen:
            return True
        _seen[delivery_id] = now
        return False


# ---------- Claude routing ----------

ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": list(ROUTES)},
        "confidence": {"type": "number"},
        "title": {"type": "string"},
        "cleaned_prompt": {"type": "string"},
        "entities": {
            "type": "object",
            "properties": {
                "people": {"type": "array", "items": {"type": "string"}},
                "organizations": {"type": "array", "items": {"type": "string"}},
                "association": {"type": "string"},
                "due": {"type": "string"},
                "amount": {"type": "string"},
            },
            "required": ["people", "organizations", "association", "due", "amount"],
            "additionalProperties": False,
        },
        "reason": {"type": "string"},
    },
    "required": ["route", "confidence", "title", "cleaned_prompt", "entities", "reason"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You route short voice prompts dictated into a smart ring by someone who raises money "
    "for medical associations and drives their memberships. Pick exactly one route for the "
    "prompt based on what the speaker wants done.\n\nRoutes:\n"
    + "\n".join(f"- {name}: {r['description']}" for name, r in ROUTES.items())
    + "\n\nAlso return a short title, the prompt rewritten as a clear instruction with filler "
    "words and transcription errors fixed (keep the speaker's meaning), any people, "
    "organizations, association name or code, due date/time (as spoken, or empty), and dollar "
    "amount mentioned (empty strings / empty lists when absent). confidence is 0-1. If nothing "
    "fits well, use the 'note' route."
)


def classify(transcript: str, recorded_at: str) -> dict:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": ROUTE_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": f"Recorded at (unix ms): {recorded_at}\n\nTranscript:\n{transcript}",
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to classify this prompt")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# ---------- dispatch ----------

def dispatch(decision: dict, payload: dict) -> str:
    route = ROUTES[decision["route"]]
    url = os.environ.get(route["env"], "")
    body = {**payload, **decision}
    if not url:
        log.info("route=%s (no %s set, logged only): %s", decision["route"], route["env"], body)
        return "logged"
    r = requests.post(url, json=body, timeout=15)
    r.raise_for_status()
    return f"forwarded ({r.status_code})"


def process(transcript: str, recorded_at: str, trigger: str, delivery_id: str) -> None:
    try:
        forced = TRIGGER_OVERRIDES.get(trigger)
        decision = classify(transcript, recorded_at)
        if forced:
            decision["reason"] = f"forced by gesture {trigger}; model suggested {decision['route']}"
            decision["route"] = forced
        result = dispatch(decision, {
            "transcript": transcript,
            "recorded_at": recorded_at,
            "trigger": trigger,
            "delivery_id": delivery_id,
        })
        log.info("delivery=%s route=%s conf=%.2f -> %s",
                 delivery_id, decision["route"], decision["confidence"], result)
    except Exception:
        log.exception("delivery=%s failed", delivery_id)


@app.post("/index-webhook")
def index_webhook():
    raw = request.get_data(cache=True)
    ok, why = _verify(raw)
    if not ok:
        log.warning("rejected: %s", why)
        return why, 401 if "signature" in why or "token" in why or "expired" in why else 400

    delivery_id = request.headers.get("X-Index-Delivery", "")
    trigger = request.headers.get("X-Index-Trigger", "")
    if request.headers.get("X-Index-Test") == "true":
        log.info("test event received (%s)", why)
        return "test ok", 200
    if delivery_id and _already_seen(delivery_id):
        return "already received", 200

    transcript = (request.form.get("transcription") or "").strip()
    if not transcript:
        # Audio-only payloads carry nothing to route; set the ring to "Transcription only" or "Both".
        return "no transcription in payload", 200

    # Reply fast so the app doesn't retry; route in the background.
    threading.Thread(
        target=process,
        args=(transcript, request.form.get("recordedAt", ""), trigger, delivery_id),
        daemon=True,
    ).start()
    return "accepted", 202


@app.get("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
