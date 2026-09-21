"""Pure-HTTP Yandex Market FAPI client — no third-party dependencies.

Endpoint + headers reverse-engineered from ru.beru.android 2026.32.3.
FAPI is a resolver API: POST /api/v1/?name=<resolver> with a JSON
`{"params": [ {...} ]}` body. Read resolvers work without authentication;
`Authorization: OAuth <token>` unlocks account/write resolvers.
"""
from __future__ import annotations

import base64
import gzip
import json
import urllib.parse
from http.client import HTTPSConnection
from typing import Any

from .device import (APP_BUILD_NUMBER, APP_BUILD_NUMBER_IOS, APP_FLAVOR, APP_ID,
                     APP_ID_IOS, APP_VERSION, APP_VERSION_IOS, STORE_TRACK,
                     STORE_TRACK_IOS, Device)

BASE_HOST = "ipa.market.yandex.ru"          # FAPI resolvers
MAPI_HOST = "mapi.vs.market.yandex.net"     # SDUI "screen" API (search, product, cart…)
API_PATH = "/api/v1/"
DEFAULT_REGION = 213  # Moscow

try:
    import brotli as _brotli
except ImportError:  # pragma: no cover
    try:
        import brotlicffi as _brotli
    except ImportError:
        _brotli = None

try:
    from curl_cffi import requests as _curl  # browser-TLS transport (impersonate)
except ImportError:  # pragma: no cover
    _curl = None


