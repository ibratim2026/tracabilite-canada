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
  const date = (s) => new Date(s + "T12:00").toLocaleDateString("fr-CA", { day: "numeric", month: "long", year: "numeric" }).replace(/^1 /, "1er ");

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

// ---- Recherche d'entreprises, entièrement dans le navigateur.
(function recherche() {
  const champ = document.getElementById("q");
  const liste = document.getElementById("resultats");
  const etat = document.getElementById("etat");
  if (!champ || !liste || !window.INDEX_RECHERCHE) return;

  // Même logique que le serveur : sans accents, sans ponctuation, en majuscules.
  const TYPES = { F: "Entreprise", N: "Organisme sans but lucratif", S: "Université ou institution publique",
    G: "Gouvernement", A: "Bénéficiaire autochtone", I: "Organisation internationale", O: "Organisme" };
  const plier = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase().replace(/[^A-Z0-9]+/g, " ").trim();
  const echapper = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // L'index est découpé par les deux premières lettres de chaque mot du nom :
  // on ne charge que le morceau utile.
  const morceaux = {};

  async function charger(prefixe) {
    if (!morceaux[prefixe]) {
      etat.textContent = "Recherche…";
      morceaux[prefixe] = fetch(`${window.INDEX_RECHERCHE}/${prefixe}.json`)
        .then((r) => (r.ok ? r.json() : []))
        .then((brut) => brut.map(([nom, total, nb, slug, type]) => ({ nom, total, nb, slug, type, cle: " " + plier(nom) + " " })));
    }
    return morceaux[prefixe];
  }

  function surligner(nom, mots) {
    let html = echapper(nom);
    for (const m of mots) {
      if (m.length < 2) continue;
      html = html.replace(new RegExp("(" + m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "i"), "<mark>$1</mark>");
    }
    return html;
  }

  async function chercher() {
    const q = plier(champ.value);
    const url = new URL(location.href);
    if (champ.value) url.searchParams.set("q", champ.value); else url.searchParams.delete("q");
    history.replaceState(null, "", url);
    if (q.length < 2) { liste.innerHTML = ""; etat.textContent = "Commencez à taper un nom."; return; }
    const mots = q.split(" ");
    // Le mot le plus long est le plus discriminant : c'est son morceau qu'on charge.
    const VIDES = new Set(["INC", "LTD", "LTEE", "LIMITED", "CORP", "CORPORATION", "CO", "THE", "OF", "AND", "DE", "DU",
      "DES", "LA", "LE", "LES", "ET", "EN", "LP", "LLP", "ULC", "SA", "INCORPORATED", "COMPANY"]);
    const pivot = mots.filter((m) => m.length >= 2 && !VIDES.has(m)).sort((x, y) => y.length - x.length)[0];
    if (!pivot) { liste.innerHTML = ""; etat.textContent = "Tapez un mot plus précis du nom."; return; }
    const donnees = await charger(pivot.slice(0, 2));
    if (plier(champ.value) !== q) return;   // l'utilisateur a continué de taper
    // Chaque mot tapé doit apparaître au début d'un mot du nom.
    const trouves = donnees.filter((e) => mots.every((m) => e.cle.includes(" " + m)));
    const n = trouves.length;
    etat.textContent = n === 0 ? "Aucun résultat. Essayez une partie du nom seulement."
      : `${n.toLocaleString("fr-CA")} résultat${n > 1 ? "s" : ""}` + (n > 30 ? " · les 30 plus importants" : "");
    const motsBruts = champ.value.trim().split(/\s+/);
    liste.innerHTML = trouves.slice(0, 30).map((e) => {
      const detail = `${TYPES[e.type] || "Entreprise"} · ${e.nb.toLocaleString("fr-CA")} contrat${e.nb > 1 ? "s" : ""} ou subvention${e.nb > 1 ? "s" : ""} depuis 2017`;
      if (e.slug) {
        return `<li><a class="resultat avec-fiche" href="${window.BASE}/entreprise/${e.slug}/">
          <span class="resultat-nom">${surligner(e.nom, motsBruts)}</span><span class="resultat-total">${argent(e.total)}</span>
          <span class="resultat-detail">${detail} · voir la fiche →</span></a></li>`;
      }
      const officiel = "https://rechercher.ouvert.canada.ca/contrats/?search_text=" + encodeURIComponent(e.nom);
      return `<li class="resultat"><span class="resultat-nom">${surligner(e.nom, motsBruts)}</span><span class="resultat-total">${argent(e.total)}</span>
        <span class="resultat-detail">${detail} · pas de fiche détaillée (moins de 1 M$) · <a href="${officiel}">contrats sur le site officiel ↗</a></span></li>`;
    }).join("");
  }

  let minuterie;
  champ.addEventListener("input", () => { clearTimeout(minuterie); minuterie = setTimeout(chercher, 120); });
  const depart = new URL(location.href).searchParams.get("q");
  if (depart) { champ.value = depart; chercher(); }
})();

