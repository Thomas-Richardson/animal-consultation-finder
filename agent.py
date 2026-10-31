"""
Consult for Animals
===================

An Agentverse hosted agent that helps UK animal advocates find open UK
government consultations that affect animals, understand them, and write
their own personal response before the deadline.

How it works:

1. A timer pulls the list of open consultations from GOV.UK and asks the AI
   which ones could affect animals, directly or indirectly. It saves the
   result in Agent Storage, so chats don't wait for it.
2. When someone chats, the agent interviews them (what they care about,
   where they live, relevant experience), picks matching consultations,
   explains them and helps draft a response in the person's own words.
3. The AI marks some things in its replies with tags like [[CAL:slug]].
   The code swaps those for real links, so the AI never has to write a web
   address itself, and uses them to keep simple counts that name nobody.

Built by Richie for the Stranger Builds hackathon (Fetch.ai challenge),
October 2026.
"""

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import requests
from openai import OpenAI
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)


# --- Settings ---------------------------------------------------------------

# Agentverse gives every hosted agent these two values, so no key lives in
# this file. For local testing, point them at any OpenAI-compatible service
# and set CONSULT_MODEL to that service's model name.
client = OpenAI(
    base_url=os.environ.get("ASI1_BASE_URL"),
    api_key=os.environ.get("ASI1_API_KEY"),
)
MODEL = os.environ.get("CONSULT_MODEL", "asi1")

GOVUK_SEARCH = "https://www.gov.uk/api/search.json"
REFRESH_AFTER = timedelta(hours=20)  # check GOV.UK for new consultations daily
CHAT_TTL = timedelta(hours=24)  # chats are deleted a day after the last message
MAX_HISTORY = 30  # how many recent messages of a chat the AI sees
CLASSIFY_BATCH = 20  # consultations sorted per AI call (smaller = more reliable JSON)


# --- Briefings ----------------------------------------------------------------

# Hand-checked notes for consultations the agent should know in depth.
# Everything here comes from the consultation document itself, so the AI
# has real facts to draw on instead of making them up.
BRIEFINGS = {
    "phasing-out-carbon-dioxide-stunning-of-pigs": {
        "respond_url": "https://consultations.defra.gov.uk/phasing-out-carbon-dioxide-stunning-of-pigs",
        "text": """\
PHASING OUT CARBON DIOXIDE STUNNING OF PIGS (Defra, on behalf of all four UK governments)

What it proposes: a ban on using carbon dioxide (CO2) gas to stun pigs in slaughterhouses
and knacker's yards, across the whole UK, after a transition period. Defra proposes three
years and also asks about two years. Anyone may respond. It closes on 21 December 2026 at
23:59. People respond online through Defra's Smart Survey page, or by email to
aw.slaughter@defra.gov.uk.

Facts from the consultation document (only use these, and say they come from Defra's
consultation):
- High-concentration CO2 is used to stun about 90% of UK pigs, roughly 10 million pigs a
  year (Slaughter Sector Survey 2024), up from about 50% in 2013.
- Defra says the method causes significant pain, fear and respiratory distress, usually
  for around 30 seconds until unconsciousness begins. Pigs experience air hunger and
  breathlessness, and the gas forms painful acid on the moist surfaces of the mouth,
  nostrils, airways and eyes.
- In 2003 the Farm Animal Welfare Council said high concentrations of CO2 (80% and above)
  to stun and kill pigs are "not acceptable", and recommended phasing out aversive gas
  mixtures within five years.
- The European Food Safety Authority (EFSA) said in 2004 and again in 2020 that high
  concentrations of CO2 are highly aversive and cause pain, fear and respiratory
  distress, and that inert gases are less aversive.
- The Animal Welfare Committee, the government's independent expert committee,
  recommended removing high-concentration CO2 from the approved stunning methods for
  pigs. It found inert gases significantly less aversive, with argon the most suitable
  for commercial use, and that automated electrical stunning gives near-instant
  unconsciousness without pain when the electrodes are placed correctly.
- The PigStun research project found that argon and helium systems reduced aversion and
  respiratory distress compared with high-concentration CO2, and that meat quality was
  comparable with argon.
- Defra notes that every extra year of transition means about 10 million more pigs
  stunned with CO2.
- Defra says campaign responses (very similar or identical wording) may be analysed
  separately from other responses. So a personal response is worth more.

The questions for the public (questions 1 to 8 ask about the respondent, such as name,
email and where they live: the person fills those in themselves, so never ask for them):
- Q9a: Should the use of carbon dioxide when stunning pigs be banned? (Yes / No / Don't know)
- Q9b: Please explain your response and provide evidence where possible.
- Q10a: If CO2 stunning is banned, do you agree that a three-year transition period should
  be given? (Agree / Disagree, it is too long / Disagree, it is too short / Don't know)
- Q10b: Please explain your response and provide evidence where possible.
- Q11: What barriers, if any, do you foresee with transitioning to an alternative
  stunning method for pigs?
- Q12: What is your preferred alternative stunning method to carbon dioxide? (Argon gas /
  Other inert gas / Automated electrical stunning / Manual electrical stunning / Other /
  Don't know)
- Q13a and Q13b: How likely is it that options such as longer working hours or extra
  equipment would keep current processing levels? Please explain.
- Q14 onwards are only for pig processors, gas suppliers and others in the industry.
  Members of the public skip them.

A pro-animal starting point (offer it, but the person decides):
- Q9a: Yes. Defra's own evidence says the method causes significant pain, fear and
  breathlessness, and experts first called it unacceptable in 2003.
- Q10a: "Disagree, it is too long", because each extra year means about 10 million more
  pigs stunned with CO2, and experts recommended a five-year phase-out back in 2003.
- Q12: the person's choice. If it helps, say the Animal Welfare Committee found inert gases
  significantly less aversive than CO2 and saw argon as the most suitable for commercial
  use. Don't claim more than that.
- Q11 and Q13 are optional for the public. Suggest skipping them unless the person knows
  the industry.
""",
    },
}


