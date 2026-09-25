"""Croise le Registre des lobbyistes avec les contrats et les subventions.

Pour chaque organisation qui fait du lobbying depuis avril 2017, on compte
ses communications déclarées avec chaque institution fédérale, et l'argent
qu'elle a reçu de cette même institution (contrats et subventions).

Ce croisement montre des faits simultanés, jamais un lien de cause : faire
du lobbying est légal, encadré et déclaré. Beaucoup d'organisations
rencontrent un ministère précisément parce qu'elles travaillent déjà avec lui.

Les organisations sont rapprochées par le même nom normalisé que les fiches
(voir analyser.py) : un rapprochement manqué est possible, un faux
rapprochement est rare.
"""
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))
from analyser import normaliser  # noqa: E402

BASE = RACINE / "data" / "canada.db"
SORTIE = RACINE / "app" / "contenu" / "lobby.json"
DEBUT = "2017-04-01"

# Institutions du registre dont le nom ne correspond pas mot pour mot à celui
# du ministère dans les contrats (anciens noms, ministères renommés).
MANUEL = {
    "Finance Canada (FIN)": "fin", "Industry Canada": "ic", "Infrastructure Canada (INFC)": "infc",
    "Housing, Infrastructure and Communities Canada (HICC)": "infc", "Environment Canada": "ec",
    "Foreign Affairs and International Trade Canada (DFAITC)": "dfatd-maecd",
    "Foreign Affairs, Trade and Development Canada": "dfatd-maecd", "Canadian International Development Agency (CIDA)": "dfatd-maecd",
    "Justice Canada (JC)": "jus", "National Research Council (NRC)": "nrc-cnrc",
    "Aboriginal Affairs and Northern Development Canada": "aandc-aadnc", "Indigenous and Northern Affairs Canada": "aandc-aadnc",
    "Women and Gender Equality (WAGE)": "wage", "Natural Sciences and Engineering Research Council (NSERC)": "nserc-crsng",
    "Public Works and Government Services Canada": "pwgsc-tpsgc", "Citizenship and Immigration Canada": "cic",
    "Social Sciences and Humanities Research Council (SSHRC)": "sshrc-crsh",
    "Human Resources and Skills Development Canada (HRSDC)": "esdc-edsc", "Human Resources and Social Development Canada (HRSDC)": "esdc-edsc",
    "Human Resources Development Canada (HRDC)": "esdc-edsc", "Canadian Coast Guard (CCG)": "dfo-mpo",
    "Canadian Environmental Assessment Agency (CEAA)": "iaac-aeic",
}
# Institutions politiques : on les compte, mais elles ne signent ni contrats ni subventions.
POLITIQUES = {"House of Commons": "Chambre des communes", "Members of the House of Commons": "Chambre des communes",
              "Prime Minister's Office (PMO)": "Cabinet du premier ministre", "Senate of Canada": "Sénat"}


def correspondances(con):
    orgs = {}
    for code, titre in con.execute("SELECT owner_org, MAX(owner_org_title) FROM brut GROUP BY owner_org "
                                   "UNION SELECT owner_org, MAX(owner_org_title) FROM sub_brut GROUP BY owner_org"):
        orgs[normaliser(titre.split("|")[0])] = code
    carte = {}
    for (inst,) in con.execute("SELECT DISTINCT institution FROM lobby_inst"):
        if inst in MANUEL:
            carte[inst] = MANUEL[inst]
        else:
            k = normaliser(re.sub(r"\s*\([^)]*\)\s*$", "", inst))
            if k in orgs:
                carte[inst] = orgs[k]
    return carte


def sujets_fr():
    chemin = RACINE / "data" / "lobby" / "comm" / "Codes_SubjectMatterTypesExport.csv"
    with open(chemin, encoding="cp1252", newline="") as f:
        return {r["SUBJECT_CODE_OBJET"]: r["SMT_FR_DESC"].strip() for r in csv.DictReader(f)}


