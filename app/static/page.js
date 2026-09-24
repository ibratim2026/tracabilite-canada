// Traçabilité Canada — interactions de la page vitrine. Aucune dépendance.

const nb = (v, d = 0) => v.toLocaleString("fr-CA", { minimumFractionDigits: d, maximumFractionDigits: d });
function argent(v) {
  if (v >= 1e9) return `${nb(v / 1e9, 1)} G$`;
  if (v >= 1e6) return `${nb(v / 1e6, v >= 1e8 ? 0 : 1)} M$`;
  return `${nb(v)} $`;
}

// ---- 1. La devinette : curseur logarithmique de 100 M$ à 1 000 G$.
(function devinette() {
  const boite = document.getElementById("devinette");
  if (!boite) return;
  const reponse = Number(boite.dataset.reponse);
  const curseur = document.getElementById("curseur");
  const sortie = document.getElementById("estimation");
  const valeur = () => 1e8 * Math.pow(1e4, curseur.value / 100);
  const afficher = () => { sortie.textContent = argent(valeur()); };
  curseur.addEventListener("input", afficher);
  afficher();

  document.getElementById("reveler").addEventListener("click", (e) => {
    const estime = valeur();
    const rapport = estime / reponse;
    let verdict;
    if (rapport > 0.8 && rapport < 1.25) verdict = "Dans le mille, ou presque. Bravo.";
    else if (rapport >= 1.25) verdict = `Vous aviez visé ${nb(rapport, rapport < 10 ? 1 : 0)} fois trop haut. La plupart des gens surestiment : on entend parler des gros contrats, jamais des 65 000 petits.`;
    else verdict = `Vous aviez visé ${nb(1 / rapport, 1 / rapport < 10 ? 1 : 0)} fois trop bas. Les milliards s'additionnent plus vite qu'on pense.`;
    document.getElementById("verdict").textContent = `Votre estimation : ${argent(estime)}. ${verdict}`;
    document.getElementById("reponse").hidden = false;
    curseur.disabled = true;
    e.currentTarget.hidden = true;
  });
})();

// ---- 11. Un vrai contrat, tiré au hasard.
(function contratAuHasard() {
  const fiche = document.getElementById("fiche");
  const donnees = document.getElementById("echantillon");
  if (!fiche || !donnees) return;
  const contrats = JSON.parse(donnees.textContent);
  const echapper = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const date = (s) => new Date(s + "T12:00").toLocaleDateString("fr-CA", { day: "numeric", month: "long", year: "numeric" });

  function tirer() {
    const c = contrats[Math.floor(Math.random() * contrats.length)];
    const grossi = c.originale > 0 && c.valeur > c.originale * 1.001;
    fiche.innerHTML = `
      <p class="surtitre">${echapper(c.ministere)}</p>
      <p class="fiche-quoi">${echapper(c.description)}</p>
      <p class="fiche-montant">${argent(c.valeur)}</p>
      <dl>
        <dt>Fournisseur</dt><dd>${echapper(c.fournisseur)}</dd>
        <dt>Signé le</dt><dd>${date(c.date)}</dd>
        <dt>Attribution</dt><dd>${echapper(c.methode)}</dd>
      </dl>
      ${grossi ? `<p class="fiche-note">Signé pour ${argent(c.originale)} au départ, puis modifié.</p>` : ""}`;
    fiche.style.animation = "none"; void fiche.offsetWidth; fiche.style.animation = "";
  }
  document.getElementById("tirer").addEventListener("click", tirer);
  tirer();
})();
