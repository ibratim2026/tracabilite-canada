"""Les signaux « À examiner en priorité ».

Chaque signal est une règle objective et publique, jamais une accusation.
Un signal dit : « ce contrat mérite une explication ». Souvent, l'explication
existe et elle est banale.

CROISSANCE      Le contrat vaut aujourd'hui plus que le montant signé :
                +25 % (gravité 1), +50 % (2), +100 % (3). Contrats signés
                à 25 000 $ ou plus. Au-delà de 20 fois : voir SAUT.
SAUT            Valeur actuelle plus de 20 fois le montant signé (et au
                moins 1 M$). Souvent des options prévues dès le départ et
                déclarées comme modifications ; parfois une erreur de saisie.
SANS_APPEL      Attribué sans appel d'offres : 100 000 $ (1), 1 M$ (2),
                10 M$ (3). Des exceptions légales existent : la raison
                déclarée est affichée.
SOUM_UNIQUE     Appel d'offres concurrentiel où une seule entreprise a
                soumissionné, 100 000 $ ou plus (1), 1 M$ ou plus (2).
MODIFS_SERIE    Trois modifications ou plus (2), six ou plus (3).
PETITS_REPETES  Au moins cinq contrats sans appel d'offres de moins de
                25 000 $ chacun, même ministère, même fournisseur, même
                exercice, pour 100 000 $ ou plus au total. (Testé à quatre
                et 75 000 $ : trop d'achats banals de fournitures.)

À EXAMINER EN PRIORITÉ (★) : contrats qui cumulent trois signaux différents
ou plus. Formulation voulue : on n'emploie jamais de mot accusatoire.

Les champs « ancien fonctionnaire » du fichier ne sont pas utilisés : ils
désignent des personnes, pas l'usage de l'argent.
"""
import sqlite3
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
BASE = RACINE / "data" / "canada.db"
PERIODE = "date_contrat BETWEEN '2017-04-01' AND date('now') AND quarantaine IS NULL"
RAISONS = {
    "71": "droits exclusifs", "81": "urgence extrême", "05": "aucune réponse à l'appel d'offres",
    "74": "livraisons supplémentaires", "20": "marché de produits de base", "21": "conditions avantageuses",
    "72": "prototype", "23": "services confidentiels", "33": "biens confidentiels",
    "85": "faible valeur", "87": "objectifs gouvernementaux", "86": "prix réglementé",
    "90": "protection de la vie ou de la santé", "00": "aucune raison exigée",
}


def main():
    con = sqlite3.connect(BASE)
    con.execute("DROP TABLE IF EXISTS signaux")
    con.execute("CREATE TABLE signaux (cle TEXT, type TEXT, gravite INTEGER, detail TEXT)")
    signaux = []

    # Nombre de modifications déclarées par contrat (lignes de type « A »).
    modifs = defaultdict(int)
    for org, pid, ref, n in con.execute(
            "SELECT owner_org, procurement_id, reference_number, COUNT(*) FROM brut "
            "WHERE instrument_type = 'A' GROUP BY owner_org, procurement_id, reference_number"):
        modifs[f"{org}|{pid.strip() or ref.strip()}"] += n

    lignes = con.execute(
        f"SELECT cle, valeur, valeur_originale, methode, raison, nb_offres, ministere, fournisseur_id, "
        f"date_contrat FROM contrats WHERE {PERIODE}").fetchall()
    groupes = defaultdict(list)
    for cle, val, orig, meth, raison, offres, minis, fid, dt in lignes:
        if orig and orig >= 25000 and val > orig * 1.25:
            ratio = val / orig
            if ratio > 20:
                if val >= 1e6:
                    signaux.append((cle, "SAUT", 0, f"Valeur actuelle {ratio:.0f} fois le montant signé."))
            else:
                g = 3 if ratio > 2 else 2 if ratio > 1.5 else 1
                signaux.append((cle, "CROISSANCE", g, f"+{(ratio - 1) * 100:.0f} % depuis la signature."))
        if meth == "TN" and val >= 100000:
            g = 3 if val >= 1e7 else 2 if val >= 1e6 else 1
            motif = RAISONS.get(raison or "", "raison non précisée")
            signaux.append((cle, "SANS_APPEL", g, f"Sans appel d'offres. Raison déclarée : {motif}."))
        if meth in ("TC", "OB", "ST") and offres == "1" and val >= 100000:
            signaux.append((cle, "SOUM_UNIQUE", 2 if val >= 1e6 else 1,
                            "Appel d'offres concurrentiel : une seule entreprise a soumissionné."))
        n = modifs.get(cle, 0)
        if n >= 3:
            signaux.append((cle, "MODIFS_SERIE", 3 if n >= 6 else 2, f"{n} modifications déclarées."))
        if meth == "TN" and val < 25000 and fid:
            exercice = int(dt[:4]) - (dt[5:7] < "04")
            groupes[(minis, fid, exercice)].append((cle, val))

    for (_, _, exercice), cs in groupes.items():
        total = sum(v for _, v in cs)
        if len(cs) >= 5 and total >= 100000:
            somme = f"{total:,.0f}".replace(",", "\u202f")
            detail = (f"{len(cs)} contrats sans appel d'offres de moins de 25 000 $ au même fournisseur "
                      f"en {exercice}-{exercice + 1}, pour {somme} $ au total.")
            signaux += [(cle, "PETITS_REPETES", 2 if len(cs) >= 10 else 1, detail) for cle, _ in cs]

    con.executemany("INSERT INTO signaux VALUES (?,?,?,?)", signaux)
    con.execute("CREATE INDEX i_sig_cle ON signaux(cle)")
    con.execute("CREATE INDEX i_sig_type ON signaux(type, gravite)")
    con.execute("DROP TABLE IF EXISTS signaux_contrat")
    con.execute("""CREATE TABLE signaux_contrat AS SELECT cle, COUNT(DISTINCT type) nb,
                   GROUP_CONCAT(type) types FROM signaux GROUP BY cle""")
    con.execute("CREATE UNIQUE INDEX i_sigc ON signaux_contrat(cle)")
    con.commit()
    for t, n in con.execute("SELECT type, COUNT(*) FROM signaux GROUP BY type ORDER BY 2 DESC"):
        print(f"{t:15} {n:>8}")
    print("★ 3 signaux ou plus :", con.execute("SELECT COUNT(*) FROM signaux_contrat WHERE nb >= 3").fetchone()[0])
    con.close()


if __name__ == "__main__":
    main()
