"""
sites.py — check definitions and runner

Usage:
    uv run sites.py
"""

import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from fetch import News, Notify, blob_hash, fetch, pdf_to_text, semver, text_diff

news = News()


class GnomePackage(BaseModel):
    pkgver: str


# @news.check(every="3h")
# def when_gnome_50():
#     response = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
#     pkg = GnomePackage.model_validate(response.__dict__)
#     if semver.matches(pkg.pkgver, ">=50"):
#         return Notify(
#             title=f"🎉 GNOME {pkg.pkgver} has landed in Arch [extra]",
#             body=f"Run `sudo pacman -Syu` to upgrade.",
#         )


@news.check(every="1h")
class ParameterGolfLeaderboard:
    """Monitor the OpenAI Parameter Golf leaderboard for new entries."""

    prev_entries: list[str] = []

    url = "https://github.com/openai/parameter-golf"

    def check(self):
        html_resp = fetch(self.url).html()
        soup = html_resp.document

        tables = soup.find_all("table")
        if len(tables) < 2:
            return None

        # Extract leaderboard entries from Table 1 (main leaderboard)
        leaderboard = tables[1]
        rows = leaderboard.find_all("tr")[1:]  # Skip header

        entries = []
        for row in rows:
            cols = row.find_all(["td", "th"])
            if len(cols) >= 5:
                entry_text = " | ".join([c.get_text(strip=True) for c in cols])
                entries.append(entry_text)

        # Find new entries
        prev_set = set(self.prev_entries)
        current_set = set(entries)
        new_entries = sorted(current_set - prev_set)

        notification = None
        if self.prev_entries and new_entries:
            # Build diff block
            diff_block = f"```diff\n+ {len(new_entries)} new leaderboard entries\n```"

            # Create ASCII table of new entries
            table_lines = ["| Run | Score | Author | Summary | Date |", "|---|---|---|---|---|"]
            for entry in new_entries[:5]:
                parts = entry.split(" | ")
                if len(parts) >= 5:
                    run_name = parts[0][:35]
                    score = parts[1]
                    author = parts[2][:15]
                    summary = parts[3][:40]
                    date = parts[4]
                    table_lines.append(f"| {run_name} | {score} | {author} | {summary} | {date} |")
            table_text = "\n".join(table_lines)

            # Build footer
            footer = f"Checkout the full leaderboard: {self.url}"

            # Combine all parts
            body = f"New entries detected:\n\n{diff_block}\n\n{table_text}\n\n{footer}"

            notification = Notify(
                title="🏌️ Parameter Golf Leaderboard Updated",
                body=body,
            )

        self.prev_entries = entries
        return notification


@news.check(every="1d")
class OpenVINODoc:
    """Monitor the OPENVINO.md file in the llama.cpp repo for changes.

    This fetches the raw GitHub file and generates a unified diff when the
    content changes. Notifications are emitted only when the check runs at
    08:00 local time to satisfy the "once a day at 8am" requirement.
    """

    url = "https://raw.githubusercontent.com/ggml-org/llama.cpp/master/docs/backend/OPENVINO.md"

    prev_text: str | None = None

    def check(self):
        now = datetime.now(ZoneInfo("Europe/Rome"))
        # Only notify when run at 08:00 Rome local time.
        if now.hour != 8:
            return None

        resp = fetch(self.url).text()
        text = resp
        if self.prev_text is not None and text != self.prev_text:
            diff_md = text_diff(self.prev_text, text, context=3)
            self.prev_text = text
            body = f"New version available at {self.url}\n\n{diff_md}"

            h = str(blob_hash(text))[:8]

            return Notify(
                title=f"📄 llama.cpp OPENVINO.md updated (hash {h})",
                body=body,
            )
        self.prev_text = text


@news.check(every="6h", enabled=False)
class AntigravityChecker:
    """Monitor the AUR `antigravity-cli` package and notify on new major/minor versions.

    Uses the AUR RPC endpoint and persists `prev_version`. Notifies when the
    major.minor tuple increases (e.g. 1.23.x -> 1.24.x or 2.x).
    """

    pkg: str = "antigravity-cli"
    prev_version: str | None = None

    aur_rpc: str = "https://aur.archlinux.org/rpc/?v=5&type=info&arg={}"

    def _major_minor(self, v: str | None) -> tuple[int, int] | None:
        if not v:
            return None
        m = re.search(r"(\d+)\.(\d+)", v)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    def check(self):
        try:
            text = fetch(self.aur_rpc.format(self.pkg)).text()
            data = json.loads(text)
        except Exception:
            return None

        results = data.get("results") or {}
        version = None
        if isinstance(results, dict):
            version = results.get("Version") or results.get("version")
        elif isinstance(results, list) and results:
            first = results[0]
            if isinstance(first, dict):
                version = first.get("Version") or first.get("version")

        if not version:
            return None

        new_mm = self._major_minor(version)
        old_mm = self._major_minor(self.prev_version)

        # Persist the latest seen version
        self.prev_version = version

        # If we have no previous value, just store and don't notify
        if old_mm is None:
            return None

        # Only notify on a larger major/minor tuple
        if new_mm and new_mm > old_mm:
            body = f"AUR package {self.pkg} updated: {version}\nhttps://aur.archlinux.org/packages/{self.pkg}"
            h = str(blob_hash(version))[:8]
            return Notify(title=f"📦 {self.pkg} updated to {version} (hash {h})", body=body)

        return None


