"""
api/index.py — Vercel Serverless 入口 (與 backend/app/main.py 100% 共用 V6.0 核心引擎)
"""

import os
import sys

_ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_BACKEND_DIR = os.path.join(_ROOT_DIR, "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.main import app  # noqa: F401
