"""Diagramme de flux (« Sankey ») dessiné en SVG, sans bibliothèque.

On donne des colonnes de nœuds et des liens (source, cible, valeur). La
hauteur de chaque nœud et l'épaisseur de chaque bande sont proportionnelles
aux montants : l'œil suit l'argent de gauche à droite.
"""


def sankey(colonnes, noeuds, liens, largeur=1100, hauteur=520, marge_g=250, marge_d=300,
           ecart=20, epaisseur=14):
    entrant, sortant = {}, {}
    for s, c, v in liens:
        sortant[s] = sortant.get(s, 0) + v
        entrant[c] = entrant.get(c, 0) + v
    valeur = {n: max(entrant.get(n, 0), sortant.get(n, 0)) for col in colonnes for n in col}

    # Une seule échelle pour tout le diagramme : la colonne la plus chargée remplit la hauteur.
    echelle = min((hauteur - ecart * (len(col) - 1)) / sum(valeur[n] for n in col) for col in colonnes)
    pas = (largeur - marge_g - marge_d - epaisseur) / max(len(colonnes) - 1, 1)

    boites = {}
    for i, col in enumerate(colonnes):
        total = sum(valeur[n] for n in col) * echelle + ecart * (len(col) - 1)
        y = (hauteur - total) / 2
        for n in col:
            h = max(valeur[n] * echelle, 1.5)
            boites[n] = dict(id=n, x=marge_g + i * pas, y=y, w=epaisseur, h=h, col=i,
                             derniere=(i == len(colonnes) - 1), premiere=(i == 0),
                             valeur=valeur[n], **noeuds[n])
            y += h + ecart

    # Les bandes partent et arrivent dans l'ordre vertical, pour ne pas se croiser inutilement.
    depart = {n: 0.0 for n in boites}
    arrivee = {n: 0.0 for n in boites}
    bandes = []
    for s, c, v in sorted(liens, key=lambda l: (boites[l[0]]["y"], boites[l[1]]["y"])):
        a, b = boites[s], boites[c]
        h = v * echelle
        y0 = a["y"] + depart[s]
        y1 = b["y"] + arrivee[c]
        depart[s] += h
        arrivee[c] += h
        x0, x1 = a["x"] + a["w"], b["x"]
        xm = (x0 + x1) / 2
        d = (f"M{x0:.1f},{y0:.1f} C{xm:.1f},{y0:.1f} {xm:.1f},{y1:.1f} {x1:.1f},{y1:.1f} "
             f"L{x1:.1f},{y1 + h:.1f} C{xm:.1f},{y1 + h:.1f} {xm:.1f},{y0 + h:.1f} {x0:.1f},{y0 + h:.1f} Z")
        bandes.append(dict(d=d, valeur=v, de=a["nom"], vers=b["nom"],
                           classe=noeuds[s].get("classe_lien") or noeuds[c].get("classe_lien") or ""))
    return dict(largeur=largeur, hauteur=hauteur, noeuds=list(boites.values()), bandes=bandes)
