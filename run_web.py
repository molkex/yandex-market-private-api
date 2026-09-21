#!/usr/bin/env python3
"""Launcher for openYaMarket Web Dashboard & Lead Magnet.

Usage:
    python run_web.py
    python run_web.py --port 8080 --host 127.0.0.1
"""
from __future__ import annotations

import os
import sys

# Ensure local package is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from openyamarket.web import main

if __name__ == "__main__":
    main()
