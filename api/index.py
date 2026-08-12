"""Vercel serverless entry point.

Vercel's Python runtime auto-detects the exported `app` WSGI callable.
The Flask app itself lives in web/app.py; `vercel.json` rewrites every
route to this function. Only masked outputs (outputs/*.json) are served.
"""

from web.app import app  # noqa: F401  (Vercel imports this as `app`)