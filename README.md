# Kastack — Message Classification, Task/Event Extraction & Sensitive-Information Detection (L1) + L2 Extension

A fully local, deterministic rule-based pipeline that processes 900 fictional messages (L1) and the L2 extension (priority, grouping, semantic retrieval + assistant, privacy routing) over 1080 corpus messages plus a 24-message demo batch:

| Part | Task | Deliverable |
|------|------|-------------|
| 1 | **Message classification** into 6 categories with confidence + reason | `outputs/classification.json` |
| 2 | **Task & event extraction** (title, description, deadline, time, person, priority) | `outputs/tasks_events.json` |
| 3 | **Sensitive-information detection** with type, risk, masked text, recommended action | `outputs/sensitive_detections.json` |
| 4 | **L2: priority engine** (per-message, full history) | `outputs/l2_priority.json` |
| 5 | **L2: related-message grouping** (threads/events) | `outputs/l2_groups.json` |
| 6 | **L2: semantic search + intelligent assistant** (local sparse index) | `outputs/l2_index.json`, `l2_answers.json` |
| 7 | **L2: privacy-aware routing** (blocked / confirm / local) | `outputs/l2_routing.json` |

No external AI service is called at runtime and no message content leaves
this machine. All decisions are made by explicit, readable rules, so every
output line can be explained.

> The assignment datasets (`data/messages.csv`, `l2_messages.csv`,
> `l2_demo_messages.csv`, `l2_demo_queries.csv`) are **not** published in
> this repository. See `data/README.md`.

---

## Quick start

