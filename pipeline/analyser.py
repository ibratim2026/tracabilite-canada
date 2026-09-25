"""Nettoie les contrats fédéraux et calcule les chiffres de la page vitrine.

Trois décisions de nettoyage, toutes expliquées au public sur la page :

1. Une ligne n'est pas un contrat. Chaque modification est republiée avec le
   total cumulé : on garde seulement la version la plus récente de chaque
   contrat (même ministère + même numéro d'achat).
2. Les offres à commandes (SOSA) sont des plafonds, pas des engagements : on
   les exclut des sommes.
3. Les valeurs aberrantes vont en quarantaine : on les montre, on ne les
   additionne pas.

Le résultat va dans app/contenu/chiffres.json, avec pour chaque chiffre sa
source et la façon dont il a été calculé.
"""
import hashlib, json, re, sqlite3, unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASE = RACINE / "data" / "canada.db"
SORTIE = RACINE / "app" / "contenu" / "chiffres.json"

# Exercice financier fédéral : 1er avril au 31 mars.
EXERCICE = ("2025-04-01", "2026-03-31")
EXERCICE_NOM = "2025-2026"

# Statistique Canada, tableau 17-10-0009-01, estimation au 1er juillet 2026,
# diffusée le 23 septembre 2026.
POPULATION = 41_798_407
POPULATION_SOURCE = {
    "nom": "Statistique Canada, tableau 17-10-0009-01 (estimation au 1er juillet 2026)",
    "url": "https://www150.statcan.gc.ca/t1/tbl1/fr/tv.action?pid=1710000901",
}
# Ministère des Finances, Rapport financier annuel 2024-2025 (dernier exercice
# dont les résultats sont publiés au moment d'écrire).
BUDGET = {
    "exercice": "2024-2025", "charges": 547.3e9, "dette": 53.4e9,
    "nom": "Ministère des Finances Canada, Rapport financier annuel du gouvernement du Canada, exercice 2024-2025",
    "url": "https://www.canada.ca/fr/ministere-finances/services/publications/rapport-financier-annuel/2025.html",
}
SOURCE_CONTRATS = {
    "nom": "Gouvernement ouvert — Publication proactive : contrats de plus de 10 000 $",
    "url": "https://ouvert.canada.ca/data/fr/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b",
}

METHODES = {
    "TC": "Concurrentielle (traditionnelle)",
    "OB": "Concurrentielle (appel d'offres ouvert)",
    "ST": "Concurrentielle (appel d'offres sélectif)",
    "AC": "Préavis d'adjudication (PAC)",
    "TN": "Sans appel d'offres",
}
RAISONS = {
    "71": "Droits exclusifs (un seul fournisseur possible)",
    "81": "Urgence extrême",
    "05": "Personne n'a répondu à l'appel d'offres",
    "74": "Livraisons supplémentaires du même fournisseur",
    "20": "Achat sur un marché de produits de base",
    "21": "Conditions exceptionnellement avantageuses",
    "00": "Aucune raison exigée (souvent sous les seuils des accords commerciaux)",
    "72": "Achat d'un prototype",
    "23": "Services confidentiels",
    "33": "Biens de nature confidentielle",
    "85": "Faible valeur (code retiré en 2022)",
    "87": "Objectifs gouvernementaux (code retiré en 2022)",
    "86": "Prix fixé par règlement (code retiré en 2022)",
    "90": "Protection de la vie ou de la santé (code retiré en 2022)",
}


