# News

A periodic check system that monitors external resources and creates GitHub issues when conditions are met.

## Overview

**News** is a simple framework for running periodic checks on external resources (APIs, websites, PDFs, etc.) and automatically opening GitHub issues when conditions are triggered. It's designed to be:

- **Lightweight** — Minimal dependencies (requests, packaging, pydantic)
- **Flexible** — Supports both function-based and class-based checks
- **Stateful** — Persists check state to `state.json`
- **Type-safe** — Uses Pydantic for automatic validation of JSON responses

## Quick Start

### Define Checks

Create checks using the `@check` decorator:

```python
from fetch import check, Notify, fetch, semver

@check(every="3h")
def when_gnome_50():
    """Check if GNOME 50 is available in Arch Linux."""
    pkg = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
    if semver.matches(pkg.pkgver, ">=50"):
        return Notify(
            title=f"🎉 GNOME {pkg.pkgver} has landed",
            body="Run `sudo pacman -Syu` to upgrade."
        )

@check(every="15m", id="geometry_exercises")
class CheckPdfUpdates:
    """Class-based check with persistent state."""
    url = "https://example.com/document.pdf"
    prev_hash: str | None = None

    def check(self):
        pdf = fetch(self.url).binary()
        h = blob_hash(pdf)
        if self.prev_hash and h != self.prev_hash:
            self.prev_hash = h
            return Notify(
                title="📄 Document updated",
                body=f"New version: {self.url}"
            )
        self.prev_hash = h
```

### Run Checks

```bash
uv run notifier.py
```

## Features

### Intervals

Supported interval formats: `15s`, `30m`, `3h`, `1d`

### Check Types

**Function checks:** Stateless, simplest form

```python
@check(every="1h")
def my_check():
    return Notify(...) if condition else None
```

**Class checks:** Maintain state across runs (annotated fields are persisted)

```python
@check(every="1h", id="my_check")
class MyCheck:
    counter: int = 0

    def check(self):
        self.counter += 1
        if self.counter >= 5:
            return Notify(...)
```

### Collision Detection

If multiple checks share the same ID, a warning is printed:

```
⚠️  Collision detected: check id 'my_check' already registered!
```

## State Management

Check state is automatically saved/restored from `state.json`:

- Last run timestamp (`_last_run`)
- Persisted data from class attributes (`_data`)

## Requirements

- Python 3.11+
- requests
- packaging
- pydantic

## Environment Variables

When running with GitHub Actions integration:

- `GITHUB_TOKEN` — Token with `issues:write` permission
- `GITHUB_REPOSITORY` — Repository for opening issues (e.g., `owner/repo`)

If not set, notifications are printed locally instead.
