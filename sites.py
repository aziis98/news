from fetch import check, Notify, fetch, semver, blob_hash


@check(every="3h")
def when_gnome_50():
    pkg = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
    if semver.matches(pkg.pkgver, ">=50"):
        return Notify(
            title=f"🎉 GNOME {pkg.pkgver} has landed in Arch [extra]",
            body=f"Run `sudo pacman -Syu` to upgrade.",
        )


@check(every="15m")
class IstGeomExercises:
    url = "https://people.dm.unipi.it/martelli/didattica/matematica/2026/Esercizi_istituzioni_2026.pdf"

    prev_hash: str = None

    def check(self):
        pdf = fetch(self.url).binary()
        h = blob_hash(pdf)
        if self.prev_hash is not None and h != self.prev_hash:
            self.prev_hash = h
            return Notify(
                title="📄 Esercizi Istituzioni di Geometria updated",
                body=f"New version available at {self.url}",
            )
        self.prev_hash = h
