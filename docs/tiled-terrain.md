# Tuilage du terrain et des couches de simulation

## Ce que fait SkiEO-HDTerrain

Lecture de **SkiEO-HDTerrain 0.6.3**, par Reyman, licence MIT, fourni dans
`Reyman-SkiEO-Installer-1.0/files/SkiEO-HDTerrain`. Son README indique des essais
avec le chargeur 1.24.4 et la démo 26036197.

Le module attribue à chaque section du sol une texture de couleur et sa chaîne
de mipmaps. Il convertit les UV globaux en UV locaux, les borne aux centres des
pixels et utilise l'adressage clamp. Il conserve les positions des sommets.
Il ajoute séparément des routes sans collision, surélevées de 1,5 m, et des
bâtiments décoratifs instanciés. Ces éléments ne remplacent ni le cache de
hauteurs, ni la neige, ni les terrassements natifs.

Dans Kitzbühel 0.1.2, la couleur standard fait 512 × 512 pixels pour 8 × 8 km.
Le dossier HD contient 10 × 10 tuiles de 512 × 512 pixels, chacune couvrant
800 × 800 m. Le fichier d'altitudes reste un R16 de 801 × 801 valeurs espacées
de 10 m ; `sample_step = 2` donne principalement un maillage visible à 20 m.
La couleur HD ne fournit donc pas de nouvelles mesures d'altitude.

## Essai avec le chargeur 1.24.8

Le module original est copié sans modification dans une installation de test,
avec un préfixe Proton séparé et un affichage hors écran. Il est chargé normalement
par UE4SS dans son propre environnement Lua. Le journal confirme :

- 100 tuiles de couleur appliquées, toutes avec mipmaps, aucune erreur ;
- 100 sections avec UV locaux ;
- 2 697 routes créées, avec **4 477 sondages de hauteur sans collision** ;
- 4 778 bâtiments décoratifs placés, de deux types, aucune erreur annoncée.

Les sondages manquants sont comptés par le module : il réutilise l'autre bord,
la dernière hauteur trouvée ou zéro. Leur cause exacte n'est pas établie par ce
compteur ; il ne permet pas de valider la hauteur de toutes les routes.
Les preuves sont sous `build/flying-snow/hd-standalone/`.
Ce contrôle vérifie l'application des textures et le chargement des décors ;
il ne constitue pas une qualification complète de l'extension.

Une tentative précédente d'exécuter le script à chaud dans l'environnement Lua
du chargeur a produit une exception UE4SS. Elle est conservée comme essai séparé,
après la qualification complète du chargeur seul. Pour tester cette extension,
utiliser son démarrage normal comme mod UE4SS indépendant.

## Généralisation à toutes les couches

L'objectif demande un tuilage commun, intégré au chargeur. L'approche de
HDTerrain peut guider le chargement des textures de couleur ; sa détection par
lecture du journal et sa correspondance entre numéro de section et numéro de
tuile dépendent du découpage interne du maillage.

Le contrat commun devrait porter l'emprise, l'origine, la taille physique des
tuiles, la résolution de chaque couche et les bordures de raccordement. Les
couches peuvent avoir des résolutions différentes, mais leurs coordonnées
monde doivent désigner le même relief.

| Couche | Travail nécessaire |
| --- | --- |
| Couleur, normales et masques | Tuiles, mipmaps et UV indépendants du découpage des sections de rendu |
| Altitudes et collision | Échantillonnage de la même surface de référence, y compris aux frontières |
| Neige visible | Géométrie assez dense pour les déformations locales et accès cohérent aux tuiles de simulation |
| Neige simulée et terrassements | Lecture, écriture et interpolation entre tuiles ; examen des limites et structures natives |
| Pentes et données dérivées | Reconstruction depuis la surface commune, avec marges entre tuiles |
| Sauvegardes et outils | Identification des tuiles, persistance des modifications et compatibilité des anciennes cartes |

La grille native 2017 × 2017 et ses transformations ne deviennent pas plus
précises en remplaçant les seules textures de couleur. Il faut examiner les
consommateurs natifs avant d'augmenter ou de répartir ces données, conserver
les gardes de compatibilité et tester les traces, le damage, la fonte et les
terrassements aux frontières. Le budget mémoire et le chargement progressif
font partie de cette évolution.

Cette généralisation n'est pas implémentée dans 1.24.8. Cette version corrige
la cohérence du relief et la déformation locale de neige sans changer le format
des cartes ni la résolution de la simulation native.
