"""Exporte la page en HTML statique dans build/, pour GitHub Pages.

Les chemins deviennent relatifs (static/…) : le site vit sous le préfixe
/tracabilite-canada/ et un chemin absolu /static/… casserait tout.
"""
import shutil, sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "app"))
from app import app  # noqa: E402

SORTIE = RACINE / "build"


def main():
    shutil.rmtree(SORTIE, ignore_errors=True)
    shutil.copytree(RACINE / "app" / "static", SORTIE / "static")
    html = app.test_client().get("/").get_data(as_text=True)
    html = html.replace('"/static/', '"static/').replace('href="/"', 'href="./"')
    (SORTIE / "index.html").write_text(html)
    (SORTIE / ".nojekyll").write_text("")
    print(f"Exporté : {SORTIE}")


if __name__ == "__main__":
    main()
