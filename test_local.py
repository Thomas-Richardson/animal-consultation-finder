"""
Try the agent on this computer, without Agentverse.

Agentverse supplies the AI key when the agent runs there. Here we borrow an
OpenAI key instead, so this tests the logic (GOV.UK, sorting, tags, links),
not how well Fetch.ai's own model writes.

Run:  OPENAI_API_KEY=... .venv/bin/python test_local.py
"""

import os
import sys

# Point the agent at OpenAI instead of Fetch.ai's model.
os.environ["ASI1_API_KEY"] = os.environ["OPENAI_API_KEY"]
os.environ["ASI1_BASE_URL"] = "https://api.openai.com/v1"
os.environ.setdefault("CONSULT_MODEL", "gpt-4.1-mini")

import agent  # noqa: E402  (must come after the settings above)


class FakeStorage:
    """Stands in for Agentverse's Agent Storage: a simple key-value store."""

    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class FakeLogger:
    def info(self, msg):
        print(f"[log] {msg}")

    def exception(self, msg):
        import traceback

        print(f"[log] {msg}")
        traceback.print_exc()


class FakeContext:
    def __init__(self):
        self.storage = FakeStorage()
        self.logger = FakeLogger()


ctx = FakeContext()

print("=== 1. Refresh the consultation list from GOV.UK ===")
agent.refresh_consultations(ctx)
items = ctx.storage.get("consultations")["items"]
for c in items:
    if c["relevance"] != "none":
        print(f"- [{c['relevance']}] {c['title']} (closes {c['closes']}) :: {c['why']}")

script = sys.argv[1:] or [
    "hi",
    "Pigs and farmed animals mostly. I live in England. I used to work on a supermarket meat counter.",
    "The pig one please",
    "I think it should be banned as soon as possible, three years is far too long. "
    "Working on the meat counter made me think about where it all comes from. "
    "I'd go with argon I guess.",
    "Thanks, I've sent it!",
    "/stats",
]

print("\n=== 2. A test chat ===")
for text in script:
    print(f"\n>>> PERSON: {text}\n")
    print(agent.respond(ctx, "test-session", text))
