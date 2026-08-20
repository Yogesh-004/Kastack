# Data files

Per the assignment rules, the supplied datasets are **not** committed to
this repository:

| File | Contents |
|------|----------|
| `data/messages.csv` | L1: 900 fictional messages (chronological) |
| `data/mandatory_demo_ids.csv` | L1/L2: 15 mandatory message IDs |
| `l2_messages.csv` (repo root, git-ignored) | L2: 180 extra messages (`MSG_0901..MSG_1080`) |
| `l2_demo_messages.csv` (repo root, git-ignored) | L2: 24 demo-batch messages (`DEMO_001..DEMO_024`) |
| `l2_demo_queries.csv` (repo root, git-ignored) | L2: demo queries (`DQ01..DQ09`) |
| `README (2).txt` (repo root, git-ignored) | assignment notes |

To re-run the pipeline locally, place the files supplied with the
assignment into the folder (paths as above), then run:

```
pip install -r requirements.txt
python -m kastack.run_pipeline data/messages.csv data/mandatory_demo_ids.csv outputs
python -m kastack.run_l2 data/messages.csv data/mandatory_demo_ids.csv \
    l2_messages.csv l2_demo_messages.csv l2_demo_queries.csv outputs
```

All generated outputs in `outputs/` are pre-computed from the datasets and
are committed **masked only**: sensitive values are replaced with
asterisks (including inside canonical keys, item titles and group
summaries), so the generated artifacts are safe to share and deploy. No
raw sensitive-looking values are contained in `outputs/` or the web app.