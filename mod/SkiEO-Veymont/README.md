# SkiEO Veymont 0.9.0

Par **Albatar (Élie Millon)**, également auteur de Custom Map et de `skieomod`.
Veymont, les renards et les téléskis sont distribués dans trois archives séparées.

Carte source pour Ski-E-O!, centrée sur
Gresse-en-Vercors, le Grand Veymont et le Mont Aiguille.

Veymont n'est plus un mod UE4SS autonome et ne contient plus de niveau Unreal
cuit. `SkiEO-CustomMaps` lit `Terrain/heightmap.r16`, construit le relief et sa
collision au chargement, puis exécute le script de carte. Le dossier n'a donc
ni `enabled.txt`, ni commande propre à Veymont. Le mapmod de renards ajoute
la touche de test **F7** pour centrer la caméra sur chaque animal à tour de rôle.

## Installation de développement

Depuis la racine du dépôt, construire et installer la carte ainsi que ses
dépendances locales, puis lancer le jeu :

```bash
skieomod run mod/SkiEO-Veymont --dependency mod/SkiEO-Foxes --dependency mod/SkiEO-SurfaceLifts
```

Pour préparer les trois archives portables séparément :

```bash
skieomod build mod/SkiEO-Foxes --check-scripts
skieomod build mod/SkiEO-SurfaceLifts --check-scripts
skieomod build mod/SkiEO-Veymont --dependency mod/SkiEO-Foxes --dependency mod/SkiEO-SurfaceLifts --check-scripts
```

## Climat et enneigement de culture

