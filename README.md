# Kastack — Message Classification, Task/Event Extraction & Sensitive-Information Detection

A fully local, deterministic rule-based pipeline that processes 900 fictional messages and produces:

| Part | Task | Deliverable |
|------|------|-------------|
| 1 | **Message classification** into 6 categories with confidence + reason | `outputs/classification.json` |
| 2 | **Task & event extraction** (title, description, deadline, time, person, priority) | `outputs/tasks_events.json` |
| 3 | **Sensitive-information detection** with type, risk, masked text, recommended action | `outputs/sensitive_detections.json` |

No external AI service is called at runtime and no message content leaves
this machine. All decisions are made by explicit, readable rules, so every
output line can be explained.

> The assignment dataset (`data/messages.csv`) is **not** published in this
> repository. See `data/README.md`.

---

## Quick start

```bash
pip install -r requirements.txt          # flask + gunicorn (web app only)

# 1. Run the pipeline (requires the dataset in data/)
python -m kastack.run_pipeline data/messages.csv data/mandatory_demo_ids.csv outputs

# 2. Tests
python -m unittest discover -s tests -v

# 3. Local web demo
python -m web.app
# open http://localhost:5000   (set PORT env var to change the port)
```

**Project layout**

```
kastack/
├── src/kastack/
│   ├── classifier.py    # Part 1: six-category classification
│   ├── extractor.py     # Part 2: tasks & events
│   ├── sensitive.py     # Part 3: sensitive detection + masking
│   ├── pipeline.py      # orchestration + output writers
│   ├── common.py        # shared helpers (dates, times, venues, masking)
│   └── run_pipeline.py  # CLI entry point
├── web/                 # Flask dashboard (cloud-deployable, masked data only)
├── tests/               # unittest suite (33 tests)
├── outputs/             # generated structured results (masked)
└── data/                # dataset location (git-ignored)
```

---

## Part 1 — Message classification

Messages are processed in chronological order. Each message is scored
against explicit **signal rules** — regex patterns grouped per category.
The category with the highest score wins; confidence combines (a) the
absolute evidence strength `1 - exp(-score/70)` and (b) the margin over the
runner-up.

**Categories**

| Category | Examples of signals |
|----------|---------------------|
| `action_required` | request verbs (`submit, reply, renew, verify, call, …`), `please`, `can/could you`, `need you to`, `don't forget`, `deadline`, `due on`, `by <date>`, task nouns (`signed document`, `electricity bill`, `privacy checklist`, …) |
| `meeting_or_event` | `Calendar update:`, `Reminder:`, `scheduled for`, `please join`, `happens on`, `are you available for`, named events (`internship orientation`, `mentor catch-up`, `client discussion`, …), plus a **structured bonus** when an ISO date + time (+ venue) co-occur |
| `personal_information` | profile/self-disclosure phrasings (`for my profile`, `personal note`), preferences (`i prefer`, `vegetarian`, `coffee without sugar`, `dark mode`, `T-shirt size`, …) |
| `general_information` | status/notice statements (`is available`, `has been updated`, `public holiday`, `weather forecast`, `under maintenance`, `closes at`, …) |
| `promotional` | promotions sender account, `Use code SAVE..`, percent discounts, sales, coupons, reward points, plan upsells |
| `sensitive_information` | any Part-3 detection in the message dominates all other signals |

**Rules that remove noise before scoring**
- Conversation openers (`For today:`, `Can you help?`, `Just checking—`,
  `FYI:`, `Important:`, …) are stripped so they cannot be mistaken for
  request verbs.
- A sentence where the *sender* promises an action (`I will send the login
  details separately.`) is treated as general information, not a request.
- A flagged sensitive value wins over weak request signals: a leaked
  password is a security problem first, a to-do item second.
- Confidence below `0.65` is marked `"uncertain": true` and the reason
  text ends with "Low-confidence match."

Every record stores `message_id, timestamp, sender, category, confidence,
reason, message_masked, is_mandatory, uncertain`.

---

## Part 2 — Task & event extraction

`action_required` messages produce **TASK** items; `meeting_or_event`
messages produce **EVENT** items. Every item stores:

```
item_id, type, title, description (masked), deadline, time, person,
priority, location (events), notes (unresolved info), source_message_id
```

- **Titles** are extracted with ordered, hand-tuned patterns
  (`Calendar update: <title>`, `Don't forget to <verb>…; deadline is …`,
  `<phrase> is due on <date>`, `please <verb> … by <date>`, …) with a
  cleaned fallback.
- **deadline / date** — the first explicit ISO date (`YYYY-MM-DD`) is used.
- **time** — normalised to 24-hour `HH:MM` (`6 PM` → `18:00`).
- **person** — extracted only when the message tells the reader to
  contact someone (`Please call Maya …` → `Maya`).
- **venue** (events) — recognised place references (`in/at …`, `Location:`,
  trailing place at sentence end); false hits like "renew the **library
  book**" are avoided by requiring a place context.
- **priority** — heuristic:
  `high` if urgency words (`important`, `deadline`, `don't forget`, …)
  appear, or the deadline is within 7 days of the message timestamp;
  `low` for soft phrasing (`if possible`, `when you are free`, `sometime`,
  `soon`); otherwise `medium`.

**No missing information is ever invented**
- No date phrase → `deadline: null`.
- A *relative* phrase (`tomorrow`, `next week`, `Friday afternoon`,
  `soon`) → `deadline: "unresolved"` plus a `notes` entry explaining why.

Example (`outputs/tasks_events.json`):

