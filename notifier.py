#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "packaging", "pydantic"]
# ///
"""
notifier.py — runs all due checks from sites.py and opens GitHub issues
for any triggered Notify values.

Usage:
    uv run notifier.py

Required env vars (set automatically in GitHub Actions):
    GITHUB_TOKEN       — token with issues:write permission
    GITHUB_REPOSITORY  — "owner/repo"
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

import sites  # registers all checks via @check decorators  # noqa: F401
from fetch import Notify, registry

STATE_FILE = Path("state.json")
GITHUB_API = "https://api.github.com"


# ─── state ────────────────────────────────────────────────────────────────────


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError as e:
            print(f"[warn] state.json malformed ({e}), starting fresh.", file=sys.stderr)
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


# ─── github ───────────────────────────────────────────────────────────────────


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def open_github_issue(n: Notify) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    if not token or not repo:
        print("  ⚠  GITHUB_TOKEN / GITHUB_REPOSITORY not set — printing locally.")
        print(f"  ╔ {n.title}")
        for line in n.body.splitlines():
            print(f"  ║ {line}")
        print("  ╚─")
        return

    headers = _gh_headers()

    # Dedup: skip if an open issue with this exact title already exists
    r = requests.get(
        f"{GITHUB_API}/repos/{repo}/issues",
        headers=headers,
        params={"state": "open", "per_page": 100},
        timeout=10,
    )
    if r.ok:
        if any(i["title"] == n.title for i in r.json()):
            print("  ↩  Issue already open — skipping.")
            return

    r = requests.post(
        f"{GITHUB_API}/repos/{repo}/issues",
        headers=headers,
        json={"title": n.title, "body": n.body},
        timeout=10,
    )
    r.raise_for_status()
    print(f"  ✅ Opened issue #{r.json()['number']}: {r.json()['html_url']}")


# ─── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    now = int(time.time())
    state = load_state()
    ran = skipped = errored = 0

    for entry in registry:
        s = state.setdefault(entry.id, {})
        last_run = s.get("_last_run", 0)
        due_in = (last_run + entry.interval) - now

        if due_in > 0:
            h, rem = divmod(due_in, 3600)
            m, sec = divmod(rem, 60)
            eta = f"{h}h {m}m {sec}s" if h else (f"{m}m {sec}s" if m else f"{sec}s")
            print(f"⏭  [{entry.id}]  next run in {eta}")
            skipped += 1
            continue

        print(f"🔍 [{entry.id}]  running …")
        ran += 1

        # Restore persisted state into the check instance (class checks only)
        entry.load_state(s.get("_data", {}))

        try:
            n = entry.run()

            # Flush updated instance state back into the state dict
            s["_data"] = entry.dump_state()
            s["_last_run"] = now

            if isinstance(n, Notify):
                print(f"  🔔 {n.title}")
                open_github_issue(n)
            elif n not in (None, False):
                print(f"  ⚠  unexpected return value: {n!r}", file=sys.stderr)
            else:
                print("  ✓  no change.")

        except Exception as exc:
            print(f"  ❌ {exc}", file=sys.stderr)
            errored += 1

    save_state(state)
    print(f"\nDone — ran {ran}, skipped {skipped}, errored {errored}.")
    if errored:
        sys.exit(1)


if __name__ == "__main__":
    main()
