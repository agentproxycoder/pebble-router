import hashlib, hmac, os, time, uuid
os.environ["INDEX_WEBHOOK_SECRET"] = "s3cret"
os.environ["ROUTINE_FIRE_URL"] = "https://api.anthropic.com/v1/claude_code/routines/trig_x/fire"
os.environ["ROUTINE_TOKEN"] = "tok"
import app as router


def signed(client, fields, trigger="single-click-hold", test=False, secret=b"s3cret", ts=None, did=None):
    boundary = uuid.uuid4().hex
    body = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, v in fields.items()
    ) + f"--{boundary}--\r\n".encode()
    ts = ts or int(time.time())
    did = did or str(uuid.uuid4())
    prefix = f"v1\n{ts}\n{did}\n{trigger}\n{1 if test else 0}\n".encode()
    h = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-Index-Webhook-Version": "1", "X-Index-Trigger": trigger, "X-Index-Delivery": did,
        "X-Index-Timestamp": str(ts),
        "X-Index-Signature": hmac.new(secret, prefix + body, hashlib.sha256).hexdigest(),
    }
    if test:
        h["X-Index-Test"] = "true"
    return client.post("/index-webhook", data=body, headers=h)


class Resp:
    def __init__(self, code):
        self.status_code, self.ok, self.text = code, code < 300, ""
    def json(self):
        return {"claude_code_session_url": "https://claude.ai/code/session_x"}


def run():
    c = router.app.test_client()
    fired, status = [], [200]
    router.fire_session = lambda text: fired.append(text) or Resp(status[0])
    note = {"transcription": "follow up with Acme about gold sponsorship", "recordedAt": "1763380000000", "client": "ring"}

    # happy path: one new session, transcript and gesture included
    did = str(uuid.uuid4())
    assert signed(c, note, did=did).status_code == 200
    assert len(fired) == 1 and "Acme" in fired[0] and "Hold & talk" in fired[0] and "2025-11-17" in fired[0]
    # retry of the same recording does not start a second session
    assert signed(c, note, did=did).data == b"already received" and len(fired) == 1

    # Claude down / rate limited -> 503 so the ring app retries, and a retry then goes through
    status[0] = 429
    did2 = str(uuid.uuid4())
    assert signed(c, note, did=did2).status_code == 503
    status[0] = 200
    assert signed(c, note, did=did2).status_code == 200 and len(fired) == 3

    # security checks
    assert signed(c, note, secret=b"wrong").status_code == 401
    assert signed(c, note, ts=int(time.time()) - 1000).status_code == 401
    # test events and audio-only payloads never start sessions
    assert signed(c, {"transcription": "t"}, trigger="test-event", test=True).data == b"test ok"
    assert signed(c, {"recordedAt": "1"}).status_code == 200
    assert len(fired) == 3

    # not configured -> 503 (retried), nothing fired
    router.FIRE_URL = ""
    assert signed(c, note).status_code == 503 and len(fired) == 3
    print("all tests passed")


run()