# --- GOV.UK -------------------------------------------------------------------


def fetch_open_consultations() -> list[dict]:
    """Every consultation GOV.UK lists as open right now (UK government only)."""
    params = {
        "filter_content_store_document_type": "open_consultation",
        "count": 200,
        "fields": "title,link,description,end_date,organisations",
    }
    r = requests.get(GOVUK_SEARCH, params=params, timeout=30)
    r.raise_for_status()
    items = []
    for res in r.json().get("results", []):
        link = res.get("link") or ""
        if not link:
            continue
        orgs = res.get("organisations") or []
        items.append(
            {
                "slug": link.rstrip("/").split("/")[-1],
                "title": (res.get("title") or "").strip(),
                "url": "https://www.gov.uk" + link if link.startswith("/") else link,
                "closes": (res.get("end_date") or "")[:10],
                "from": ", ".join(o.get("title", "") for o in orgs if isinstance(o, dict)),
                "summary": (res.get("description") or "").strip(),
            }
        )
    return items


CLASSIFY_PROMPT = """You sort UK government consultations for animal advocates.
For each consultation, decide whether its outcome could affect animals:
- "direct": it is about animals (farmed animals, wildlife, fish, pets, animals in science,
  animal health or welfare, hunting, slaughter, zoos).
- "indirect": it is mainly about something else, but it has a clear, specific route to
  changing animals' lives: farming, fishing, food and food labelling, new foods, pesticides,
  wildlife habitats, land use for farming, or pollution from farms.
- "none": no clear route to animals. If unsure, choose "none".

These are "none" unless the summary itself mentions farming, fishing, food, animals or
wildlife: energy, heating, infrastructure, shipping safety, taxes, general chemicals rules,
housing, land registers, transport, technology and health guidance. General environmental
benefits (less pollution, lower carbon) don't count.

Include every consultation in your reply, including the "none" ones.
Reply with only a JSON array, one object per consultation, like this:
[{"slug": "...", "relevance": "direct", "animals": "which animals, in a few words",
  "why": "one plain sentence on how it could affect animals"}]"""


