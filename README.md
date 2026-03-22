# News

Periodic check system that monitors external resources and opens GitHub issues when conditions are met.

## What is this?

**News** lets you define periodic checks that monitor APIs, websites, PDFs, or any external resource. When a check detects a change or meets a condition, it automatically opens a GitHub issue. Perfect for tracking software releases, document updates, configuration changes, or any other event you want to be notified about.

State is automatically persisted across runs, so class-based checks can maintain memory of what they've seen before.

## Usage

Define checks with the `@check` decorator:

```python
from fetch import check, Notify, fetch, semver, blob_hash

@check(every="3h")
def when_gnome_50():
    pkg = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
    if semver.matches(pkg.pkgver, ">=50"):
        return Notify(title=f"🎉 GNOME {pkg.pkgver}", body="Upgrade available")

@check(every="15m", id="pdf_check")
class CheckUpdates:
    prev_hash: str | None = None

    def check(self):
        h = blob_hash(fetch(self.url).binary())
        if self.prev_hash and h != self.prev_hash:
            self.prev_hash = h
            return Notify(title="📄 Updated", body="New version")
        self.prev_hash = h
```

Run with:

```bash
uv run notifier.py
```

## Utilities (fetch.py)

- **`check(every, *, id)`** — Decorator for function/class checks. Intervals: `15s`, `30m`, `3h`, `1d`. Optional `id` for explicit check naming.

- **`Notify(title, body)`** — Return value that triggers a GitHub issue.

- **`fetch(url)`** — HTTP request with auto HTTPS prefix. Returns `Response` object.
    - `.json()` — Parse body as Pydantic-validated JSON
    - `.text()` — Get response as string
    - `.binary()` — Get response as bytes

- **`semver.matches(version, spec)`** — Check version against PEP 440 specifier (e.g., `">=50"`, `"==2.*"`)

- **`blob_hash(data, algo)`** — SHA256 (default) hex digest of bytes or string

- **`registry`** — List of all registered check entries
