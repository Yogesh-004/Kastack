# Loom Demonstration Script — L2 Extension (≤ 5 minutes)

Record with **Loom**. Show the live system: terminal + the Flask
dashboard (`/l2`). Every checklist item below must be **visible** on
screen. All on-screen text is already masked by the system; never type
raw values into the terminal. Keep the terminal font large.

The demo must visibly load `l2_demo_messages.csv` as an unseen batch and
run every query from `l2_demo_queries.csv` through the real pipeline.

---

## 0:00–0:35 — L1 → L2 extension, one shared state
- Say: *"The L2 extension reuses the L1 pipeline output. It then ingests
  180 new messages (MSG_0901..MSG_1080) in the same chronological state,
  and finally the 24 unseen demo-batch messages."*
- Run:
  `python -m kastack.run_l2 data/messages.csv data/mandatory_demo_ids.csv l2_messages.csv l2_demo_messages.csv l2_demo_queries.csv outputs`
- Point at the printed summary: canonical items 52, priority decisions
  523, routes 135, and the basic benchmark line.

## 0:35–1:15 — Related-message grouping (≥2 correct examples)
- Open the web app → **L2 Assistant → Related-message groups**.
- Show **GROUP_032 "Submit the weekly report"** (11 messages across the
  whole corpus — the rarity-weighted resolver picks this thread, not the
  "project review" thread that merely shares the word "report").
- Show the **interview-slot group** (DEMO_001/DEMO_003/DEMO_016/…:
  urgent → reschedule → unclear, all kept in one thread with a timeline
  summary).
- Read one group summary line aloud.

## 1:15–2:00 — Priority engine + honest failure
- Open the **Priority engine** tab and filter `critical`.
- Show **DQ07 / DEMO_016**: the interview slot has status *unclear* but
  stays *critical* (`uncertainty_keeps_priority` — uncertainty about a
  status is not uncertainty about urgency).
- Show one honest limitation: the high-risk bank-note server warning,
  or the SQ11-style generic query producing "retrieved evidence, no
  definitive answer".

## 2:00–2:40 — Semantic search + benchmark
- Open the **Benchmark** tab: 246x speedup, mean latency of the index,
  and `top-1 21/21` agreement with the naive baseline.
- Explain: same TF-IDF formula on both paths, only the precomputation
  differs — that is why the comparison is fair.

## 2:40–3:20 — Privacy routing, all three routes (demo batch)
- Open **Privacy routing** and switch the scope to the demo batch.
- Show one row per route:
  - `blocked` — DEMO_012 OTP / DEMO_013 password (masked evidence only,
    never the raw value);
  - `ask_for_confirmation` — DEMO_015/016/017/023 (medical note, status
    ambiguity);
  - `process_locally` — DEMO_014 delivery address.
- Count them aloud: 3 blocked / 4 ask / 1 local.

## 3:20–4:10 — Live assistant on the demo queries
- Open the **Ask the assistant** box, run **DQ01–DQ09** in order from
  `l2_demo_queries.csv` (or load them from the dropdown).
- Call out DQ02 (completed/cancelled: 3 items), DQ03 (orientation
  rescheduled via DEMO_007/DEMO_009), DQ08 (no approval recorded — the
  assistant refuses to guess), DQ07 (critical-kept).
- Type one masked-sensitive question (e.g. the OTP) and show the
  **"Privacy route: blocked"** prefix on the answer.

## 4:10–4:45 — Masked-sensitive output everywhere
- Open `outputs/l2_items.json` and `l2_groups.json` briefly: show the
  bank-note title `Note my bank account number ******` and the address
  thread titled `Wait for confirmation` — raw values never appear in
  keys, titles, summaries or logs.
- Mention: a dedicated test scans every generated JSON and asserts that
  none of the known secret patterns appear anywhere.

## 4:45–5:00 — Wrap up
- Close with the repo link, cloud demo URL, `DELIVERABLES.md`, and the
  tests (`python -m unittest discover -s tests -v` → 60 passed).
- One-sentence honesty note: the engine is rules-only; it cannot
  generalise to vocabulary it has never seen, and that limitation is
  listed in the README.

---

## Required-feature checklist (all must appear on screen)

- [ ] L1 → L2 extension visibly running (terminal + dashboard)
- [ ] Unseen demo batch loaded and queries DQ01–DQ09 executed for real
- [ ] ≥2 correct grouped examples (weekly-report thread; interview-slot thread)
- [ ] All 3 privacy routes demonstrated (1 blocked, 1 ask, 1 local)
- [ ] Masked sensitive output visible (bank account title, OTP answer, addresses)
- [ ] Performance/quality comparison (benchmark tab: speedup + top-1)
- [ ] One honest failure/limitation (generic "no definitive answer" or
      the unresolved-date examples)
- [ ] No sensitive-looking values anywhere on screen

## Tips
- Close all other windows; hide folder paths that contain personal names.
- Use the L2 dropdown for DQ queries and read each answer aloud briefly.
- Rehearse once at 1.25x to trim silence and stay under 5 minutes.