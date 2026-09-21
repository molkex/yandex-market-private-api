"""Zero-device synthetic identity for Yandex Market FAPI.

No physical device needed: all identifiers are generated locally and are the
exact fields the app sends (captured from ru.beru.android 2026.32.3).
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from dataclasses import dataclass, field

# Captured app constants (ru.beru.android 2026.32.3.c, build 36532)
APP_VERSION = "2026.32.3"
APP_BUILD_NUMBER = "36532"
APP_ID = "ru.beru.android"
APP_FLAVOR = "release"
STORE_TRACK = "rustore"
USER_AGENT_TMPL = "Beru/{ver} (Android/{android}; {model}/{brand})"
USER_AGENT_IOS = "Beru/{ver} (iPhone; iOS {ios}; Scale/{scale})"

# iOS app (ru.yandex.blue.market 2026.32.7) — same backend, iOS User-Agent.
APP_VERSION_IOS = "2026.32.7"
APP_BUILD_NUMBER_IOS = "20263207"
APP_ID_IOS = "ru.yandex.blue.market"
STORE_TRACK_IOS = "appstore"
IOS_MODELS = [
    ("iPhone9,4", "15.8.8", "3.00"),    # iPhone 7 Plus
    ("iPhone14,5", "17.5.1", "3.00"),   # iPhone 13
    ("iPhone15,3", "18.0", "3.00"),     # iPhone 14 Pro Max
]

# A believable stock-Android device profile (override freely).
DEFAULT_MODELS = [
    ("samsung", "SM-A346E", "Samsung", "13"),
    ("Google", "Pixel 7", "Google", "14"),
    ("Xiaomi", "23021RAA2Y", "Xiaomi", "13"),
]


def _hex(nbytes: int) -> str:
    return os.urandom(nbytes).hex()


@dataclass
class Device:
    """A synthetic Yandex Market device identity (Android or iOS)."""

    platform: str = "android"          # "android" | "ios"
    manufacturer: str = "samsung"
    model: str = "SM-A346E"
    brand: str = "Samsung"
    android_version: str = "13"
    uuid: str = field(default_factory=lambda: _hex(16))            # 32 hex
    android_id: str = field(default_factory=lambda: _hex(8))       # 16 hex
    gaid: str = field(default_factory=lambda: str(uuid.uuid4()))   # advertising id
    appmetrica_device_id: str = field(default_factory=lambda: _hex(16))
    hardware_serial: str = "unknown"
    ios_scale: str = "3.00"

    @classmethod
    def ios(cls, model: str = "iPhone9,4", ios_version: str = "15.8.8", ios_scale: str = "3.00") -> "Device":
        """Factory for a dedicated zero-device iOS identity (default iPhone 7 Plus)."""
        return cls(platform="ios", manufacturer="Apple", brand="Apple",
                   model=model, android_version=ios_version, ios_scale=ios_scale)

    @classmethod
    def android(cls, manufacturer: str = "Samsung", model: str = "SM-A346E",
                brand: str = "Samsung", android_version: str = "13") -> "Device":
        """Factory for a dedicated zero-device Android identity."""
        return cls(platform="android", manufacturer=manufacturer, model=model,
                   brand=brand, android_version=android_version)

    @classmethod
    def random(cls, platform: str = "android") -> "Device":
        import random
        if platform == "ios":
            model, ver, scale = random.choice(IOS_MODELS)
            return cls(platform="ios", manufacturer="Apple", brand="Apple",
                       model=model, android_version=ver, ios_scale=scale)
        man, model, brand, av = random.choice(DEFAULT_MODELS)
        return cls(platform="android", manufacturer=man, model=model, brand=brand, android_version=av)

    def user_agent(self) -> str:
        if self.platform == "ios":
            return USER_AGENT_IOS.format(ver=APP_VERSION_IOS,
                                         ios=self.android_version, scale=self.ios_scale)
        return USER_AGENT_TMPL.format(
            ver=APP_VERSION, android=self.android_version,
            model=self.model, brand=self.brand.lower(),
        )

    def x_device_info(self) -> str:
        """Base64 of the JSON blob the app sends as x-device-info."""
        if self.platform == "ios":
            blob = {
                "deviceId": {
                    "iosModel": self.model,
                    "iosDeviceId": self.android_id,
                    "iosVendorId": self.uuid,
                },
                "emulator": False,
            }
        else:
            blob = {
                "deviceId": {
                    "androidBuildManufacturer": self.manufacturer,
                    "androidBuildModel": self.model,
                    "androidDeviceId": self.android_id,
                    "androidHardwareSerial": self.hardware_serial,
                },
                "emulator": False,
            }
        raw = json.dumps(blob, separators=(",", ":")).encode()
        return base64.b64encode(raw).decode()

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "manufacturer": self.manufacturer, "model": self.model,
            "brand": self.brand, "android_version": self.android_version,
            "uuid": self.uuid, "android_id": self.android_id,
            "gaid": self.gaid, "appmetrica_device_id": self.appmetrica_device_id,
            "hardware_serial": self.hardware_serial,
            "ios_scale": self.ios_scale,
        }

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Device":
        with open(path) as f:
            return cls(**json.load(f))
