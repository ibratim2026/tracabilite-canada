"""Charge les rapports de communication du Registre des lobbyistes.

Source : Commissariat au lobbying du Canada, données ouvertes
(« Monthly Communication Reports »). Le site du Commissariat bloque les
téléchargements automatisés : les fichiers sont téléchargés à la main et
déposés dans data/lobby/. Ce script lit ce qui s'y trouve.

On garde les organisations et les institutions. Les noms des lobbyistes et
des titulaires de charge publique restent dans le registre officiel : le site
suit l'argent et les organisations, pas les personnes.
"""
import csv
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "data" / "lobby"
BASE = RACINE / "data" / "canada.db"


def lire(nom):
    # Fichiers encodés en Windows-1252 (pas en UTF-8) par le Commissariat.
    with open(DOSSIER / "comm" / nom, encoding="cp1252", errors="replace", newline="") as f:
        yield from csv.DictReader(f)


def propre(v):
    return "" if v in (None, "null") else v.strip()


def dezipper():
    """Dézippe les archives déposées à la main, si elles sont plus récentes."""
    import zipfile
    zips = {"communications_ocl_cal.zip": "comm", "registrations_enregistrements_ocl_cal.zip": "enr"}
    for nom, dossier in zips.items():
        archive = DOSSIER / nom
        if archive.exists():
            cible = DOSSIER / dossier
            temoin = cible / "Codes_SubjectMatterTypesExport.csv"
            if not temoin.exists() or archive.stat().st_mtime > temoin.stat().st_mtime:
                zipfile.ZipFile(archive).extractall(cible)
                temoin.touch()


def main():
    dezipper()
    if not (DOSSIER / "comm" / "Communication_PrimaryExport.csv").exists():
        print("Pas de données de lobbying dans data/lobby/comm : étape sautée.")
        return
    csv.field_size_limit(sys.maxsize)
    con = sqlite3.connect(BASE)
    con.execute("DROP TABLE IF EXISTS lobby_comm")
    con.execute("""CREATE TABLE lobby_comm (id TEXT PRIMARY KEY, client_num TEXT, client_en TEXT, client_fr TEXT,
                   date TEXT, type_enr TEXT, publie TEXT)""")
    con.executemany("INSERT OR REPLACE INTO lobby_comm VALUES (?,?,?,?,?,?,?)", (
        (propre(r["COMLOG_ID"]), propre(r["CLIENT_ORG_CORP_NUM"]), propre(r["EN_CLIENT_ORG_CORP_NM_AN"]),
         propre(r["FR_CLIENT_ORG_CORP_NM"]), propre(r["COMM_DATE"])[:10], propre(r["REG_TYPE_ENR"]),
         propre(r["POSTED_DATE_PUBLICATION"])[:10]) for r in lire("Communication_PrimaryExport.csv")))
    con.execute("DROP TABLE IF EXISTS lobby_inst")
    con.execute("CREATE TABLE lobby_inst (id TEXT, institution TEXT)")
    # Une ligne par communication et par institution (pas par personne rencontrée).
    vus = set()
    lignes = []
    for r in lire("Communication_DpohExport.csv"):
        cle = (propre(r["COMLOG_ID"]), propre(r["INSTITUTION"]))
        if cle[1] and cle not in vus:
            vus.add(cle)
            lignes.append(cle)
    con.executemany("INSERT INTO lobby_inst VALUES (?,?)", lignes)
    con.execute("DROP TABLE IF EXISTS lobby_sujets")
    con.execute("CREATE TABLE lobby_sujets (id TEXT, sujet TEXT)")
    con.executemany("INSERT INTO lobby_sujets VALUES (?,?)", (
        (propre(r["COMLOG_ID"]), propre(r.get("SUBJECT_CODE_OBJET") or r.get("SUBJECT_MATTER_CODE") or ""))
        for r in lire("Communication_SubjectMattersExport.csv")))
    con.execute("CREATE INDEX i_li ON lobby_inst(id)")
    con.execute("CREATE INDEX i_ls ON lobby_sujets(id)")
    con.commit()
    n = con.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM lobby_comm").fetchone()
    print(f"Communications : {n[0]} ({n[1]} → {n[2]}), liens institution : {len(lignes)}")
    con.close()


if __name__ == "__main__":
    main()
