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
    dict(nom="Suivre l'argent", url="/suivre-l-argent/", sous=[
        ("/suivre-l-argent/", "Où va l'argent"), ("/contrats/", "Contrats"), ("/subventions/", "Subventions"),
        ("/lobbying/", "Lobbying"), ("/ecarts/", "Les écarts"), ("/a-examiner/", "À examiner"),
        ("/ministeres/", "Ministères")]),
    dict(nom="Comprendre", url="/comprendre/", sous=[
        ("/comprendre/", "Vue d'ensemble"), ("/comprendre/budget/", "Le budget en une page"),
        ("/comprendre/provinces/", "Ottawa et les provinces"), ("/comprendre/on-clarifie/", "On clarifie")]),
    dict(nom="Chercher", url="/chercher/", sous=[]),
    dict(nom="Méthode", url="/methode/", sous=[]),
]


def rubrique_de(page):
    """La rubrique active : celle dont un sous-onglet (ou l'adresse) correspond à la page."""
    if not page:
        return NAVIGATION[0]
    for r in NAVIGATION:
        if page == r["url"] or any(page == u for u, _ in r["sous"]):
            return r
    return NAVIGATION[0] if page.startswith(("/contrat/", "/ministere/", "/a-examiner/", "/entreprise/")) else None


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
                rubrique_de=rubrique_de, ecart=ecart,
                methodes=METHODES, signaux_def=SIGNAUX, types_benef=TYPES_BENEF, ententes=ENTENTES,
                donnees_du=charger("chiffres")["genere_le"], seuil_fiche=SEUIL_FICHE,
                periode_debut=PERIODE_DEBUT)


def version_statique():
    """Change dès qu'on modifie le CSS ou le JS : les navigateurs ne gardent pas l'ancien."""
    return int(max((RACINE / "static" / f).stat().st_mtime for f in ("style.css", "page.js")))


def ecart(valeur, originale):
    """Écart entre la valeur actuelle et le montant signé, avec sa gravité.

    Gravité comme sur le site québécois : +10 % (1), +25 % (2), +50 % (3).
    Contrats signés à 25 000 $ ou plus. Au-delà de 20 fois : « saut à vérifier ».
    """
    if not valeur or not originale or originale < 25000 or valeur <= originale * 1.10:
        return None
    ratio = valeur / originale
    if ratio > 20:
        return dict(saut=True, gravite=0, pct=None, dollars=valeur - originale, ratio=ratio)
    return dict(saut=False, gravite=3 if ratio > 1.5 else 2 if ratio > 1.25 else 1,
                pct=(ratio - 1) * 100, dollars=valeur - originale, ratio=ratio)


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
                    "c.ministere, c.ministere_nom, c.reference, f.nom fournisseur, f.slug, f.a_fiche, "
                    "(SELECT types FROM signaux_contrat sc WHERE sc.cle = c.cle) signaux, "
                    "(SELECT slug FROM contrat_page cp WHERE cp.cle = c.cle) page_contrat")

# Les signaux : nom court, explication, et ce qui peut l'expliquer sans faute de personne.
SIGNAUX = {
    "CROISSANCE": dict(nom="A grossi après signature", court="Grossi",
        regle="Le contrat vaut aujourd'hui au moins 25 % de plus que le montant signé (contrats signés à 25 000 $ ou plus).",
        normal="Phase supplémentaire prévue, délai prolongé, hausse des coûts d'un projet de plusieurs années."),
    "SAUT": dict(nom="Saut à vérifier", court="Saut",
        regle="La valeur actuelle dépasse 20 fois le montant signé (et au moins 1 M$).",
        normal="Des options prévues dès le départ, déclarées comme modifications. Parfois, une erreur de saisie."),
    "SANS_APPEL": dict(nom="Sans appel d'offres", court="Sans appel",
        regle="Contrat de 100 000 $ ou plus attribué sans appel d'offres. La raison déclarée est affichée.",
        normal="Un seul fournisseur possible (logiciel, pièces d'origine), urgence réelle, sécurité nationale."),
    "SOUM_UNIQUE": dict(nom="Un seul soumissionnaire", court="1 offre",
        regle="Appel d'offres concurrentiel de 100 000 $ ou plus auquel une seule entreprise a répondu.",
        normal="Marché très spécialisé, exigences que peu d'entreprises peuvent remplir, délai court."),
    "MODIFS_SERIE": dict(nom="Modifications en série", court="Modifié",
        regle="Trois modifications déclarées ou plus sur le même contrat.",
        normal="Contrat de longue durée renouvelé chaque année, ajustements administratifs."),
    "PETITS_REPETES": dict(nom="Petits contrats répétés", court="Répétés",
        regle="Au moins cinq contrats sans appel d'offres de moins de 25 000 $ chacun, même ministère, même fournisseur, même année, pour 100 000 $ ou plus.",
        normal="Achats courants auprès d'un fournisseur habituel (fournitures, abonnements, pièces)."),
}
# Les particuliers ne sont jamais nommés : leur nom est remplacé à la source.
SUB_COLONNES = ("s.debut, s.fin, s.programme, s.titre, s.valeur, s.valeur_max, s.type_entente, s.type_benef, "
                "s.ministere, s.ministere_nom, s.reference, s.ville, s.province, "
                "CASE WHEN s.type_benef IN ('P','LOT') THEN NULL ELSE f.nom END beneficiaire, f.slug, f.a_fiche")


