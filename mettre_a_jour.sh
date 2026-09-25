#!/bin/zsh
# Mise à jour quotidienne de Traçabilité Canada, lancée par launchd à 5 h 30.
#
# 1. Télécharge le fichier fédéral des contrats (640 Mo). Si le téléchargement
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

.venv/bin/python pipeline/ingerer.py
.venv/bin/python pipeline/analyser.py > /dev/null
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
