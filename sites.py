"""
sites.py — check definitions and runner

Usage:
    uv run sites.py
"""

import json
import re
from datetime import datetime
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


@news.check(every="6h")
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
