"""Yandex Passport phonish registration/login — pure HTTP, no deps.

Reverse-engineered from com.yandex.passport (Passport SDK 7.57.0) inside
ru.beru.android. No request signing; credentials decrypted offline (AES-256/CFB,
key = XOR of hex(SHA-256(w)) for w in "yandex account manager").
"""
from __future__ import annotations

# --- STATUS (2026-09-02) ---
# WORKING live: _decrypt_credential (client_id/secret cracked), start(), send_sms(),
#   confirm_sms(), validate phone. Passport endpoints + AES/CFB creds fully reversed.
# COMPLETE: full zero-device pipeline works end-to-end.
#   register_neophonish -> /1/bundle/mobile/register/neophonish/ (track_id, firstname,
#   lastname, eula_accepted=true) -> {access_token, x_token, uid}. Proven: self-registered
#   account (uid 2430359246) queried Market search successfully (broken=False).


import base64
import hashlib
import json
import urllib.parse
from http.client import HTTPSConnection

HOST = "mobileproxy.passport.yandex.net"
AM_VERSION = "7.57.0.757005328"
AM_VERSION_NAME = "7.57.0(757005328)"

# Decrypted Market client credentials — Android (from the APK, AES/CFB).
CLIENT_ID = "c0ebe342af7d48fbbbfcf2d2eedb8f9e"
CLIENT_SECRET = "ad0a908f0aa341a182a37ecd75bc319e"
CLIENT_ID_2 = "21e27582fcb04aa4b11356934b7f28f1"
CLIENT_SECRET_2 = "afff6b0ce658454b9bb7e3ef1afe6711"

# iOS Market Passport clients (ru.yandex.blue.market), captured from live login.
IOS_XTOKEN_CLIENT_ID = "1c747d5239b04e18ab0b218f00da333e"
IOS_XTOKEN_CLIENT_SECRET = "a90f4acfa33e44019d6465429bee12e3"
IOS_CLIENT_ID = "3cc7464b4a95462b888de3e0664d7091"
IOS_CLIENT_SECRET = "7b29f9bb126c465ca0912c05bd973bf5"
IOS_AM_VERSION = "6.39.0"


def _decrypt_credential(b64: str) -> str:
    """AES-256/CFB decrypt of a Passport credential blob (util/b.java)."""
    buf = bytearray(32)
    for w in "yandex account manager".split(" "):
        hx = hashlib.sha256(w.encode()).digest().hex().encode()
        for i in range(32):
            buf[i] ^= hx[i]
    key = bytes(buf)
    ct = base64.b64decode(b64)
    try:
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        pt = Cipher(algorithms.AES(key), CFB(b"\x00" * 16)).decryptor().update(ct)
    except ImportError:  # pragma: no cover
        from Crypto.Cipher import AES
        pt = AES.new(key, AES.MODE_CFB, iv=b"\x00" * 16, segment_size=128).decrypt(ct)
    return pt.split(b"^")[0].decode("utf-8")


class PassportError(Exception):
    def __init__(self, payload):
        super().__init__(str(payload))
        self.payload = payload


