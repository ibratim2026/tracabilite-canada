"""Charge le CSV fédéral des subventions et contributions dans SQLite.

Source : Gouvernement ouvert, « Divulgation proactive — Subventions et
contributions » (2,3 Go).
https://ouvert.canada.ca/data/fr/dataset/432527ab-7aac-45b5-81d6-7597107a7013

On ne garde que les colonnes utiles au site : les longs textes (résultats
attendus, renseignements supplémentaires) restent dans le fichier source.
"""
import csv
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CSV = RACINE / "data" / "grants.csv"
BASE = RACINE / "data" / "canada.db"

COLONNES = [
    "ref_number", "amendment_number", "amendment_date", "agreement_type", "recipient_type",
    "recipient_business_number", "recipient_legal_name", "recipient_operating_name",
    "recipient_country", "recipient_province", "recipient_city", "federal_riding_name_fr",
    "federal_riding_number", "prog_name_fr", "prog_name_en", "agreement_title_fr",
    "agreement_title_en", "agreement_value", "agreement_start_date", "agreement_end_date",
    "additional_information_fr", "owner_org", "owner_org_title",
]


def nombre(v):
    try:
        return float(v.replace(",", "").replace("$", "").strip()) if v and v.strip() else None
    except ValueError:
        return None


def main():
    csv.field_size_limit(sys.maxsize)
    con = sqlite3.connect(BASE)
    con.execute("DROP TABLE IF EXISTS sub_brut")
    con.execute(f"CREATE TABLE sub_brut ({', '.join(c + ' TEXT' for c in COLONNES)}, valeur REAL, "
                f"no_modif INTEGER)")
    marques = ", ".join("?" * (len(COLONNES) + 2))
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        lot = []
        for ligne in csv.DictReader(f):
            info = (ligne.get("additional_information_fr") or "")[:300]
            valeurs = [ligne.get(c, "") for c in COLONNES]
            valeurs[COLONNES.index("additional_information_fr")] = info
            try:
                modif = int(float(ligne["amendment_number"] or 0))
            except ValueError:
                modif = 0
            lot.append(valeurs + [nombre(ligne["agreement_value"]), modif])
            if len(lot) == 50000:
                con.executemany(f"INSERT INTO sub_brut VALUES ({marques})", lot)
                lot = []
        con.executemany(f"INSERT INTO sub_brut VALUES ({marques})", lot)
    con.execute("CREATE INDEX i_sub_ref ON sub_brut(owner_org, ref_number)")
    con.commit()
    con.close()


if __name__ == "__main__":
    main()
