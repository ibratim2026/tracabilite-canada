# Traçabilité Canada — prototype

Le grand frère fédéral de Traçabilité Québec. Même posture : pro-transparence,
anti-complot. Un signal n'est pas une accusation, chaque chiffre a sa source.

## État (25 septembre 2026)

Pages (toutes statiques, exportées par `pipeline/exporter.py`). Menu à deux
niveaux comme Traçabilité Québec : **Suivre l'argent** (Où va l'argent,
Contrats, Subventions, Lobbying, Les écarts, À examiner, Ministères) ·
**Comprendre** · Chercher · Méthode.

- `/suivre-l-argent/` — deux diagrammes de flux (budget ; ministères → contrats
  ou subventions → bénéficiaires), bilan « ce qui va bien / mérite une
  explication », plus grands écarts (`app/sankey.py`, SVG sans bibliothèque)
- `/ecarts/` — écart = valeur actuelle vs montant signé ; drapeaux +10/+25/+50 %
- `/contrat/<ministère>/<numéro>/` — ~11 200 fiches (≥ 5 M$, écart > 50 % dès
  250 000 $, ou ★) avec la trace trimestre par trimestre (`pipeline/traces.py`)

- `/` — « Ce qu'Ottawa achète » (contrats 2025-2026)
- `/subventions/` — « Ce qu'Ottawa donne » (subventions et contributions)
- `/a-examiner/` et `/a-examiner/<signal>/` — six signaux publics (`pipeline/signaux.py`)
- `/chercher/` — recherche dans ~300 000 entreprises et organismes, index
  découpé par préfixe de mot (`/recherche/XX.json`)
- `/entreprise/<slug>/` — ~26 700 fiches (≥ 1 M$ reçus, contrats + subventions)
- `/ministere/<code>/`, `/ministeres/`
- `/comprendre/` : budget en une page, Ottawa et les provinces, On clarifie
  (chiffres sourcés dans `app/contenu/budget.json`, à rafraîchir à chaque
  Rapport financier annuel, en général à l'automne)
- `/methode/`

Plan validé par William : 1 ✔ recherche et fiches · 2 ✔ subventions ·
3 ✔ signaux · 4 ✔ lobbying (fichiers manuels, voir plus bas) · 5 ✔ Comprendre ·
élection fédérale en dernier.

## Règles de publication (non négociables)

- **Les particuliers ne sont jamais nommés** (type P et « rapports en lots »
  des subventions) : comptés dans les totaux, jamais affichés ni cherchables.
- **Pas de champ « ancien fonctionnaire »** : il vise des personnes.
- Aucun mot accusatoire : « ★ À examiner en priorité », jamais « fraude ».
- Pas de quarantaine automatique pour les subventions : testée, elle
  effaçait des faits réels (WE Charity ramenée à 0 $, etc.).

## Poids du site

~38 000 pages, ~630 Mo (limite GitHub Pages : 1 Go). Les fiches de contrats à 1 M$ portaient le site à 770 Mo : seuil relevé à 5 M$. Le poids vient du
nombre de fiches (≥ 1 M$). Si ça devient un problème : monter le seuil
`SEUIL_FICHE` (2 M$ ≈ 17 000 fiches) dans `analyser.py` ET `app.py`.

## En ligne

- Site public : https://ibratim2026.github.io/tracabilite-canada/ (branche `gh-pages`)
- Code : https://github.com/ibratim2026/tracabilite-canada (branche `main`)
- **Mise à jour automatique chaque jour à 5 h 30** : launchd
  `com.tracabilite-canada.maj` → `~/Library/Application Support/tracabilite-canada/run-maj.sh`
  → `mettre_a_jour.sh` (téléchargement des contrats et des subventions, base, chiffres, signaux, export, publication). Dure environ 10 minutes.
  Journal : `data/maj.log`. Chaque publication remplace la précédente sur
  `gh-pages` (un seul commit, sinon +200 Mo par jour).
- L'export échoue s'il trouve un lien interne mort : rien n'est publié.

## Faire tourner

```bash
cd ~/Projets/tracabilite-canada
curl -sL -o data/contracts.csv "https://open.canada.ca/data/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b/resource/fac950c0-00d5-4ec1-a4d3-9cbebf98a305/download/contracts.csv"
.venv/bin/python pipeline/ingerer.py     # CSV (640 Mo) -> data/canada.db
.venv/bin/python pipeline/analyser.py    # nettoyage + app/contenu/chiffres.json
.venv/bin/python app/app.py              # http://localhost:5072
.venv/bin/python pipeline/exporter.py    # site statique complet dans build/ (~1 min)
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

## Lobbying (étape 4)

Page `/lobbying/` et section « Lobbying déclaré » sur les fiches
(`pipeline/ingerer_lobby.py` puis `pipeline/lobby.py`). Seules les
organisations et les institutions sont affichées, jamais les noms des
lobbyistes ni des responsables rencontrés.

Le Commissariat au lobbying bloque les téléchargements automatisés (on ne
contourne pas). **Environ une fois par mois**, William télécharge à la main
ces deux fichiers et les dépose dans `data/lobby/` (en remplaçant les
anciens) ; la mise à jour du lendemain matin les dézippe et les relit :

- https://lobbycanada.gc.ca/media/zwcjycef/registrations_enregistrements_ocl_cal.zip
- https://lobbycanada.gc.ca/media/mqbbmaqk/communications_ocl_cal.zip

Pièges : fichiers en Windows-1252 (pas UTF-8) ; une même organisation change
de numéro à chaque enregistrement, on regroupe par nom normalisé.
