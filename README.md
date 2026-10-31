# Animal Consultation Finder

## Summary

Animal Consultation Finder finds open UK government consultations that affect animals and helps you write your own response before the deadline. It asks what you care about, picks the consultations that matter to you, explains them in plain English and drafts answers in your own words for you to edit and send.

Right now it knows the Defra consultation on phasing out carbon dioxide stunning of pigs in depth. That consultation is open to anyone and closes on 21 December 2026.

## Key features

- Checks GOV.UK every day for new open consultations, and works out which ones could affect animals, directly or indirectly.
- Asks you a few short questions (which animals you care about, where in the UK you live, any relevant experience) and only suggests consultations that fit.
- If you mention the organisation you work or volunteer for, it looks it up on the web to learn what the organisation does and where it stands, then suggests consultations and arguments that fit. It tells you what it found, with sources, and asks you to check it's the right organisation.
- Explains what each consultation asks, which questions are for the public and which are only for the industry.
- Drafts your answers from your own views and experience, starting from a pro-animal position. Governments often analyse near-identical campaign responses separately, so a personal response counts for more.
- Gives you the official link to respond, and a Google Calendar or Outlook reminder three days before the deadline.

## How to use it

Ask it things like:

- "What UK consultations about animals are open right now?"
- "Help me respond to the pig stunning consultation."
- "I care about farmed fish. Is there anything I can respond to?"
- "I work for Compassion in World Farming. What should I respond to?"
- "What's closing soon that affects wildlife?"
- "I'm just trying this out. Show me an example."

It replies with a short plain-English explanation, then a draft for you to edit, the official link and a calendar reminder. You submit the response yourself. It never submits anything for you.

## Use cases

- An animal advocate who wants to respond to a consultation but doesn't know where to start.
- Campaign staff at a small group who want to help supporters write personal responses instead of copying a template.
- Anyone who wants to know which government decisions about animals are open for comment.

## Limitations

- UK government consultations only (those listed on GOV.UK). It doesn't yet cover the Scottish, Welsh or Northern Irish governments' own consultation sites, UK Parliament committees, or other countries.
- It only goes deep on consultations it has a briefing for. For the rest it works from the GOV.UK summary, so check the consultation document itself before you send anything.
- It starts from a pro-animal position. It's built by an animal advocate and says so.
- It's a hackathon project. The drafts are a starting point, not legal or expert advice.

## Privacy

It doesn't ask for or keep names, email addresses or other contact details. Chats are kept for up to a day so it can follow the conversation, then deleted. It keeps anonymous counts of which consultations people ask about, the main argument in each draft (a few words, no personal details) and how many people say they sent a response. Send `/stats` to see those counts.

If you name an organisation, it searches the web (using Firecrawl) for public information about that organisation, not about you. It keeps that public summary for a week, so the next person from the same organisation doesn't trigger another search. The summary isn't linked to you or your chat once the chat is deleted.

## Credits

Built by Richie for the Stranger Builds hackathon, October 2026. Runs as a hosted agent on Fetch.ai's Agentverse, using Fetch.ai's asi1 model. Consultation data from GOV.UK. Version 0.1.

## Changes made from feedback

None yet. Notes from hackathon testers will be listed here as "they told me X, I changed Y".

## For developers

The whole agent is `agent.py`. Paste it into a hosted agent's Build tab on Agentverse and press Run. Agentverse supplies the model key (`ASI1_API_KEY` and `ASI1_BASE_URL`). For the organisation lookup, add a Firecrawl key as `FIRECRAWL_API_KEY` in the agent's Agent Secrets tab. Without it, everything else still works and the lookup is switched off.

To try it locally without Agentverse, `test_local.py` runs a scripted chat against any OpenAI-compatible API:

```bash
python3 -m venv .venv
.venv/bin/pip install uagents uagents-core openai requests
OPENAI_API_KEY=your-key .venv/bin/python test_local.py
```

How it fits together:

1. A timer refreshes the list of open consultations from the GOV.UK search API and asks the model to sort new ones into direct, indirect or no effect on animals. Indirect ones also have to mention something animal-related, because the model is generous.
2. Each chat message goes to the model with the sorted list, any briefings, and the conversation so far (kept in Agent Storage for a day).
3. The model writes tags such as `[[LINK:slug]]` and `[[CAL:slug]]` instead of web addresses. The code swaps them for real links and uses `[[ASKED:...]]`, `[[ARG:...]]` and `[[SENT:...]]` tags for the anonymous counts.
4. Until a chat has an organisation, a small separate model call checks each message for one. If it finds one, the code runs two Firecrawl searches (who the organisation is, and where it stands on the main consultation), has the model write a short profile with sources, caches it for a week, and adds it to the instructions. Lookups are capped at 30 a day.
