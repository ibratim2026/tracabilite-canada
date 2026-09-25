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
    ("/subventions/", "Ce qu'Ottawa donne"),
    ("/chercher/", "Chercher"),
    ("/ministeres/", "Ministères"),
    ("/methode/", "Méthode"),
]

METHODES = {
    "TC": "Concurrentielle", "OB": "Appel d'offres ouvert", "ST": "Appel d'offres sélectif",
    "AC": "Préavis d'adjudication", "TN": "Sans appel d'offres",
}
TYPES_BENEF = {
    "F": "Entreprise", "N": "Organisme sans but lucratif", "S": "Université ou institution publique",
    "G": "Gouvernement", "A": "Bénéficiaire autochtone", "I": "Organisation internationale",
    "P": "Particulier", "O": "Autre", "": "Non précisé", "LOT": "Paiements regroupés",
}
ENTENTES = {"G": "Subvention", "C": "Contribution", "O": "Autre transfert"}


@app.context_processor
def contexte():
    return dict(base=app.config["BASE"], version_statique=version_statique(), navigation=NAVIGATION,
                methodes=METHODES, types_benef=TYPES_BENEF, ententes=ENTENTES,
                donnees_du=charger("chiffres")["genere_le"], seuil_fiche=SEUIL_FICHE,
                periode_debut=PERIODE_DEBUT)


def version_statique():
    """Change dès qu'on modifie le CSS ou le JS : les navigateurs ne gardent pas l'ancien."""
    return int(max((RACINE / "static" / f).stat().st_mtime for f in ("style.css", "page.js")))


def lien_officiel(org, reference):
    return f"https://rechercher.ouvert.canada.ca/contrats/record/{org},{reference}"


def lien_officiel_subvention(org, reference):
    return f"https://rechercher.ouvert.canada.ca/subventions/record/{org},{reference},current"


app.jinja_env.globals.update(lien_officiel=lien_officiel, lien_officiel_subvention=lien_officiel_subvention)

PERIODE = f"date_contrat BETWEEN '{PERIODE_DEBUT}' AND date('now') AND quarantaine IS NULL"
PERIODE_SUB = f"debut BETWEEN '{PERIODE_DEBUT}' AND date('now') AND quarantaine IS NULL"
# Exercice financier fédéral (avril à mars) d'une date.
exercice_sql = lambda col: f"CAST(substr({col},1,4) AS INT) - (substr({col},6,2) < '04')"


@lru_cache(maxsize=1)
def reperes():
    """Moyennes fédérales, pour situer chaque fiche par rapport à l'ensemble."""
    con = sqlite3.connect(f"file:{BASE_DONNEES}?mode=ro", uri=True)
    nb, total, nb_tn, val_tn = con.execute(
        f"SELECT COUNT(*), SUM(valeur), SUM(methode='TN'), SUM(CASE WHEN methode='TN' THEN valeur END) "
        f"FROM contrats WHERE {PERIODE}").fetchone()
    nb_sub, total_sub = con.execute(f"SELECT COUNT(*), SUM(valeur) FROM subventions WHERE {PERIODE_SUB}").fetchone()
    nb_fourn = con.execute("SELECT COUNT(*) FROM fournisseurs").fetchone()[0]
    con.close()
    return dict(nb=nb, total=total, part_tn_nb=nb_tn / nb, part_tn_valeur=val_tn / total,
                nb_fournisseurs=nb_fourn, nb_sub=nb_sub, total_sub=total_sub)


