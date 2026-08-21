# KaStack L2 — 5-Minute Demo Script (rejection-proof)

**Goal:** a Loom screen recording that shows the running app and hits **every**
"Results for mandatory test cases" / "What We Check" item. Keep the app at
`https://kastack-phi.vercel.app` (it is already live and runs the same
deterministic, masked engine). Record full-screen; zoom tables so text is
readable. All numbers below are取自 the committed outputs — say them as shown.

**Rejection-proof checklist (each grader item → where it appears):**

| What the grader checks | In video at | Proof on screen |
|---|---|---|
| L1 system + how L2 extends it | 0:00–0:30 | Dashboard nav + `/l2` open; "900 L1 → +180 L2 → +24 demo" |
| ≥2 grouped examples | 0:30–1:20 | Groups tab: Family dinner (12), Pay electricity bill (13) |
| Local request | 1:20–1:50 | DEMO_014 → `process_locally` (masked "Deliver … to ******") |
| Ask-for-confirmation request | 1:50–2:20 | DEMO_015 → `ask_for_confirmation` (health note ******) |
| Blocked request | 2:20–2:40 | DEMO_012 → `blocked` (OTP ******) |
| Sensitive only masked | 2:20–3:10 | Sensitive tab + blocked assistant answer |
| Perf comparison (time/size/quality) | 3:10–4:00 | Benchmark tab: 9.0118ms→0.0366ms, 246×, 396KB vs 130KB, 21/21 |
| Challenge / incorrect result + fix | 4:00–4:40 | Title-leak bug → mask-before-extract + leak-scan test |
| Mandatory cases + testing notes | 4:40–5:00 | 15/15 mandatory, 60 tests, device + measurement |

---

## 0:00–0:30 — Intro: L1 → L2 extension (show the running app)
- Open `https://kastack-phi.vercel.app` → Dashboard. Point at nav:
  **Dashboard · Mandatory IDs · L2 Assistant · Health**.
- Click **L2 Assistant**. Say:
  > "This is the L2 extension of an L1 message classifier. L1 processed
  > **900** messages (classification, tasks/events, sensitive detection, the
  > 15 mandatory IDs). L2 continues in the *same* shared state: **+180** L2
  > messages (MSG_0901–MSG_1080), then a hidden **24-message demo batch**
  > (DEMO_001–DEMO_024) and 9 queries (DQ01–DQ09). The result is **52
  > canonical items/groups** and **523 priority decisions**."
- Show the stat cards at top of `/l2` (Messages processed, Items/Groups,
  Priority decisions, Search speedup, Top-1 agreement).

## 0:30–1:20 — Grouping: two correct examples (Groups tab)
- On `/l2`, open **Related-message groups** tab. Type `family` in the search.
- **Example 1 — Family dinner:** 12 messages (`MSG_0001, MSG_0043, MSG_0275,
  MSG_0435, MSG_0479, MSG_0603, MSG_0646, MSG_0697 …`) merged into one thread,
  kept in **chronological order**, status `rescheduled`. Say: "Messages spread
  across the corpus, about the same event, are merged by similarity, not by
  keyword equality."
- Clear search, type `electricity`. **Example 2 — Pay the electricity bill:**
  13 messages (`MSG_0010, MSG_0265, MSG_0339, MSG_0536, MSG_0614, MSG_0620,
  MSG_0667, MSG_0743 …`), status `in_progress`. Point at the **Latest deadline**
  and **Summary** columns to show chronology + meaning.

## 1:20–2:20 — Privacy-aware routing (3 routes, using the supplied demo messages)
- Open **Demo batch details** tab (or Routing tab → scope "Demo batch (24)").
  Say: "I'll use the supplied demo messages. Each is routed by a rule-based
  privacy policy; evidence is always masked."
- **Local (process_locally):** `DEMO_014` —
  _"Deliver the demo device to ******."_ → safe to process locally (medium
  private-address risk).
- **Ask for confirmation:** `DEMO_015` —
  _"My private medical note mentions ******."_ → `ask_for_confirmation`
  (health information, medium risk).
- **Blocked:** `DEMO_012` — _"Your fictional OTP is ******. Do not share it."_
  → `blocked` (high-risk one-time-password).
- Emphasise: the **masked_evidence** column shows `******` every time — no raw
  secret is ever displayed or stored.

## 2:20–3:10 — Sensitive data is only ever masked
- Open **Sensitive Detections** on the Dashboard: e.g.
  `type: private_address, risk: medium, masked: "Hi, My home address is ******."`
- Back on `/l2`, **Ask** box: type a blocked query, e.g.
  _"what is my OTP code?"_ → answer returns with the **"Privacy route:"**
  prefix and `route: blocked`. Say: "The live assistant refuses and explains
  why, instead of leaking."

## 3:10–4:00 — Performance: original vs optimized (fair comparison)
- Open **Benchmark** tab. Read the cards:
  > "Mean latency per query: naive **9.0118 ms** vs sparse index
  > **0.0366 ms** → **246.38×** speedup. Index size **396 KB** vs raw docs
  > **130 KB** (the index is bigger on disk, but ~246× faster). Quality is
  > **unchanged**: top-1 agreement naive == index is **21/21**, top-5 overlap
  > 1.0. Both paths use the *identical* TF-IDF formula — only precomputation
  > differs, so this is a fair comparison."
- Mention device + measurement: "I measured on my laptop (Python 3.9.13) with
  `time.perf_counter` over the query set; the benchmark script reports the mean
  latency and top-1 agreement you see here."

## 4:00–4:40 — One challenge / incorrect result and the fix
- Say: "The interesting bug we caught: extraction originally ran on the *raw*
  text, so a generated item title once contained a bank account number
  (`Note my bank account number 91XXXXXX12`). That's a leak — an incorrect
  output. **Fix:** mask *before* classify/extract/resolution, so downstream
  stages only ever see masked text (`Note my bank account number ***************`).
  We guard it with a **leak-scan test** that re-applies every secret pattern
  across `outputs/` — it must stay empty. Result: **0 secret leaks**."
- (Optional, if time:) "A second challenge was hyphenated addresses like
  `Chennai-B`; the address regex was extended to allow hyphenated localities."

## 4:40–5:00 — Mandatory cases, tests, and wrap
- Open **Mandatory IDs** page (Dashboard nav) → show **15 / 15** found.
- Say: "Prioritization is explainable (every decision has reason + signals +
  confidence); grouping is chronological and meaningful; search and privacy
  routing are deterministic. **60 tests pass** (32 L1 + 28 L2), including the
  leak-scan and the 21/21 retrieval checks. The live demo is at
  kastack-phi.vercel.app. That's the complete L2 system."

---

## Recording tips
- Use Loom, full-screen, ~5:00. Speak the bolded numbers; they are the proof.
- Keep the **Groups**, **Routing/Demo**, and **Benchmark** tabs readable
  (zoom to 125–150%).
- Do **not** open raw CSVs or any file containing unmasked secrets on screen.
- If a tab is slow, pre-load `/l2` once before recording.
- The queries shown (DEMO_012/014/015, DQ01) are exactly the supplied demo
  messages/queries, satisfying "use the supplied demo messages and queries".