```bash
pip install -r requirements.txt          # flask + gunicorn (web app only)

# 1. Run the L1 pipeline (requires the dataset in data/)
python -m kastack.run_pipeline data/messages.csv data/mandatory_demo_ids.csv outputs

# 2. Run the L2 extension (L1 -> L2 -> demo batch, one shared state)
python -m kastack.run_l2 data/messages.csv data/mandatory_demo_ids.csv \
    l2_messages.csv l2_demo_messages.csv l2_demo_queries.csv outputs

# 3. Tests
python -m unittest discover -s tests -v

# 4. Local web demo
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
│   ├── pipeline.py      # L1 orchestration + output writers
│   ├── common.py        # shared helpers (dates, times, venues, masking)
│   ├── run_pipeline.py  # L1 CLI entry point
│   ├── l2_core.py       # ItemRegistry state machine + canonical topics
│   ├── l2_priority.py   # per-message priority engine (full history)
│   ├── l2_groups.py     # related-message thread grouping + summaries
│   ├── l2_index.py      # local TF-IDF sparse index (+ naive baseline)
│   ├── l2_assistant.py  # intent dispatch + evidence-guarded answers
│   ├── l2_routing.py    # privacy routing policy (blocked/confirm/local)
│   ├── l2_benchmark.py  # fair naive-vs-index comparison
│   ├── l2_pipeline.py   # L2 orchestration + masked-state serialization
│   └── run_l2.py        # L2 CLI entry point
├── web/                 # Flask dashboard (cloud-deployable, masked data only)
├── tests/               # unittest suite (60 tests: 32 L1 + 28 L2)
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

L1:
- `outputs/classification.json` (+ `.csv`) — 900 decisions, reason + confidence
- `outputs/tasks_events.json` (+ `.csv`) — extracted tasks & events
- `outputs/sensitive_detections.json` — type / risk / masked text / action
- `outputs/mandatory_results.json` — all three parts for the 15 mandatory IDs
- `outputs/summary.json` — aggregate statistics

L2 (written by `run_l2.py`):
- `l2_summary.json` — aggregate stats per corpus/demo scope
- `l2_items.json`, `l2_demo_items.json` — canonical items (masked titles)
- `l2_groups.json`, `l2_demo_groups.json` — related-message groups + summaries
- `l2_priority.json` — per-message priority decisions (reason/signals/confidence)
- `l2_routing.json`, `l2_demo_routing.json` — privacy routes for all three policies
- `l2_index.json`, `l2_index_docs.json` — serialized sparse index + document store
- `l2_answers.json`, `l2_query_routing.json` — assistant answers + query routes
- `l2_web_state.json` — masked living state for the cloud demo assistant
- `benchmark_comparison.json` — naive-vs-index benchmark

Current run: 1080 corpus + 24 demo messages → 52 canonical items/groups,
523 priority decisions, 135 routing entries (75 blocked / 35 ask / 25
local), 15/15 mandatory IDs, benchmark 246.38x.

---

## Web demo (cloud-ready)

`web/app.py` is a small Flask app that serves only the masked outputs:

- Dashboard: filterable classification table (6 categories), confidence
  bars, uncertain flag, tasks/events table, sensitive detections table
- `/mandatory` — the 15 mandatory IDs with all three parts side by side
- `/l2` — priority engine, related-message groups, privacy routing (all
  three routes), demo-batch details, benchmark, precomputed demo answers
  and a **live assistant** (`/api/l2/ask`) that runs the same
  deterministic intent engine over the serialized masked state — no raw
  data and no external AI on the server
- JSON API (`/api/*`) + `/healthz`

Deployment: `web: gunicorn --bind 0.0.0.0:$PORT web.app:app` (see
`Procfile`, `requirements.txt`, `vercel.json`). The datasets themselves
are never deployed.

---

## L2 extension — priority, grouping, retrieval, assistant & privacy routing

The L2 extension consumes the L1 pipeline output (900 classified
messages) plus 180 additional messages (`MSG_0901..MSG_1080`), all
processed **chronologically in one shared state**, then the 24-message
demo batch (`DEMO_001..DEMO_024`) and its 9 demo queries (`DQ01..DQ09`).

Each processed message is resolved onto a **canonical item** (task or
event) through a registry with fuzzy topic matching. There are **no
gaps, no invented facts**: an item only has the statuses, deadlines,
priorities and message references that the evidence actually supports.

```
corpus  : 1080 messages (900 L1 + 180 L2)   | demo  : 24 messages
items   : 52 canonical records (cumulative) | groups: 52
priority: 523 per-message decisions         | routes: 135 (75 blocked,
            with full history                       35 ask, 25 local)
index   : 1156 docs / 738 terms             | benchmark 246x vs naive
mandatory ids: 15/15 found
```

### 1) Priority engine (`l2_priority.py`)

Every message that can be tied to an item receives a priority decision;
ties to an item are required, so ambiguous notices go to a noticeboard
instead of receiving a fabricated priority. Scoring is a transparent
point system:

| Signal | Points |
|--------|--------|
| new item creation | +20 |
| overdue deadline | +70 |
| deadline today / tomorrow / 2–7 days / 8–14 days | +40 / +35 / 25–5 / +5 |
| relative deadline (`tomorrow`, `today`) | +30 / +35 |
| urgency wording (`treat this as urgent`) | +25 |
| deadline pulled in earlier | +20 |
| status conflict, follow-ups, response requested, high-risk secret, authoritative sender | +10..+20 |
| `not urgent`, deadline extended | −15 / −10 |

Thresholds: `≥75` critical, `≥50` high, `≥25` medium, else low. A
**completed/cancelled** message always drops the item to `low` with
`no_action_needed`; an **unclear** status never downgrades an item
below its current priority (`uncertainty_keeps_priority`) because
uncertainty about a status says nothing about urgency. Every decision
records `reason`, `signals` and `confidence`.

The registry also tracks `status_history`, `deadline_history` (concrete
dates only — relative phrases are stored as `"unresolved"`, never
guessed) and `priority_history` (explicit transitions), which the
assistant uses as structured evidence.

### 2) Related-message grouping (`l2_core.py`, `l2_groups.py`)

Messages are grouped when their canonical topic matches an existing
thread:

- **exact** key match (confidence 0.97),
- **containment** ("model results" ⊂ "review the model results"),
- **Jaccard** with a wide margin (≥0.62 and ≥0.18 ahead of the runner-up
  — ties are deliberately left unresolved),
- a rarity-weighted **loose** fallback (≥0.50) so "weekly report"
  resolves to its own thread instead of a "project review" thread that
  merely shares the word "report".

Junk keys are impossible at creation time: a new topic needs ≥2 content
tokens, and status-marker words led by `has/is/was` never become items.
Each group ships with a chronological summary line, status, latest
deadline and conflict notes (`l2_groups.json`).

### 3) Semantic search + intelligent assistant (`l2_index.py`, `l2_assistant.py`)

**Retrieval** is a fully local, deterministic TF-IDF sparse index over
the *masked* text of messages, items, groups and priority decisions
(word tokens + 5-char prefix stems; IDF prefers distinctive subject
words). An identical-formula `naive_search` baseline exists so the
benchmark is fair: same formula, only the precomputation differs,
resulting in **246x speedup** on 21 representative queries with **21/21
top-1 agreement** between baseline and index.

**Assistant** (`l2_answers.json`, live in the web app via
`/api/l2/ask`) dispatches queries to explicit intents —
`became_critical`, `completed_or_cancelled`, `rescheduled`,
`comparative status`, `conflicting`, `blocked`, `confirmation`,
`approval_status`, `deadlines_changed`, `related`, `today_tasks`, … —
and answers only from structured evidence plus retrieved (masked)
messages. Guards keep it honest:

- priority/status answers always cite `supporting_message_ids`;
- question-shaped messages ("Was X approved?") are never treated as
  approval statements;
- when no evidence exists it says so ("No item's priority was newly
  raised…") instead of guessing;
- generic queries degrade to a visible "retrieved evidence" fallback.

All 9 demo queries (DQ01–DQ09) answer correctly, e.g. DQ07 keeps the
interview slot *critical* even though its status is *unclear*.

### 4) Privacy-aware routing (`l2_routing.py`)

Every message and every demo query is routed according to an explicit
policy, and **only masked evidence** leaves the engine:

| Route | When | Example |
|-------|------|---------|
| `blocked` | high-risk secret (password, OTP, token, account, recovery code, card) | OTP `864219` |
| `ask_for_confirmation` | medium-risk/approval-required data or an ambiguous status | medical note, unclear reschedule |
| `process_locally` | low/medium-risk data the policy marks as safe | delivery address |

Demo batch: 3 blocked / 4 ask-for-confirmation / 1 process-locally (all
three routes exercised). Queries that were blocked get the note
"Privacy route: this request was blocked from any external processing;
the answer below uses masked evidence only."

**Masking guarantee** — classification, extraction and topic resolution
run on the *masked* text (via deterministic `mask_value`), so even
canonical keys, item titles and group summaries can never embed a raw
secret (e.g. the bank-note title becomes "Note my bank account number
******"). A dedicated test scans every generated JSON and asserts that
none of the known secret patterns appear.

### 5) Benchmark (`l2_benchmark.py`)

The `naive_search` baseline and the `SparseIndex` share the identical
TF-IDF scoring formula over the same documents; only precomputation
differs, so the comparison measures the engineering win, not a formula
shortcut. Latest run: **246.38x** faster mean query latency,
`quality_top1_agreement = 21/21`, deterministic outputs.

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
  previously scheduled event). *Addressed by the L2 extension*: the
  item registry groups threads, tracks reschedules, conflicts and
  priority history, and the assistant reasons across all of it.

---

## AI-tool usage declaration (required by the assignment)

- **AI development tools used:** `opencode` (DeepSeek model) was used as
  a coding assistant to draft the rule tables, boilerplate, tests and this
  documentation, and to review the code.
- **Runtime:** the pipeline itself calls **no** AI service — no ChatGPT,
  no embeddings, no external APIs. All classification, extraction,
  prioritisation, retrieval, routing and assistant answers are
  deterministic local Python (stdlib + Flask for the demo).
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

60 tests (32 L1 + 28 L2) cover: expected categories for 30 curated
messages, reason contents, confidence bounds, sensitive-flag dominance,
uncertainty handling, task/event fields, "no invented data" behaviour,
all ten sensitive types, masking (raw values never appear in outputs),
pipeline counts, chronological order, mandatory-ID coverage,
deterministic re-runs, secret-leak scans over all generated files, and
for L2: status-detection normalisation (hyphens/ISO dates, `Confirmed:`
vs auto-complete), junk-topic refusal (`has/is/was` never become items),
registry lifecycle, priority thresholds + `unclear`-keeps-priority,
privacy routing for all three routes, index serialization round-trip and
naive-vs-index top-1 agreement, and live-assistant end-to-end answers.

---

## AI-tool usage declaration 

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