def par_exercice(where, params, table="contrats"):
    col, periode = ("date_contrat", PERIODE) if table == "contrats" else ("debut", PERIODE_SUB)
    lignes = bd().execute(
        f"SELECT {exercice_sql(col)} a, SUM(valeur) v, COUNT(*) n FROM {table} WHERE {periode} AND {where} "
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
# Les particuliers ne sont jamais nommés : leur nom est remplacé à la source.
SUB_COLONNES = ("s.debut, s.fin, s.programme, s.titre, s.valeur, s.valeur_max, s.type_entente, s.type_benef, "
                "s.ministere, s.ministere_nom, s.reference, s.ville, s.province, "
                "CASE WHEN s.type_benef IN ('P','LOT') THEN NULL ELSE f.nom END beneficiaire, f.slug, f.a_fiche")


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


@app.route("/subventions/")
def subventions():
    s = charger("subventions")
    s["part_contributions"] = next(e["valeur"] for e in s["ententes"] if e["code"] == "C") / s["total"]
    s["ratio_contrats"] = s["total"] / charger("chiffres")["total"]
    a = {x["exercice"]: x["valeur"] for x in s["par_annee"]}
    s["pic"] = max(s["par_annee"], key=lambda x: x["valeur"])
    return render_template("subventions.html", s=s, pop=charger("population"), page="/subventions/")


@app.route("/chercher/")
def chercher():
    return render_template("chercher.html", r=reperes(), page="/chercher/")


def plier(texte):
    """Même pliage que la recherche du navigateur : sans accents, majuscules, mots."""
    import re, unicodedata
    t = unicodedata.normalize("NFD", texte).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", t).split()


# Mots trop communs pour servir de clé de recherche (formes juridiques, articles).
MOTS_VIDES = {"INC", "LTD", "LTEE", "LIMITED", "CORP", "CORPORATION", "CO", "THE", "OF", "AND", "DE", "DU",
              "DES", "LA", "LE", "LES", "ET", "EN", "LP", "LLP", "ULC", "SA", "INCORPORATED", "COMPANY"}


@lru_cache(maxsize=1)
def index_par_prefixe():
    """Index découpé par les deux premières lettres de chaque mot du nom.

    300 000 noms en un seul fichier, ce serait 13 Mo à charger. Découpé, la
    recherche ne charge que le morceau utile (quelques dizaines de Ko).
    """
    con = sqlite3.connect(f"file:{BASE_DONNEES}?mode=ro", uri=True)
    morceaux = {}
    for nom, total, nb, slug, a_fiche, typ in con.execute(
            "SELECT nom, total, nb, slug, a_fiche, type_benef FROM fournisseurs ORDER BY total DESC"):
        entree = [nom, round(total), nb, slug if a_fiche else 0, typ]
        for prefixe in {mot[:2] for mot in plier(nom) if len(mot) >= 2 and mot not in MOTS_VIDES}:
            morceaux.setdefault(prefixe, []).append(entree)
    con.close()
    return morceaux


@app.route("/recherche/<prefixe>.json")
def index_recherche(prefixe):
    donnees = index_par_prefixe().get(prefixe, [])
    return Response(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), mimetype="application/json")


@app.route("/entreprise/<slug>/")
def entreprise(slug):
    f = bd().execute("SELECT * FROM fournisseurs WHERE slug = ?", (slug,)).fetchone()
    if not f:
        abort(404)
    ou, p = "fournisseur_id = ?", (f["id"],)
    contrats = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id "
        f"WHERE {PERIODE} AND c.{ou} ORDER BY c.valeur DESC LIMIT 30", p).fetchall()
    ministeres = bd().execute(
        f"SELECT ministere, ministere_nom, SUM(v) v, SUM(n) n FROM ("
        f"SELECT ministere, ministere_nom, valeur v, 1 n FROM contrats WHERE {PERIODE} AND {ou} UNION ALL "
        f"SELECT ministere, ministere_nom, valeur v, 1 n FROM subventions WHERE {PERIODE_SUB} "
        f"AND beneficiaire_id = ?) GROUP BY ministere ORDER BY v DESC", p + p).fetchall()
    bornes = bd().execute(f"SELECT MIN(d), MAX(d), MAX(fin) FROM (SELECT date_contrat d, fin FROM contrats "
                          f"WHERE {PERIODE} AND {ou} UNION ALL SELECT debut d, fin FROM subventions "
                          f"WHERE {PERIODE_SUB} AND beneficiaire_id = ?)", p + p).fetchone()
    subs = bd().execute(
        f"SELECT {SUB_COLONNES} FROM subventions s JOIN fournisseurs f ON f.id = s.beneficiaire_id "
        f"WHERE s.debut BETWEEN '{PERIODE_DEBUT}' AND date('now') AND s.quarantaine IS NULL "
        f"AND s.beneficiaire_id = ? ORDER BY s.valeur DESC LIMIT 30", p).fetchall()
    programmes = bd().execute(
        f"SELECT programme, ministere_nom, SUM(valeur) v, COUNT(*) n FROM subventions WHERE {PERIODE_SUB} "
        f"AND beneficiaire_id = ? GROUP BY programme ORDER BY v DESC LIMIT 8", p).fetchall()
    return render_template(
        "entreprise.html", f=f, variantes=json.loads(f["variantes"]), contrats=contrats, subs=subs,
        programmes=programmes, ministeres=ministeres, annees=par_exercice(ou, p),
        annees_sub=par_exercice("beneficiaire_id = ?", p, "subventions"),
        m=methodes_de(ou, p) if f["nb_contrats"] else None, r=reperes(),
        premier=bornes[0], dernier=bornes[1], fin_max=bornes[2], population=POPULATION, page="")


