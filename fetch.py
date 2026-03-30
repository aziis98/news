"""
fetch.py — runtime for sites.py checks.

Public API (imported by sites.py):
    News        — class that registers and runs checks
    Notify      — return value that triggers a GitHub issue
    fetch()     — HTTP fetch returning a Response
    semver      — semver.matches(version, spec)
    blob_hash() — sha256 hex digest of bytes or str
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
import yaml
from bs4 import BeautifulSoup
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from pydantic import BaseModel, create_model


def _format_yaml(data: Any) -> str:
    """Return a nicely formatted YAML string."""
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False).rstrip()


# ─── Notify ───────────────────────────────────────────────────────────────────


@dataclass
class Notify:
    title: str
    body: str = ""
    image: str | None = None


# ─── HTML ────────────────────────────────────────────────────────────────────


class HTMLMetadata:
    """Extracted metadata from an HTML page."""

    def __init__(
        self, title: str | None = None, description: str | None = None, image: str | None = None
    ) -> None:
        self.title = title
        self.description = description
        self.image = image


class HTML:
    """Parsed HTML document with metadata extraction."""

    def __init__(self, content: str, url: str | None = None) -> None:
        self._content = content
        self._url = url
        self._soup = BeautifulSoup(content, "html.parser")

    @property
    def document(self) -> BeautifulSoup:
        """Return the parsed DOM."""
        return self._soup

    @property
    def metadata(self) -> HTMLMetadata:
        """Extract metadata from og/twitter tags with fallbacks."""
        # Open Graph tags (primary)
        og_title = self._soup.find("meta", property="og:title")
        og_description = self._soup.find("meta", property="og:description")
        og_image = self._soup.find("meta", property="og:image")

        # Twitter tags (fallbacks)
        twitter_title = self._soup.find("meta", attrs={"name": "twitter:title"})
        twitter_description = self._soup.find("meta", attrs={"name": "twitter:description"})
        twitter_image = self._soup.find("meta", attrs={"name": "twitter:image"})

        # HTML fallbacks
        title_tag = self._soup.find("title")
        h1_tag = self._soup.find("h1")
        meta_description = self._soup.find("meta", attrs={"name": "description"})

        # Extract with fallbacks
        title = None
        if og_title and og_title.get("content"):
            title = str(og_title["content"])
        elif twitter_title and twitter_title.get("content"):
            title = str(twitter_title["content"])
        elif title_tag and title_tag.string:
            title = title_tag.string
        elif h1_tag and h1_tag.string:
            title = h1_tag.string

        description = None
        if og_description and og_description.get("content"):
            description = str(og_description["content"])
        elif twitter_description and twitter_description.get("content"):
            description = str(twitter_description["content"])
        elif meta_description and meta_description.get("content"):
            description = str(meta_description["content"])

        image = None
        if og_image and og_image.get("content"):
            image = str(og_image["content"])
        elif twitter_image and twitter_image.get("content"):
            image = str(twitter_image["content"])

        return HTMLMetadata(title=title, description=description, image=image)


# ─── Response ─────────────────────────────────────────────────────────────────


class Response:
    def __init__(self, resp: requests.Response) -> None:
        self._resp = resp

    def json(self) -> BaseModel:
        """Parse JSON body; returns validated Pydantic model."""
        data = self._resp.json()
        # Create a dynamic Pydantic model from the JSON structure
        if isinstance(data, dict):
            model = _dict_to_pydantic_model(data)
            return model(**data)
        raise ValueError(f"Expected dict from JSON, got {type(data)}")

    def text(self) -> str:
        return self._resp.text

    def binary(self) -> bytes:
        return self._resp.content

    def html(self) -> HTML:
        """Parse response as HTML with metadata extraction."""
        return HTML(self._resp.text, self._resp.url)


def _dict_to_pydantic_model(data: dict[str, Any]) -> type[BaseModel]:
    """Convert a dict to a Pydantic model class."""
    fields = {}
    for key, value in data.items():
        if isinstance(value, dict):
            fields[key] = (_dict_to_pydantic_model(value), ...)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            fields[key] = (list, ...)
        elif value is None:
            fields[key] = (Any, None)
        else:
            fields[key] = (type(value), ...)
    return create_model("DynamicModel", **fields)  # type: ignore[return-value]


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
    if isinstance(data, bytes):
        data_bytes = data
    else:
        assert isinstance(data, str)
        data_bytes = data.encode()
    h = hashlib.new(algo)
    h.update(data_bytes)
    return h.hexdigest()


def pdf_to_text(data: bytes) -> str:
    """Extract plain text from PDF bytes using PyMuPDF (pymupdf/fitz).

    Raises RuntimeError if PyMuPDF is not available.
    """
    # Prefer the modern `pymupdf` import, but fall back to the historical `fitz` name
    mupdf = None
    try:
        import pymupdf as mupdf
    except Exception:
        try:
            import fitz as mupdf
        except Exception:
            mupdf = None

    if mupdf is not None:
        try:
            doc = mupdf.open(stream=data, filetype="pdf")
            pages = [str(p.get_text("text")) for p in doc]
            return "\n\n".join(pages)
        except Exception:
            pass
    raise RuntimeError("PDF text extraction requires PyMuPDF (pymupdf/fitz).")


def text_diff(old: str, new: str, context: int = 3) -> str:
    """Return a markdown-friendly unified diff wrapped in a ```diff block.

    The diff is truncated if extremely large to keep notifications readable.
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff_lines = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile="previous", tofile="current", lineterm="", n=context
        )
    )
    if not diff_lines:
        return ""

    # Truncate if very large
    max_lines = 800
    if len(diff_lines) > max_lines:
        head = diff_lines[: max_lines // 2]
        tail = diff_lines[-(max_lines // 2) :]
        diff_lines = head + ["... (diff truncated) ..."] + tail

    return "```diff\n" + "\n".join(diff_lines) + "\n```"


# ─── registry & check entries ─────────────────────────────────────────────────

registry: list[_CheckEntry] = []


class _CheckEntry:
    """Internal base for a registered check."""

    id: str
    interval: int  # seconds

    def run(self) -> Notify | None:
        raise NotImplementedError

    def dump_state(self) -> dict:
        return {}

    def load_state(self, data: dict) -> None:
        pass


class _FunctionCheck(_CheckEntry):
    def __init__(self, fn: Callable, interval: int, id: str | None = None) -> None:
        self.id = id or fn.__name__
        self.interval = interval
        self._fn = fn

    def run(self) -> Notify | None:
        return self._fn()


class _ClassCheck(_CheckEntry):
    def __init__(self, instance: object, interval: int, id: str | None = None) -> None:
        self.id = id or type(instance).__name__
        self.interval = interval
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


# ─── News class ───────────────────────────────────────────────────────────────


def _parse_interval(s: str) -> int:
    m = re.fullmatch(r"(\d+)([smhd])", s.strip())
    if not m:
        raise ValueError(f"Bad interval {s!r}  (expected e.g. '15m', '3h', '1d')")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


class News:
    """Check registry and runner."""

    def __init__(self) -> None:
        self.registry: list[_CheckEntry] = []

    def check(self, every: str, *, id: str | None = None) -> Callable:
        """Decorator for function and class checks.

        Usage:
            news = News()

            @news.check(every="3h")
            def my_check():
                return Notify(...) or None

            @news.check(every="15m", id="custom_id")
            class MyCheck:
                state: str = None
                def check(self):
                    return Notify(...) or None
        """
        interval = _parse_interval(every)

        def decorator(target: type | Callable) -> type | Callable:
            check_id = id or (target.__name__ if isinstance(target, type) else target.__name__)

            # Check for ID collisions
            if any(entry.id == check_id for entry in self.registry):
                print(f"⚠️  Collision detected: check id '{check_id}' already registered!", file=sys.stderr)

            if isinstance(target, type):
                entry = _ClassCheck(target(), interval, check_id)
            else:
                entry = _FunctionCheck(target, interval, check_id)
            self.registry.append(entry)
            return target  # preserve original so the name / repr stay intact

        return decorator

    def _load_state(self, state_file: Path) -> dict:
        if state_file.exists():
            try:
                return json.loads(state_file.read_text())
            except json.JSONDecodeError as e:
                print(f"[warn] state.json malformed ({e}), starting fresh.", file=sys.stderr)
        return {}

    def _save_state(self, state_file: Path, state: dict) -> None:
        state_file.write_text(json.dumps(state, indent=2) + "\n")

    def _gh_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _open_github_issue(self, n: Notify) -> None:
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPOSITORY", "")

        if not token or not repo:
            print("  ⚠  GITHUB_TOKEN / GITHUB_REPOSITORY not set — printing locally.")
            print(f"  ╔ {n.title}")
            for line in n.body.splitlines():
                print(f"  ║ {line}")
            print("  ╚─")
            return

        headers = self._gh_headers()

        # Dedup: skip if an open issue with this exact title already exists
        r = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            headers=headers,
            params={"state": "open", "per_page": 100},
            timeout=10,
        )
        if r.ok:
            if any(i["title"] == n.title for i in r.json()):
                print("  ↩  Issue already open — skipping.")
                return

        r = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers=headers,
            json={"title": n.title, "body": n.body},
            timeout=10,
        )
        r.raise_for_status()
        print(f"  ✅ Opened issue #{r.json()['number']}: {r.json()['html_url']}")

    def run(self, state_file: Path | str = "state.json", *, force: bool | None = None) -> None:
        """Run all registered checks and open GitHub issues for notifications.

        Args:
            state_file: Path to the state file for persisting check data.
            force: If True, ignore timer cooldown and run all checks immediately. If None,
                the `FORCE_RECHECK` environment variable is consulted.
        """
        state_file = Path(state_file)
        now = int(time.time())
        state = self._load_state(state_file)
        ran = skipped = errored = 0
        if force is None:
            force = os.environ.get("FORCE_RECHECK", "").lower() in ("1", "true", "yes")
        else:
            force = bool(force)

        for entry in self.registry:
            s = state.setdefault(entry.id, {})
            last_run = s.get("_last_run", 0)
            due_in = (last_run + entry.interval) - now

            if not force and due_in > 0:
                h, rem = divmod(due_in, 3600)
                m, sec = divmod(rem, 60)
                eta = f"{h}h {m}m {sec}s" if h else (f"{m}m {sec}s" if m else f"{sec}s")
                print(f"⏭  [{entry.id}]  next run in {eta}")
                skipped += 1
                continue

            print(f"🔍 [{entry.id}]  running …")
            ran += 1

            # Restore persisted state into the check instance (class checks only)
            cached_state = s.get("_data", {})
            if cached_state:
                formatted = _format_yaml(cached_state)
                print("\033[38;2;136;136;136m  📦 Restored state:\033[0m")
                for line in formatted.splitlines():
                    print(f"\033[38;2;136;136;136m  ║ {line}\033[0m")
            entry.load_state(cached_state)

            try:
                n = entry.run()

                # Flush updated instance state back into the state dict
                s["_data"] = entry.dump_state()
                s["_last_run"] = now

                if isinstance(n, Notify):
                    print(f"  🔔 {n.title}")
                    # Print the new cached state as nicely formatted YAML (or JSON fallback)
                    new_cached = s.get("_data", {})
                    if new_cached:
                        formatted = _format_yaml(new_cached)
                        print("\033[38;2;136;136;136m  📦 New cached state:\033[0m")
                        for line in formatted.splitlines():
                            print(f"\033[38;2;136;136;136m  ║ {line}\033[0m")
                    self._open_github_issue(n)
                elif n not in (None, False):
                    print(f"  ⚠  unexpected return value: {n!r}", file=sys.stderr)
                else:
                    print("  ✓  no change.")

            except Exception as exc:
                print(f"  ❌ {exc}", file=sys.stderr)
                errored += 1

        self._save_state(state_file, state)
        print(f"\nDone — ran {ran}, skipped {skipped}, errored {errored}.")
        if errored:
            sys.exit(1)
