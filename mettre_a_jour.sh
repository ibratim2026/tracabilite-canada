#!/bin/zsh
# Mise à jour quotidienne de Traçabilité Canada, lancée par launchd à 5 h 30.
#
# 1. Télécharge les fichiers fédéraux des contrats (640 Mo) et des subventions
#    (2,3 Go). Si le téléchargement
#    échoue ou semble tronqué, on s'arrête : le site garde les données d'hier.
# 2. Reconstruit la base, recalcule les chiffres, exporte le site statique.
#    L'export vérifie chaque lien interne et échoue plutôt que de publier un
#    lien mort.
# 3. Publie build/ sur la branche gh-pages. Chaque publication remplace la
#    précédente (un seul commit) pour que le dépôt ne grossisse pas de
#    200 Mo par jour.
#
# Journal : data/maj.log

set -e
cd "$(dirname "$0")"
exec >> data/maj.log 2>&1
echo ""
echo "=== Mise à jour, $(date '+%Y-%m-%d %H:%M') ==="

URL="https://open.canada.ca/data/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b/resource/fac950c0-00d5-4ec1-a4d3-9cbebf98a305/download/contracts.csv"
curl -sSL --retry 3 --max-time 1800 -o data/contracts.csv.tmp "$URL"
TAILLE=$(stat -f%z data/contracts.csv.tmp)
if (( TAILLE < 400000000 )) || ! head -c 200 data/contracts.csv.tmp | grep -q "reference_number"; then
  echo "Téléchargement suspect ($TAILLE octets) : on garde les données d'hier."
  rm -f data/contracts.csv.tmp
  exit 1
fi
mv data/contracts.csv.tmp data/contracts.csv
echo "Téléchargé : $TAILLE octets"

# Subventions et contributions (2,3 Go), même prudence.
URL_SUB="https://open.canada.ca/data/dataset/432527ab-7aac-45b5-81d6-7597107a7013/resource/1d15a62f-5656-49ad-8c88-f40ce689d831/download/grants.csv"
curl -sSL --retry 3 --max-time 3600 -o data/grants.csv.tmp "$URL_SUB"
TAILLE_SUB=$(stat -f%z data/grants.csv.tmp)
if (( TAILLE_SUB < 1500000000 )) || ! head -c 200 data/grants.csv.tmp | grep -q "ref_number"; then
  echo "Téléchargement des subventions suspect ($TAILLE_SUB octets) : on garde les données d'hier."
  rm -f data/grants.csv.tmp
  exit 1
fi
mv data/grants.csv.tmp data/grants.csv
echo "Subventions téléchargées : $TAILLE_SUB octets"

.venv/bin/python pipeline/ingerer.py
.venv/bin/python pipeline/ingerer_subventions.py
.venv/bin/python pipeline/analyser.py > /dev/null
.venv/bin/python pipeline/signaux.py
.venv/bin/python pipeline/traces.py
# Lobbying : fichiers déposés à la main dans data/lobby/ (téléchargement
# automatisé bloqué par le Commissariat). Sautés s'ils sont absents.
.venv/bin/python pipeline/ingerer_lobby.py
.venv/bin/python pipeline/lobby.py
.venv/bin/python pipeline/exporter.py

# Dépôt git temporaire hors du dossier exporté : jamais de .git dans build/.
TMPGIT=$(mktemp -d)/git
export GIT_DIR="$TMPGIT" GIT_WORK_TREE="$PWD/build"
git init -q -b gh-pages
git add -A
git -c user.name="William Carrier" -c user.email="williamcarrierlive@gmail.com" \
    commit -qm "Site statique — données du $(date '+%Y-%m-%d')"
git push -q -f https://github.com/ibratim2026/tracabilite-canada.git gh-pages
unset GIT_DIR GIT_WORK_TREE
rm -rf "$(dirname "$TMPGIT")"

echo "=== Publié : $(date '+%Y-%m-%d %H:%M') ==="
