"""Traçabilité Canada — l'application.

Sert les pages en local (port 5072). Pour GitHub Pages, pipeline/exporter.py
rend chaque page en HTML fixe : aucune page ne doit donc dépendre d'une
requête au serveur. La recherche tourne dans le navigateur, sur un index JSON.
"""
import json
import sqlite3
from datetime import date
from functools import lru_cache
from pathlib import Path
from flask import Flask, abort, g, render_template, Response

RACINE = Path(__file__).resolve().parent
BASE_DONNEES = RACINE.parent / "data" / "canada.db"
PERIODE_DEBUT = "2017-04-01"
SEUIL_FICHE = 1_000_000
POPULATION = 41_798_407   # Statistique Canada, 17-10-0009-01, 1er juillet 2026

app = Flask(__name__)
app.config["BASE"] = ""   # « /tracabilite-canada » à l'export
# Moins d'espaces vides dans le HTML : 8 000 fiches, ça compte.
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True


def charger(nom):
    return json.loads((RACINE / "contenu" / f"{nom}.json").read_text())


def bd():
    if "bd" not in g:
        g.bd = sqlite3.connect(f"file:{BASE_DONNEES}?mode=ro", uri=True)
        g.bd.row_factory = sqlite3.Row
    return g.bd


@app.teardown_appcontext
def fermer(_):
    if "bd" in g:
        g.bd.close()


# ---- Formats à la québécoise : espace insécable pour les milliers, virgule décimale.
def nombre(v, decimales=0):
    s = f"{v:,.{decimales}f}"
    return s.replace(",", " ").replace(".", ",")


def argent(v):
    """18 296 996 058 -> « 18,3 G$ » ; 24 966 -> « 24 966 $ »."""
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"{nombre(v / 1e9, 1)} G$"
    if abs(v) >= 1e6:
        return f"{nombre(v / 1e6, 0 if abs(v) >= 1e8 else 1)} M$"
    return f"{nombre(v)} $"


def pourcent(v):
    return f"{nombre(v * 100)} %"


MOIS = "janv. févr. mars avr. mai juin juill. août sept. oct. nov. déc.".split()


def date_fr(s):
    try:
        d = date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return "—"
    jour = "1er" if d.day == 1 else d.day
    return f"{jour} {MOIS[d.month - 1]} {d.year}"


app.jinja_env.filters.update(nombre=nombre, argent=argent, pourcent=pourcent, date_fr=date_fr)

NAVIGATION = [
    ("/", "Ce qu'Ottawa achète"),
    ("/chercher/", "Chercher"),
    ("/ministeres/", "Ministères"),
    ("/methode/", "Méthode"),
]

METHODES = {
    "TC": "Concurrentielle", "OB": "Appel d'offres ouvert", "ST": "Appel d'offres sélectif",
    "AC": "Préavis d'adjudication", "TN": "Sans appel d'offres",
}


@app.context_processor
def contexte():
    return dict(base=app.config["BASE"], version_statique=version_statique(), navigation=NAVIGATION, methodes=METHODES,
                donnees_du=charger("chiffres")["genere_le"], seuil_fiche=SEUIL_FICHE,
                periode_debut=PERIODE_DEBUT)


def version_statique():
    """Change dès qu'on modifie le CSS ou le JS : les navigateurs ne gardent pas l'ancien."""
    return int(max((RACINE / "static" / f).stat().st_mtime for f in ("style.css", "page.js")))


def lien_officiel(org, reference):
    return f"https://rechercher.ouvert.canada.ca/contrats/record/{org},{reference}"


app.jinja_env.globals["lien_officiel"] = lien_officiel

PERIODE = f"date_contrat BETWEEN '{PERIODE_DEBUT}' AND date('now') AND quarantaine IS NULL"
# Exercice financier fédéral (avril à mars) d'une date de contrat.
EXERCICE_SQL = "CAST(substr(date_contrat,1,4) AS INT) - (substr(date_contrat,6,2) < '04')"


