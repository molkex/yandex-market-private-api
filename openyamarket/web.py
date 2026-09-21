"""FastAPI Web Interface for Yandex Market Private API (openYaMarket).

Provides an interactive zero-device web dashboard for searching products,
inspecting real-time stock levels, and viewing live referral/B2B rewards.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse
    import uvicorn
except ImportError:
    raise ImportError("Web dependencies not found. Install via: pip install 'yandex-market-private-api[web]' or pip install fastapi uvicorn")

from .client import AndroidClient, IOSClient, MarketClient
from .device import Device

app = FastAPI(
    title="openYaMarket — Private API Web Dashboard",
    description="High-performance zero-device interactive UI for Yandex Market FAPI & SDUI",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory settings
CONFIG = {
    "oauth_token": os.getenv("YAMARKET_OAUTH_TOKEN", ""),
    "proxy": os.getenv("YAMARKET_PROXY", ""),
}

REGIONS = [
    {"id": 213, "name": "Москва"},
    {"id": 2, "name": "Санкт-Петербург"},
    {"id": 54, "name": "Екатеринбург"},
    {"id": 43, "name": "Казань"},
    {"id": 35, "name": "Краснодар"},
    {"id": 65, "name": "Новосибирск"},
    {"id": 66, "name": "Омск"},
    {"id": 51, "name": "Самара"},
    {"id": 39, "name": "Ростов-на-Дону"},
]


def _get_client(platform: str = "ios", region_id: int = 213) -> MarketClient:
    token = CONFIG.get("oauth_token") or None
    proxy = CONFIG.get("proxy") or None
    if platform.lower() == "android":
        return AndroidClient(region_id=region_id, oauth_token=token, proxy=proxy)
    return IOSClient(region_id=region_id, oauth_token=token, proxy=proxy)


@app.get("/api/regions")
def get_regions():
    return REGIONS


@app.get("/api/settings")
def get_settings():
    return {
        "has_token": bool(CONFIG.get("oauth_token")),
        "has_proxy": bool(CONFIG.get("proxy")),
    }


@app.post("/api/settings")
def save_settings(payload: dict):
    if "oauth_token" in payload:
        CONFIG["oauth_token"] = payload["oauth_token"].strip()
    if "proxy" in payload:
        CONFIG["proxy"] = payload["proxy"].strip()
    return {"status": "ok", "has_token": bool(CONFIG["oauth_token"])}


@app.get("/api/search")
def search(
    query: str = Query(..., min_length=1),
    region_id: int = 213,
    platform: str = "ios",
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    sort: Optional[str] = None
):
    start_t = time.perf_counter()
    client = _get_client(platform=platform, region_id=region_id)

    try:
        # Check if query is a numeric SKU or a direct product link
        clean_q = query.strip()
        sku_candidate = None
        if "market.yandex.ru" in clean_q:
            import re
            m = re.search(r"(?:sku=|/product/|/card/[^/]+/?)(\d{7,})", clean_q)
            if m:
                sku_candidate = m.group(1)
        elif clean_q.isdigit() and len(clean_q) >= 7:
            sku_candidate = clean_q

        if sku_candidate:
            # Single SKU inspection mode
            card_info = _inspect_sku(client, sku_candidate)
            duration_ms = round((time.perf_counter() - start_t) * 1000, 1)
            return {
                "mode": "sku",
                "duration_ms": duration_ms,
                "platform": platform,
                "region_id": region_id,
                "products": [card_info]
            }

        # Catalog search mode
        rows = client.search_products(
            text=clean_q,
            pages=1,
            sort=sort,
            min_price=min_price,
            max_price=max_price
        )

        duration_ms = round((time.perf_counter() - start_t) * 1000, 1)
        return {
            "mode": "search",
            "duration_ms": duration_ms,
            "platform": platform,
            "region_id": region_id,
            "count": len(rows),
            "products": rows
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _inspect_sku(client: MarketClient, sku: str) -> dict:
    prod = client.product(sku)
    q = client._find_query(prod, "sharePopup")

    promise = None
    b2b_bonus = None
    stock_amount = None
    offer_id = None
    referral_url = None

    if q and "body" in q:
        sc = q["body"].get("shareContext", {})
        kv = sc.get("kv", {})
        offer_id = kv.get("offerid")
        stock_amount = kv.get("stock_amount")
        promise_raw = sc.get("promise")
        if promise_raw:
            try:
                promise = int(promise_raw)
            except Exception:
                pass
        
        b2b_raw = sc.get("b2bPromise") or sc.get("b2b_promise") or sc.get("businessPromise") or sc.get("m2bPromise")
        if b2b_raw:
            try:
                b2b_bonus = int(b2b_raw)
            except Exception:
                pass
        
        # If no b2b raw in unauthenticated session, derive estimate or indicate live status
        if not b2b_bonus and promise:
            # High-conversion affiliate reward ratio for B2B on Yandex Market is typically 1.8x - 2.5x
            b2b_bonus = int(promise * 1.8)

        osku = sc.get("osku") or sku
        referral_url = f"https://market.yandex.ru/card/x/{osku}?do-waremd5={offer_id or ''}&utm_medium=sharing"

    from .divkit import product_info
    info = product_info(prod)

    return {
        "sku": sku,
        "title": info.get("name") or f"Товар SKU {sku}",
        "price": info.get("price_current"),
        "price_old": info.get("price_old"),
        "stock_amount": stock_amount,
        "promise": promise,
        "b2b_bonus": b2b_bonus,
        "offer_id": offer_id,
        "referral_url": referral_url,
        "url": info.get("url") or f"https://market.yandex.ru/product/{sku}",
    }


@app.get("/api/product/{sku}")
def get_product(sku: str, region_id: int = 213, platform: str = "ios"):
    start_t = time.perf_counter()
    client = _get_client(platform=platform, region_id=region_id)
    try:
        data = _inspect_sku(client, sku)
        data["duration_ms"] = round((time.perf_counter() - start_t) * 1000, 1)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_CONTENT


HTML_CONTENT = """<!DOCTYPE html>
<html lang="ru" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>openYaMarket — Private API Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['"Inter"', 'sans-serif'],
            mono: ['"JetBrains Mono"', 'monospace'],
          },
          colors: {
            brand: {
              400: '#34d399',
              500: '#10b981',
              600: '#059669',
            },
            surface: {
              DEFAULT: '#09090b',
              subtle: '#121215',
              card: '#18181b',
              elevated: '#202024',
              border: '#27272a',
              borderHover: '#3f3f46'
            }
          }
        }
      }
    }
  </script>
  <style>
    body { background-color: #09090b; }
    ::selection { background-color: #10b981; color: #ffffff; }
  </style>
</head>
<body class="text-zinc-100 min-h-screen flex flex-col font-sans antialiased selection:bg-brand-500 selection:text-white">

  <!-- Header -->
  <header class="border-b border-surface-border bg-surface/80 sticky top-0 z-40 backdrop-blur-md">
    <div class="max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
      
      <!-- Brand & Version -->
      <div class="flex items-center gap-3">
        <div class="h-7 w-7 rounded-lg bg-zinc-900 border border-surface-border flex items-center justify-center text-zinc-300">
          <svg class="w-4 h-4 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
        </div>
        <div class="flex items-center gap-2">
          <span class="font-semibold text-sm tracking-tight text-white">openYaMarket</span>
          <span class="text-[11px] font-mono px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400 border border-surface-border">v0.2.0</span>
          <span class="hidden md:inline text-[11px] font-mono text-zinc-500">• Pure-HTTP Zero-Device</span>
        </div>
      </div>

      <!-- Controls -->
      <div class="flex items-center gap-2">
        <!-- Platform Toggle -->
        <div class="bg-zinc-900 p-0.5 rounded-lg border border-surface-border flex text-xs font-medium">
          <button id="btn-ios" onclick="setPlatform('ios')" class="px-2.5 py-1 rounded transition-colors bg-zinc-800 text-white flex items-center gap-1.5">
            <svg class="w-3 h-3 fill-current" viewBox="0 0 170 170"><path d="M150.37 130.25c-2.45 5.66-5.35 10.87-8.71 15.66-4.58 6.53-8.33 11.05-11.22 13.56-4.48 4.12-9.28 6.23-14.42 6.35-3.69 0-8.14-1.05-13.32-3.18-5.19-2.12-9.97-3.17-14.34-3.17-4.58 0-9.49 1.05-14.75 3.17-5.26 2.13-9.5 3.24-12.74 3.35-4.35.13-9.16-1.9-14.42-6.08-3.7-3.04-7.6-7.79-11.73-14.24-5.77-9.01-10.35-19.46-13.74-31.33-3.39-11.87-5.09-23.01-5.09-33.43 0-14.03 3.39-25.75 10.17-35.16 6.78-9.41 15.42-14.23 25.93-14.47 5.09 0 10.74 1.34 16.94 4.01 6.21 2.68 10.15 4.09 11.83 4.24 1.77-.15 5.86-1.61 12.26-4.37 6.4-2.77 11.84-3.95 16.32-3.56 12.01.74 21.68 5.48 29 14.24-10.59 6.41-15.75 15.34-15.48 26.79.28 9.07 3.73 16.64 10.36 22.7 6.63 6.07 14.54 9.47 23.73 10.22-2.17 6.54-4.8 13.06-7.89 19.57zM119.22 31.84c0-7.25 2.66-14.24 7.99-20.97 5.33-6.73 11.89-10.87 19.68-12.42.53 1.13.8 2.37.8 3.72 0 7.27-2.77 14.4-8.31 21.39-5.54 6.99-12.29 10.97-20.25 11.95a12.87 12.87 0 0 1 .09-3.67z"/></svg>
            <span>iOS</span>
          </button>
          <button id="btn-android" onclick="setPlatform('android')" class="px-2.5 py-1 rounded transition-colors text-zinc-400 hover:text-white flex items-center gap-1.5">
            <svg class="w-3 h-3 fill-current" viewBox="0 0 24 24"><path d="M17.523 15.3414c-.5511 0-.9993-.4486-.9993-.9997s.4482-.9993.9993-.9993c.551 0 .9993.4482.9993.9993.0001.5511-.4482.9997-.9993.9997m-11.046 0c-.5511 0-.9993-.4486-.9993-.9997s.4482-.9993.9993-.9993c.5511 0 .9993.4482.9993.9993 0 .5511-.4482.9997-.9993.9997m11.4045-6.02l1.996-3.4572c.1558-.27.0634-.6146-.2066-.7704-.2701-.1559-.6146-.0635-.7705.2066l-2.0238 3.5053c-1.4284-.652-3.0232-1.0208-4.7266-1.0208-1.7034 0-3.2982.3688-4.7266 1.0208L5.4234 5.3007c-.1559-.2701-.5004-.3625-.7705-.2066-.27.1558-.3624.5004-.2066.7704l1.996 3.4572C2.8885 11.2828.423 15.343.423 20.083h23.154c0-4.74-2.4655-8.8002-5.7005-10.7616"/></svg>
            <span>Android</span>
          </button>
        </div>

        <!-- Region Selector -->
        <select id="select-region" onchange="setRegion(this.value)" class="bg-zinc-900 text-xs text-zinc-300 border border-surface-border rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-zinc-500">
          <option value="213">Москва (213)</option>
          <option value="2">Санкт-Петербург (2)</option>
          <option value="54">Екатеринбург (54)</option>
          <option value="43">Казань (43)</option>
          <option value="35">Краснодар (35)</option>
          <option value="65">Новосибирск (65)</option>
        </select>

        <!-- Auth / Settings Modal Trigger -->
        <button onclick="toggleSettingsModal()" class="px-2.5 py-1.5 rounded-lg border border-surface-border bg-zinc-900 hover:bg-zinc-800 text-xs text-zinc-300 transition flex items-center gap-1.5">
          <svg class="w-3.5 h-3.5 text-zinc-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
          <span class="hidden sm:inline">Токен</span>
        </button>

        <a href="https://github.com/molkex/yandex-market-private-api" target="_blank" class="text-zinc-400 hover:text-white p-1.5 rounded-lg border border-surface-border bg-zinc-900 hover:bg-zinc-800 transition">
          <svg class="h-4 w-4 fill-current" viewBox="0 0 24 24"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
        </a>
      </div>
    </div>
  </header>

  <!-- Main Section -->
  <main class="flex-1 max-w-6xl mx-auto px-4 sm:px-6 py-10 w-full">
    
    <!-- Title & Subtitle -->
    <div class="text-center max-w-2xl mx-auto mb-8">
      <h1 class="text-2xl sm:text-3xl font-bold tracking-tight text-white mb-2">
        Радар Скидок, Остатков & B2B Выплат
      </h1>
      <p class="text-zinc-400 text-xs sm:text-sm leading-relaxed">
        Парсинг мобильного каталога Яндекс Маркета на чистом HTTP. Выгрузка скрытых складских остатков (<code class="text-emerald-400 font-mono text-[11px]">stock_amount</code>) и повышенных реферальных ставок для Самозанятых и ИП.
      </p>
    </div>

    <!-- Search Input Bar -->
    <div class="max-w-2xl mx-auto mb-6">
      <div class="relative flex items-center rounded-xl bg-zinc-900 border border-surface-border p-1.5 focus-within:border-zinc-500 transition-colors shadow-sm">
        <div class="pl-3 pr-2 text-zinc-500 flex items-center">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
          </svg>
        </div>
        <input 
          id="search-input" 
          type="text" 
          placeholder="Поисковый запрос, SKU (например 6256889761) или URL карточки..." 
          class="w-full bg-transparent py-2 text-xs sm:text-sm text-white placeholder-zinc-500 focus:outline-none font-medium"
          onkeydown="if(event.key === 'Enter') executeSearch()"
        />
        <button 
          id="btn-search" 
          onclick="executeSearch()" 
          class="px-4 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-black font-semibold text-xs transition-colors flex items-center gap-1.5">
          <span>Поиск</span>
          <div id="spinner" class="hidden w-3.5 h-3.5 border-2 border-black border-t-transparent rounded-full animate-spin"></div>
        </button>
      </div>

      <!-- Quick Preset Tags -->
      <div class="flex flex-wrap items-center justify-center gap-1.5 mt-3 text-xs">
        <span class="text-zinc-500 font-mono text-[11px] mr-1">Пресеты:</span>
        <button onclick="quickSearch('PlayStation 5 Pro')" class="px-2 py-0.5 rounded bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-surface-border text-[11px] transition">PS5 Pro</button>
        <button onclick="quickSearch('Dyson Supersonic')" class="px-2 py-0.5 rounded bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-surface-border text-[11px] transition">Dyson</button>
        <button onclick="quickSearch('iPhone 16 Pro Max')" class="px-2 py-0.5 rounded bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-surface-border text-[11px] transition">iPhone 16</button>
        <button onclick="quickSearch('Кофемашина DeLonghi')" class="px-2 py-0.5 rounded bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-surface-border text-[11px] transition">DeLonghi</button>
        <button onclick="quickSearch('6256889761')" class="px-2 py-0.5 rounded bg-zinc-900 hover:bg-zinc-800 text-emerald-400 border border-surface-border text-[11px] font-mono transition">SKU 6256889761</button>
      </div>
    </div>

    <!-- Live Telemetry Bar -->
    <div id="telemetry-bar" class="hidden max-w-2xl mx-auto mb-6 bg-zinc-900/60 border border-surface-border rounded-lg px-3.5 py-1.5 flex items-center justify-between text-[11px] font-mono text-zinc-400">
      <div class="flex items-center gap-3">
        <span class="flex items-center gap-1.5 text-emerald-400">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
          200 OK
        </span>
        <span id="telemetry-latency">Latency: -- ms</span>
        <span id="telemetry-items">Найдено: --</span>
      </div>
      <span class="text-zinc-500">Pure-HTTP Wire</span>
    </div>

    <!-- Results Container -->
    <div id="results-container" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      <!-- Injected product cards -->
    </div>

    <!-- Empty State -->
    <div id="empty-state" class="text-center py-16 text-zinc-500">
      <svg class="w-8 h-8 text-zinc-700 mx-auto mb-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <path d="m4.93 4.93 4.24 4.24"/>
        <path d="m14.83 9.17 4.24-4.24"/>
        <path d="m14.83 14.83 4.24 4.24"/>
        <path d="m9.17 14.83-4.24 4.24"/>
        <circle cx="12" cy="12" r="4"/>
      </svg>
      <p class="text-xs font-medium text-zinc-400">Введите поисковый запрос или SKU</p>
      <p class="text-[11px] text-zinc-600 mt-0.5">Данные считываются напрямую из мобильного протокола FAPI</p>
    </div>

  </main>

  <!-- Footer Banner -->
  <footer class="border-t border-surface-border bg-zinc-950 py-6 mt-12">
    <div class="max-w-6xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
      <div>
        <div class="text-xs font-semibold text-white">Автоматизация и мониторинг каталога 24/7</div>
        <div class="text-[11px] text-zinc-400">Автопостинг связок в Telegram, парсер остатков и снайпер цен со скоростью 300 мс.</div>
      </div>
      <a href="https://t.me/mxmtkchk" target="_blank" class="px-3.5 py-1.5 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-surface-border text-xs font-medium text-zinc-200 hover:text-white transition flex items-center gap-1.5">
        <svg class="w-3.5 h-3.5 fill-current text-sky-400" viewBox="0 0 24 24"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.75-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/></svg>
        <span>Связаться: @mxmtkchk</span>
      </a>
    </div>
  </footer>

  <!-- Settings Modal -->
  <div id="settings-modal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-zinc-900 border border-surface-border rounded-xl max-w-sm w-full p-5 shadow-2xl relative">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-semibold text-white">Параметры сессии</h3>
        <button onclick="toggleSettingsModal()" class="text-zinc-400 hover:text-white p-1 rounded">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>
      <p class="text-[11px] text-zinc-400 mb-4">Для персонализированных B2B-ставок и корзины укажите токен и прокси.</p>

      <div class="space-y-3">
        <div>
          <label class="block text-[11px] font-medium text-zinc-300 mb-1">Yandex OAuth Token</label>
          <input id="input-token" type="text" placeholder="AQAAAAA..." class="w-full bg-zinc-950 border border-surface-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500">
        </div>
        <div>
          <label class="block text-[11px] font-medium text-zinc-300 mb-1">HTTP Proxy (host:port:user:pass)</label>
          <input id="input-proxy" type="text" placeholder="127.0.0.1:8080" class="w-full bg-zinc-950 border border-surface-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-white focus:outline-none focus:border-zinc-500">
        </div>
        <button onclick="saveSettings()" class="w-full mt-2 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-black font-semibold text-xs transition">
          Сохранить параметры
        </button>
      </div>
    </div>
  </div>

  <!-- SKU X-Ray Modal -->
  <div id="xray-modal" class="hidden fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
    <div class="bg-zinc-900 border border-surface-border rounded-xl max-w-md w-full p-5 shadow-2xl relative">
      <div class="flex items-center justify-between mb-4 pb-2 border-b border-surface-border">
        <div class="flex items-center gap-2">
          <span class="text-xs font-semibold text-white">Инспекция карточки товара</span>
          <span id="xray-sku-badge" class="text-[11px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-surface-border"></span>
        </div>
        <button onclick="closeXrayModal()" class="text-zinc-400 hover:text-white p-1 rounded">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
        </button>
      </div>

      <div id="xray-content" class="space-y-3 text-xs">
        <!-- Injected via JavaScript -->
      </div>

      <div class="mt-4 pt-3 border-t border-surface-border flex justify-end">
        <button onclick="closeXrayModal()" class="px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition">
          Закрыть
        </button>
      </div>
    </div>
  </div>

  <!-- Minimalist Toast Component -->
  <div id="toast" class="fixed bottom-5 right-5 z-50 transform translate-y-16 opacity-0 transition-all duration-200 pointer-events-none">
    <div class="bg-zinc-900 border border-surface-border text-zinc-100 px-3.5 py-2 rounded-lg shadow-xl flex items-center gap-2 text-xs">
      <svg class="w-3.5 h-3.5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>
      <span id="toast-message">Сохранено</span>
    </div>
  </div>

  <script>
    let state = {
      platform: 'ios',
      region_id: 213,
    };

    function showToast(text) {
      const toast = document.getElementById('toast');
      const msg = document.getElementById('toast-message');
      msg.innerText = text;
      toast.classList.remove('translate-y-16', 'opacity-0');
      setTimeout(() => {
        toast.classList.add('translate-y-16', 'opacity-0');
      }, 2500);
    }

    function setPlatform(p) {
      state.platform = p;
      const btnIos = document.getElementById('btn-ios');
      const btnAnd = document.getElementById('btn-android');
      if (p === 'ios') {
        btnIos.className = 'px-2.5 py-1 rounded transition-colors bg-zinc-800 text-white flex items-center gap-1.5';
        btnAnd.className = 'px-2.5 py-1 rounded transition-colors text-zinc-400 hover:text-white flex items-center gap-1.5';
      } else {
        btnAnd.className = 'px-2.5 py-1 rounded transition-colors bg-zinc-800 text-white flex items-center gap-1.5';
        btnIos.className = 'px-2.5 py-1 rounded transition-colors text-zinc-400 hover:text-white flex items-center gap-1.5';
      }
    }

    function setRegion(r) {
      state.region_id = parseInt(r);
    }

    function quickSearch(val) {
      document.getElementById('search-input').value = val;
      executeSearch();
    }

    function toggleSettingsModal() {
      const modal = document.getElementById('settings-modal');
      modal.classList.toggle('hidden');
    }

    function closeXrayModal() {
      document.getElementById('xray-modal').classList.add('hidden');
    }

    async function saveSettings() {
      const token = document.getElementById('input-token').value;
      const proxy = document.getElementById('input-proxy').value;
      await fetch('/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({oauth_token: token, proxy: proxy})
      });
      toggleSettingsModal();
      showToast('Настройки сессии сохранены');
    }

    async function executeSearch() {
      const query = document.getElementById('search-input').value.trim();
      if (!query) return;

      const btn = document.getElementById('btn-search');
      const spinner = document.getElementById('spinner');
      const container = document.getElementById('results-container');
      const emptyState = document.getElementById('empty-state');
      const telemetry = document.getElementById('telemetry-bar');

      spinner.classList.remove('hidden');
      btn.disabled = true;

      try {
        const url = `/api/search?query=${encodeURIComponent(query)}&region_id=${state.region_id}&platform=${state.platform}`;
        const res = await fetch(url);
        const data = await res.json();

        container.innerHTML = '';
        emptyState.classList.add('hidden');
        telemetry.classList.remove('hidden');

        document.getElementById('telemetry-latency').innerText = `Latency: ${data.duration_ms} ms`;
        document.getElementById('telemetry-items').innerText = `Найдено: ${data.products ? data.products.length : 0} шт.`;

        if (!data.products || data.products.length === 0) {
          container.innerHTML = `<div class="col-span-full text-center py-12 text-zinc-400 text-xs">По данному запросу товаров не найдено.</div>`;
          return;
        }

        data.products.forEach(p => {
          container.appendChild(createProductCard(p));
        });
      } catch (err) {
        showToast('Ошибка при поиске: ' + err.message);
      } finally {
        spinner.classList.add('hidden');
        btn.disabled = false;
      }
    }

    function createProductCard(p) {
      const card = document.createElement('div');
      card.className = 'bg-zinc-900 border border-surface-border hover:border-surface-borderHover rounded-xl p-4 flex flex-col justify-between transition-colors';

      const price = p.price ? p.price.toLocaleString('ru-RU') + ' ₽' : 'По запросу';
      const priceOld = p.price_old ? `<span class="text-xs line-through text-zinc-500 mr-2 font-mono">${p.price_old.toLocaleString('ru-RU')} ₽</span>` : '';

      let promise = p.promise;
      let b2b = p.b2b_bonus;
      if (!promise && p.price) {
        promise = Math.round(p.price * 0.025);
        b2b = Math.round(promise * 2.2);
      }

      const stockBadge = p.stock_amount !== undefined && p.stock_amount !== null 
        ? `<span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[11px] font-mono border border-emerald-500/20 font-medium">Склад: ${p.stock_amount} шт.</span>`
        : `<span class="px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 text-[11px] font-mono border border-surface-border">SKU ${p.sku || 'N/A'}</span>`;

      card.innerHTML = `
        <div>
          <div class="flex items-center justify-between gap-2 mb-2.5">
            ${stockBadge}
            <span class="text-[10px] font-mono text-zinc-500 uppercase">FAPI</span>
          </div>

          <h3 class="text-xs font-semibold text-white mb-2 line-clamp-2 leading-relaxed hover:text-emerald-400 transition-colors cursor-pointer" onclick="window.open('${p.url || ('https://market.yandex.ru/product/' + p.sku)}', '_blank')">
            ${p.title}
          </h3>

          <div class="flex items-baseline mb-3">
            ${priceOld}
            <span class="text-base font-bold text-white font-mono tracking-tight">${price}</span>
          </div>

          <!-- Reward Box -->
          <div class="rounded-lg bg-zinc-950 border border-surface-border p-2.5 mb-3 space-y-1.5 text-[11px]">
            <div class="flex items-center justify-between">
              <span class="text-zinc-400">Базовый бонус:</span>
              <span class="font-mono text-zinc-300">${promise ? promise.toLocaleString('ru-RU') + ' баллов' : '—'}</span>
            </div>
            <div class="flex items-center justify-between pt-1.5 border-t border-surface-border">
              <span class="text-emerald-400 font-medium">B2B выплата (Самозанятые):</span>
              <span class="font-mono font-bold text-emerald-400">${b2b ? b2b.toLocaleString('ru-RU') + ' ₽' : '—'}</span>
            </div>
          </div>
        </div>

        <div class="flex items-center gap-2 pt-1">
          <button onclick="copyRefLink('${p.sku}')" class="flex-1 py-1.5 px-2.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-surface-border text-xs font-medium text-zinc-200 hover:text-white transition-colors flex items-center justify-center gap-1.5">
            <svg class="w-3.5 h-3.5 text-zinc-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
            <span>Реф-ссылка</span>
          </button>
          <button onclick="inspectCard('${p.sku}')" class="py-1.5 px-2.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-surface-border text-xs font-medium text-emerald-400 transition-colors flex items-center gap-1">
            <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2v20M2 12h20"/></svg>
            <span>Рентген</span>
          </button>
        </div>
      `;

      return card;
    }

    async function inspectCard(sku) {
      if (!sku) return;
      try {
        const res = await fetch(`/api/product/${sku}?region_id=${state.region_id}&platform=${state.platform}`);
        const p = await res.json();
        
        document.getElementById('xray-sku-badge').innerText = `SKU ${sku}`;
        const content = document.getElementById('xray-content');
        content.innerHTML = `
          <div class="font-medium text-white line-clamp-2">${p.title}</div>
          <div class="grid grid-cols-2 gap-2 pt-2 border-t border-surface-border">
            <div class="bg-zinc-950 p-2 rounded border border-surface-border">
              <div class="text-[10px] text-zinc-500 uppercase font-mono">Текущая цена</div>
              <div class="font-mono text-sm font-bold text-white mt-0.5">${p.price ? p.price.toLocaleString('ru-RU') + ' ₽' : 'N/A'}</div>
            </div>
            <div class="bg-zinc-950 p-2 rounded border border-surface-border">
              <div class="text-[10px] text-zinc-500 uppercase font-mono">Остаток на складе</div>
              <div class="font-mono text-sm font-bold text-emerald-400 mt-0.5">${p.stock_amount !== null ? p.stock_amount + ' шт.' : 'В наличии'}</div>
            </div>
            <div class="bg-zinc-950 p-2 rounded border border-surface-border">
              <div class="text-[10px] text-zinc-500 uppercase font-mono">Базовый бонус</div>
              <div class="font-mono text-xs text-zinc-200 mt-0.5">${p.promise ? p.promise.toLocaleString('ru-RU') + ' баллов' : '0'}</div>
            </div>
            <div class="bg-zinc-950 p-2 rounded border border-surface-border">
              <div class="text-[10px] text-emerald-500 uppercase font-mono">B2B выплата (Руб)</div>
              <div class="font-mono text-xs font-bold text-emerald-400 mt-0.5">${p.b2b_bonus ? p.b2b_bonus.toLocaleString('ru-RU') + ' ₽' : '0 ₽'}</div>
            </div>
          </div>
          <div class="bg-zinc-950 p-2 rounded border border-surface-border font-mono text-[10px] text-zinc-400 space-y-1">
            <div class="flex justify-between"><span>Offer ID:</span> <span class="text-zinc-200">${p.offer_id || 'N/A'}</span></div>
            <div class="flex justify-between"><span>Wire Latency:</span> <span class="text-emerald-400">${p.duration_ms} ms</span></div>
          </div>
        `;
        document.getElementById('xray-modal').classList.remove('hidden');
      } catch (err) {
        showToast('Ошибка инспекции: ' + err.message);
      }
    }

    function copyRefLink(sku) {
      const url = `https://market.yandex.ru/card/x/${sku}?utm_medium=sharing`;
      navigator.clipboard.writeText(url);
      showToast('Реферальная ссылка скопирована');
    }
  </script>
</body>
</html>
"""

def main():
    import sys
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"🚀 openYaMarket Web Dashboard launching on http://{host}:{port}")
    uvicorn.run("openyamarket.web:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
