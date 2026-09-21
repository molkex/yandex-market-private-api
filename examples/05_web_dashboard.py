#!/usr/bin/env python3
"""Example 05: Launching the Interactive Web Dashboard & Lead Magnet.

The web dashboard provides a complete zero-device UI for:
1. Searching catalog items across Russian regions (Moscow, SPb, Kazan, etc.).
2. Inspecting real-time warehouse stock levels (before sellers hide them).
3. Viewing exact referral reward rates (Standard Plus points vs elevated B2B ₽).
4. Generating instant clean sharing links.
"""
from __future__ import annotations

import os
import sys

# Ensure library is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openyamarket.web import main

if __name__ == "__main__":
    print("Launching Yandex Market Private API Web Dashboard...")
    print("Open http://localhost:8000 in your browser.")
    main()
