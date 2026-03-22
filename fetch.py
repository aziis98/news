"""
fetch.py — runtime for sites.py checks.

Public API (imported by sites.py):
    check       — decorator for function and class checks
    Notify      — return value that triggers a GitHub issue
    fetch()     — HTTP fetch returning a Response
    semver      — semver.matches(version, spec)
    blob_hash() — sha256 hex digest of bytes or str
"""

from __future__ import annotations

import hashlib
import re
import types
from dataclasses import dataclass
from typing import Callable

import requests
from packaging.specifiers import SpecifierSet
from packaging.version import Version


# ─── Notify ───────────────────────────────────────────────────────────────────

@dataclass
class Notify:
    title: str
    body:  str = ""


# ─── Response ─────────────────────────────────────────────────────────────────

def _deep_namespace(obj: object) -> object:
    """Recursively convert dicts to SimpleNamespace for dot-access."""
    if isinstance(obj, dict):
        return types.SimpleNamespace(**{k: _deep_namespace(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_deep_namespace(i) for i in obj]
    return obj


class Response:
    def __init__(self, resp: requests.Response) -> None:
        self._resp = resp

    def json(self) -> types.SimpleNamespace:
        """Parse JSON body; nested dicts become dot-accessible namespaces."""
        return _deep_namespace(self._resp.json())

    def text(self) -> str:
        return self._resp.text

    def binary(self) -> bytes:
        return self._resp.content


# ─── fetch() ──────────────────────────────────────────────────────────────────

def fetch(url: str, *, method: str = "GET", **kwargs) -> Response:
    """HTTP fetch.  Prepends https:// when no scheme is present."""
    if not re.match(r"https?://", url):
        url = "https://" + url
    resp = requests.request(method, url, timeout=15, **kwargs)
    resp.raise_for_status()
    return Response(resp)


# ─── semver ───────────────────────────────────────────────────────────────────

class _Semver:
    def matches(self, version: str, spec: str) -> bool:
        """
        Returns True when *version* satisfies *spec*.
        Uses PEP 440 specifiers: '>=50', '==49.*', '~=48.1', etc.
        Arch pkgver strings like '50.0' or '49.4' parse cleanly.
        """
        try:
            return Version(version) in SpecifierSet(spec)
        except Exception:
            return False


semver = _Semver()


# ─── blob_hash() ──────────────────────────────────────────────────────────────

def blob_hash(data: bytes | str, algo: str = "sha256") -> str:
    """Return a hex digest of *data*."""
    h = hashlib.new(algo)
    h.update(data if isinstance(data, bytes) else data.encode())
    return h.hexdigest()


# ─── registry & check entries ─────────────────────────────────────────────────

registry: list[_CheckEntry] = []


class _CheckEntry:
    """Internal base for a registered check."""
    id:       str
    interval: int  # seconds

    def run(self) -> Notify | None:
        raise NotImplementedError

    def dump_state(self) -> dict:
        return {}

    def load_state(self, data: dict) -> None:
        pass


class _FunctionCheck(_CheckEntry):
    def __init__(self, fn: Callable, interval: int) -> None:
        self.id       = fn.__name__
        self.interval = interval
        self._fn      = fn

    def run(self) -> Notify | None:
        return self._fn()


class _ClassCheck(_CheckEntry):
    def __init__(self, instance: object, interval: int) -> None:
        self.id        = type(instance).__name__
        self.interval  = interval
        self._instance = instance

    def run(self) -> Notify | None:
        return self._instance.check()  # type: ignore[attr-defined]

    def dump_state(self) -> dict:
        cls = type(self._instance)
        return {
            k: getattr(self._instance, k)
            for k in getattr(cls, "__annotations__", {})
            if not k.startswith("_")
        }

    def load_state(self, data: dict) -> None:
        cls = type(self._instance)
        for k in getattr(cls, "__annotations__", {}):
            if not k.startswith("_") and k in data:
                setattr(self._instance, k, data[k])


# ─── check decorator ──────────────────────────────────────────────────────────

def _parse_interval(s: str) -> int:
    m = re.fullmatch(r"(\d+)([smhd])", s.strip())
    if not m:
        raise ValueError(f"Bad interval {s!r}  (expected e.g. '15m', '3h', '1d')")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def check(every: str) -> Callable:
    """
    Universal decorator — works on both functions and classes.

        @check(every="3h")
        def my_fn_check():
            ...
            return Notify(...) or None

        @check(every="15m")
        class MyClassCheck:
            some_state: str = None
            def check(self):
                ...
                return Notify(...) or None

    Annotated class attributes are automatically persisted to state.json.
    """
    interval = _parse_interval(every)

    def decorator(target: type | Callable) -> type | Callable:
        if isinstance(target, type):
            entry = _ClassCheck(target(), interval)
        else:
            entry = _FunctionCheck(target, interval)
        registry.append(entry)
        return target  # preserve original so the name / repr stay intact

    return decorator