# ---------------------------------------------------------------------------
@app.route("/")
def accueil():
    c, s, b = charger("chiffres"), charger("subventions"), charger("budget")
    l = charger("lobby") if (RACINE / "contenu" / "lobby.json").exists() else None
    nb_prio = bd().execute("SELECT COUNT(*) FROM signaux_contrat WHERE nb >= 3").fetchone()[0]
    entreprises = next(x for x in s["beneficiaires"] if x["code"] == "F")
    ecarts_total = bd().execute(
        f"SELECT SUM(valeur - valeur_originale) FROM contrats WHERE {PERIODE} AND valeur_originale >= 25000 "
        f"AND valeur > valeur_originale * 1.10 AND valeur <= valeur_originale * 20").fetchone()[0]
    return render_template(
        "accueil.html", c=c, s=s, b=b, l=l, r=reperes(), nb_prio=nb_prio, ecarts_total=ecarts_total,
        par_seconde=b["charges"] / (365 * 24 * 3600), part_entreprises=entreprises["valeur"] / s["total"],
        lignes=c["nettoyage"]["lignes_brutes"] + bd().execute("SELECT COUNT(*) FROM sub_brut").fetchone()[0], page="/")


ECART_SQL = ("valeur_originale >= 25000 AND valeur > valeur_originale * 1.10 "
             "AND valeur <= valeur_originale * 20")


