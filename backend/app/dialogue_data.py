"""
NPC dialogue trees for the venue scene (PLAN.md sections 3/10) -- this is
the file to edit to deepen or add conversations. Deliberately plain data
(no classes, no imports beyond nothing): dialogue_service.py is the only
code that reads it.

Each NPC is a self-contained dict, keyed by the `npc_id` used in the venue
scene hotspots (see venue.js's NPCS) and the URL
(`/api/v/{slug}/npcs/{npc_id}/dialogue`):

    "npc_id": {
        "display_name": "...",           # shown as the speech bubble's speaker
        "avatar": "assets/sprites/...",  # sprite path, /static/ prefix added client-side
        "start": "<node id>",            # which node `dialogue_service.get_start_node` opens on
        "nodes": {
            "<node id>": {
                # Exactly one of these two:
                "line": "static text",                    # ...or...
                "action": "<name in dialogue_service.ACTIONS>",  # dynamic line+choices from live DB state

                "choices": [
                    {"label": "...", "next": "<node id>"},   # -> another node
                    {"label": "...", "end": True},           # closes the dialogue, no server round-trip
                ],
            },
        },
    }

A node with an `action` can *also* list its own `choices` in some flows (see
"greet" below -- `menu`'s choices are static even though its line is
dynamic); when the action itself needs to build choices dynamically (the
hacker's queue-item picker), it returns its own `choices` and the ones
written here are ignored for that node. See dialogue_service.py's
`resolve_node` for exactly how the two combine.

Splitting a tree that outgrows this file into its own `dialogue/<npc_id>.py`
module (each exporting the same dict shape, merged into NPCS) is a drop-in
change later -- nothing in dialogue_service.py assumes this is one file.
"""

NPCS = {
    "bartender": {
        "display_name": "Bartender",
        "avatar": "assets/sprites/avatars/avatars_6_r2_c3.png",
        "start": "greet",
        "nodes": {
            "greet": {
                "line": "What can I get you?",
                "choices": [
                    {"label": "What's on the menu?", "next": "menu"},
                    {"label": "Just looking, thanks.", "end": True},
                ],
            },
            "menu": {
                "action": "show_products",
                "choices": [{"label": "Thanks.", "end": True}],
            },
        },
    },

    "dj": {
        "display_name": "DJ",
        "avatar": "assets/sprites/avatars/avatars_5_r1_c5.png",
        "start": "greet",
        "nodes": {
            "greet": {
                "line": "Yo. Want to know what's on tonight?",
                "choices": [
                    {"label": "What's the program?", "next": "program"},
                    {"label": "Just vibing.", "end": True},
                ],
            },
            "program": {
                "action": "show_event_program",
                "choices": [{"label": "Nice, thanks.", "end": True}],
            },
        },
    },

    "bouncer": {
        "display_name": "Bouncer",
        "avatar": "assets/sprites/avatars/avatars_r4_c0.png",
        "start": "greet",
        "nodes": {
            "greet": {
                "action": "bouncer_status",
                "choices": [{"label": "Got it.", "end": True}],
            },
        },
    },

    "hacker": {
        "display_name": "???",
        "avatar": "assets/sprites/avatars/avatars_6_r5_c1.png",
        "start": "greet",
        "nodes": {
            # hacker_greet decides everything about the first line based on
            # the player's tier -- see dialogue_service.py's ACTIONS. Low
            # tier never even sees a queue picker; mid/high get one built
            # dynamically from the venue's actual current queue.
            "greet": {
                "action": "hacker_greet",
            },
            # Reached by picking a song at "greet" (mid/high tier only).
            # Recomputes the tier from scratch rather than trusting anything
            # about the earlier greeting -- see hacker_confirm.
            "confirm_hack": {
                "action": "hacker_confirm",
            },
            # Reached by picking a bribe amount at "confirm_hack" (mid tier
            # only -- high tier resolves for free right at confirm_hack).
            "pay_hack": {
                "action": "hacker_pay",
            },
        },
    },
}
