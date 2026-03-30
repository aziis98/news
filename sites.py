#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "packaging", "pydantic", "beautifulsoup4", "PyMuPDF"]
# ///
"""
sites.py — check definitions and runner

Usage:
    uv run sites.py
"""

from pydantic import BaseModel

from fetch import News, Notify, fetch, pdf_to_text, semver, text_diff

news = News()


class GnomePackage(BaseModel):
    pkgver: str


@news.check(every="3h")
def when_gnome_50():
    response = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
    pkg = GnomePackage.model_validate(response.__dict__)
    if semver.matches(pkg.pkgver, ">=50"):
        return Notify(
            title=f"🎉 GNOME {pkg.pkgver} has landed in Arch [extra]",
            body=f"Run `sudo pacman -Syu` to upgrade.",
        )


@news.check(every="15m")
class IstGeomExercises:
    url = "https://people.dm.unipi.it/martelli/didattica/matematica/2026/Esercizi_istituzioni_2026.pdf"

    prev_text: str | None = None

    def check(self):
        pdf = fetch(self.url).binary()
        text = pdf_to_text(pdf)
        if self.prev_text is not None and text != self.prev_text:
            diff_md = text_diff(self.prev_text, text, context=3)
            self.prev_text = text
            body = f"New version available at {self.url}\n\n{diff_md}"
            return Notify(
                title="📄 Esercizi Istituzioni di Geometria updated",
                body=body,
            )
        self.prev_text = text


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