@app.route("/suivre-l-argent/")
def suivre():
    from sankey import sankey
    c, s, b = charger("chiffres"), charger("subventions"), charger("budget")

    # 1. Le budget : d'où vient l'argent, où il va (exercice du Rapport financier annuel).
    rev = {x["nom"]: x["valeur"] for x in b["revenus_detail"]}
    sources = [("imp", "Impôt des particuliers", rev["Impôt sur le revenu des particuliers"]),
               ("soc", "Impôt des sociétés", rev["Impôt sur le revenu des sociétés"]),
               ("tps", "TPS", rev["TPS"]), ("ae", "Cotisations d'assurance-emploi", rev["Cotisations d'assurance-emploi"]),
               ("pol", "Tarification de la pollution", rev["Tarification de la pollution"]),
               ("aut", "Autres taxes et revenus", b["revenus"] - sum(rev[k] for k in (
                   "Impôt sur le revenu des particuliers", "Impôt sur le revenu des sociétés", "TPS",
                   "Cotisations d'assurance-emploi", "Tarification de la pollution"))),
               ("emp", "Emprunt (le déficit)", b["deficit"])]
    dep = {x["nom"]: x["valeur"] for x in b["charges_detail"]}
    trouve = lambda debut: next(v for k, v in dep.items() if k.startswith(debut))
    depenses = [("ain", "Prestations aux aînés", trouve("Prestations aux aînés"), "/comprendre/budget/"),
                ("enf", "Prestations pour enfants", trouve("Prestations pour enfants"), "/comprendre/budget/"),
                ("aem", "Assurance-emploi", trouve("Assurance-emploi"), "/comprendre/budget/"),
                ("pro", "Transferts aux provinces", trouve("Transferts aux provinces"), "/comprendre/provinces/"),
                ("sub", "Subventions et autres transferts", trouve("Autres paiements"), "/subventions/"),
                ("fon", "Fonctionnement (dont les contrats)", trouve("Fonctionnement"), "/contrats/"),
                ("int", "Intérêts sur la dette", trouve("Intérêts"), "/comprendre/budget/"),
                ("rpo", "Retour de la tarification de la pollution", trouve("Retour"), None),
                ("div", "Autres (retraites, récupérations)", b["charges"] - sum(x[2] for x in [
                    ("", "", trouve(k)) for k in ("Prestations aux aînés", "Prestations pour enfants", "Assurance-emploi",
                                                   "Transferts aux provinces", "Autres paiements", "Fonctionnement",
                                                   "Intérêts", "Retour")]), None)]
    noeuds = {k: dict(nom=n) for k, n, _ in sources}
    noeuds["emp"]["classe"] = "rouge"
    noeuds["bud"] = dict(nom="Budget fédéral", classe="fonce")
    for k, n, _, url in depenses:
        noeuds[k] = dict(nom=n, url=url)
    noeuds["int"]["classe"] = "rouge"
    liens = [(k, "bud", v) for k, _, v in sources] + [("bud", k, v) for k, _, v, _ in depenses]
    flux_budget = sankey([[k for k, *_ in sources], ["bud"], [k for k, *_ in depenses]], noeuds, liens)

    # 2. L'argent qu'on peut suivre au dollar près : contrats et subventions de l'exercice.
    debut, fin = "2025-04-01", "2026-03-31"
    par_minis = {}
    for m, nom, v in bd().execute(f"SELECT ministere, MAX(ministere_nom), SUM(valeur) FROM contrats WHERE "
                                  f"date_contrat BETWEEN '{debut}' AND '{fin}' AND quarantaine IS NULL GROUP BY 1"):
        par_minis.setdefault(m, dict(nom=nom, c=0, s=0))["c"] = v
    for m, nom, v in bd().execute(f"SELECT ministere, MAX(ministere_nom), SUM(valeur) FROM subventions WHERE "
                                  f"debut BETWEEN '{debut}' AND '{fin}' AND quarantaine IS NULL GROUP BY 1"):
        par_minis.setdefault(m, dict(nom=nom, c=0, s=0))["s"] = v
    classes = sorted(par_minis.items(), key=lambda x: -(x[1]["c"] + x[1]["s"]))
    tete, reste = classes[:8], classes[8:]
    noeuds2, liens2, gauche = {}, [], []
    for m, d in tete:
        noeuds2[m] = dict(nom=d["nom"], url=f"/ministere/{m}/")
        gauche.append(m)
        liens2 += [(m, "C", d["c"])] if d["c"] else []
        liens2 += [(m, "S", d["s"])] if d["s"] else []
    noeuds2["autres"] = dict(nom=f"{len(reste)} autres ministères et organismes", url="/ministeres/")
    gauche.append("autres")
    liens2 += [("autres", "C", sum(d["c"] for _, d in reste)), ("autres", "S", sum(d["s"] for _, d in reste))]
    noeuds2["C"] = dict(nom="Contrats", classe="fonce", url="/contrats/")
    noeuds2["S"] = dict(nom="Subventions et contributions", classe="rouge", url="/subventions/", classe_lien="lien-rouge")
    groupes = {"F": ("ent", "Entreprises"), "N": ("obnl", "Organismes sans but lucratif"),
               "A": ("aut", "Bénéficiaires autochtones"), "G": ("gou", "Gouvernements"),
               "S": ("uni", "Universités et institutions"), "P": ("par", "Particuliers (jamais nommés)"),
               "LOT": ("par", "Particuliers (jamais nommés)")}
    droite = {}
    for x in s["beneficiaires"]:
        k, nom = groupes.get(x["code"], ("div", "Autres bénéficiaires"))
        droite.setdefault(k, [nom, 0])[1] += x["valeur"]
    total_c = sum(d["c"] for _, d in classes)
    droite.setdefault("ent", ["Entreprises", 0])
    for k, (nom, v) in droite.items():
        noeuds2[k] = dict(nom=nom)
        if v:
            liens2.append(("S", k, v))
    noeuds2["ent"] = dict(nom="Entreprises et fournisseurs", url="/chercher/")
    liens2.append(("C", "ent", total_c))
    ordre_droite = [k for k in ("ent", "obnl", "aut", "gou", "uni", "par", "div") if k in droite]
    flux_suivi = sankey([gauche, ["C", "S"], ordre_droite], noeuds2, liens2, hauteur=560)

    # 3. Ce qui va bien, ce qui mérite une explication (exercice 2025-2026).
    ok = f"date_contrat BETWEEN '{debut}' AND '{fin}' AND quarantaine IS NULL"
    un = lambda q: bd().execute(q).fetchone()
    nb, total, v_conc, jamais, conc_connus, conc_plusieurs = un(
        f"SELECT COUNT(*), SUM(valeur), SUM(CASE WHEN methode IN ('TC','OB','ST') THEN valeur ELSE 0 END), "
        f"SUM(valeur <= COALESCE(valeur_originale, valeur) * 1.001), "
        f"SUM(methode IN ('TC','OB','ST') AND nb_offres NOT IN ('', '0')), "
        f"SUM(methode IN ('TC','OB','ST') AND CAST(nb_offres AS INT) >= 2) FROM contrats WHERE {ok}")
    ecarts_nb, ecarts_dollars = un(f"SELECT COUNT(*), SUM(valeur - valeur_originale) FROM contrats "
                                   f"WHERE {PERIODE} AND {ECART_SQL} AND valeur > valeur_originale * 1.5")
    sig = dict(bd().execute("SELECT type, COUNT(DISTINCT cle) FROM signaux GROUP BY type").fetchall())
    nb_prio = un("SELECT COUNT(*) FROM signaux_contrat WHERE nb >= 3")[0]
    top_ecarts = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id "
        f"WHERE c.date_contrat BETWEEN '{PERIODE_DEBUT}' AND date('now') AND c.quarantaine IS NULL "
        f"AND c.{ECART_SQL.replace(' AND valeur', ' AND c.valeur')} "
        f"ORDER BY c.valeur - c.valeur_originale DESC LIMIT 10").fetchall()
    return render_template(
        "suivre.html", b=b, c=c, s=s, flux_budget=flux_budget, flux_suivi=flux_suivi,
        bien=dict(part_conc=v_conc / total, jamais=jamais / nb, plusieurs=conc_plusieurs / conc_connus if conc_connus else 0),
        expl=dict(ecarts_nb=ecarts_nb, ecarts_dollars=ecarts_dollars, sans_appel=sig.get("SANS_APPEL", 0),
                  soum_unique=sig.get("SOUM_UNIQUE", 0), prio=nb_prio),
        top_ecarts=top_ecarts, page="/suivre-l-argent/")


