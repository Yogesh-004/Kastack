# Loom Demonstration Script (7–10 minutes)

Record with **Loom** (or any screen recorder + mic). Show the live system:
terminal + the Flask dashboard. Every checklist item below **must be
visible** on screen. All on-screen text is already masked by the system.
Keep the terminal font large (Ctrl+scroll or "Large Text" mode).

Proposed timing: ~9 minutes total.

---

## 0:00–0:50 — Intro & approach
- Say: *"I built a fully local, deterministic rule engine. No external AI
  service is used at runtime; every decision has an explicit reason."*
- Show the repo structure in the file explorer or terminal (`tree`):
  `src/kastack/{classifier,extractor,sensitive,pipeline}.py`, `web/`, `tests/`.
- Explain the flow in one sentence: *messages → Part 1 classification →
  Part 2 tasks/events → Part 3 sensitive scan (masking happens first).*

## 0:50–1:40 — Dataset structure (no sensitive-looking values)
- Show `data/messages.csv` header: `message_id, timestamp, sender, message`.
- Show a **few non-sensitive rows only** (e.g. MSG_0001, MSG_0002,
  MSG_0004, MSG_0006). Do **not** scroll into rows containing values.
- Explain: 900 fictional messages, chronological order, sorted before
  processing; `data/` is git-ignored and not in the public repo.

## 1:40–4:00 — Run the pipeline (system must be seen running)
- In the terminal:
  `python -m kastack.run_pipeline data/messages.csv data/mandatory_demo_ids.csv outputs`
- Point at the printed summary: counts per category, tasks/events, risk
  split. Read the six categories aloud.

## 4:00–5:00 — Classification results, all six categories
- Open `http://localhost:5000` → Dashboard → Classification tab.
- Use the category filter and show **one clear example per category**:
  - Action Required: MSG_0007 (reply to client email by 2026-09-04)
  - Meeting or Event: MSG_0001 (family dinner 2026-09-19 10:00)
  - Personal Information: MSG_0009 (emergency contact = brother)
  - General Information: MSG_0006 (battery fully charged)
  - Promotional: MSG_0014 (festival discount, code SAVE17)
  - Sensitive Information: MSG_0005 (home address, masked as `******`)
- For **three of them, read the reason line aloud** (e.g. MSG_0002, MSG_0001,
  MSG_0053) — this covers "at least three classification decisions with
  explanations".

## 5:00–5:50 — Mandatory 15 IDs
- Open the **Mandatory IDs** page. Scroll through all 15 cards
  (MSG_0001, 0002, 0003, 0004, 0005, 0006, 0007, 0009, 0012, 0013, 0014,
  0015, 0016, 0024, 0037). Read the ID list aloud.
- Point at **MSG_0037** ("The review could be Friday afternoon") — this is
  the *incorrect/uncertain result*: confidence 53%, flagged `uncertain`,
  date `unresolved`. Explain why: tentative wording, no date given. (This
  also covers "one example containing missing or unclear information".)

## 5:50–6:40 — Tasks (at least three, correct)
Dashboard → Tasks & Events → filter Tasks. Show:
- `TASK` from MSG_0007 — Reply to the client email, deadline 2026-09-04, high
- `TASK` from MSG_0010 — Pay the electricity bill, deadline 2026-09-09, high
- `TASK` from MSG_0056 — Call Maya, person = Maya, low (soft wording)
Add: the task for MSG_0002 (review privacy checklist).

## 6:40–7:20 — Events (at least three, correct)
Filter Events. Show:
- MSG_0001 → Family dinner, 2026-09-19, 10:00, the library
- MSG_0003 → Mentor catch-up, 2026-09-16, 11:00, the city clinic
- MSG_0011 → Internship orientation, 2026-09-18, 13:00, Conference Room 2
Mention: `EVENT_007` from MSG_0037 (`Review (tentative)`, deadline
`unresolved`) as the missing/unclear example already covered.

## 7:20–8:10 — Sensitive detection + masking
- Sensitive tab. Filter High risk.
- Show one record per type (password MSG_0086, OTP MSG_0243, card
  MSG_0013, token MSG_0074) and read the risk + recommended action aloud.
- Emphasise: the app **never** prints the raw value — masked text column
  shows only asterisks. Note MSG_0012 ("I will send the login details
  separately.") is *not* flagged: no value present.

## 8:10–8:50 — One important code section, explained in your own words
Open `src/kastack/sensitive.py` and explain `detect_sensitive` /
`mask_message`: rules capture the value, masking replaces it with
asterisks *before* anything is written out; show the test
`test_no_secret_values_in_output_files` proving no leak. Use your own
words, e.g.:
> "The detector only fires when it captures a real value — a bare mention
> like 'login details' is not sensitive. And masking happens on the same
> pass, so nothing downstream can ever see the raw value."

## 8:50–9:30 — Limitations & improvements (tying to the viva)
- Read the "uncertain" count from the dashboard (≈70) and explain why
  low-confidence rows exist (fallback/no-date messages).
- Improvements: a local sentence-embedding model for out-of-vocabulary
  wording; cross-message linking ("next week" → last scheduled event);
  training labels to calibrate confidence; multi-label classification.
- Close: link the cloud demo URL + repo + outputs summary.

---

## Required-feature checklist (all must appear on screen)

- [ ] System running live (terminal + web app)
- [ ] Dataset structure (non-sensitive rows only)
- [ ] All six categories demonstrated
- [ ] All 15 mandatory IDs shown
- [ ] ≥3 correct tasks (MSG_0007, MSG_0010, MSG_0056 + more)
- [ ] ≥3 correct meetings/events (MSG_0001, MSG_0003, MSG_0011)
- [ ] Missing/unclear info example (MSG_0037 → `unresolved`)
- [ ] Sensitive detection: type, risk, masking, recommended action
- [ ] ≥3 classification decisions with explanations (read the reasons)
- [ ] One incorrect/uncertain result + why (MSG_0037, 53% confidence)
- [ ] One code section explained in own words (sensitive.py masking)
- [ ] Limitations and improvements
- [ ] No sensitive-looking values anywhere on screen

## Tips
- Close all other windows; hide the file paths if they contain personal
  names. Prefer the browser dashboard over raw JSON for readability.
- Speak slowly; numbers are small on recordings.
- Rehearse once at 1.25x speed to trim silence.