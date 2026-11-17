import hashlib, hmac, time, uuid, os
os.environ["INDEX_WEBHOOK_SECRET"] = "s3cret"
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
import app as router

def signed(client, fields, trigger="single-click-hold", test=False, secret=b"s3cret", ts=None):
    boundary = uuid.uuid4().hex
    body = b"".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()) + f"--{boundary}--\r\n".encode()
    ts = ts or int(time.time()); did = str(uuid.uuid4())
    prefix = f"v1\n{ts}\n{did}\n{trigger}\n{1 if test else 0}\n".encode()
    sig = hmac.new(secret, prefix + body, hashlib.sha256).hexdigest()
    h = {"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Index-Webhook-Version": "1",
         "X-Index-Trigger": trigger, "X-Index-Delivery": did, "X-Index-Timestamp": str(ts), "X-Index-Signature": sig}
    if test: h["X-Index-Test"] = "true"
    return client.post("/index-webhook", data=body, headers=h), did, body, h

def run():
    c = router.app.test_client()
    calls = []
    router.classify = lambda t, r: {"route": "sponsor", "confidence": 0.9, "title": "x", "cleaned_prompt": t, "entities": {}, "reason": "r"}
    router.dispatch = lambda d, p: calls.append((d, p)) or "ok"
    router.threading.Thread = lambda target, args, daemon: type("T", (), {"start": lambda s: target(*args)})()
    r, did, body, h = signed(c, {"transcription": "follow up with Acme about gold sponsorship", "recordedAt": "1", "client": "ring"})
    assert r.status_code == 202, r.data; assert calls[-1][0]["route"] == "sponsor"
    assert c.post("/index-webhook", data=body, headers=h).status_code == 200 and len(calls) == 1  # dedupe
    assert signed(c, {"transcription": "x"}, secret=b"wrong")[0].status_code == 401
    assert signed(c, {"transcription": "x"}, ts=int(time.time()) - 1000)[0].status_code == 401
    assert signed(c, {"transcription": "test"}, trigger="test-event", test=True)[0].data == b"test ok"
    router.TRIGGER_OVERRIDES["double-click-hold"] = "task"
    signed(c, {"transcription": "x", "recordedAt": "1"}, trigger="double-click-hold")
    assert calls[-1][0]["route"] == "task"
    print("all tests passed")
run()