@app.route("/ecarts/")
def ecarts():
    base_ecart = f"{PERIODE} AND {ECART_SQL}"
    gravites = []
    for g, (bas, haut, nom) in enumerate([(1.10, 1.25, "+10 % à +25 %"), (1.25, 1.5, "+25 % à +50 %"),
                                          (1.5, 20, "plus de +50 %")], 1):
        n, d = bd().execute(f"SELECT COUNT(*), SUM(valeur - valeur_originale) FROM contrats WHERE {base_ecart} "
                            f"AND valeur > valeur_originale * {bas} AND valeur <= valeur_originale * {haut}").fetchone()
        gravites.append(dict(g=g, nom=nom, nb=n, dollars=d))
    total_nb = sum(x["nb"] for x in gravites)
    total_dollars = sum(x["dollars"] for x in gravites)
    nb_contrats, total_signe = bd().execute(
        f"SELECT COUNT(*), SUM(valeur_originale) FROM contrats WHERE {PERIODE} AND valeur_originale >= 25000").fetchone()
    par_ministere = bd().execute(
        f"SELECT ministere, MAX(ministere_nom) ministere_nom, COUNT(*) n, SUM(valeur - valeur_originale) d "
        f"FROM contrats WHERE {base_ecart} GROUP BY ministere ORDER BY d DESC LIMIT 12").fetchall()
    joint = f"c.date_contrat BETWEEN '{PERIODE_DEBUT}' AND date('now') AND c.quarantaine IS NULL " \
            f"AND c.valeur_originale >= 25000 AND c.valeur > c.valeur_originale * 1.10 AND c.valeur <= c.valeur_originale * 20"
    en_dollars = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE {joint} "
        f"ORDER BY c.valeur - c.valeur_originale DESC LIMIT 50").fetchall()
    en_pct = bd().execute(
        f"SELECT {CONTRAT_COLONNES} FROM contrats c JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE {joint} "
        f"AND c.valeur_originale >= 1e6 ORDER BY c.valeur / c.valeur_originale DESC LIMIT 50").fetchall()
    sauts = bd().execute(f"SELECT COUNT(*) FROM contrats WHERE {PERIODE} AND valeur_originale >= 25000 "
                         f"AND valeur > valeur_originale * 20").fetchone()[0]
    return render_template("ecarts.html", gravites=gravites, total_nb=total_nb, total_dollars=total_dollars,
                           nb_contrats=nb_contrats, total_signe=total_signe, par_ministere=par_ministere,
                           en_dollars=en_dollars, en_pct=en_pct, sauts=sauts, page="/ecarts/")