def classify(items: list[dict]) -> dict:
    """Ask the AI which consultations affect animals. Returns {slug: label}."""
    labels = {}
    for start in range(0, len(items), CLASSIFY_BATCH):
        batch = items[start : start + CLASSIFY_BATCH]
        listing = "\n".join(
            f"- slug: {c['slug']} | {c['title']} | from {c['from']} | {c['summary']}"
            for c in batch
        )
        r = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": CLASSIFY_PROMPT},
                {"role": "user", "content": listing},
            ],
            max_tokens=4000,
        )
        text = r.choices[0].message.content or ""
        # The AI sometimes wraps the JSON in other text, so pull out the array.
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            continue
        try:
            rows = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("slug"):
                labels[row["slug"]] = {
                    "relevance": str(row.get("relevance", "unknown")).lower(),
                    "animals": str(row.get("animals", ""))[:80],
                    "why": str(row.get("why", ""))[:240],
                }
        # Models often leave out the ones that don't matter, even when asked not
        # to. If the batch parsed but a consultation is missing, it means "none".
        for c in batch:
            labels.setdefault(c["slug"], {"relevance": "none", "animals": "", "why": ""})
    return labels


def refresh_consultations(ctx) -> None:
    """Pull GOV.UK, sort any new consultations, and save the list."""
    saved = ctx.storage.get("consultations") or {}
    old = {c["slug"]: c for c in saved.get("items", [])}
    fresh = fetch_open_consultations()

    # Only send the AI consultations it hasn't sorted yet (or failed to sort).
    to_sort = [
        c
        for c in fresh
        if c["slug"] not in old or old[c["slug"]].get("relevance") == "unknown"
    ]
    labels = classify(to_sort) if to_sort else {}

    items = []
    for c in fresh:
        if c["slug"] in labels:
            c.update(labels[c["slug"]])
        elif c["slug"] in old and old[c["slug"]].get("relevance") != "unknown":
            c.update({k: old[c["slug"]].get(k, "") for k in ("relevance", "animals", "why")})
        else:
            c.update({"relevance": "unknown", "animals": "", "why": ""})
        items.append(c)

    ctx.storage.set("consultations", {"updated": now().isoformat(), "items": items})
    counts = {}
    for c in items:
        counts[c["relevance"]] = counts.get(c["relevance"], 0) + 1
    ctx.logger.info(f"Refreshed {len(items)} open consultations: {counts}")


def get_consultations(ctx) -> tuple[list[dict], str]:
    """The open consultations that could affect animals, refreshing if stale."""
    saved = ctx.storage.get("consultations") or {}
    updated = saved.get("updated")
    stale = not updated or now() - datetime.fromisoformat(updated) > REFRESH_AFTER
    if stale:
        try:
            refresh_consultations(ctx)
            saved = ctx.storage.get("consultations") or {}
        except Exception:
            # GOV.UK or the AI is down: carry on with the last good list.
            ctx.logger.exception("Refresh failed, using the saved list")
    today = date.today().isoformat()
    items = [
        c
        for c in saved.get("items", [])
        if (c.get("closes") or "9999") >= today
        and (
            c.get("relevance") == "direct"
            # The AI is too generous with "indirect" (it counted undersea cables), so
            # an indirect one also has to mention something to do with animals.
            or (c.get("relevance") in ("indirect", "unknown") and mentions_animals(c))
        )
    ]
    return items, (saved.get("updated") or "")[:10]


ANIMAL_WORDS = re.compile(
    r"animal|farm|agricultur|livestock|fish|aquacultur|shellfish|marine|wildlife|nature|"
    r"habitat|species|bird|pig|poultry|chicken|cattle|sheep|dairy|egg|meat|slaughter|"
    r"veterinar|pest|food|feed|crop|hunt|zoo|pet\b|pets\b|dog|cat\b|cats\b|horse",
    re.I,
)


def mentions_animals(item: dict) -> bool:
    return bool(ANIMAL_WORDS.search(f"{item.get('title', '')} {item.get('summary', '')}"))


# --- Links ----------------------------------------------------------------------


def respond_url(item: dict) -> str:
    """Where to respond: the department's own response page if we know it."""
    return BRIEFINGS.get(item["slug"], {}).get("respond_url") or item["url"]


