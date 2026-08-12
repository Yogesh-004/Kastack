"""Vercel serverless entry point.

Vercel's Python runtime auto-detects the exported `app` WSGI callable.
The Flask app itself lives in web/app.py; `vercel.json` routes every
request to this function and restores the original request path via a
`request.path` transform. Only masked outputs (outputs/*.json) are served.
"""

from web.app import app  # noqa: F401  (Vercel imports this as `app`)