@app.route("/contrat/<path:slug_contrat>/")
def contrat(slug_contrat):
    p = bd().execute("SELECT cle FROM contrat_page WHERE slug = ?", (slug_contrat,)).fetchone()
    if not p:
        abort(404)
    c = bd().execute(
        f"SELECT c.*, f.nom fournisseur_nom, f.slug, f.a_fiche FROM contrats c "
        f"LEFT JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE c.cle = ?", (p["cle"],)).fetchone()
    versions = bd().execute("SELECT * FROM versions WHERE cle = ? ORDER BY ordre", (p["cle"],)).fetchall()
    signaux = bd().execute("SELECT * FROM signaux WHERE cle = ? ORDER BY gravite DESC", (p["cle"],)).fetchall()
    # La trace en escalier : chaque version déclarée, dans l'ordre.
    points = [v for v in versions if v["valeur"] and not v["ecartee"]]
    haut = max([v["valeur"] for v in points] + [c["valeur_originale"] or 0, c["valeur"] or 0]) or 1
    return render_template("contrat.html", c=c, versions=versions, signaux=signaux, points=points, haut=haut,
                           e=ecart(c["valeur"], c["valeur_originale"]), page="")


@app.route("/contrats/")
def contrats():
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
    return render_template("contrats.html", c=c, page="/contrats/")


@app.route("/subventions/")
def subventions():
    s = charger("subventions")
    s["part_contributions"] = next(e["valeur"] for e in s["ententes"] if e["code"] == "C") / s["total"]
    s["ratio_contrats"] = s["total"] / charger("chiffres")["total"]
    a = {x["exercice"]: x["valeur"] for x in s["par_annee"]}
    s["pic"] = max(s["par_annee"], key=lambda x: x["valeur"])
    return render_template("subventions.html", s=s, pop=charger("population"), page="/subventions/")