@lru_cache(maxsize=1)
def reperes():
    """Moyennes fédérales, pour situer chaque fiche par rapport à l'ensemble."""
    con = sqlite3.connect(f"file:{BASE_DONNEES}?mode=ro", uri=True)
    nb, total, nb_tn, val_tn = con.execute(
        f"SELECT COUNT(*), SUM(valeur), SUM(methode='TN'), SUM(CASE WHEN methode='TN' THEN valeur END) "
        f"FROM contrats WHERE {PERIODE}").fetchone()
    nb_fourn = con.execute("SELECT COUNT(*) FROM fournisseurs").fetchone()[0]
    con.close()
    return dict(nb=nb, total=total, part_tn_nb=nb_tn / nb, part_tn_valeur=val_tn / total,
                nb_fournisseurs=nb_fourn)


def par_exercice(where, params):
    lignes = bd().execute(
        f"SELECT {EXERCICE_SQL} a, SUM(valeur) v, COUNT(*) n FROM contrats WHERE {PERIODE} AND {where} "
        f"GROUP BY a ORDER BY a", params).fetchall()
    trouve = {r["a"]: r for r in lignes}
    fin = date.today().year - (date.today().month < 4)
    return [dict(exercice=f"{a}-{str(a + 1)[2:]}", valeur=trouve[a]["v"] if a in trouve else 0,
                 nb=trouve[a]["n"] if a in trouve else 0, en_cours=(a == fin)) for a in range(2017, fin + 1)]


def methodes_de(where, params):
    r = bd().execute(
        f"SELECT COUNT(*) n, SUM(valeur) v, SUM(methode='TN') n_tn, "
        f"SUM(CASE WHEN methode='TN' THEN valeur ELSE 0 END) v_tn, "
        f"SUM(CASE WHEN valeur_originale > 0 AND valeur > valeur_originale * 1.001 "
        f"THEN valeur - valeur_originale ELSE 0 END) croissance, "
        f"SUM(valeur_originale > 0 AND valeur > valeur_originale * 1.001) n_modifies "
        f"FROM contrats WHERE {PERIODE} AND {where}", params).fetchone()
    return dict(r) | dict(part_tn_nb=r["n_tn"] / r["n"] if r["n"] else 0,
                          part_tn_valeur=r["v_tn"] / r["v"] if r["v"] else 0)


CONTRAT_COLONNES = ("c.date_contrat, c.description, c.valeur, c.valeur_originale, c.methode, c.fin, "
                    "c.ministere, c.ministere_nom, c.reference, f.nom fournisseur, f.slug, f.a_fiche")


# ---------------------------------------------------------------------------
@app.route("/")
def accueil():
    c = charger("chiffres")
    c["moyenne"] = c["total"] / c["nb"]
    c["par_jour"] = c["total"] / c["jours_ouvrables"]
    c["contrats_par_jour"] = c["nb"] / c["jours_ouvrables"]
    sans = next(m for m in c["methodes"] if m["code"] == "TN")
    c["sans_appel"] = dict(sans, part_nb=sans["nb"] / c["nb"], part_valeur=sans["valeur"] / c["total"])
    c["defense_part"] = c["ministeres"][0]["valeur"] / c["total"]
    n24 = c["naif"]["2024-2025"]
    c["geants_total"] = sum(g["valeur"] for g in c["geants_2024"])
    c["geants_part"] = c["geants_total"] / n24["somme_contrats"]
    c["annees_en_secondes"] = c["total"] / 31_557_600       # une année moyenne, en secondes
    c["annee_depart"] = 2026 - round(c["annees_en_secondes"])
    c["budget"]["par_seconde"] = c["budget"]["charges"] / (365 * 24 * 3600)
    return render_template("accueil.html", c=c, page="/")


@app.route("/chercher/")
def chercher():
    return render_template("chercher.html", r=reperes(), page="/chercher/")