class Passport:
    def __init__(self, device, proxy: str | None = None, display_language: str = "ru"):
        self.device = device
        self.lang = display_language
        self.ios = getattr(device, "platform", "android") == "ios"
        # platform-specific Passport clients
        if self.ios:
            self.x_client_id, self.x_client_secret = IOS_XTOKEN_CLIENT_ID, IOS_XTOKEN_CLIENT_SECRET
            self.client_id, self.client_secret = IOS_CLIENT_ID, IOS_CLIENT_SECRET
        else:
            self.x_client_id, self.x_client_secret = CLIENT_ID, CLIENT_SECRET
            self.client_id, self.client_secret = CLIENT_ID_2, CLIENT_SECRET_2
        self.track_id: str | None = None
        self.proxy_host = self.proxy_port = self.proxy_auth = None
        if proxy:
            p = proxy.split(":")
            self.proxy_host, self.proxy_port = p[0], int(p[1])
            if len(p) >= 4:
                self.proxy_auth = "Basic " + base64.b64encode(
                    f"{p[2]}:{p[3]}".encode()).decode()

    # ---- transport ----
    def _conn(self) -> HTTPSConnection:
        if self.proxy_host:
            c = HTTPSConnection(self.proxy_host, self.proxy_port, timeout=30)
            h = {"Proxy-Authorization": self.proxy_auth} if self.proxy_auth else {}
            c.set_tunnel(HOST, 443, headers=h)
            return c
        return HTTPSConnection(HOST, timeout=30)

    def _ua(self) -> str:
        d = self.device
        if self.ios:
            return (f"com.yandex.mobile.auth.sdk/{IOS_AM_VERSION}.72867 "
                    f"(Apple {d.model}; iOS {d.android_version}) PassportSDK/{IOS_AM_VERSION}")
        return (f"com.yandex.mobile.auth.sdk/{AM_VERSION} "
                f"({d.manufacturer} {d.model}; Android {d.android_version})")

    def _common_query(self) -> dict:
        d = self.device
        if self.ios:
            return {
                "manufacturer": "Apple", "model": d.model,
                "app_platform": "iPhone", "am_version_name": IOS_AM_VERSION,
                "app_id": "ru.yandex.blue.market", "app_version_name": "2026.32.7",
                "am_app": "ru.yandex.blue.market", "device_id": d.android_id, "uuid": d.uuid,
            }
        return {
            "manufacturer": d.manufacturer, "model": d.model,
            "app_platform": "android", "am_version_name": AM_VERSION_NAME,
            "app_id": "ru.beru.android", "app_version_name": "2026.32.3",
            "am_app": "ru.beru.android", "device_id": d.android_id, "uuid": d.uuid,
        }

    def _post(self, path: str, form: dict) -> dict:
        q = urllib.parse.urlencode(self._common_query())
        body = urllib.parse.urlencode({k: v for k, v in form.items() if v is not None})
        headers = {
            "User-Agent": self._ua(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "gzip",
        }
        conn = self._conn()
        try:
            conn.request("POST", path + "?" + q, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read()
            if resp.getheader("content-encoding", "").lower() == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            data = json.loads(raw.decode("utf-8", "replace"))
            return data
        finally:
            conn.close()

    # ---- flow steps ----
    def start(self, phone: str, force_register: bool = True) -> dict:
        r = self._post("/2/bundle/mobile/start/", {
            "login": phone, "force_register": str(force_register).lower(),
            "is_phone_number": "true",
            "x_token_client_id": self.x_client_id, "x_token_client_secret": self.x_client_secret,
            "client_id": self.client_id, "client_secret": self.client_secret,
            "display_language": self.lang,
        })
        self.track_id = r.get("track_id", self.track_id)
        return r

    @classmethod
    def ios(cls, device=None, proxy: str | None = None, display_language: str = "ru") -> "Passport":
        """Convenience constructor for iOS Passport authentication."""
        from .device import Device
        dev = device or Device.random(platform="ios")
        return cls(dev, proxy=proxy, display_language=display_language)

    @classmethod
    def android(cls, device=None, proxy: str | None = None, display_language: str = "ru") -> "Passport":
        """Convenience constructor for Android Passport authentication."""
        from .device import Device
        dev = device or Device.random(platform="android")
        return cls(dev, proxy=proxy, display_language=display_language)

    def send_sms(self, phone: str, country: str = "RU") -> dict:
        pkg = "ru.yandex.blue.market" if self.ios else "ru.beru.android"
        return self._post("/1/bundle/phone/confirm/submit/", {
            "track_id": self.track_id, "number": phone, "country": country,
            "display_language": self.lang, "gps_package_name": pkg,
        })

    def confirm_sms(self, code: str) -> dict:
        return self._post("/1/bundle/phone/confirm/commit/", {
            "track_id": self.track_id, "code": code,
        })

    def register_neophonish(self, firstname: str = "Ivan",
                            lastname: str = "Petrov") -> dict:
        """Create a passwordless neophonish account on the confirmed-phone track.
        Returns {access_token, x_token, uid, display_login, ...}. Idempotent per track."""
        return self._post("/1/bundle/mobile/register/neophonish/", {
            "track_id": self.track_id, "firstname": firstname,
            "lastname": lastname, "eula_accepted": "true",
        })

    def refresh_token(self, x_token: str) -> dict:
        """Exchange a Passport master (x-)token for a fresh OAuth access_token.
        `x_token` is the value returned by register/login (keep it to re-issue
        access tokens without re-registering)."""
        return self._post("/1/token", {
            "grant_type": "x-token", "access_token": x_token,
            "client_id": self.x_client_id, "client_secret": self.x_client_secret,
        })

    # ---- full zero-device pipeline ----
    def register(self, phone: str, sms_code_provider,
                 firstname: str = "Ivan", lastname: str = "Petrov") -> dict:
        """End-to-end: start -> SMS -> confirm -> register neophonish.
        sms_code_provider() is called to obtain the 6-digit code. Returns the
        register response including a fresh access_token for the Market API."""
        self.start(phone)
        self.send_sms(phone)
        code = sms_code_provider()
        self.confirm_sms(code)
        return self.register_neophonish(firstname, lastname)
