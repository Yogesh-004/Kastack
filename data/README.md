# Data files

Per the assignment rules, the supplied dataset (`messages.csv` with 900
messages) is **not** committed to this repository.

To re-run the pipeline locally, place the two files supplied with the
assignment into this folder:

```
data/messages.csv            (900 fictional messages, chronological)
data/mandatory_demo_ids.csv  (15 mandatory message IDs)
```

Then run:

```
pip install -r requirements.txt
python -m kastack.run_pipeline data/messages.csv data/mandatory_demo_ids.csv outputs
```

All generated outputs in `outputs/` are pre-computed from the dataset and
are committed **masked only**: sensitive values are replaced with
asterisks, so the generated artifacts are safe to share and deploy. No raw
sensitive-looking values are contained in `outputs/` or the web app.