"""Extract structured data from Yandex Market SDUI (DivKit) responses.

The SDUI screens render product/price data via DivKit templates, but the raw
values are present as literals + in the baobab analytics blocks. These helpers
pull clean fields out without a full DivKit engine.
"""
from __future__ import annotations

import json
import re
from typing import Any

_PRICE_RE = re.compile(r'(\d{2,7})\.000000')


def _dumps(resp: Any) -> str:
    return resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)


def product_info(resp: Any) -> dict:
    """From a product screen response, extract:
    {name, sku_id, product_id, nid, hid, price_current, price_old, url}."""
    s = _dumps(resp)

    def first(pat):
        m = re.search(pat, s)
        return m.group(1) if m else None

    product_id = first(r'"productId":\s*"?(\d+)"?')
    sku_id = first(r'"sku_id":"(\d+)"') or first(r'"skuId":\s*"?(\d+)"?')
    nid = first(r'"nid":\s*"?(\d+)"?')
    hid = first(r'"hid":\s*"?(\d+)"?')

    # name: longest realistic product title mentioning the model line
    names = re.findall(r'"((?:Смартфон )?Apple[^"]{5,80}|Смартфон Apple[^"]{5,80})"', s)
    name = max(names, key=len) if names else None

    # prices in the price-offer section: current (min shown) & old (crossed-out max)
    prices = sorted({int(x) for x in _PRICE_RE.findall(s) if 100 < int(x) < 10_000_000})
    # heuristic: within the ProductCardPriceOfferSection only
    i = s.find("PriceOffer")
    if i >= 0:
        seg = s[i:i + 4000]
        seg_prices = sorted({int(x) for x in _PRICE_RE.findall(seg) if 100 < int(x) < 10_000_000})
        if seg_prices:
            prices = seg_prices
    price_current = prices[0] if prices else None
    price_old = prices[-1] if len(prices) > 1 else None

    url = f"https://market.yandex.ru/product/{product_id}" if product_id else None
    return {
        "name": name, "sku_id": sku_id, "product_id": product_id,
        "nid": nid, "hid": hid,
        "price_current": price_current, "price_old": price_old, "url": url,
    }


def search_skus(resp: Any) -> list[str]:
    """SKU ids present in a search-result response."""
    s = _dumps(resp)
    skus = set(re.findall(r'skuId["\\:= ]{1,5}(\d{6,})', s))
    skus |= set(re.findall(r'sku_id["\\:= ]{1,5}(\d{6,})', s))
    skus |= set(re.findall(r'item_id["\\:= ]{1,5}(\d{6,})', s))
    return sorted(skus)


def cart_total(resp: Any) -> dict:
    """Extract cart totals from a cart screen response.
    Looks for the cartState model's structured price fields."""
    s = _dumps(resp)
    out = {}
    for key, pats in {
        "items_total": [r'"totalItemsPrice"[^0-9]{0,20}(\d{3,7})',
                        r'"itemsTotal"[^0-9]{0,20}(\d{3,7})'],
        "buyer_total": [r'"buyerTotalPrice"[^0-9]{0,20}(\d{3,7})',
                        r'"totalBuyerPrice"[^0-9]{0,20}(\d{3,7})',
                        r'"totalPrice"[^0-9]{0,20}(\d{3,7})'],
        "weight_total": [r'"totalWeight"[^0-9]{0,20}(\d{3,7})'],
    }.items():
        for p in pats:
            m = re.search(p, s)
            if m:
                out[key] = int(m.group(1))
                break
    return out


def next_page_token(resp: Any) -> str | None:
    """Extract the search-result nextPageToken (pass to search(page_token=...))."""
    s = _dumps(resp)
    m = re.search(r'"nextPageToken":\s*("(?:[^"\\]|\\.)*")', s)
    if not m:
        return None
    return json.loads(m.group(1))


def search_results(resp: Any) -> list[dict]:
    """Parse the search result grid (only the results, not recommendations):
    list of {sku, title, price} in display order, straight from the response.

    The first result page packs *all* products into a single DivKit content
    element (one blob per section, not one card per product), so iterating cards
    yields only 1 of N. Instead we segment the chosen section's blob by product
    title — the layout is a clean repeat of `title → price → skuId` per product —
    and pair each title with the nearest following price and sku."""
    secs = resp.get("ui", {}).get("sections", []) if isinstance(resp, dict) else []
    grid, best = None, 0
    for sec in secs:
        c = sec.get("content")
        if isinstance(c, list):
            n = len(set(re.findall(r"osku(\d{6,})", json.dumps(c, ensure_ascii=False))))
            if n > best:
                best, grid = n, c
    if not grid:
        return []
    s = json.dumps(grid, ensure_ascii=False)
    # ordered product titles (skip DivKit template/state labels)
    titles = [m for m in re.finditer(r'"title":\s*"([^"]{6,90})"', s)
              if not any(x in m.group(1) for x in ("Config", "Snippet", "State"))]
    out, seen = [], set()
    for i, m in enumerate(titles):
        start = m.end()
        end = titles[i + 1].start() if i + 1 < len(titles) else len(s)
        win = s[start:end]
        pm = re.search(r'"price":\s*\{"value":\s*(\d+)', win)
        km = re.search(r'"skuId":\s*"?(\d{6,})', win) or re.search(r"osku(\d{6,})", win)
        sku = km.group(1) if km else None
        if sku in seen:                       # trailing carousel repeats the grid
            continue
        if sku:
            seen.add(sku)
        out.append({
            "sku": sku,
            "title": m.group(1),
            "price": int(pm.group(1)) if pm else None,
        })
    return out


def available_filters(resp: Any) -> list[dict]:
    """List filters offered for a search: [{id, name, type}]. Use the id in
    search_filtered's checkedFilters (glprice for price; enum id + value id else)."""
    s = _dumps(resp)
    out, seen = [], set()
    for m in re.finditer(
        r'"id":\s*"([a-z0-9_]{3,})"[^{}]{0,150}?"name":\s*"([^"]{2,30})"'
        r'[^{}]{0,150}?"type":\s*"(ENUM|BOOLEAN|RANGE|NUMERIC|COLOR)"', s):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"id": m.group(1), "name": m.group(2), "type": m.group(3)})
    return out
