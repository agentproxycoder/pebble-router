# Pebble Index 01 → Claude router

The Index 01 ring posts each recording to `/index-webhook`. Claude reads the transcript, picks a route (task, email_draft, sponsor, membership, event, question, note), and the service forwards the result as JSON to that route's URL.

## Ring setup (Pebble app → Index 01 Settings → Webhook)
1. Gesture: **Hold & talk** and/or **Double click & hold**
2. URL: `https://<your-host>/index-webhook`
3. **Sign requests**: on. Use the same value as `INDEX_WEBHOOK_SECRET` (generate it with `openssl rand -hex 32`).
4. Payload: **Transcription only** or **Both**. Recording-only payloads have no text to route.
5. **Send test event**, which should log `test ok`, then **Save**.

## Environment
| Var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `INDEX_WEBHOOK_SECRET` | Must match the ring's signing secret |
| `ROUTE_URL_<ROUTE>` | Destination webhook per route (Zapier/Make/n8n/Slack). If unset, the route is only logged. |
| `ROUTER_TOKEN` | Optional. Requires `Authorization: Bearer <token>`, which you add as a header in the ring settings. |

## Forwarded JSON
`transcript, recorded_at, trigger, delivery_id, route, confidence, title, cleaned_prompt, entities{people, organizations, association, due, amount}, reason`

Edit `routes.py` to add or rename routes, or to pin a gesture to a route (`TRIGGER_OVERRIDES`).

Run locally: `pip install -r requirements.txt && python app.py`. Tests: `python test_app.py`.