class FapiError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class MarketClient:
    def __init__(self, device: Device | None = None, region_id: int = DEFAULT_REGION,
                 oauth_token: str | None = None, rearr_factors: str = "",
                 proxy: str | None = None, cookie: str | None = None,
                 timeout: int = 30, impersonate: str | None = None):
        self.device = device or Device.random()
        self.region_id = region_id
        self.oauth_token = oauth_token
        self.rearr_factors = rearr_factors
        self.cookie = cookie
        self.timeout = timeout
        # browser-TLS fingerprint via curl_cffi (e.g. "chrome"). Yandex anti-bot
        # blocks Python's stdlib TLS (JA3) on some IPs (datacenter especially);
        # a browser fingerprint passes even direct from a datacenter host. When
        # None the client uses the stdlib http.client transport (no dependency).
        self.impersonate = impersonate
        self._proxy = proxy
        # proxy: "host:port" or "host:port:user:pass"
        self.proxy_host = self.proxy_port = self.proxy_auth = None
        if proxy:
            parts = proxy.split(":")
            self.proxy_host, self.proxy_port = parts[0], int(parts[1])
            if len(parts) >= 4:
                tok = base64.b64encode(f"{parts[2]}:{parts[3]}".encode()).decode()
                self.proxy_auth = f"Basic {tok}"

    @classmethod
    def ios(cls, **kwargs) -> "IOSClient":
        """Dedicated constructor for a Fully headless iOS client."""
        return IOSClient(**kwargs)

    @classmethod
    def android(cls, **kwargs) -> "AndroidClient":
        """Dedicated constructor for a Fully headless Android client."""
        return AndroidClient(**kwargs)

    def _connect(self) -> HTTPSConnection:
        if self.proxy_host:
            conn = HTTPSConnection(self.proxy_host, self.proxy_port, timeout=self.timeout)
            hdrs = {"Proxy-Authorization": self.proxy_auth} if self.proxy_auth else {}
            conn.set_tunnel(BASE_HOST, 443, headers=hdrs)
            return conn
        return HTTPSConnection(BASE_HOST, timeout=self.timeout)

    # ---- headers ----
    def _headers(self) -> dict[str, str]:
        d = self.device
        ios = d.platform == "ios"
        h = {
            "content-type": "application/json",
            "api-platform": "IOS" if ios else "ANDROID",
            "user-agent": d.user_agent(),
            "x-app-version": APP_VERSION_IOS if ios else APP_VERSION,
            "x-app-id": APP_ID_IOS if ios else APP_ID,
            "x-app-flavor": APP_FLAVOR,
            "x-app-build-number": APP_BUILD_NUMBER_IOS if ios else APP_BUILD_NUMBER,
            "x-store-track": STORE_TRACK_IOS if ios else STORE_TRACK,
            "x-market-rearrfactors": self.rearr_factors,
            "uuid": d.uuid,
            "x-device-info": d.x_device_info(),
            "x-ya-gaid": d.gaid,
            "x-appmetrica-deviceid": d.appmetrica_device_id,
            "x-region-id": str(self.region_id),
            "accept-encoding": "gzip",
        }
        if self.oauth_token:
            # Market FAPI uses X-User-Authorization
            h["x-user-authorization"] = f"OAuth {self.oauth_token}"
            if ios:
                h["authorization"] = f"OAuth {self.oauth_token}"
        if self.cookie:
            h["cookie"] = self.cookie
        return h

    # ---- core call ----
    def resolve(self, name: str, params: dict | None = None,
                dictionary: bool = True, extra_query: dict | None = None) -> Any:
        """Call one FAPI resolver, return its parsed JSON result."""
        query = {"name": name}
        if dictionary:
            query["dictionary"] = "true"
        if self.rearr_factors:
            query["rearr-factors"] = self.rearr_factors
        if extra_query:
            query.update(extra_query)
        path = API_PATH + "?" + urllib.parse.urlencode(query)
        body = json.dumps({"params": [params or {}]}, ensure_ascii=False).encode()

        conn = self._connect()
        try:
            conn.request("POST", path, body=body, headers=self._headers())
            resp = conn.getresponse()
            raw = resp.read()
            if resp.getheader("content-encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8", "replace")
            if resp.status != 200:
                raise FapiError(resp.status, text)
            return json.loads(text)
        finally:
            conn.close()

    # ---- convenience wrappers (resolver names verified empirically) ----
    def get_toggles(self) -> Any:
        return self.resolve("getToggles", {})

    def resolve_region(self, region_id: int) -> Any:
        return self.resolve("resolveRegionById", {"regionId": region_id})

    # ---- SDUI "screen" API (mapi.vs) — needs oauth_token ----
    def screen(self, name: str, query: dict | None = None,
               body: Any = None, method: str = "POST") -> Any:
        """Fetch an SDUI screen from mapi.vs. Screens: product, search-result,
        main, cart, catalog, category, my-orders, profile, favourites, …
        Returns parsed JSON (DivKit UI + collections). Requires oauth_token."""
        path = "/api/screen/" + name
        if query:
            path += "?" + urllib.parse.urlencode(query)
        payload = None
        if body is not None:
            payload = body if isinstance(body, (bytes, str)) else json.dumps(body)

        if self.impersonate:
            return self._screen_curl(path, payload, method)

        conn = self._connect_host(MAPI_HOST)
        try:
            conn.request(method, path, body=payload, headers=self._headers())
            resp = conn.getresponse()
            raw = resp.read()
            enc = resp.getheader("content-encoding", "").lower()
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc == "br" and _brotli is not None:
                raw = _brotli.decompress(raw)
            text = raw.decode("utf-8", "replace")
            if resp.status != 200:
                raise FapiError(resp.status, text)
            broken = resp.getheader("X-Screen-Is-Broken") == "true"
            data = json.loads(text)
            if isinstance(data, dict):
                data["_broken"] = broken
            return data
        finally:
            conn.close()

    def _screen_curl(self, path: str, payload, method: str) -> Any:
        """SDUI screen fetch over a browser-TLS fingerprint (curl_cffi)."""
        if _curl is None:
            raise RuntimeError("impersonate set but curl_cffi not installed "
                               "(pip install curl_cffi)")
        url = f"https://{MAPI_HOST}{path}"
        proxies = None
        if self._proxy:
            parts = self._proxy.split(":")
            if len(parts) >= 4:
                pu = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
            else:
                pu = f"http://{parts[0]}:{parts[1]}"
            proxies = {"http": pu, "https": pu}
        r = _curl.request(method, url, data=payload, headers=self._headers(),
                          impersonate=self.impersonate, timeout=self.timeout,
                          proxies=proxies)
        text = r.text
        if r.status_code != 200:
            raise FapiError(r.status_code, text)
        data = json.loads(text)
        if isinstance(data, dict):
            data["_broken"] = r.headers.get("X-Screen-Is-Broken") == "true"
        return data

    def _connect_host(self, host: str) -> HTTPSConnection:
        if self.proxy_host:
            conn = HTTPSConnection(self.proxy_host, self.proxy_port, timeout=self.timeout)
            hdrs = {"Proxy-Authorization": self.proxy_auth} if self.proxy_auth else {}
            conn.set_tunnel(host, 443, headers=hdrs)
            return conn
        return HTTPSConnection(host, timeout=self.timeout)

    def product(self, sku_id: int | str) -> Any:
        return self.screen("product", query={"skuId": sku_id, "oskuId": sku_id})

    # ---- write actions (SDUI RemoteAction mechanism) ----
    @staticmethod
    def _find_remote_action(obj: Any, path_contains: str):
        """Walk an SDUI response for a RemoteAction whose query.path matches.
        Screens embed ready-to-send write actions (add to cart, favourite, …)."""
        if isinstance(obj, dict):
            if obj.get("type") == "RemoteAction" and \
                    path_contains in str(obj.get("query", {}).get("path", "")):
                return obj["query"]
            for v in obj.values():
                r = MarketClient._find_remote_action(v, path_contains)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = MarketClient._find_remote_action(v, path_contains)
                if r:
                    return r
        return None

    def run_action(self, query: dict) -> Any:
        """Execute a RemoteAction query {path, params, body} from a screen."""
        path = "/" + query["path"].lstrip("/")
        params = {k: (v[0] if isinstance(v, list) else v)
                  for k, v in (query.get("params") or {}).items()}
        if params:
            path += "?" + urllib.parse.urlencode(params)
        body = {"request": query["body"]} if query.get("body") is not None else None
        conn = self._connect_host(MAPI_HOST)
        try:
            conn.request("POST", path,
                         body=json.dumps(body) if body is not None else None,
                         headers=self._headers())
            resp = conn.getresponse()
            raw = resp.read()
            enc = resp.getheader("content-encoding", "").lower()
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc == "br" and _brotli is not None:
                raw = _brotli.decompress(raw)
            text = raw.decode("utf-8", "replace")
            if resp.status != 200:
                raise FapiError(resp.status, text)
            return json.loads(text)
        finally:
            conn.close()

    def add_to_cart(self, sku_id: int | str) -> Any:
        """Add a product's buybox offer to the cart (write). Requires oauth_token."""
        prod = self.product(sku_id)
        q = self._find_remote_action(prod, "addItemsToCart")
        if not q:
            raise FapiError(0, "no addItemsToCart action on product screen")
        return self.run_action(q)

    @staticmethod
    def price_filter(min_price: int | None = None, max_price: int | None = None) -> dict:
        """Build a glprice checkedFilter (value = 'min~max')."""
        return {"glprice": {"isGuruLight": False,
                            "value": f"{min_price or ''}~{max_price or ''}", "id": "glprice"}}

    def search_filtered(self, text: str, checked_filters: dict,
                        sort: str | None = None) -> Any:
        """Server-side filtered search (real Market filtering). `checked_filters` is a
        {filterId: {value, id, isGuruLight}} map — use price_filter() for price, or
        {"<filterId>": {"value": "<valueId>", "id": "<filterId>"}} for attributes.
        Returns the filtered search screen (parse with divkit.search_results)."""
        import uuid as _uuid
        import re as _re
        import json as _json
        iid = str(_uuid.uuid4())
        # 1) establish the search session (server assigns the screenId = iid we send)
        r1 = self.screen("search-result",
                         body={"request": self._search_req(text, iid), "payload": {"state": {}}})
        s1 = _json.dumps(r1, ensure_ascii=False)

        def sv(key):
            m = _re.search(r"store\(\[[^\]]*'" + key + r"'[^\]]*\],\s*(\{.+?\}|\"[^\"]*\"|\[[^\]]*\])\s*,\s*@", s1)
            return m.group(1) if m else None

        rs = _json.loads(sv("reportState")) if sv("reportState") else None
        cp = sv("currentParams")
        cp = _json.loads(cp) if cp and cp.startswith("{") else {"text": text}
        pt = sv("pageToken")
        pt = _json.loads(pt) if pt else None
        screen = {
            "requestAction": "filter", "checkedFilters": checked_filters,
            "pageToken": _json.dumps(pt) if pt else "", "backendState": None,
            "previousFilters": {}, "reportState": rs,
            "urlParams": {"is_formalized": "0"}, "currentParams": cp,
            "selectedSort": self.SORTS.get(sort, sort) if sort else "dpop",
            "reloadedFlag": True,
        }
        return self.screen("search-result", body={
            "request": self._search_req(text, iid),
            "payload": {"state": {"search": {"screens": {iid: screen}}}},
        })

    def main(self) -> Any:
        """Fetch the main home screen / feed."""
        return self.screen("main", body={})

    def cart(self) -> Any:
        return self.screen("cart", body={})

    def profile(self) -> Any:
        """Fetch user profile screen (requires oauth_token)."""
        return self.screen("profile", body={})

    def orders(self) -> Any:
        """Fetch my orders screen (requires oauth_token)."""
        return self.screen("my-orders", body={})

    def catalog(self) -> Any:
        """Fetch the root catalog screen."""
        try:
            return self.screen("root-catalog", body={})
        except Exception:
            return self.screen("catalog", body={})

    def checkout(self) -> Any:
        """Fetch the checkout screen to start the ordering process (requires oauth_token)."""
        try:
            return self.screen("checkout/summary", body={})
        except Exception:
            return self.screen("checkout", body={})

    def favourites(self) -> Any:
        """Fetch user favourites/wishlist screen (requires oauth_token)."""
        return self.screen("favourites", body={})

    def category(self, nid: int | str) -> Any:
        """Fetch category screen by catalog nid (e.g. 54440)."""
        return self.screen("category", body={"request": {"nid": int(nid)}})


    def product_reviews(self, sku_id: int | str) -> Any:
        """Fetch user reviews for a given product/sku."""
        return self.screen("product-reviews", query={"skuId": str(sku_id)})

    def delivery_points(self) -> Any:
        """Fetch available pickup / delivery points screen."""
        return self.screen("mainDeliveryPoints", body={})

    def chats(self) -> Any:
        """Fetch customer support / seller chats screen."""
        return self.screen("my/chats", body={})

    def purchased_items(self) -> Any:
        """Fetch previously purchased items screen (requires oauth_token)."""
        return self.screen("purchased-items", body={})

    def search_history(self) -> Any:
        """Fetch user search history screen (requires oauth_token)."""
        return self.screen("search-history", body={})



    def _product_action(self, sku_id: int | str, action_path: str) -> Any:
        prod = self.product(sku_id)
        q = self._find_remote_action(prod, action_path)
        if not q:
            raise FapiError(0, f"no {action_path} action on product screen")
        return self.run_action(q)

    @staticmethod
    def _find_query(obj: Any, path_contains: str):
        """Find any {query:{path,body}} whose path matches (broader than RemoteAction)."""
        if isinstance(obj, dict):
            q = obj.get("query")
            if isinstance(q, dict) and path_contains in str(q.get("path", "")):
                return q
            for v in obj.values():
                r = MarketClient._find_query(v, path_contains)
                if r:
                    return r
        elif isinstance(obj, list):
            for v in obj:
                r = MarketClient._find_query(v, path_contains)
                if r:
                    return r
        return None

    def referral_share(self, sku_id: int | str) -> dict:
        """Referral share data for a product: the bonus you earn per referral
        (`bonus`), your account referral id (`public_id`), and a working referral
        link (`referral_url`). Requires oauth_token (per-account referral context)."""
        import urllib.parse as _u
        prod = self.product(sku_id)
        q = self._find_query(prod, "sharePopup")
        if not q:
            raise FapiError(0, "no share action on product screen")
        sc = q["body"].get("shareContext", {})
        kv = sc.get("kv", {})
        osku = sc.get("osku")
        offer_id = kv.get("offerid")
        ctx = kv.get("utm_referral_context", "")
        url = (f"https://market.yandex.ru/card/x/{osku}?do-waremd5={offer_id}"
               f"&utm_referral_context={_u.quote(ctx)}")
        
        b2b_str = sc.get("b2bPromise") or sc.get("b2b_promise") or sc.get("businessPromise") or sc.get("m2bPromise")
        b2b = int(b2b_str) if b2b_str else None

        return {
            "bonus": int(sc["promise"]) if sc.get("promise") else None,
            "b2b_bonus": b2b,
            "public_id": kv.get("publicId"),
            "offer_id": offer_id, "osku": osku,
            "referral_url": url, "share_context": sc,
        }

    def add_to_favourites(self, sku_id: int | str) -> Any:
        return self._product_action(sku_id, "addWishlistItem")

    def remove_from_favourites(self, sku_id: int | str) -> Any:
        return self._product_action(sku_id, "deleteWishlistItem")

    def remove_from_cart(self, sku_id: int | str) -> Any:
        """Remove a product from the cart (write). Requires oauth_token."""
        prod = self.product(sku_id)
        q = self._find_remote_action(prod, "removeItemsFromCart")
        if not q:
            q = self._find_remote_action(prod, "deleteItemsFromCart")
        if not q:
            raise FapiError(0, "no remove/delete cart action on product screen")
        return self.run_action(q)

    def clear_cart(self) -> Any:
        """Clear all items from the cart."""
        c = self.cart()
        q = self._find_remote_action(c, "clearCart") or self._find_remote_action(c, "removeAllCartItems")
        if q:
            return self.run_action(q)
        return c

    def search_products(self, text: str, pages: int = 1, sort: str | None = None,
                        min_price: int | None = None, max_price: int | None = None,
                        contains: str | list[str] | None = None) -> list[dict]:
        """Fast search: parse the result grid directly (1 request/page, no per-product
        fetches). Returns [{sku, title, price}] client-filtered and sorted.
        `contains` = keyword(s) all of which the title must include (case-insensitive)
        — a robust client-side substitute for server attribute filters (memory/color/…),
        since server-side filtering returns an un-parseable DivKit patch."""
        from . import divkit
        rows: list[dict] = []
        seen: set = set()
        token = None
        for _ in range(max(1, pages)):
            res = self.search(text, page_token=token, sort=sort)
            for r in divkit.search_results(res):
                if r["sku"] and r["sku"] not in seen:
                    seen.add(r["sku"])
                    rows.append(r)
            token = divkit.next_page_token(res)
            if not token:
                break
        kws = [contains] if isinstance(contains, str) else (contains or [])
        out = []
        for r in rows:
            p = r.get("price")
            if p is None:
                continue
            if min_price is not None and p < min_price:
                continue
            if max_price is not None and p > max_price:
                continue
            title = (r.get("title") or "").lower()
            if any(k.lower() not in title for k in kws):
                continue
            out.append(r)
        out.sort(key=lambda r: r.get("price") or 1 << 60)
        return out

    def find_products(self, text: str, limit: int = 10, pages: int = 1,
                      sort: str | None = None, min_price: int | None = None,
                      max_price: int | None = None) -> list[dict]:
        """Like search_products, but enriches the top `limit` with product_id/url
        (one product() fetch each, after price-filtering on the cheap grid data)."""
        from . import divkit
        rows = self.search_products(text, pages=pages, sort=sort,
                                    min_price=min_price, max_price=max_price)
        out = []
        for r in rows[:limit]:
            try:
                info = divkit.product_info(self.product(r["sku"]))
                info.setdefault("name", r.get("title"))
                out.append(info)
            except Exception:
                out.append(r)
        return out

    # Sort ids: dpop=popular, aprice=cheapest, dprice=priciest, rating=top-rated.
    SORTS = {"popular": "dpop", "cheapest": "aprice", "priciest": "dprice", "rating": "rating"}

    @staticmethod
    def _search_req(text: str, instance_id: str) -> dict:
        import uuid as _uuid
        return {
            "text": text,
            "expressSearch": False, "isRedirect": False, "isShopInShop": False,
            "isUnivermagSearch": False, "supplierIds": [],
            "searchResultInstanceId": instance_id,
            "deviceIsTablet": False, "deviceScreenWidth": 411.0, "deviceScreenDensity": 2.625,
            "isCategoryRefinementRequest": True, "isNewFlow": False, "vertical": "all",
            "verticalIds": ["marketAi", "all", "select", "ultima", "weekly"],
            "verticalsTabBarInstanceId": _uuid.uuid4().hex,
            "hasSuggestsHeader": False, "shopInShopContext": False, "allOffers": False,
        }

    def search(self, text: str, filters: dict | None = None,
               page_token: str | None = None, sort: str | None = None) -> Any:
        """Plain search. For server-side attribute filters use search_filtered().
        `sort` is a raw id (dpop/aprice/dprice/rating) or key (cheapest/priciest/…)."""
        import uuid as _uuid
        req = self._search_req(text, str(_uuid.uuid4()))
        if filters:
            req["filters"] = filters
        if sort:
            req["selectedSortId"] = self.SORTS.get(sort, sort)
        query = {"pageToken": page_token} if page_token else None
        return self.screen("search-result", query=query,
                           body={"request": req, "payload": {"state": {}}})


class IOSClient(MarketClient):
    """Full SDK Pure-HTTP Zero-Device Fully headless iOS client (standalone, device-independent, all operations)."""

    def __init__(self, device: Device | None = None, **kwargs):
        if device is None:
            device = Device.random(platform="ios")
        elif device.platform != "ios":
            device.platform = "ios"
            device.manufacturer = "Apple"
            device.brand = "Apple"
        super().__init__(device=device, **kwargs)


class AndroidClient(MarketClient):
    """Full SDK Pure-HTTP Zero-Device Fully headless Android client (standalone, device-independent, all operations)."""

    def __init__(self, device: Device | None = None, **kwargs):
        if device is None:
            device = Device.random(platform="android")
        elif device.platform != "android":
            device.platform = "android"
        super().__init__(device=device, **kwargs)