def main():
    con = sqlite3.connect(BASE)
    if not con.execute("SELECT name FROM sqlite_master WHERE name = 'lobby_comm'").fetchone():
        print("Pas de données de lobbying : étape sautée.")
        return
    carte = correspondances(con)
    noms_minis = dict(con.execute("SELECT ministere, MAX(ministere_nom) FROM contrats GROUP BY ministere "
                                  "UNION SELECT ministere, MAX(ministere_nom) FROM subventions GROUP BY ministere"))
    cles = {k: (i, slug, a_fiche, nom) for i, k, slug, a_fiche, nom in
            con.execute("SELECT id, cle_norm, slug, a_fiche, nom FROM fournisseurs")}

    # Organisation du registre -> fiche du site.
    org_fiche = {}
    for num, en, fr in con.execute("SELECT DISTINCT client_num, client_en, client_fr FROM lobby_comm"):
        for nom in (en, fr):
            k = normaliser(nom) if nom else ""
            if k in cles:
                org_fiche[num] = cles[k][0]
                break

    comms = con.execute(f"SELECT id, client_num, client_en, client_fr, date FROM lobby_comm WHERE date >= '{DEBUT}'").fetchall()
    insts = defaultdict(list)
    for cid, inst in con.execute("SELECT i.id, i.institution FROM lobby_inst i JOIN lobby_comm c ON c.id = i.id "
                                 f"WHERE c.date >= '{DEBUT}'"):
        insts[cid].append(inst)

    par_inst, par_org, noms_org, num_de = Counter(), Counter(), {}, {}
    par_annee = Counter()
    fiche_minis = defaultdict(Counter)       # fournisseur_id -> ministère -> communications
    fiche_total, fiche_dernier = Counter(), {}
    for cid, num, en, fr, d in comms:
        cle_org = normaliser(fr or en or num) or num
        par_org[cle_org] += 1
        noms_org[cle_org] = fr or en
        num_de[cle_org] = num
        par_annee[int(d[:4]) - (d[5:7] < "04")] += 1
        fid = org_fiche.get(num)
        if fid:
            fiche_total[fid] += 1
            fiche_dernier[fid] = max(fiche_dernier.get(fid, ""), d)
        for inst in insts.get(cid, []):
            libelle = POLITIQUES.get(inst) or (noms_minis.get(carte[inst]) if inst in carte else None) or inst
            par_inst[(libelle, carte.get(inst, ""))] += 1
            if fid and inst in carte:
                fiche_minis[fid][carte[inst]] += 1

    # Table pour les fiches : communications par ministère, et l'argent reçu de ce ministère.
    con.execute("DROP TABLE IF EXISTS lobby_fiche")
    con.execute("""CREATE TABLE lobby_fiche (fournisseur_id INTEGER, ministere TEXT, ministere_nom TEXT,
                   communications INTEGER, argent REAL)""")
    argent = defaultdict(float)
    for fid, minis, v in con.execute(
            f"SELECT fournisseur_id, ministere, SUM(valeur) FROM contrats WHERE fournisseur_id IS NOT NULL "
            f"AND quarantaine IS NULL AND date_contrat >= '{DEBUT}' GROUP BY 1, 2 "
            f"UNION ALL SELECT beneficiaire_id, ministere, SUM(valeur) FROM subventions WHERE beneficiaire_id IS NOT NULL "
            f"AND quarantaine IS NULL AND debut >= '{DEBUT}' GROUP BY 1, 2"):
        argent[(fid, minis)] += v or 0
    lignes = [(fid, m, noms_minis.get(m, m), n, argent.get((fid, m), 0))
              for fid, compte in fiche_minis.items() for m, n in compte.items()]
    con.executemany("INSERT INTO lobby_fiche VALUES (?,?,?,?,?)", lignes)
    con.execute("DROP TABLE IF EXISTS lobby_totaux")
    con.execute("CREATE TABLE lobby_totaux (fournisseur_id INTEGER PRIMARY KEY, communications INTEGER, derniere TEXT)")
    con.executemany("INSERT INTO lobby_totaux VALUES (?,?,?)", [(f, n, fiche_dernier[f]) for f, n in fiche_total.items()])
    con.execute("CREATE INDEX i_lf ON lobby_fiche(fournisseur_id)")
    con.commit()

    # Le croisement : argent reçu d'un ministère que l'organisation a sollicité.
    croises = defaultdict(lambda: dict(communications=0, argent=0.0, ministeres=[]))
    for fid, m, nom_m, n, a in lignes:
        if a > 0:
            c = croises[fid]
            c["communications"] += n
            c["argent"] += a
            c["ministeres"].append((nom_m, n, a))
    top_croises = []
    for fid, c in sorted(croises.items(), key=lambda x: -x[1]["argent"])[:25]:
        _, slug, a_fiche, nom = next(v for v in cles.values() if v[0] == fid)
        m = max(c["ministeres"], key=lambda x: x[2])
        top_croises.append(dict(nom=nom, slug=slug, a_fiche=a_fiche, communications=c["communications"],
                                argent=c["argent"], principal=m[0], principal_comm=m[1], principal_argent=m[2]))

    sujets = sujets_fr()
    top_sujets = [dict(nom=sujets.get(code, code), nb=n) for code, n in con.execute(
        f"SELECT s.sujet, COUNT(DISTINCT s.id) FROM lobby_sujets s JOIN lobby_comm c ON c.id = s.id "
        f"WHERE c.date >= '{DEBUT}' AND s.sujet <> '' GROUP BY 1 ORDER BY 2 DESC LIMIT 12")]

    top_orgs = []
    for cle_org, n in par_org.most_common(15):
        num = num_de[cle_org]
        fid = org_fiche.get(num)
        info = next((v for v in cles.values() if v[0] == fid), None) if fid else None
        recu = con.execute("SELECT total FROM fournisseurs WHERE id = ?", (fid,)).fetchone()[0] if fid else 0
        top_orgs.append(dict(nom=noms_org[cle_org], nb=n, recu=recu, slug=info[1] if info else None,
                             a_fiche=info[2] if info else 0))

    orgs_avec_argent = len({org_fiche[num_de[k]] for k in par_org if num_de[k] in org_fiche})
    derniere = con.execute("SELECT MAX(date), MAX(publie) FROM lobby_comm").fetchone()
    resultat = dict(
        debut=DEBUT, nb=len(comms), nb_orgs=len(par_org), orgs_avec_argent=orgs_avec_argent,
        institutions=[dict(nom=k[0], code=k[1], nb=n) for k, n in par_inst.most_common(15)],
        orgs=top_orgs, croises=top_croises, sujets=top_sujets,
        par_annee=[dict(exercice=f"{a}-{a + 1}", nb=n) for a, n in sorted(par_annee.items())],
        donnees_du=derniere[0], publie=derniere[1],
        source=dict(nom="Commissariat au lobbying du Canada, Registre des lobbyistes, rapports de communication mensuels",
                    url="https://ouvert.canada.ca/data/fr/dataset/a34eb330-7136-4f5e-9f5f-3ba41df58b06"),
    )
    SORTIE.write_text(json.dumps(resultat, ensure_ascii=False, indent=1))
    print(f"{resultat['nb']} communications, {resultat['nb_orgs']} organisations, "
          f"{orgs_avec_argent} reçoivent de l'argent fédéral ; {len(lignes)} paires organisation-ministère.")
    con.close()


if __name__ == "__main__":
    main()