// ---- « Acheter ou donner ? » : la devinette à choix.
(function choix() {
  const boite = document.getElementById("choix");
  if (!boite) return;
  const bonne = boite.dataset.bonne;
  boite.querySelectorAll("[data-choix]").forEach((b) => b.addEventListener("click", () => {
    const juste = b.dataset.choix === bonne;
    document.getElementById("choix-verdict").textContent = juste
      ? (boite.dataset.juste || "Exact. La plupart des gens pensent le contraire.")
      : (boite.dataset.faux || "Ce sont les subventions, et de loin. La plupart des gens pensent le contraire.");
    boite.querySelectorAll("[data-choix]").forEach((x) => { x.disabled = true; x.classList.toggle("choisi", x === b); });
    document.getElementById("choix-reponse").hidden = false;
  }));
})();

// ---- Une vraie entente, tirée au hasard.
(function ententeAuHasard() {
  const fiche = document.getElementById("fiche-sub");
  const donnees = document.getElementById("echantillon-sub");
  if (!fiche || !donnees) return;
  const ententes = JSON.parse(donnees.textContent);
  const echapper = (s) => String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const date = (s) => new Date(s + "T12:00").toLocaleDateString("fr-CA", { day: "numeric", month: "long", year: "numeric" }).replace(/^1 /, "1er ");
  function tirer() {
    const e = ententes[Math.floor(Math.random() * ententes.length)];
    const ville = (e.ville || "").split(/\s*[|│]\s*/).pop();
    const lieu = [ville, e.province].filter(Boolean).join(", ");
    fiche.innerHTML = `
      <p class="surtitre">${echapper(e.ministere)}</p>
      <p class="fiche-quoi">${echapper(e.titre || e.programme)}</p>
      <p class="fiche-montant">${argent(e.valeur)}</p>
      <dl>
        <dt>Bénéficiaire</dt><dd>${echapper(e.nom)}${e.type ? ` <span class="etiquette">${echapper(e.type)}</span>` : ""}</dd>
        ${lieu ? `<dt>Où</dt><dd>${echapper(lieu)}</dd>` : ""}
        <dt>Programme</dt><dd>${echapper(e.programme)}</dd>
        <dt>Début</dt><dd>${date(e.debut)}</dd>
      </dl>`;
    fiche.style.animation = "none"; void fiche.offsetWidth; fiche.style.animation = "";
  }
  document.getElementById("tirer-sub").addEventListener("click", tirer);
  tirer();
})();

// ---- Couverture : l'argent dépensé depuis l'arrivée sur la page.
(function compteur() {
  const el = document.getElementById("compteur");
  if (!el) return;
  const parSeconde = Number(el.dataset.parSeconde);
  const debut = performance.now();
  const afficher = () => {
    const v = Math.floor(((performance.now() - debut) / 1000) * parSeconde);
    el.textContent = v.toLocaleString("fr-CA") + "\u00a0$";
  };
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setInterval(afficher, 1000);
  } else {
    const boucle = () => { afficher(); requestAnimationFrame(boucle); };
    requestAnimationFrame(boucle);
  }
})();
