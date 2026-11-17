"""Edit this file to change where prompts go.

Each route has a description (what Claude reads to decide) and the name of an
environment variable holding the destination webhook URL (Zapier, Make, n8n,
Slack incoming webhook, your own API...). A route with no URL set is just logged.
"""

ROUTES = {
    "task": {
        "description": "A to-do or reminder for the speaker (call someone back, follow up, renew, prepare something).",
        "env": "ROUTE_URL_TASK",
    },
    "email_draft": {
        "description": "Asks to write, reply to, or send an email or message to someone.",
        "env": "ROUTE_URL_EMAIL_DRAFT",
    },
    "sponsor": {
        "description": "About a sponsor, exhibitor, donor or fundraising ask: pledges, sponsorship levels, logos, invoices, payments.",
        "env": "ROUTE_URL_SPONSOR",
    },
    "membership": {
        "description": "About members or prospective members: sign-ups, renewals, dues, recruiting a physician, member counts.",
        "env": "ROUTE_URL_MEMBERSHIP",
    },
    "event": {
        "description": "About an event or meeting: dates, venue, agenda, speakers, RSVPs, scheduling.",
        "env": "ROUTE_URL_EVENT",
    },
    "question": {
        "description": "A question the speaker wants answered or researched.",
        "env": "ROUTE_URL_QUESTION",
    },
    "note": {
        "description": "An idea, observation or anything to remember that is none of the above.",
        "env": "ROUTE_URL_NOTE",
    },
}

# Optional: force a route for a ring gesture, skipping Claude's choice.
# Gestures: "single-click-hold" (Hold & talk), "double-click-hold".
TRIGGER_OVERRIDES: dict[str, str] = {
    # "double-click-hold": "task",
}