def fetch_gemini_models() -> list[str]:
    """Fetch available model IDs from Gemini OpenAI-compatible /models endpoint.

    Returns an empty list if GEMINI_API_KEY is not configured or on request error.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠  GEMINI_API_KEY not set.", file=sys.stderr)
        return []
    try:
        resp = fetch(
            "https://generativelanguage.googleapis.com/v1beta/openai/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = json.loads(resp.text())
        return sorted([m["id"] for m in data.get("data", []) if "id" in m])
    except Exception as exc:
        print(f"⚠️  Failed to fetch Gemini models: {exc}", file=sys.stderr)
        return []


@news.check(every="15m")
class GeminiModelsChecker:
    """Monitor Gemini OpenAI-compatible /models endpoint for newly added models."""

    prev_models: list[str] = []

    def check(self):
        models = fetch_gemini_models()
        print(f"  Fetched {len(models)} models.")
        if not models:
            return None

        # If baseline is empty (e.g. first run), initialize without notifying
        if not self.prev_models:
            self.prev_models = models
            return None

        prev_set = set(self.prev_models)
        new_models = [m for m in models if m not in prev_set]

        notification = None
        if new_models:
            diff_block = "```diff\n" + "\n".join(f"+ {m}" for m in new_models) + "\n```"
            body = (
                f"New Gemini model(s) detected:\n\n{diff_block}\n\n"
                f"Total models available: {len(models)}"
            )
            names = [m.removeprefix("models/") for m in new_models]
            if len(names) <= 3:
                title_names = ", ".join(names)
            else:
                title_names = f"{', '.join(names[:3])} (+{len(names) - 3} more)"

            title = (
                f"New Gemini model: {title_names}"
                if len(names) == 1
                else f"New Gemini models: {title_names}"
            )
            notification = Notify(
                title=title,
                body=body,
            )

        self.prev_models = models
        return notification


def _github_api_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_preprints_tree_sha(repo: str, branch: str, subpath: str) -> str | None:
    """Fetch the Git tree SHA for *subpath* on *branch* in *repo*."""
    try:
        resp = fetch(
            f"https://api.github.com/repos/{repo}/git/trees/{branch}",
            headers=_github_api_headers(),
        )
        data = json.loads(resp.text())
        for entry in data.get("tree", []):
            if entry.get("path") == subpath and entry.get("type") == "tree":
                return entry.get("sha")
        print(f"⚠️  Subpath {subpath!r} not found in {repo}@{branch}.", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"⚠️  Failed to fetch {repo}@{branch} root tree: {exc}", file=sys.stderr)
        return None


def _is_preprint_pdf(path: str, entry_type: str | None) -> bool:
    return entry_type == "blob" and path.lower().endswith(".pdf") and "build" not in path.split("/")


def _fetch_preprints_pdfs(repo: str, tree_sha: str, prev_pdfs: list[str]) -> list[str] | None:
    """List preprint PDF paths under *tree_sha*, falling back to shallow dir trees if truncated."""
    headers = _github_api_headers()
    try:
        resp = fetch(
            f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}?recursive=1",
            headers=headers,
        )
        data = json.loads(resp.text())
        if not data.get("truncated"):
            return sorted(
                entry["path"]
                for entry in data.get("tree", [])
                if _is_preprint_pdf(entry.get("path", ""), entry.get("type"))
            )

        if not prev_pdfs:
            print(
                f"⚠️  Git tree {tree_sha} truncated on empty baseline; skipping.",
                file=sys.stderr,
            )
            return None

        top_resp = fetch(
            f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}",
            headers=headers,
        )
        top_tree = json.loads(top_resp.text()).get("tree", [])

        root_pdfs = [
            e["path"]
            for e in top_tree
            if _is_preprint_pdf(e.get("path", ""), e.get("type"))
        ]
        current_dirs = {
            e["path"]: e["sha"] for e in top_tree if e.get("type") == "tree" and "path" in e and "sha" in e
        }
        known_dirs = {p.split("/")[0] for p in prev_pdfs if "/" in p}
        kept_pdfs = [p for p in prev_pdfs if "/" in p and p.split("/")[0] in current_dirs]

        added_pdfs: list[str] = []
        for dir_name, dir_sha in current_dirs.items():
            if dir_name in known_dirs:
                continue
            dir_resp = fetch(
                f"https://api.github.com/repos/{repo}/git/trees/{dir_sha}",
                headers=headers,
            )
            for child in json.loads(dir_resp.text()).get("tree", []):
                child_path = child.get("path", "")
                if child.get("type") == "blob" and child_path.lower().endswith(".pdf"):
                    added_pdfs.append(f"{dir_name}/{child_path}")

        return sorted(set(kept_pdfs) | set(root_pdfs) | set(added_pdfs))
    except Exception as exc:
        print(f"⚠️  Failed to fetch preprints tree {tree_sha}: {exc}", file=sys.stderr)
        return None


def _format_preprints_title(labels: list[str], max_len: int = 250) -> str:
    """Build a GitHub-safe issue title containing new preprint names."""
    if len(labels) == 1:
        title = f"New OpenAI math preprint: {labels[0]}"
        return title if len(title) <= max_len else title[: max_len - 3] + "..."

    prefix = "New OpenAI math preprints: "
    chosen: list[str] = []
    for idx, label in enumerate(labels[:3]):
        rem = len(labels) - (idx + 1)
        suffix = f" (+{rem} more)" if rem > 0 else ""
        if not chosen:
            avail = max_len - len(prefix) - len(suffix)
            chosen.append(label if len(label) <= avail else label[: max(0, avail - 3)] + "...")
        else:
            candidate = ", ".join([*chosen, label])
            if len(prefix) + len(candidate) + len(suffix) <= max_len:
                chosen.append(label)
            else:
                break

    rem = len(labels) - len(chosen)
    suffix = f" (+{rem} more)" if rem > 0 else ""
    return f"{prefix}{', '.join(chosen)}{suffix}"


@news.check(every="1h")
class OpenAIMathPreprints:
    """Monitor openai/math `preprints/` for newly added PDF files."""

    repo = "openai/math"
    branch = "main"
    subpath = "preprints"

    prev_tree_sha: str | None = None
    prev_pdfs: list[str] = []

    def check(self):
        tree_sha = _fetch_preprints_tree_sha(self.repo, self.branch, self.subpath)
        if not tree_sha:
            return None

        if self.prev_tree_sha == tree_sha and self.prev_pdfs:
            print(f"  Preprints tree unchanged ({len(self.prev_pdfs)} PDFs).")
            return None

        pdfs = _fetch_preprints_pdfs(self.repo, tree_sha, self.prev_pdfs)
        if pdfs is None:
            return None

        print(f"  Fetched {len(pdfs)} preprint PDFs.")

        # Initialize baseline without notifying on first run
        if not self.prev_pdfs:
            self.prev_tree_sha = tree_sha
            self.prev_pdfs = pdfs
            return None

        prev_set = set(self.prev_pdfs)
        new_pdfs = [p for p in pdfs if p not in prev_set]

        self.prev_tree_sha = tree_sha
        self.prev_pdfs = pdfs

        if not new_pdfs:
            return None

        labels = [p.split("/")[0] if "/" in p else p for p in new_pdfs]
        title = _format_preprints_title(labels)

        lines = []
        for p in new_pdfs[:100]:
            url = f"https://github.com/{self.repo}/blob/{self.branch}/{self.subpath}/{quote(p, safe='/')}"
            lines.append(f"- [`{p}`]({url})")
        if len(new_pdfs) > 100:
            lines.append(f"- ... and {len(new_pdfs) - 100} more")

        body = (
            f"New preprint PDF(s) detected:\n\n"
            + "\n".join(lines)
            + f"\n\nTotal preprint PDFs: {len(pdfs)}\n"
            + f"Browse all: https://github.com/{self.repo}/tree/{self.branch}/{self.subpath}"
        )
        return Notify(title=title, body=body)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run registered news checks")
    parser.add_argument(
        "--force",
        action="store_true",
        default=None,
        help="Ignore timer cooldown and run all checks immediately",
    )
    parser.add_argument(
        "--state-file",
        default="state.json",
        help="Path to the state file for persisting check data",
    )
    args = parser.parse_args()

    news.run(state_file=args.state_file, force=args.force)
