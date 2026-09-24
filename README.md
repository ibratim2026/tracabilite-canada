# Traçabilité Canada — prototype

Le grand frère fédéral de Traçabilité Québec. Même posture : pro-transparence,
anti-complot. Un signal n'est pas une accusation, chaque chiffre a sa source.

## État (24 septembre 2026)

Une seule page vitrine, « Ce qu'Ottawa achète », construite sur les contrats
fédéraux de plus de 10 000 $ (exercice 2025-2026). Sert à tester deux choses :
la qualité des données fédérales, et le ton de vulgarisation.

## En ligne

- Site public : https://ibratim2026.github.io/tracabilite-canada/ (branche `gh-pages`)
- Code : https://github.com/ibratim2026/tracabilite-canada (branche `main`)
- Republier : `.venv/bin/python pipeline/exporter.py`, puis pousser `build/` sur
  `gh-pages`. Pas de mise à jour automatique pour l'instant.

## Faire tourner

```bash
cd ~/Projets/tracabilite-canada
curl -sL -o data/contracts.csv "https://open.canada.ca/data/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b/resource/fac950c0-00d5-4ec1-a4d3-9cbebf98a305/download/contracts.csv"
.venv/bin/python pipeline/ingerer.py     # CSV (640 Mo) -> data/canada.db
.venv/bin/python pipeline/analyser.py    # nettoyage + app/contenu/chiffres.json
.venv/bin/python app/app.py              # http://localhost:5072
```

## Pièges des données fédérales (à lire)

- **Une ligne n'est pas un contrat.** Chaque modification republie une ligne
  avec le total cumulé. Additionner les lignes double les montants
  (2024-2025 : 117 G$ naïf contre 56,6 G$ réel).
- **Les offres à commandes (SOSA)** sont des plafonds, pas des engagements :
  exclues des sommes.
- **Coquilles.** Règle de quarantaine volontairement étroite : une version est
  écartée seulement si elle se contredit elle-même (voir `analyser.py`). Une
  règle plus large écartait des contrats réels (P3 de la Défense, Canadarm3).
- **Valeur totale, pas dépense annuelle.** Un contrat de 25 ans est inscrit en
  entier à sa date de signature : une année peut doubler à cause de 7 contrats.
- **Population** : Statistique Canada 17-10-0009-01, codée en dur dans
  `analyser.py` — à rafraîchir.
- **Budget total** : Rapport financier annuel 2024-2025 (547,3 G$), codé en dur.

## Prochaines étapes possibles

Subventions et contributions, registre des lobbyistes (croisement
lobbying → contrats), fiches fournisseurs, export statique, mise à jour
automatique.