def cle_periode(p):
    """« 2024-2025-Q3 » -> (2024, 3). Les formats fantaisistes passent en dernier."""
    m = re.match(r"\s*(\d{4})\D+\d{2,4}\D*Q?(\d)?", p or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def construire_contrats(con):
    con.execute("DROP TABLE IF EXISTS contrats")
    con.execute("""CREATE TABLE contrats (
        cle TEXT PRIMARY KEY, ministere TEXT, ministere_nom TEXT, fournisseur TEXT,
        pays TEXT, date_contrat TEXT, description TEXT, methode TEXT, raison TEXT,
        valeur REAL, valeur_originale REAL, nb_versions INTEGER, quarantaine TEXT,
        reference TEXT, debut TEXT, fin TEXT, fournisseur_id INTEGER)""")
    # On regroupe toutes les versions de chaque contrat.
    groupes = {}
    for rowid, org, pid, ref, periode, val, orig, modif in con.execute(
            "SELECT rowid, owner_org, procurement_id, reference_number, reporting_period, valeur, "
            "valeur_originale, valeur_modif FROM brut WHERE instrument_type <> 'SOSA'"):
        cle = f"{org}|{pid.strip() or ref.strip()}"
        groupes.setdefault(cle, []).append(((cle_periode(periode), rowid), rowid, val or 0, orig, modif))

    # Une version est une coquille démontrable quand elle se contredit elle-même :
    # plus de 100 millions, et plus de 50 fois la somme de sa propre valeur
    # d'origine et de sa propre modification, ET plus de 50 fois toutes les
    # autres versions du même contrat. On l'écarte et on garde la version la plus
    # récente parmi les autres. Règle volontairement étroite : un contrat qui a
    # vraiment grossi ne doit jamais être mis de côté.
    derniers, versions, coquilles = {}, {}, []
    for cle, vs in groupes.items():
        versions[cle] = len(vs)
        valeurs = sorted(v[2] for v in vs)
        suspecte = max(vs, key=lambda x: x[2])
        _, _, val, orig, modif = suspecte
        if (len(vs) > 1 and val >= 1e8 and val > 50 * max(valeurs[-2], 1)
                and orig is not None and modif is not None
                and val > 50 * (abs(orig) + abs(modif))):
            coquilles.append((suspecte[1], valeurs[-2]))
            vs = [x for x in vs if x is not suspecte]
        derniers[cle] = max(vs)[:2]
    con.execute("DROP TABLE IF EXISTS coquilles")
    con.execute("CREATE TABLE coquilles (rowid_brut INTEGER, valeur_voisine REAL)")
    con.executemany("INSERT INTO coquilles VALUES (?,?)", coquilles)

    lignes = []
    requete = ("SELECT owner_org, owner_org_title, vendor_name, country_of_vendor, contract_date, "
               "description_fr, solicitation_procedure, limited_tendering_reason, valeur, "
               "valeur_originale, reference_number, contract_period_start, delivery_date "
               "FROM brut WHERE rowid = ?")
    for cle, (_, rowid) in derniers.items():
        org, titre, fourn, pays, dt, desc, meth, raison, val, orig, ref, deb, fin = \
            con.execute(requete, (rowid,)).fetchone()
        nom = titre.split("|")[-1].strip() if "|" in titre else titre
        quarantaine = "valeur nulle ou négative" if val is None or val <= 0 else None
        lignes.append((cle, org, nom, (fourn or "").strip(), pays, (dt or "")[:10],
                       (desc or "").strip(), meth, raison, val, orig, versions[cle], quarantaine,
                       ref, (deb or "")[:10], (fin or "")[:10], None))
    con.executemany("INSERT INTO contrats VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lignes)
    con.execute("CREATE INDEX i_date ON contrats(date_contrat)")
    con.commit()


# ---- Les entreprises -------------------------------------------------------
# Le même fournisseur s'écrit de dix façons (« IBM CANADA LTD. », « IBM Canada
# Limited »…). On regroupe sur un nom normalisé : majuscules, sans accents ni
# ponctuation, sans les formes juridiques. Les variantes sont conservées et
# affichées sur chaque fiche, pour que le regroupement reste vérifiable.
FORMES_JURIDIQUES = re.compile(
    r"\b(INC|INCORPORATED|INCORPOREE|LTD|LTEE|LIMITED|LIMITEE|CORP|CORPORATION|CO|COMPANY|"
    r"LLP|LP|ULC|LLC|SENC|SENCRL|S E N C R L|SA|SAS|GMBH|PLC|AG|THE)\b")
PERIODE_DEBUT = "2017-04-01"   # avant, les déclarations sont trop inégales
SEUIL_FICHE = 1_000_000        # une fiche complète à partir de 1 M$ reçus


def normaliser(nom):
    # Noms bilingues « X LIMITED / X LIMITÉE » : si les deux moitiés disent la
    # même chose, on n'en garde qu'une.
    moities = {normaliser(m) for m in nom.split("/")} - {""} if "/" in nom else None
    if moities and len(moities) == 1:
        return moities.pop()
    n = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().upper()
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    n = FORMES_JURIDIQUES.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def fabriquer_slug(nom):
    s = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:70].rstrip("-") or "sans-nom"


def construire_fournisseurs(con):
    groupes, variantes = defaultdict(list), defaultdict(Counter)
    for cle, nom, val in con.execute(
            "SELECT cle, fournisseur, valeur FROM contrats WHERE quarantaine IS NULL "
            f"AND date_contrat BETWEEN '{PERIODE_DEBUT}' AND date('now') AND fournisseur <> ''"):
        k = normaliser(nom)
        if not k:
            continue
        groupes[k].append((cle, val))
        variantes[k][nom] += 1

    con.execute("DROP TABLE IF EXISTS fournisseurs")
    con.execute("""CREATE TABLE fournisseurs (id INTEGER PRIMARY KEY, cle_norm TEXT, nom TEXT,
        variantes TEXT, total REAL, nb INTEGER, slug TEXT, a_fiche INTEGER)""")
    pris, lignes, liens = set(), [], []
    for i, (k, cs) in enumerate(sorted(groupes.items(), key=lambda g: -sum(v for _, v in g[1])), 1):
        total = sum(v for _, v in cs)
        # Nom affiché : de préférence une variante en casse normale, la plus fréquente.
        nom = max(variantes[k].items(), key=lambda x: (any(c.islower() for c in x[0]), x[1]))[0]
        nom = re.sub(r"\s+", " ", nom).strip(" /,")
        # Adresse stable d'une mise à jour à l'autre : tirée du nom normalisé.
        slug = fabriquer_slug(k)
        if slug in pris:   # deux noms très longs coupés au même endroit
            slug = f"{slug[:60]}-{hashlib.md5(k.encode()).hexdigest()[:6]}"
        pris.add(slug)
        lignes.append((i, k, nom, json.dumps(sorted(variantes[k]), ensure_ascii=False),
                       total, len(cs), slug, int(total >= SEUIL_FICHE)))
        liens += [(i, cle) for cle, _ in cs]
    con.executemany("INSERT INTO fournisseurs VALUES (?,?,?,?,?,?,?,?)", lignes)
    con.executemany("UPDATE contrats SET fournisseur_id = ? WHERE cle = ?", liens)
    con.execute("CREATE INDEX i_fourn ON contrats(fournisseur_id)")
    con.execute("CREATE INDEX i_minis ON contrats(ministere)")
    con.execute("CREATE UNIQUE INDEX i_slug ON fournisseurs(slug)")
    con.commit()


def calculer(con):
    debut, fin = EXERCICE
    ok = f"date_contrat BETWEEN '{debut}' AND '{fin}' AND quarantaine IS NULL"
    un = lambda sql: con.execute(sql).fetchone()

    lignes_brutes = un("SELECT COUNT(*) FROM brut")[0]
    contrats_tous = un("SELECT COUNT(*) FROM contrats")[0]
    nb, total = un(f"SELECT COUNT(*), SUM(valeur) FROM contrats WHERE {ok}")
    mediane = con.execute(f"SELECT valeur FROM contrats WHERE {ok} ORDER BY valeur "
                          f"LIMIT 1 OFFSET {nb // 2}").fetchone()[0]

    # Jours ouvrables de l'exercice (lundi à vendredi, sans retirer les fériés : on le dit).
    d0, d1 = date.fromisoformat(debut), date.fromisoformat(fin)
    jours_ouvrables = sum(1 for i in range((d1 - d0).days + 1)
                          if date.fromordinal(d0.toordinal() + i).weekday() < 5)

    ministeres = [dict(nom=n, valeur=v, nb=c) for n, v, c in con.execute(
        f"SELECT ministere_nom, SUM(valeur), COUNT(*) FROM contrats WHERE {ok} "
        f"GROUP BY ministere ORDER BY 2 DESC LIMIT 10")]
    fournisseurs = [dict(nom=n, valeur=v, nb=c) for n, v, c in con.execute(
        f"SELECT MAX(fournisseur), SUM(valeur), COUNT(*) FROM contrats WHERE {ok} "
        f"GROUP BY UPPER(TRIM(REPLACE(REPLACE(fournisseur,'.',''),',',''))) ORDER BY 2 DESC LIMIT 10")]

    # La concentration : quelle part de l'argent va aux 1 % plus gros contrats ?
    top1 = max(1, nb // 100)
    part_top1 = un(f"SELECT SUM(valeur) FROM (SELECT valeur FROM contrats WHERE {ok} "
                   f"ORDER BY valeur DESC LIMIT {top1})")[0] / total

    methodes = []
    for code, n, v in con.execute(f"SELECT methode, COUNT(*), SUM(valeur) FROM contrats "
                                  f"WHERE {ok} GROUP BY methode ORDER BY 3 DESC"):
        methodes.append(dict(code=code, nom=METHODES.get(code, "Non précisée"), nb=n, valeur=v))
    raisons = [dict(code=c, nom=RAISONS.get(c, "Non précisée"), nb=n, valeur=v)
               for c, n, v in con.execute(
                   f"SELECT raison, COUNT(*), SUM(valeur) FROM contrats WHERE {ok} AND methode='TN' "
                   f"GROUP BY raison ORDER BY 2 DESC LIMIT 6")]

    # Les contrats qui grossissent après la signature.
    modifies, croissance = un(
        f"SELECT COUNT(*), SUM(valeur - valeur_originale) FROM contrats "
        f"WHERE {ok} AND valeur_originale > 0 AND valeur > valeur_originale * 1.001")

    modifies_top = [dict(fournisseur=f, ministere=m, originale=o, valeur=v) for f, m, o, v in con.execute(
        f"SELECT fournisseur, ministere_nom, valeur_originale, valeur FROM contrats "
        f"WHERE {ok} AND valeur_originale > 0 AND valeur > valeur_originale * 1.001 "
        f"ORDER BY valeur - valeur_originale DESC LIMIT 4")]

    etranger = un(f"SELECT SUM(valeur) FROM contrats WHERE {ok} AND pays NOT IN ('CA','')")[0] or 0
    pays_vide = un(f"SELECT SUM(valeur) FROM contrats WHERE {ok} AND pays = ''")[0] or 0

    par_annee = [dict(exercice=f"{a}-{a+1}", nb=n, valeur=v) for a, n, v in con.execute(
        "SELECT CAST(substr(date_contrat,1,4) AS INT) - (substr(date_contrat,6,2) < '04') a, "
        "COUNT(*), SUM(valeur) FROM contrats WHERE quarantaine IS NULL "
        "AND date_contrat BETWEEN '2017-04-01' AND '2026-03-31' GROUP BY a ORDER BY a")]

    coquilles = [dict(fournisseur=f.strip(), ministere=m.split("|")[-1].strip(), date=d[:10],
                      valeur=v, voisine=vv, commentaire=c)
                 for f, m, d, v, vv, c in con.execute(
                     "SELECT b.vendor_name, b.owner_org_title, b.contract_date, b.valeur, k.valeur_voisine, "
                     "b.comments_fr FROM coquilles k JOIN brut b ON b.rowid = k.rowid_brut "
                     "ORDER BY b.valeur DESC")]

    # Un échantillon de vrais contrats pour le bouton « un contrat au hasard ».
    echantillon = [dict(fournisseur=f, ministere=m, date=d, description=desc, valeur=v,
                        originale=o, methode=METHODES.get(meth, "Non précisée"), versions=nv)
                   for f, m, d, desc, v, o, meth, nv in con.execute(
                       f"SELECT fournisseur, ministere_nom, date_contrat, description, valeur, "
                       f"valeur_originale, methode, nb_versions FROM contrats WHERE {ok} "
                       f"AND description <> '' AND fournisseur <> '' ORDER BY random() LIMIT 400")]

    # Ce qu'on obtiendrait en additionnant naïvement toutes les lignes du fichier.
    naif = {}
    for nom, (a, b) in {"2024-2025": ("2024-04-01", "2025-03-31"), EXERCICE_NOM: EXERCICE}.items():
        brut_n, brut_v = un(f"SELECT COUNT(*), SUM(valeur) FROM brut WHERE contract_date BETWEEN '{a}' AND '{b}'")
        propre_n, propre_v = un(f"SELECT COUNT(*), SUM(valeur) FROM contrats WHERE date_contrat BETWEEN '{a}' "
                                f"AND '{b}' AND quarantaine IS NULL")
        naif[nom] = dict(lignes=brut_n, somme_lignes=brut_v, contrats=propre_n, somme_contrats=propre_v)

    # Les géants de 2024-2025 : les contrats d'un milliard et plus.
    geants = [dict(fournisseur=f, ministere=m, valeur=v, description=d) for f, m, v, d in con.execute(
        "SELECT fournisseur, ministere_nom, valeur, description FROM contrats WHERE date_contrat "
        "BETWEEN '2024-04-01' AND '2025-03-31' AND quarantaine IS NULL AND valeur >= 1e9 ORDER BY valeur DESC")]

    return {
        "budget": BUDGET, "naif": naif, "geants_2024": geants,
        "genere_le": date.today().isoformat(),
        "exercice": EXERCICE_NOM,
        "sources": {"contrats": SOURCE_CONTRATS, "population": POPULATION_SOURCE},
        "population": POPULATION,
        "nettoyage": {"lignes_brutes": lignes_brutes, "contrats_uniques": contrats_tous},
        "nb": nb, "total": total, "mediane": mediane,
        "jours_ouvrables": jours_ouvrables,
        "par_personne": total / POPULATION,
        "part_top1": part_top1, "nb_top1": top1,
        "ministeres": ministeres, "fournisseurs": fournisseurs,
        "methodes": methodes, "raisons_sans_appel": raisons,
        "modifies": {"nb": modifies, "croissance": croissance, "top": modifies_top},
        "etranger": etranger, "pays_vide": pays_vide,
        "par_annee": par_annee,
        "coquilles": coquilles,
        "echantillon": echantillon,
    }


def main():
    con = sqlite3.connect(BASE)
    construire_contrats(con)
    construire_fournisseurs(con)
    chiffres = calculer(con)
    SORTIE.write_text(json.dumps(chiffres, ensure_ascii=False, indent=1))
    c = {k: v for k, v in chiffres.items() if k not in ("echantillon",)}
    print(json.dumps(c, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
