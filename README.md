# News

Periodic check system that monitors external resources and opens GitHub issues when conditions are met.

## What is this?

**News** lets you define periodic checks that monitor APIs, websites, PDFs, or any external resource. When a check detects a change or meets a condition, it automatically opens a GitHub issue. Perfect for tracking software releases, document updates, configuration changes, or any other event you want to be notified about.

State is automatically persisted across runs, so class-based checks can maintain memory of what they've seen before.

## Usage

Define checks on a `News` instance:

```python
from fetch import News, Notify, fetch, semver

news = News()

@news.check(every="3h")
def when_gnome_50():
    pkg = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
    if semver.matches(pkg.pkgver, ">=50"):
        return Notify(title=f"🎉 GNOME {pkg.pkgver}", body="Upgrade available")

@news.check(every="15m", id="hackernews_keyword")
class HackerNewsKeywordNotifier:
    last_check: int = 0

    def check(self):
        stories = fetch("https://hacker-news.firebaseio.com/v0/topstories.json").json()
        for story_id in stories[:30]:  # Check top 30 stories
            story = fetch(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json").json()
            title = story.title.lower() if hasattr(story, 'title') else ""
            if "rust" in title or "python" in title:
                if story.time > self.last_check:
                    self.last_check = story.time
                    # Fetch and extract metadata from story URL
                    url = story.url if hasattr(story, 'url') else ""
                    image = None
                    if url:
                        try:
                            html = fetch(url).html()
                            image = html.metadata.image
                        except:
                            pass
                    return Notify(
                        title=f"📰 {story.title}",
                        body=f"https://news.ycombinator.com/item?id={story_id}",
                        image=image
                    )

if __name__ == "__main__":
    news.run()
```

Run with:

```bash
uv run sites.py
```

## Utilities (fetch.py)

- **`News()`** — Create a check registry instance.
    - `.check(every, *, id)` — Decorator for function/class checks. Intervals: `15s`, `30m`, `3h`, `1d`. Optional `id` for explicit check naming and collision detection.
    - `.run(state_file)` — Execute all registered checks, persisting state to JSON file (default: `state.json`).

- **`Notify(title, body, image)`** — Return value from a check that triggers a GitHub issue. Only `title` is required; `body` and `image` are optional.

- **`fetch(url)`** — HTTP request with auto HTTPS prefix. Returns `Response` object.
    - `.json()` — Parse body as Pydantic-validated JSON
    - `.text()` — Get response as string
    - `.binary()` — Get response as bytes
    - `.html()` — Parse as HTML, returns `HTML` object with `.document` (BeautifulSoup) and `.metadata` (lazy title, description, image from og tags with fallbacks)

- **`semver.matches(version, spec)`** — Check version against PEP 440 specifier (e.g., `">=50"`, `"==2.*"`)

- **`blob_hash(data, algo)`** — SHA256 (default) hex digest of bytes or string
