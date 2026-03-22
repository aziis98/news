from pydantic import BaseModel

from fetch import Notify, blob_hash, check, fetch, semver


class GnomePackage(BaseModel):
    pkgver: str


@check(every="3h")
def when_gnome_50():
    response = fetch("https://archlinux.org/packages/extra/x86_64/gnome-shell/json/").json()
    pkg = GnomePackage.model_validate(response.__dict__)
    if semver.matches(pkg.pkgver, ">=50"):
        return Notify(
            title=f"🎉 GNOME {pkg.pkgver} has landed in Arch [extra]",
            body=f"Run `sudo pacman -Syu` to upgrade.",
        )


@check(every="15m")
class IstGeomExercises:
    url = "https://people.dm.unipi.it/martelli/didattica/matematica/2026/Esercizi_istituzioni_2026.pdf"

    prev_hash: str | None = None

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
