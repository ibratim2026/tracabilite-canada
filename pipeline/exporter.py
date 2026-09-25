"""Exporte le site complet en HTML statique dans build/, pour GitHub Pages.

Toutes les pages sont rendues par l'application elle-même, avec le préfixe
/tracabilite-canada/ (adresse d'un site de projet GitHub). La recherche n'a
pas besoin de serveur : elle lit index-recherche.json dans le navigateur.

À la fin, chaque lien interne est vérifié : l'export échoue plutôt que de
publier un lien mort.
"""
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "app"))
from app import app, BASE_DONNEES, index_par_prefixe  # noqa: E402

SORTIE = RACINE / "build"
BASE = "/tracabilite-canada"


def pages():
    con = sqlite3.connect(BASE_DONNEES)
    yield from ["/", "/suivre-l-argent/", "/ecarts/", "/contrats/", "/subventions/", "/lobbying/", "/a-examiner/", "/chercher/", "/ministeres/", "/methode/",
                "/comprendre/", "/comprendre/budget/", "/comprendre/provinces/", "/comprendre/on-clarifie/"]
    from app import SIGNAUX
    for t in SIGNAUX:
        yield f"/a-examiner/{t.lower().replace('_', '-')}/"
    for (org,) in con.execute("SELECT DISTINCT ministere FROM contrats WHERE fournisseur_id IS NOT NULL "
                              "UNION SELECT DISTINCT ministere FROM subventions WHERE debut >= '2017-04-01' "
                              "AND quarantaine IS NULL"):
        yield f"/ministere/{org}/"
    for (slug,) in con.execute("SELECT slug FROM fournisseurs WHERE a_fiche = 1"):
        yield f"/entreprise/{slug}/"
    for (slug,) in con.execute("SELECT slug FROM contrat_page"):
        yield f"/contrat/{slug}/"
    con.close()


def verifier_liens():
    """Chaque lien interne doit pointer vers un fichier exporté."""
    morts = set()
    for fichier in SORTIE.rglob("*.html"):
        for lien in re.findall(r'(?:href|src)="' + BASE + r'(/[^"#?]*)', fichier.read_text()):
            cible = SORTIE / lien.lstrip("/")
            if not (cible.is_file() or (cible / "index.html").is_file()):
                morts.add((lien, fichier.relative_to(SORTIE).as_posix()))
    return morts


def main():
    debut = time.time()
    app.config["BASE"] = BASE
    client = app.test_client()
    shutil.rmtree(SORTIE, ignore_errors=True)
    shutil.copytree(RACINE / "app" / "static", SORTIE / "static")

    n = 0
    for chemin in pages():
        rep = client.get(chemin)
        if rep.status_code != 200:
            raise SystemExit(f"Échec {rep.status_code} : {chemin}")
        cible = SORTIE / chemin.strip("/") / "index.html" if chemin != "/" else SORTIE / "index.html"
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(rep.data)
        n += 1

    (SORTIE / "recherche").mkdir()
    for prefixe in index_par_prefixe():
        (SORTIE / "recherche" / f"{prefixe}.json").write_bytes(client.get(f"/recherche/{prefixe}.json").data)
    (SORTIE / "404.html").write_bytes(client.get("/page-introuvable/").data)
    (SORTIE / ".nojekyll").write_text("")

    morts = verifier_liens()
    if morts:
        for lien, page in sorted(morts)[:20]:
            print(f"Lien mort : {lien} (dans {page})")
        raise SystemExit(f"{len(morts)} liens morts : export annulé.")

    taille = sum(f.stat().st_size for f in SORTIE.rglob("*") if f.is_file()) / 1e6
    print(f"Exporté : {n} pages, {taille:.0f} Mo, en {time.time() - debut:.0f} s -> {SORTIE}")


if __name__ == "__main__":
    main()