def calendar_links(item: dict) -> tuple[str, str]:
    """Google and Outlook 'add to calendar' links for a reminder before the deadline."""
    closes = date.fromisoformat(item["closes"])
    # Remind three days before it closes, or today if that's already passed.
    remind = max(closes - timedelta(days=3), date.today())
    title = f"Respond to consultation: {item['title']}"
    details = (
        f"Closes {closes.day} {closes:%B %Y} at 23:59. "
        f"Respond here: {respond_url(item)}"
    )
    google = requests.Request(
        "GET",
        "https://calendar.google.com/calendar/render",
        params={
            "action": "TEMPLATE",
            "text": title,
            "dates": f"{remind:%Y%m%d}/{remind + timedelta(days=1):%Y%m%d}",
            "details": details,
        },
    ).prepare().url
    outlook = requests.Request(
        "GET",
        "https://outlook.office.com/calendar/0/deeplink/compose",
        params={
            "path": "/calendar/action/compose",
            "rru": "addevent",
            "subject": title,
            "body": details,
            "startdt": remind.isoformat(),
            "enddt": (remind + timedelta(days=1)).isoformat(),
            "allday": "true",
        },
    ).prepare().url
    return google, outlook


# --- Tags in the AI's replies -----------------------------------------------------

TAG = re.compile(r"\[\[(LINK|CAL|ASKED|SENT|ARG):([A-Za-z0-9\-]+)(?:\|([^\]]{1,80}))?\]\]")


def process_tags(text: str, items: list[dict], ctx) -> str:
    """Swap link tags for real links, count the others, and remove them."""
    by_slug = {c["slug"]: c for c in items}
    stats = ctx.storage.get("stats") or {"asked": {}, "sent": {}, "args": {}}
    # The AI sometimes forgets the reminder tag, so a link always brings one along.
    has_cal = {m.group(2) for m in TAG.finditer(text) if m.group(1) == "CAL"}

    def reminder(item):
        try:
            google, outlook = calendar_links(item)
        except ValueError:
            return ""
        return f"Add a reminder: [Google Calendar]({google}) or [Outlook]({outlook})"

    def swap(m):
        kind, slug, extra = m.group(1), m.group(2), m.group(3)
        item = by_slug.get(slug)
        if not item:
            return ""  # the AI made up a slug: drop the tag rather than guess
        if kind == "LINK":
            link = f"[Respond on the official page]({respond_url(item)})"
            return link if slug in has_cal else f"{link}\n{reminder(item)}"
        if kind == "CAL":
            return reminder(item)
        if kind == "ASKED":
            stats["asked"][slug] = stats["asked"].get(slug, 0) + 1
        elif kind == "SENT":
            stats["sent"][slug] = stats["sent"].get(slug, 0) + 1
        elif kind == "ARG" and extra:
            stats["args"].setdefault(slug, []).append(extra.strip())
            stats["args"][slug] = stats["args"][slug][-200:]
        return ""

    out = TAG.sub(swap, text)
    ctx.storage.set("stats", stats)
    # Models love dashes as separators even when told not to. Swap them out.
    out = re.sub(r"\s*—\s*", ", ", out)
    out = re.sub(r" – ", ": ", out)
    # Tidy the gaps the removed tags leave behind.
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def stats_report(ctx) -> str:
    """A plain summary of the anonymous counts (send '/stats' to see it)."""
    stats = ctx.storage.get("stats") or {"asked": {}, "sent": {}, "args": {}}
    lines = ["Anonymous counts so far:"]
    for slug in sorted(set(stats["asked"]) | set(stats["sent"])):
        lines.append(
            f"- {slug}: asked about {stats['asked'].get(slug, 0)} times, "
            f"responses sent {stats['sent'].get(slug, 0)}"
        )
        args = stats["args"].get(slug, [])
        if args:
            lines.append(f"  main arguments: {', '.join(args[-10:])}")
    return "\n".join(lines) if len(lines) > 1 else "No chats counted yet."


# --- The conversation -------------------------------------------------------------

