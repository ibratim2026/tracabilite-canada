"""La trace de chaque contrat : signé à tant, modifié tel jour, rendu à tant.

Pour les contrats qui ont une fiche (5 M$ ou plus, écart de plus de 50 % à
partir de 250 000 $, ou ★ à examiner), on garde toutes les versions déclarées
au fil des trimestres, dans l'ordre. C'est ce qui permet de « suivre
l'argent » d'un contrat, et pas seulement de voir son total.

Écart = valeur actuelle comparée au montant signé. Gravité, comme sur le site
québécois : +10 % (1), +25 % (2), +50 % (3). Au-delà de 20 fois, c'est un
« saut à vérifier » (options prévues ou erreur de saisie), pas un écart.
"""
import hashlib
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))
from analyser import cle_periode  # noqa: E402

BASE = RACINE / "data" / "canada.db"
PERIODE = "date_contrat BETWEEN '2017-04-01' AND date('now') AND quarantaine IS NULL"


def slug(texte):
    s = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60] or "contrat"


def main():
    con = sqlite3.connect(BASE)
    choisis = {cle for (cle,) in con.execute(
        # Seuils choisis pour garder le site sous la limite de GitHub Pages (1 Go) :
        # à 1 M$ et +25 %, 31 000 fiches portaient le site à 770 Mo.
        f"SELECT cle FROM contrats WHERE {PERIODE} AND (valeur >= 5e6 "
        f"OR (valeur_originale >= 250000 AND valeur > valeur_originale * 1.5) "
        f"OR cle IN (SELECT cle FROM signaux_contrat WHERE nb >= 3))")}

    # Adresse stable : ministère + numéro d'achat.
    con.execute("DROP TABLE IF EXISTS contrat_page")
    con.execute("CREATE TABLE contrat_page (cle TEXT PRIMARY KEY, slug TEXT UNIQUE)")
    pris, pages = set(), []
    for cle in sorted(choisis):
        org, num = cle.split("|", 1)
        s = f"{org}/{slug(num)}"
        if s in pris:
            s = f"{s}-{hashlib.md5(cle.encode()).hexdigest()[:5]}"
        pris.add(s)
        pages.append((cle, s))
    con.executemany("INSERT INTO contrat_page VALUES (?,?)", pages)

    # Toutes les versions déclarées de ces contrats.
    versions = defaultdict(list)
    coquilles = {r for (r,) in con.execute("SELECT rowid_brut FROM coquilles")}
    for rowid, org, pid, ref, periode, dt, val, orig, modif, typ, com in con.execute(
            "SELECT rowid, owner_org, procurement_id, reference_number, reporting_period, contract_date, "
            "valeur, valeur_originale, valeur_modif, instrument_type, comments_fr FROM brut "
            "WHERE instrument_type <> 'SOSA'"):
        cle = f"{org}|{pid.strip() or ref.strip()}"
        if cle in choisis:
            versions[cle].append((cle_periode(periode), rowid, periode, (dt or "")[:10], val, orig, modif, typ,
                                  (com or "").strip()[:400], int(rowid in coquilles)))
    con.execute("DROP TABLE IF EXISTS versions")
    con.execute("""CREATE TABLE versions (cle TEXT, ordre INTEGER, periode TEXT, date TEXT, valeur REAL,
                   valeur_originale REAL, modif REAL, type TEXT, commentaire TEXT, ecartee INTEGER)""")
    lignes = []
    for cle, vs in versions.items():
        for i, v in enumerate(sorted(vs)):
            lignes.append((cle, i) + v[2:])
    con.executemany("INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?)", lignes)
    con.execute("CREATE INDEX i_versions ON versions(cle, ordre)")
    con.commit()
    print(f"{len(pages)} fiches de contrats, {len(lignes)} versions.")
    con.close()


if __name__ == "__main__":
    main()