@app.route("/lobbying/")
def lobbying():
    l = charger("lobby")
    l["par_jour"] = l["nb"] / (len(l["par_annee"]) - 0.5) / 261   # ~jours ouvrables ; dernier exercice à moitié
    return render_template("lobbying.html", l=l, page="/lobbying/")


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
    lobby = lobby_ministeres = None
    if bd().execute("SELECT 1 FROM sqlite_master WHERE name = 'lobby_totaux'").fetchone():
        lobby = bd().execute("SELECT * FROM lobby_totaux WHERE fournisseur_id = ?", p).fetchone()
        lobby_ministeres = bd().execute("SELECT * FROM lobby_fiche WHERE fournisseur_id = ? "
                                        "ORDER BY communications DESC LIMIT 10", p).fetchall()
    return render_template(
        "entreprise.html", lobby=lobby, lobby_ministeres=lobby_ministeres, f=f, variantes=json.loads(f["variantes"]), contrats=contrats, subs=subs,
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


@app.route("/a-examiner/")
def a_examiner():
    comptes = {t: dict(nb=n, valeur=v) for t, n, v in bd().execute(
        "SELECT s.type, COUNT(DISTINCT s.cle), SUM(c.valeur) FROM signaux s JOIN contrats c ON c.cle = s.cle "
        "GROUP BY s.type")}
    prioritaires = bd().execute(
        f"SELECT {CONTRAT_COLONNES}, sc.nb FROM signaux_contrat sc JOIN contrats c ON c.cle = sc.cle "
        f"JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE sc.nb >= 3 ORDER BY c.valeur DESC LIMIT 60").fetchall()
    nb_prio, val_prio = bd().execute(
        "SELECT COUNT(*), SUM(c.valeur) FROM signaux_contrat sc JOIN contrats c ON c.cle = sc.cle "
        "WHERE sc.nb >= 3").fetchone()
    grands, grands_signal = bd().execute(
        f"SELECT COUNT(*), SUM(EXISTS(SELECT 1 FROM signaux_contrat sc WHERE sc.cle = c.cle)) FROM contrats c "
        f"WHERE {PERIODE} AND valeur >= 100000").fetchone()
    return render_template("a_examiner.html", comptes=comptes, prioritaires=prioritaires, nb_prio=nb_prio,
                           val_prio=val_prio, grands=grands, grands_signal=grands_signal, r=reperes(),
                           page="/a-examiner/")


@app.route("/a-examiner/<type_signal>/")
def signal_type(type_signal):
    t = type_signal.upper().replace("-", "_")
    if t not in SIGNAUX:
        abort(404)
    lignes = bd().execute(
        f"SELECT {CONTRAT_COLONNES}, s.gravite, s.detail FROM signaux s JOIN contrats c ON c.cle = s.cle "
        f"JOIN fournisseurs f ON f.id = c.fournisseur_id WHERE s.type = ? "
        f"ORDER BY s.gravite DESC, c.valeur DESC LIMIT 100", (t,)).fetchall()
    nb, valeur = bd().execute("SELECT COUNT(DISTINCT s.cle), SUM(c.valeur) FROM signaux s "
                              "JOIN contrats c ON c.cle = s.cle WHERE s.type = ?", (t,)).fetchone()
    par_ministere = bd().execute(
        "SELECT c.ministere, c.ministere_nom, COUNT(*) n, SUM(c.valeur) v FROM signaux s "
        "JOIN contrats c ON c.cle = s.cle WHERE s.type = ? GROUP BY c.ministere ORDER BY n DESC LIMIT 10",
        (t,)).fetchall()
    return render_template("signal.html", t=t, d=SIGNAUX[t], lignes=lignes, nb=nb, valeur=valeur,
                           par_ministere=par_ministere, page="/a-examiner/")


@app.route("/comprendre/")
def comprendre():
    return render_template("comprendre.html", b=charger("budget"), page="/comprendre/")


@app.route("/comprendre/budget/")
def budget():
    b = charger("budget")
    b["par_seconde"] = b["charges"] / (365 * 24 * 3600)
    b["interets_par_seconde"] = b["interets"] / (365 * 24 * 3600)
    b["dette_par_personne"] = b["dette"] / b["population"]["valeur"]
    b["famille"] = 1e7   # on divise tout par 10 millions
    return render_template("budget.html", b=b, page="/comprendre/")


@app.route("/comprendre/provinces/")
def provinces():
    b, pop = charger("budget"), charger("population")
    t = b["transferts"]
    lignes = []
    for code, total in t["total_par_province"].items():
        per = t["perequation_par_province"].get(code)
        lignes.append(dict(code=code, nom=pop["noms"][code], total=total, per=per,
                           per_hab=(per / pop["provinces"][code]) if per is not None else None,
                           total_hab=t["par_habitant_officiel"][code]))
    receveuses = sorted([x for x in lignes if x["per"]], key=lambda x: -x["per_hab"])
    qc = next(x for x in lignes if x["code"] == "QC")
    rang_qc = [x["code"] for x in receveuses].index("QC") + 1
    return render_template("provinces.html", b=b, t=t, pop=pop, lignes=sorted(lignes, key=lambda x: -x["total"]),
                           receveuses=receveuses, qc=qc, rang_qc=rang_qc, page="/comprendre/")


@app.route("/comprendre/on-clarifie/")
def on_clarifie():
    b, c, s = charger("budget"), charger("chiffres"), charger("subventions")
    entreprises = next(x for x in s["beneficiaires"] if x["code"] == "F")
    tn = next(x for x in c["methodes"] if x["code"] == "TN")
    raisons = {r["code"]: r for r in c["raisons_sans_appel"]}
    t = b["transferts"]
    return render_template("on_clarifie.html", b=b, c=c, s=s, entreprises=entreprises, tn=tn, raisons=raisons,
                           part_qc=t["perequation_par_province"]["QC"] / t["perequation"],
                           pop=charger("population"), page="/comprendre/")


@app.route("/methode/")
def methode():
    return render_template("methode.html", c=charger("chiffres"), s=charger("subventions"), r=reperes(),
                           page="/methode/")


@app.errorhandler(404)
def introuvable(_):
    return render_template("introuvable.html", page=""), 404


if __name__ == "__main__":
    app.run(port=5072, debug=True)