SYSTEM_PROMPT = """You are Consult for Animals, a friendly helper made by an animal advocate.
You help people in the UK find open UK government consultations that affect animals,
understand them, and write their own response before the deadline. You are openly on the
side of animals.

Today is {today}. Write in plain British English. Keep replies short: a few short
paragraphs. Explain any jargon. Don't use dashes as separators: use a colon or a full stop.

HOW A CHAT GOES
1. First reply: say in one or two sentences what you do. Mention that you don't keep names
   or contact details, and that chats are deleted after a day. Then ask, in one message,
   up to three short questions:
   - Which animals or issues they care about most.
   - Whether they live in England, Scotland, Wales or Northern Ireland (or outside the UK).
   - Any work, study or experience that's relevant (for example farming, vet work,
     science or campaigning). Say this one is optional.
   If they've already said what they want (for example "help me respond to the pig
   consultation"), skip what they've answered and get on with it.
2. Recommend at most three consultations from the list below that clearly fit what they
   told you: ones a person who cares about those animals would obviously want to answer.
   Usually that's one or two. One good match is better than three loose ones. If the
   other matches are only loosely linked, say so in a line instead of listing them in
   full. For each one you recommend: what it's about in
   one sentence, how it could affect animals, who it's from, and the closing date. Put
   [[ASKED:slug]] after each one. Ask which they'd like help with.
3. When they pick one, put [[ASKED:slug]] and explain what it asks in plain English. If
   there's a briefing for it below, use it, and say which questions are for the public
   and which are only for the industry.
4. Before drafting, ask two or three short questions about their own view: what they think
   should happen, why it matters to them, and anything from their own life or work that's
   relevant. Ask these once only. As soon as they answer, write the draft. If they say
   "just draft it" or anything like it, draft straight away without asking anything,
   with [square brackets] where they should add something personal.
5. Draft their answers (rules below). Then always end that reply with these, in order:
   a. One line asking them to read it, change anything that isn't how they'd say it, and
      submit it themselves. Say that personal responses count for more, because
      governments often analyse near-identical campaign responses separately.
   b. [[LINK:slug]] on its own line.
   c. [[CAL:slug]] on its own line.
   d. [[ARG:slug|a few words naming their main argument]], for example
      [[ARG:phasing-out-carbon-dioxide-stunning-of-pigs|transition too long]]. Never put
      personal details in it.
   e. A short question asking them to tell you once they've sent it.
6. If they say they've sent it, thank them and put [[SENT:slug]].

DRAFTING RULES
- Start from a pro-animal position, then build each answer from the person's own reasons,
  experience and words, so no two drafts read the same.
- The draft itself must include what only this person told you: their experience, their
  reasons, their phrases. Don't summarise what they said before the draft: put it in the
  draft. If they gave you nothing personal, put a [square-bracket prompt] in the draft for
  them to add something.
- For optional questions they have nothing to say on, write "Leave blank" rather than
  filling the space.
- Answer the consultation's actual questions, in its order, with the question numbers
  where you know them. Keep each answer to a few sentences.
- Write in the first person, as them, in plain words. It shouldn't read like a campaign email.
- Only use facts from the briefing or the consultation summary below. Never invent
  statistics, studies, quotes, experiences, jobs or qualifications. If they want to add
  evidence, tell them to add it themselves.
- If they disagree with the pro-animal starting point, help them say what they actually
  think. It's their response.
- Some people oppose killing animals for food altogether. If they say so, help them say
  that and still answer the question asked (for example, backing a ban as a step that
  reduces suffering), if that's what they want.
- You never submit anything for them.

OTHER RULES
- Never ask for their name, email, address or phone number. If they share them, don't
  repeat them back. The official forms ask for these, and they fill them in themselves.
- Only recommend consultations from the list below. If nothing fits, say so honestly and
  offer the closest ones.
- Be honest about how strong the link to animals is. If a consultation is mainly about
  something else (for example shipping safety), say so plainly, and don't overstate what
  a response could change for animals.
- UK government consultations only, for now. If they ask about another country, say so.
- Use slugs exactly as written in the list. Never write a web address yourself: the
  [[LINK:slug]] and [[CAL:slug]] tags turn into real links.
- If someone says they're just trying you out, or they don't live in the UK, give them a
  quick demo in that same reply, without asking questions first: explain the pig stunning
  consultation in two sentences, then show a short example draft for a made-up person
  (say who, in one line, and label it clearly as an example). End by saying how it works
  for a real person: you'd ask about their views first and write it in their words.
- If they ask about something unrelated, answer in a sentence if you can, then steer back.

OPEN CONSULTATIONS THAT COULD AFFECT ANIMALS (from GOV.UK, checked {updated})
{listing}

BRIEFINGS
{briefings}"""