@app.route("/ministeres/")
def ministeres():
    liste = bd().execute(
        f"SELECT ministere, MAX(ministere_nom) ministere_nom, SUM(vc) vc, SUM(vs) vs, SUM(vc) + SUM(vs) v FROM ("
        f"SELECT ministere, ministere_nom, valeur vc, 0 vs FROM contrats WHERE {PERIODE} UNION ALL "
        f"SELECT ministere, ministere_nom, 0, valeur FROM subventions WHERE {PERIODE_SUB}) "
        f"GROUP BY ministere ORDER BY v DESC").fetchall()
    return render_template("ministeres.html", liste=liste, r=reperes(), page="/ministeres/")


@app.route("/ministere/<org>/")
def ministere(org):
    ou, p = "ministere = ?", (org,)
    tete = bd().execute(f"SELECT MAX(ministere_nom) ministere_nom, SUM(valeur) v, COUNT(*) n FROM contrats "
                        f"WHERE {PERIODE} AND {ou}", p).fetchone()
    tete_sub = bd().execute(f"SELECT MAX(ministere_nom) ministere_nom, SUM(valeur) v, COUNT(*) n FROM subventions "
                            f"WHERE {PERIODE_SUB} AND {ou}", p).fetchone()
    if not tete["n"] and not tete_sub["n"]:
        abort(404)
    nom = tete["ministere_nom"] or tete_sub["ministere_nom"]
    rang = bd().execute(
        f"SELECT COUNT(*) + 1 FROM (SELECT SUM(valeur) v FROM contrats WHERE {PERIODE} "
        f"GROUP BY ministere HAVING v > ?)", (tete["v"] or 0,)).fetchone()[0]
    fournisseurs = bd().execute(
        f"SELECT f.nom, f.slug, f.a_fiche, SUM(c.valeur) v, COUNT(*) n FROM contrats c "
        f"JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE {PERIODE} AND c.{ou} "
        f"GROUP BY f.id ORDER BY v DESC LIMIT 20", p).fetchall()
    categories = bd().execute(
        f"SELECT description, SUM(valeur) v, COUNT(*) n FROM contrats WHERE {PERIODE} AND {ou} "
        f"AND description <> '' GROUP BY description ORDER BY v DESC LIMIT 10", p).fetchall()
    contrats = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id "
        f"WHERE {PERIODE} AND c.{ou} ORDER BY c.valeur DESC LIMIT 30", p).fetchall()
    programmes = bd().execute(
        f"SELECT programme, SUM(valeur) v, COUNT(*) n FROM subventions WHERE {PERIODE_SUB} AND {ou} "
        f"GROUP BY programme ORDER BY v DESC LIMIT 10", p).fetchall()
    # Bénéficiaires : les particuliers et paiements regroupés sont additionnés sans nom.
    beneficiaires = bd().execute(
        f"SELECT CASE WHEN s.type_benef IN ('P','LOT') THEN 'Particuliers (non nommés)' ELSE f.nom END nom, "
        f"CASE WHEN s.type_benef IN ('P','LOT') THEN NULL ELSE f.slug END slug, "
        f"CASE WHEN s.type_benef IN ('P','LOT') THEN 0 ELSE f.a_fiche END a_fiche, SUM(s.valeur) v, COUNT(*) n "
        f"FROM subventions s LEFT JOIN fournisseurs f ON f.id = s.beneficiaire_id "
        f"WHERE s.debut BETWEEN '{PERIODE_DEBUT}' AND date('now') AND s.quarantaine IS NULL AND s.{ou} "
        f"GROUP BY CASE WHEN s.type_benef IN ('P','LOT') THEN -1 ELSE s.beneficiaire_id END "
        f"ORDER BY v DESC LIMIT 15", p).fetchall()
    part_top = sum(x["v"] for x in fournisseurs) / tete["v"] if tete["v"] else 0
    return render_template(
        "ministere.html", org=org, nom=nom, tete=tete, tete_sub=tete_sub, rang=rang, fournisseurs=fournisseurs,
        categories=categories, contrats=contrats, programmes=programmes, beneficiaires=beneficiaires,
        annees=par_exercice(ou, p), annees_sub=par_exercice(ou, p, "subventions"),
        m=methodes_de(ou, p) if tete["n"] else None, r=reperes(), part_top=part_top,
        population=POPULATION, page="/ministeres/")


@app.route("/methode/")
def methode():
    return render_template("methode.html", c=charger("chiffres"), s=charger("subventions"), r=reperes(),
                           page="/methode/")


@app.errorhandler(404)
def introuvable(_):
    return render_template("introuvable.html", page=""), 404


if __name__ == "__main__":
    app.run(port=5072, debug=True)