La carte utilise un profil saisonnier propre à Gresse, sans neige ni température
forcées en permanence. Les prévisions et les événements restent gérés par le jeu.
[Data/climate.json](Data/climate.json) contient les statistiques 1991–2020 et leur
provenance : neige fraîche observée à Gresse (1 220 m), températures minimales et
maximales de Saint-Baudille (1 040 m), avec une correction explicite de −1,17 °C
pour les 180 m de dénivelé. La couverture des observations et les empreintes des
fichiers d'entrée sont conservées ; les jours manquants ne sont pas assimilés à
une absence de neige. Les données Météo-France sont sous Licence Ouverte 2.0 :
[données quotidiennes départementales](https://www.data.gouv.fr/datasets/donnees-climatologiques-de-base-quotidiennes).
Les fréquences et l'intensité des précipitations sont adaptées au modèle météo du jeu.

Un réseau de 21 canons natifs dessert les Bruyères (14) et les Faisans (7).
Leur implantation est une couverture conçue pour la carte, pas un inventaire
historique de la station. Ils disposent des commandes normales du jeu : activer
une session avec leur bouton d'alimentation lorsque la température le permet.
Les réglages initiaux sont −2 °C et 60 cm, avec le mode natif de contrôle activé.
Leur placement, leurs réglages et les suppressions du joueur survivent aux
sauvegardes. Une migration unique ajoute le réseau aux anciennes parties.

Les deux Pras partagent une voie de service, tout comme les deux Bessards.
Les dameuses attendent que les skieurs évacués des deux remontées aient libéré
la voie. Les perches débrayables continuent à revenir à la gare aval pendant
une fermeture normale, jusqu'au rangement complet, même sans skieur en ligne.
Ces comportements nécessitent le chargeur 1.29.0.

## Remontées mécaniques

La version 0.8.0 adapte les huit téléskis avec le mapmod `community.surface-lifts` :
gares Poma, perches animées, pylônes, câbles et transport debout au niveau de la
neige. Le Pré Levé reçoit sa gare couverte et ses deux virages. Les caractéristiques
et les approximations sont détaillées dans [le guide](../../docs/surface-lifts.md).
Le Blanchon reçoit ses gares sur portique, dont la salle des machines vitrée.
Vus du départ vers le sommet, Pré Levé, Blavet et Alleyrons montent à gauche ;
Pierre Blanche et le Blanchon montent à droite. Les deux paires Pras et Bessards
sont en miroir, avec les brins montants au centre et les retours à l’extérieur.
Les nouvelles parties utilisent le télésiège natif deux places pour le Blanchon
et tous les points intermédiaires OSM des axes. Les objets existants d'une
sauvegarde ne sont pas remplacés ; leur identité et les suppressions sont conservées.
Le chargeur de cette branche prend en charge les versions Steam **26143813**
et **26178224**, avec UE4SS **1181** pour éviter la rétention des tables Lua.

## Pistes et vue initiale

La carte configure les quatre couleurs avec `api.game:set_trail_rating_system` :
vert pour les pistes novices, bleu pour les faciles, rouge pour les intermédiaires
et noir pour les avancées et le freeride. Les sept pistes OSM intermédiaires sont
distinctes des six pistes faciles. La palette est appliquée aussi à la reprise
d'une sauvegarde. Une nouvelle partie oriente la caméra native vers le front de
neige ; une reprise conserve le cadrage enregistré par le joueur.

## Sources

- heightmap LiDAR 2017 × 3025, pas de 4 m, 8,064 × 12,096 km ;
- altitudes 745–2341 m NGF-IGN69 ;
- 20 pistes et 9 axes de remontées issus d'OpenStreetMap ;
- bâtiments fonctionnels du front de neige décrits par le script Lua.

Le chargeur produit un maillage runtime à un sommet tous les 16 m sur les
pentes ordinaires et tous les 4 m sur les falaises, avec des raccords continus
entre ces résolutions et des normales calculées à 4 m. Il génère aussi une forêt
de 383 500 arbres, la neige native et une jupe calculée automatiquement depuis
les bords du relief. Le sol utilise une texture de roche distincte de celle
des parois striées de la jupe. Le paquet ne contient plus de contour de jupe
préfabriqué ni de liste de lieux réservée à un ancien overlay.

L’extension 0.6 ajoute le Mont Aiguille et conserve le centre géographique,
les altitudes de toute l’ancienne emprise et les positions des bâtiments,
pistes et remontées. Les 255 667 arbres existants gardent leurs coordonnées ;
127 833 arbres sont ajoutés uniquement dans les nouvelles bandes. Le cache
natif reste 2017 × 2017, rééchantillonné à 4 × 6 m sur toute la carte.
Le [guide des grandes cartes](../../docs/large-maps.md) précise ces résolutions.

La version 0.7.7 utilise le mobilier de la mise à jour du jeu 25970577 :
40 panneaux aux départs des 20 pistes, avec la variante native correspondant
à leur difficulté, et 14 équipements autour de la billetterie et des services
(porte-skis doubles, bancs, tables et deux jardinières). Ces emplacements
sont des hypothèses d'aménagement autour des points existants. Ils ne
proviennent pas d'un inventaire de mobilier historique. Ils sont créés dans
les nouvelles parties ; les sauvegardes existantes conservent leurs objets.
L'[inventaire de la mise à jour](../../docs/game-update-25970577.md) détaille
les ressources disponibles et les limites de leur intégration.

La version 0.6.1 remplace quatre dalles de 500 m défectueuses près des Deux
et du Col des Deux par le MNT IGN reclassifié le 20 février 2025. Le carré
d’un kilomètre utilise entièrement ce relief corrigé ; une marge de 32 m
raccorde ses bords au reste du terrain. L’encodage R16, les positions des
arbres et l’ancienne emprise centrale sont conservés. Les sources et la
procédure reproductible sont documentées dans
[Terrain repairs](../../docs/terrain-repairs.md).

Une nouvelle partie crée le poste `Ski Patrol Hut` 14 m au sud de la billetterie,
avec la même orientation, pour représenter leur bâtiment réel commun. Le jeu
embauche et affecte deux pisteurs au poste, deux dameurs au garage et deux
agents à chacune des neuf remontées, un par terminal. Les employés déjà
embauchés sont réutilisés ; salaires, déplacements et sauvegardes restent gérés
par le jeu. Les affectations d'une sauvegarde chargée sont conservées.

MNT : IGN LiDAR HD Isère 2021–2022, EPSG:2154 / NGF-IGN69, Licence Ouverte
v2.0. Pistes, remontées et lieux : © contributeurs OpenStreetMap, ODbL.

### Albédo de calcaire blanc

Le sol utilise `Terrain/limestone-albedo.png`, une texture de calcaire blanc
compact avec un grain discret et très peu de défauts, accompagnée de neuf
niveaux de détail portables. La jupe conserve son matériau séparé.
Le bouton natif de masquage des arbres agit aussi sur la forêt portable.

La texture a été créée avec l'outil intégré imagegen, puis préparée par
`tools/build_texture_mips.py`. Prompt final : « Calcaire compact blanc cassé,
très homogène et presque sans défaut, grain minéral très fin, texture répétable,
albédo à éclairage uniforme, sans fissures importantes ni motifs diagonaux. »

Le prototype d'[extraction de surface depuis des photos](../../docs/rock-surface-extraction.md)
reprojette les photos sur le R16 à l'aide d'une caméra candidate, avec GPS et
heure EXIF quand ils sont disponibles. Il exporte des corrections bornées et
des maillages portables ; ces essais ne sont pas encore appliqués automatiquement
à la carte ni préparés en ressources Nanite.

## Illustration du menu

[Preview/veymont.png](Preview/veymont.png) sert de vignette et de fond de
chargement. Cette illustration du domaine est générée avec l'outil intégré
imagegen ; elle ne représente pas une capture du terrain en jeu. Les compteurs
du menu correspondent aux 20 pistes et 9 remontées de `Scripts/veymont_data.lua`.

Prompt final utilisé (6 octobre 2026) :

> Use case: stylized-concept. Asset type: landscape background illustration for the Ski-E-O! Custom Map loading screen and Veymont map thumbnail. Primary request: a polished cozy 3D game illustration of a snowy ski resort inspired by Gresse-en-Vercors and Grand Veymont in the French Alps. Scene: broad snow-covered slopes, dense conifer forests, a long dramatic limestone cliff summit ridge spanning the upper middle horizon, blue winter sky and soft white clouds. On the right foreground, a warm timber ski chalet with glowing windows and balcony, wooden terrace rail and a few upright skis; chair lifts climb the slopes behind it. Composition: wide landscape 16:9, scenic mountain and forest remain visible across the whole image, chalet occupies the right third; the left half is quiet snowy slopes and trees which a UI information card can cover. Style: richly textured friendly stylized 3D render, soft snow, warm carved timber, like a high quality cozy ski resort management game menu. Lighting: bright clear winter daylight, warm sunlight, blue snow shadows, welcoming atmosphere. Constraints: an illustration, no interface, no frames, no logo, no lettering, no readable signs, no text, no watermark. Generate at 1536x1024 or a wide 16:9 landscape.

La version 0.7.5 dépend du mapmod séparé `community.foxes =0.4.0`.
Les rongeurs sont simulés dans des galeries sous la neige et n'ont aucun modèle
visible. Les renards les écoutent, bondissent puis capturent leur proie. Les
changements d'animation sont fondus sur 0,16 seconde, y compris les appuis
adaptés au terrain, et restent immobiles pendant les pauses.
Cliquer sur un renard ouvre une petite fiche avec son espèce, son activité et
son habitat. La neige ne s'accumule sur son pelage que pendant les fortes
chutes locales ; son masque est doux et n'est plus découpé par triangles.
Les renards effectuent aussi de courtes courses. Leurs bonds suivent une
trajectoire balistique sous une gravité de 9,8 m/s², même lorsqu'ils ralentissent
dans la neige profonde.
Les quatre renards occupent des territoires éloignés, chacun avec forêt, prairie
et traversée nocturne d’une piste. F7 permet de visiter chaque renard.
Le contact des animaux et des traces est calibré à −12 cm par rapport à
la hauteur physique calculée, d’après des mesures de profondeur du rendu natif
sur les quatre territoires. Le maillage et la simulation de neige restent inchangés.
Les appuis utilisent le dessous des quatre pattes du modèle. Le corps suit la
pente longitudinale et reste droit en dévers, compensé par les jambes. Les
renards s'enfoncent dans la couche fraîche et ne se déplacent par bonds que
lorsque leurs jambes sont entièrement enfoncées. La cadence suit la distance
parcourue. Chaque appui dépose le profil de la semelle et déclenche un bref
crissement natif local ; les traces restent des maillages visuels temporaires.
L'adaptation des pattes se limite aux appuis visibles de près : elle s'estompe
entre 6 et 10 mètres et dès que les pattes s'enfoncent dans la neige. La foulée
est plus courte, les pattes moins écartées et les transitions sont progressives.
Les renards alternent recherche de nourriture, écoute, chasse et repos. Ils
évitent les visiteurs, les employés et les remontées en fonctionnement, et se
retirent vers un endroit calme lorsqu'ils sont dérangés. La caméra n'est pas
considérée comme une personne.
Voir le [guide mapmods](../../docs/mapmods.md) pour les habitats, animations et
le lancement local avec `--dependency mod/SkiEO-Foxes --dependency mod/SkiEO-SurfaceLifts`.
