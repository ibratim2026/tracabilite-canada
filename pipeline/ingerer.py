"""Charge le CSV fédéral des contrats de plus de 10 000 $ dans SQLite.

Source : Gouvernement ouvert, « Publication proactive — Contrats »
https://ouvert.canada.ca/data/fr/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b
"""
import csv, sqlite3, sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CSV = RACINE / "data" / "contracts.csv"
BASE = RACINE / "data" / "canada.db"

def nombre(v):
    try:
        return float(v.replace(",", "").replace("$", "").strip()) if v and v.strip() else None
    except ValueError:
        return None

def main():
    csv.field_size_limit(sys.maxsize)
    temp = BASE.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    con = sqlite3.connect(temp)
    with open(CSV, encoding="utf-8-sig", newline="") as f:
        lecteur = csv.DictReader(f)
        colonnes = lecteur.fieldnames
        con.execute(f"CREATE TABLE brut ({', '.join(c + ' TEXT' for c in colonnes)}, valeur REAL, valeur_originale REAL, valeur_modif REAL)")
        marques = ", ".join("?" * (len(colonnes) + 3))
        lot = []
        for ligne in lecteur:
            lot.append([ligne[c] for c in colonnes] + [nombre(ligne["contract_value"]), nombre(ligne["original_value"]), nombre(ligne["amendment_value"])])
            if len(lot) == 50000:
                con.executemany(f"INSERT INTO brut VALUES ({marques})", lot); lot = []
        con.executemany(f"INSERT INTO brut VALUES ({marques})", lot)
    con.commit()
    con.close()
    temp.replace(BASE)

if __name__ == "__main__":
    main()
