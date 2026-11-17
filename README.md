# Pebble Index 01 → new Claude session

Each recording from the Index 01 ring is posted to `/index-webhook`. The service checks Pebble's signature, then fires a Claude Code scheduled task's API trigger with the transcript, which starts a **new Claude session** at claude.ai/code. That session decides what the request is about and acts on it with your connectors. Its instructions are in `ROUTINE_PROMPT.md`.

## 1. Scheduled task (claude.ai/code/routines)
- Prompt: the contents of `ROUTINE_PROMPT.md`
- Connectors: the ones the sessions should use (Gmail/Outlook, Drive, Sheets…)
- Trigger: **API**. Copy the **Fire URL**, click **Generate token**, and copy the token (it's shown once).

## 2. Render environment
| Var | Value |
|---|---|
| `INDEX_WEBHOOK_SECRET` | Same secret as the ring's **Sign requests** field |
| `ROUTINE_FIRE_URL` | The task's Fire URL |
| `ROUTINE_TOKEN` | The task's API token |
| `ROUTER_TOKEN` | Optional. Also require `Authorization: Bearer <token>` from the ring |

## 3. Ring (Pebble app → Index 01 Settings → Ring Button → gesture)
Keep **Index agent** and turn on **Also send to webhook** (or pick **Webhook only**). Then in **Webhook settings**:
- URL `https://<host>/index-webhook`
- Sign requests on
- Payload **Transcription only** or **Both**

## Behaviour
- One recording starts one session. Retries of the same recording (same `X-Index-Delivery`) are not sent again.
- If Claude can't be reached, or the 30-fires-per-hour limit is hit, the service returns 503. The ring app then retries every minute, up to 10 times, so the recording isn't lost.
- Test events and audio-only payloads never start a session.

Run tests with `python test_app.py`.