```json
{
  "item_id": "EVENT_007",
  "type": "event",
  "title": "Review (tentative)",
  "deadline": "unresolved",
  "time": null,
  "person": null,
  "priority": "low",
  "location": null,
  "notes": ["Relative time phrase 'friday' cannot be resolved to a concrete date without external context."],
  "source_message_id": "MSG_0037"
}
```

---

## Part 3 — Sensitive-information detection and masking

Detection is **value-based**, not topic-based: a message is flagged only
when a concrete secret pattern matches.

| Type | Example pattern | Risk | Recommended action |
|------|-----------------|------|--------------------|
| `password` | `Use password BlueRiver#29 …` | high | `do_not_store` |
| `one_time_password` | `Your OTP is 482193-50.` | high | `do_not_store` |
| `bank_account_number` | `bank account number 006418220145-38` | high | `do_not_send_to_external_service` |
| `card_number` | `card number 4111 1111 1111 1111-92` | high | `do_not_send_to_external_service` |
| `authentication_token` | `access token tok_demo_A8K29Q-53` | high | `do_not_store` |
| `recovery_code` | `recovery code RC-88-KL-19-59` | high | `do_not_store` |
| `personal_identification_number` | `identification number ID-7842-XY-94` | medium | `ask_for_confirmation` |
| `health_information` | `test result says vitamin D deficiency-97` | medium | `ask_for_confirmation` |
| `private_address` | `home address is 42 Lake View Road, Chennai-45` | medium | `safe_to_process_locally` |
| `private_phone_number` | `contact me on 98765 43210-86` | medium | `safe_to_process_locally` |

**Masking policy** — the single strongest guarantee of the project:
- Raw values are replaced by asterisks during the very first processing
  pass (`sensitive.py -> mask_message`).
- Every output file, CLI log line and web page stores/serves only the
  **masked** text. A test (`test_pipeline.py`) scans every generated file
  and asserts that none of the known secret patterns appear anywhere.

Nothing without a value is flagged: *"I will send the login details
separately."* or *"my emergency contact is my brother"* contain no secret
and are intentionally **not** reported as sensitive.

---

## Output files (all masked)

- `outputs/classification.json` (+ `.csv`) — 900 decisions, reason + confidence
- `outputs/tasks_events.json` (+ `.csv`) — extracted tasks & events
- `outputs/sensitive_detections.json` — type / risk / masked text / action
- `outputs/mandatory_results.json` — all three parts for the 15 mandatory IDs
- `outputs/summary.json` — aggregate statistics

Current run: 900 messages → 240 tasks / 170 events / 100 sensitive
detections (10 per type); all 15 mandatory IDs processed.

---

## Web demo (cloud-ready)

`web/app.py` is a small Flask app that serves only the masked outputs:

- Dashboard: filterable classification table (6 categories), confidence
  bars, uncertain flag, tasks/events table, sensitive detections table
- `/mandatory` — the 15 mandatory IDs with all three parts side by side
- JSON API (`/api/*`) + `/healthz`

Deployment: `web: gunicorn --bind 0.0.0.0:$PORT web.app:app` (see
`Procfile`, `requirements.txt`). The dataset itself is never deployed.

---

## Assumptions and limitations

**Assumptions**
1. The dataset is internally consistent and the message text is the only
   content considered (the sender field additionally helps promotional
   detection).
2. `YYYY-MM-DD` dates are unambiguous; `HH:MM` and `X AM/PM` times are
   normalised to 24-hour format.
3. Relative dates (`tomorrow`, `next week`, `Friday afternoon`) cannot be
   resolved without external context (calendar, language, timezone), so
   they are stored as `"unresolved"` instead of guessing.
4. Names outside the known contact set are treated as unknown; "person"
   is only filled when the message *asks the reader to contact someone*.
5. A message may belong to exactly one primary category; the six
   assignment categories are mutually exclusive here.

**Limitations**
- The engine is a hand-built rule system: it is fully explainable and
  deterministic, but it cannot generalise to vocabulary it has never seen
  (no learned embeddings). A hybrid with a small local embedding model
  would reduce fallback noise (`uncertain` messages).
- Priority is heuristic; "review by Friday" with no explicit date is
  treated as medium because no concrete deadline exists.
- Promotional detection uses the sender account + promo wording; a person
  forwarding an ad with no promo keywords would be classified differently.
- Single-category assignment can hide secondary intents (e.g. a message
  that is both an interview confirmation and a task).
- No cross-message reasoning (a "meet next week" reply is not linked to a
  previously scheduled event).

---

## AI-tool usage declaration (required by the assignment)

- **AI development tools used:** `opencode` (DeepSeek model) was used as
  a coding assistant to draft the rule tables, boilerplate, tests and this
  documentation, and to review the code.
- **Runtime:** the pipeline itself calls **no** AI service — no ChatGPT,
  no embeddings, no external APIs. All classification, extraction and
  masking is deterministic local Python (stdlib + Flask for the demo).
- **Data handling:** the dataset and all raw values stay on the local
  machine; generated outputs are masked before they are shared, deployed
  or recorded in the demo video.
- **Accountability:** every rule, scoring formula and confidence/reason
  mechanism is documented in this README and the source code, and is
  described in the demonstration video.

---

## Tests

```
python -m unittest discover -s tests -v
```

32 tests cover: expected categories for 30 curated messages, reason
contents, confidence bounds, sensitive-flag dominance, uncertainty
handling, task/event fields, "no invented data" behaviour, all ten
sensitive types, masking (raw values never appear in outputs), pipeline
counts, chronological order, mandatory-ID coverage, deterministic
re-runs, and secret-leak scans over all generated files.