@app.route("/index-recherche.json")
def index_recherche():
    """Toutes les entreprises, en format compact : [nom, total, nb, slug si fiche]."""
    lignes = bd().execute("SELECT nom, total, nb, slug, a_fiche FROM fournisseurs ORDER BY total DESC")
    donnees = [[r["nom"], round(r["total"]), r["nb"], r["slug"] if r["a_fiche"] else 0] for r in lignes]
    return Response(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")),
                    mimetype="application/json")


@app.route("/entreprise/<slug>/")
def entreprise(slug):
    f = bd().execute("SELECT * FROM fournisseurs WHERE slug = ?", (slug,)).fetchone()
    if not f:
        abort(404)
    ou, p = "fournisseur_id = ?", (f["id"],)
    contrats = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id "
        f"WHERE {PERIODE} AND c.{ou} ORDER BY c.valeur DESC LIMIT 100", p).fetchall()
    ministeres = bd().execute(
        f"SELECT ministere, ministere_nom, SUM(valeur) v, COUNT(*) n FROM contrats WHERE {PERIODE} "
        f"AND {ou} GROUP BY ministere ORDER BY v DESC", p).fetchall()
    bornes = bd().execute(f"SELECT MIN(date_contrat), MAX(date_contrat), MAX(fin) FROM contrats "
                          f"WHERE {PERIODE} AND {ou}", p).fetchone()
    return render_template(
        "entreprise.html", f=f, variantes=json.loads(f["variantes"]), contrats=contrats,
        ministeres=ministeres, annees=par_exercice(ou, p), m=methodes_de(ou, p), r=reperes(),
        premier=bornes[0], dernier=bornes[1], fin_max=bornes[2], population=POPULATION, page="")


@app.route("/ministeres/")
def ministeres():
    liste = bd().execute(
        f"SELECT ministere, ministere_nom, SUM(valeur) v, COUNT(*) n FROM contrats WHERE {PERIODE} "
        f"GROUP BY ministere ORDER BY v DESC").fetchall()
    return render_template("ministeres.html", liste=liste, r=reperes(), page="/ministeres/")


@app.route("/ministere/<org>/")
def ministere(org):
    ou, p = "ministere = ?", (org,)
    tete = bd().execute(f"SELECT ministere_nom, SUM(valeur) v, COUNT(*) n FROM contrats "
                        f"WHERE {PERIODE} AND {ou}", p).fetchone()
    if not tete["n"]:
        abort(404)
    rang = bd().execute(
        f"SELECT COUNT(*) + 1 FROM (SELECT SUM(valeur) v FROM contrats WHERE {PERIODE} "
        f"GROUP BY ministere HAVING v > ?)", (tete["v"],)).fetchone()[0]
    fournisseurs = bd().execute(
        f"SELECT f.nom, f.slug, f.a_fiche, SUM(c.valeur) v, COUNT(*) n FROM contrats c "
        f"JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE {PERIODE} AND c.{ou} "
        f"GROUP BY f.id ORDER BY v DESC LIMIT 20", p).fetchall()
    categories = bd().execute(
        f"SELECT description, SUM(valeur) v, COUNT(*) n FROM contrats WHERE {PERIODE} AND {ou} "
        f"AND description <> '' GROUP BY description ORDER BY v DESC LIMIT 10", p).fetchall()
    contrats = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id "
        f"WHERE {PERIODE} AND c.{ou} ORDER BY c.valeur DESC LIMIT 50", p).fetchall()
    # Part des 20 premiers fournisseurs : ce ministère dépend-il de quelques entreprises ?
    part_top = sum(x["v"] for x in fournisseurs) / tete["v"]
    return render_template(
        "ministere.html", org=org, tete=tete, rang=rang, fournisseurs=fournisseurs,
        categories=categories, contrats=contrats, annees=par_exercice(ou, p), m=methodes_de(ou, p),
        r=reperes(), part_top=part_top, population=POPULATION, page="/ministeres/")


@app.route("/methode/")
def methode():
    return render_template("methode.html", c=charger("chiffres"), r=reperes(), page="/methode/")


@app.errorhandler(404)
def introuvable(_):
    return render_template("introuvable.html", page=""), 404


if __name__ == "__main__":
    app.run(port=5072, debug=True)
