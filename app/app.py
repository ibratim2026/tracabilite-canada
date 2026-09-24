"""Traçabilité Canada — prototype. Une seule page vitrine pour l'instant."""
import json
from pathlib import Path
from flask import Flask, render_template

RACINE = Path(__file__).resolve().parent
app = Flask(__name__)


def charger(nom):
    return json.loads((RACINE / "contenu" / f"{nom}.json").read_text())


# ---- Formats à la québécoise : espace insécable pour les milliers, virgule décimale.
def nombre(v, decimales=0):
    s = f"{v:,.{decimales}f}"
    return s.replace(",", " ").replace(".", ",")


def argent(v):
    """18 296 996 058 -> « 18,3 G$ » ; 24 966 -> « 24 966 $ »."""
    if abs(v) >= 1e9:
        return f"{nombre(v / 1e9, 1)} G$"
    if abs(v) >= 1e6:
        return f"{nombre(v / 1e6, 0 if abs(v) >= 1e8 else 1)} M$"
    return f"{nombre(v)} $"


def pourcent(v):
    return f"{nombre(v * 100)} %"


app.jinja_env.filters.update(nombre=nombre, argent=argent, pourcent=pourcent)


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
    return render_template("accueil.html", c=c)


if __name__ == "__main__":
    app.run(port=5072, debug=True)