def build_system_prompt(items: list[dict], updated: str) -> str:
    listing = "\n".join(
        f"- slug: {c['slug']} | {c['title']} | from {c['from']} | closes {c['closes']} | "
        f"{c['relevance']} ({c.get('animals', '')}): {c.get('why', '')} | {c['summary']}"
        for c in sorted(items, key=lambda c: (c["relevance"] != "direct", c["closes"]))
    ) or "(none found right now)"
    live = {c["slug"] for c in items}
    briefings = "\n\n".join(b["text"] for s, b in BRIEFINGS.items() if s in live) or "(none)"
    today = date.today()
    return SYSTEM_PROMPT.format(
        today=f"{today.day} {today:%B %Y}",
        updated=updated or "not yet",
        listing=listing,
        briefings=briefings,
    )


def load_chat(ctx, key: str) -> list[dict]:
    saved = ctx.storage.get(f"chat:{key}") or {}
    updated = saved.get("updated")
    if updated and now() - datetime.fromisoformat(updated) > CHAT_TTL:
        return []
    return saved.get("messages", [])


def save_chat(ctx, key: str, messages: list[dict]) -> None:
    stamp = now().isoformat()
    ctx.storage.set(f"chat:{key}", {"updated": stamp, "messages": messages[-MAX_HISTORY:]})
    index = ctx.storage.get("chat_index") or {}
    index[key] = stamp
    ctx.storage.set("chat_index", index)


def purge_old_chats(ctx) -> None:
    """Delete chats nobody has touched for a day."""
    index = ctx.storage.get("chat_index") or {}
    keep = {}
    for key, stamp in index.items():
        if now() - datetime.fromisoformat(stamp) > CHAT_TTL:
            ctx.storage.set(f"chat:{key}", {})
        else:
            keep[key] = stamp
    ctx.storage.set("chat_index", keep)


def respond(ctx, key: str, text: str) -> str:
    """One turn of the conversation: the person's message in, the reply out."""
    if text.strip().lower() == "/stats":
        return stats_report(ctx)

    messages = load_chat(ctx, key)
    messages.append({"role": "user", "content": text})
    items, updated = get_consultations(ctx)

    r = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": build_system_prompt(items, updated)}]
        + messages[-MAX_HISTORY:],
        max_tokens=2048,
    )
    raw = r.choices[0].message.content or ""

    # Keep the tags in the saved chat so the AI sees how it used them, but send
    # the person the version with real links and no tags.
    messages.append({"role": "assistant", "content": raw})
    save_chat(ctx, key, messages)
    return process_tags(raw, items, ctx)


def now() -> datetime:
    return datetime.now(timezone.utc)


# --- Agentverse wiring ------------------------------------------------------------


def create_text_chat(text: str, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(timestamp=now(), msg_id=uuid4(), content=content)


agent = Agent()
protocol = Protocol(spec=chat_protocol_spec)


@protocol.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    # Tell the sender straight away that the message arrived.
    await ctx.send(sender, ChatAcknowledgement(timestamp=now(), acknowledged_msg_id=msg.msg_id))

    text = msg.text()
    if not text or not text.strip():
        return  # e.g. a message that only starts or ends a session

    # One saved chat per conversation. ASI:One keeps the same session for a chat.
    key = str(ctx.session) if ctx.session else sender
    try:
        reply = respond(ctx, key, text)
    except Exception:
        ctx.logger.exception("Error answering")
        reply = "Sorry, something went wrong on my side. Please try again in a minute."
    await ctx.send(sender, create_text_chat(reply))


@protocol.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@agent.on_interval(period=3 * 60 * 60)
async def scheduled_jobs(ctx: Context):
    # Every three hours: refresh the consultation list if it's a day old, and
    # delete chats older than a day. This is the work the agent does on its own.
    try:
        get_consultations(ctx)
    except Exception:
        ctx.logger.exception("Scheduled refresh failed")
    purge_old_chats(ctx)


agent.include(protocol, publish_manifest=True)

if __name__ == "__main__":
    agent.run()
