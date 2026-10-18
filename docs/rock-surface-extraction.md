# Extraction de surface rocheuse depuis des photos

`tools/extract_rock_surface.py` est un prototype hors moteur. Il estime des
normales de surface, intègre une correction de profondeur et exporte un
maillage réellement modifié. Il peut prendre le R16 portable comme géométrie
de référence. Il ne modifie ni ce R16 ni les réglages du jeu.

Avec une seule photo, l'estimation conserve les informations que fournit la
géométrie initiale et choisit la normale compatible avec l'intensité lumineuse
qui s'en écarte le moins. Il ne s'agit pas d'une mesure unique : orientation,
albédo, ombre portée et exposition peuvent expliquer le même pixel. Avec au
moins trois photos recalées de la **même surface**, prises sous des éclairages
connus suffisamment différents, le second mode utilise la stéréo photométrique
lambertienne. Les directions presque identiques ou dégénérées sont refusées.
Les gains d'exposition peuvent être calibrés explicitement ; leur estimation
automatique s'appuie sur la géométrie initiale et l'albédo supposé.

Cette méthode suit le modèle décrit par
[Woodham, Photometric method for determining surface orientation from multiple images](https://www.cs.ubc.ca/~woodham/papers/Woodham80c.pdf).
Les hypothèses de surface diffuse, d'éclairage et de recalage restent
nécessaires. Des photos prises de points de vue différents ne constituent
pas directement une série de stéréo photométrique.

## Premier essai Veymont

Dépendances : Python, NumPy et Pillow. L'exemple sélectionne une petite paroi
de la photo 1400 × 700 du soleil levant. Le canal vert évite de dépendre des
hautes lumières rouges écrêtées. Un masque colorimétrique ajusté à **cette
photo** distingue la roche éclairée des bandes de neige blanches. La neige
reste disponible comme indice géométrique distinct. Les masques doivent être
vérifiés visuellement ; ils ne constituent pas un détecteur général de neige.

```bash
python3 -B tools/extract_rock_surface.py \
  maps/veymont/rock-surface.example.json \
  --photo /chemin/PL231203-02047-grand-veymont-hiver-1400x700.jpg \
  --output-dir build/rock-surface/veymont-sunrise/output
```

La direction de lumière, la taille métrique de la zone et la géométrie plane
de cet exemple sont **supposées**. L'essai teste la chaîne de calcul ; il
n'effectue pas le recalage de cette paroi sur le Grand Veymont. Le rapport
`surface.json` l'indique et conserve les paramètres, les gains employés et le
caractère identifiable ou non des normales sous le modèle.

## Profil d'extraction

Le profil JSON est distinct du manifeste de carte et porte `version: 1`.

| Champ | Usage |
| --- | --- |
| `views` | Une photo avec a priori géométrique, ou trois à huit photos recalées. |
| `views[].file`, `crop` | Image source et rectangle `[gauche, haut, droite, bas]` après orientation EXIF. |
| `views[].camera`, `camera_file` | Caméra perspective explicite ou rapport du recalage ; ils exigent la heightmap et excluent `crop`. |
| `views[].light_direction` | Vecteur **vers** la source lumineuse, dans le repère local `[u, v, avant]`. |
| `views[].exposure_gain` | Gain positif calibré ; sinon estimation depuis l'a priori. |
| `views[].ambient_linear` | Contribution ambiante additive dans le canal linéaire choisi. |
| `channel` | `luminance`, `red`, `green` ou `blue`. Le sRGB est linéarisé avant le calcul. |
| `size` | Dimensions de sortie, de 8 à 512 pixels par axe. Redimensionner ne crée pas de détail photographique. |
| `rock_polygons_uv` | Surface de la paroi à traiter, y compris ses dépôts de neige ; coordonnées `[0, 1]` dans le recadrage, lignes vers le bas. |
| `exclude_polygons_uv` | Zones à retirer entièrement : ciel, végétation, défauts de photo, dépôts dont l'orientation est trompeuse. |
| `rock_color_gate` | Filtre facultatif de rapports rouge/bleu et rouge/vert, propre à la photo. |
| `snow_cue.weight` | Poids de l'indice de neige, de 0 (désactivé) à 1 ; 0,35 dans l'exemple. |
| `snow_cue.minimum_up_cosine` | Orientation vers le haut suggérée, de 0 à 1 ; cible indicative, pas une pente mesurée. |
| `snow_cue.polygons_uv` | Masque de neige dessiné explicitement ; sinon filtre de couleur sur la première photo. |
| `snow_cue.min_brightness_srgb`, `max_red_over_blue` | Seuils de luminosité minimale et de rapport rouge/bleu du filtre de neige. |
| `snow_cue.up_direction` | Direction vers le haut dans le repère local ; par défaut, verticale de la carte transformée dans ce repère. |
| `surface.extent_meters` | Largeur et hauteur réelles de la surface rectifiée. |
| `surface.origin_meters` | Coin inférieur gauche de la zone dans le repère de la carte. |
| `surface.axes` | Axes unitaires orthogonaux `u` et `v`, ce dernier orienté vers le haut. Leur produit vectoriel définit l'avant. |
| `surface.reference_albedo` | Réflectance diffuse supposée, en espace linéaire. |
| `surface.max_displacement_meters` | Amplitude maximale de correction. |
| `surface.max_angle_degrees` | Limite sur les normales estimées **et sur les angles du maillage final**. |
| `surface.detail_scale_meters` | Échelle du filtre d'intégration ; les grandes longueurs d'onde restent ancrées à la géométrie source. |
| `surface.edge_fade_meters` | Retour progressif à la source au bord des observations utilisables. |
| `surface.albedo_srgb`, `roughness` | Paramètres choisis du profil de roche ; ils ne sont pas mesurés depuis la photo. |
| `procedural_seed` | Graine déterministe de synthèse du détail. |

Sans caméra, les photos doivent déjà correspondre à la même zone rectifiée.
Avec caméra, les points de la heightmap sont projetés dans la photographie
complète puis échantillonnés bilinéairement. Les pixels hors cadre, les faces
tournées à l'opposé et les points masqués par le terrain sont rejetés. Cette
visibilité est échantillonnée ; elle ne modélise pas les arbres ou les surplombs.
Le simple redimensionnement d'une photographie ne remplace pas le recalage. Les masques permettent aussi
d'exclure les zones dont la couleur varie ou dont la lumière n'est pas celle
du modèle. Le masque `validity.png` marque les indices utilisables, roche ou
neige ; les zones rejetées conservent leur géométrie source au lieu de devenir
des trous.

## La neige comme indice de corniche

Les bandes de neige peuvent indiquer des replats ou des faces plus orientées
vers le haut que la paroi voisine. Leur luminosité ne doit pas être ajustée
comme si elle provenait du calcaire nu : ce serait confondre une différence
d'albédo avec une différence de normale.

Le prototype sépare donc les observations de roche et le masque de neige.
Dans ce dernier, il suggère une normale plus orientée vers la verticale,
mélangée à la normale initiale selon `weight`, puis limitée par le même angle
maximal que les corrections photographiques. Une surface déjà suffisamment
orientée vers le haut ne change pas. Même un pixel de neige écrêté peut fournir
cet indice sans participer à la stéréo photométrique.

Cette contrainte reste souple : givre, vent, neige adhérente et épaisseur du
dépôt peuvent masquer une surface raide. La cible `minimum_up_cosine` ne
mesure pas un angle exact. Son poids peut être réduit ou annulé, et les dépôts
ambigus retirés du masque. Pour une application au terrain, les bandes doivent
être recalées sur les corniches qu'elles recouvrent.

## Couplage avec la heightmap

Pour une paroi orientée vers l'est, `u` peut être dirigé vers le sud de la
carte et `v` vers le haut :

```json
{
  "heightmap": {
    "manifest": "../../mod/SkiEO-Veymont/custom-map.json",
    "ray_distance_meters": 100,
    "ray_step_meters": 4
  },
  "surface": {
    "origin_meters": [-1400, 1750, 2000],
    "axes": [[0, 1, 0], [0, 0, 1]],
    "extent_meters": [80, 100]
  }
}
```

Ce fragment illustre les coordonnées ; il ne calibre pas la photo Veymont.
Le chemin du manifeste est relatif au profil. Les paramètres `surface`
complètent ceux du profil d'extraction. Les rayons parcourent la normale du
plan depuis l'avant et cherchent la première intersection avec le R16,
interpolé bilinéairement. Le datum, l'origine, l'ordre des lignes et l'ordre
des octets du R16 sont conservés. Les normales de cette géométrie servent
d'a priori au solveur photographique.

La correction des gradients est intégrée par un solveur de Poisson régularisé,
avec ancrage des grandes longueurs d'onde. Les bords retournent exactement à
la surface source. L'amplitude est limitée, puis le déplacement est réduit si
les normales **calculées sur le maillage exporté** dépassent l'angle autorisé.
Les coordonnées 3D changent effectivement : on ne remplace pas seulement les
normales envoyées à l'éclairage. La forme générale reste celle du terrain.

Le recalage final doit identifier la surface observée et sa projection :
repères sur les crêtes, position de caméra ou rectification locale de paroi.
Une normale provenant d'un pixel non recalé ne doit pas être appliquée à une
cellule de terrain simplement parce qu'elles sont proches dans leurs images.

## Recalage perspective avec GPS et silhouette

`tools/register_rock_photo.py` ajuste une caméra candidate sur des observations
de la ligne de crête, avec position, direction et focale bornées. La position
verticale reste l'altitude de la heightmap plus la hauteur de prise de vue.
Le repère de calcul est **est, sud, haut**, en mètres ; une photo tournée vers
l'ouest a donc le nord à droite de l'image. NumPy, Pillow et SciPy sont requis ;
le diagnostic `--preview` emploie aussi Matplotlib.

L'exemple GPS utilise `20250118_103053.jpg`, dont les métadonnées donnent
44,896944° N, 5,556944° E, le 18 janvier 2025 à 09:30:35 UTC et une focale
équivalente de 26 mm. Le cap photographique est absent. L'altitude GPS vaut
zéro et **ne sert jamais de datum au terrain**. PROJ (`cs2cs`) convertit la
position en Lambert-93, autour de laquelle la recherche reste limitée à
40 mètres. La focale EXIF amorce la recherche avec une marge de ±20 %, car
le recadrage du capteur et la convention de focale équivalente restent incertains.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B tools/register_rock_photo.py \
  maps/veymont/rock-registration-gps.example.json \
  --photo /chemin/20250118_103053.jpg \
  --output-dir build/rock-surface/registration/gps --preview

python3 -B tools/extract_rock_surface.py \
  build/rock-surface/registration/gps/registered-surface.json \
  --output-dir build/rock-surface/registration/gps/surface
```

`camera.json` conserve la caméra, les métadonnées, les observations et l'erreur
de silhouette. `skyline-overlay.png` superpose la crête observée et celle du
terrain projeté. Un `patch` facultatif sélectionne un pixel et une étendue
métrique : son rayon intersecte le R16 et produit `registered-surface.json`,
dont le repère local suit la paroi. Les masques de l'ancien recadrage sont
retirés, car ils ne sont pas valables dans ce nouveau repère.

L'éclairage peut être calculé à partir du GPS et de l'heure UTC par les
[équations approchées NOAA](https://gml.noaa.gov/grad/solcalc/solareqns.PDF).
Le calcul tient compte de la convergence de la grille Lambert-93, sans
modèle météorologique ou de réfraction. Il indique la direction du soleil,
pas l'intensité reçue par une paroi à l'ombre. Une photo sans heure UTC fiable
nécessite une direction renseignée séparément. Les faces non éclairées ne
participent pas au calcul photométrique ; si aucun échantillon éclairé ne
permet de calibrer l'exposition, le mode à une photo garde la géométrie
initiale et peut encore employer les indices de neige.

Le profil du soleil levant, `rock-registration.example.json`, utilise la
Crête du Brisou indiquée par l'utilisateur, avec une direction de lumière
**supposée**. Il ne réutilise pas le GPS de la photo de janvier : les lieux et
dates de prise de vue diffèrent.

Le premier essai GPS, avec l'ancienne enveloppe de points isolés, donnait une
erreur quadratique de **23,0 pixels**,
sans buter sur les bornes de recherche. La caméra candidate se trouve à
environ `[823,7, -1203,9, 1238,1]` mètres. Sur la petite paroi sélectionnée,
433 indices restent utilisables, dont 133 de roche et 300 de neige ; la
correction effective est au plus **3,0 cm et 1,78°**, pour les limites choisies
de 30 cm et 15°. La faible correction est cohérente avec cette paroi surtout
à l'ombre, mais ne valide pas l'emplacement exact de ses détails.

La silhouette seule ne détermine pas une caméra unique ni les correspondances
des fissures internes. Le modèle suppose un point principal centré ; le
roulis est nul par défaut, ou ajusté dans les bornes explicites
`camera_search.roll_degrees` (au maximum ±15°). Il ignore la distorsion optique
et la végétation.
`camera_search.landmarks` permet d'ajouter des correspondances indépendantes
`world_meters` → `photo_pixels`. Le rapport reste `candidate`, `verified: false`
après optimisation : inspecter la superposition et ces repères avant toute
application à la carte. Le recalage courant projette les **triangles raccordés**
de la grille : leurs segments sont interpolés aux centres des colonnes de
l'image. Des points isolés produisaient de fausses dents entre les sommets
espacés, particulièrement dans les vues proches. La silhouette reste limitée
par la résolution du R16. La zone choisie doit couvrir les crêtes observées ;
éviter une grille grossière autour de la caméra, qui peut placer ses triangles
au-dessus de l'altitude bilinéaire du point de vue.

## Sélection des photographies de l'auteur

Le dossier fourni contient 16 photos : 13 ont GPS et heure UTC, trois n'ont
pas de GPS. Aucune n'est un doublon exact. `tools/catalog_rock_photos.py`
produit un inventaire JSON, des miniatures et une galerie HTML filtrable.
Il conserve les originaux et sépare les métadonnées des appréciations visuelles
de `maps/veymont/rock-photos.example.json`.

```bash
python3 -B tools/catalog_rock_photos.py /chemin/Veymont \
  --georeference maps/veymont/map.json \
  --manifest mod/SkiEO-Veymont/custom-map.json \
  --review maps/veymont/rock-photos.example.json \
  --output-dir build/rock-surface/photo-selection/catalog
```

Ouvrir `index.html` dans le dossier de sortie. Les rôles « silhouette »,
« corniches enneigées », « roche sans neige » et « éclairage à examiner » sont
des choix de revue humaine, pas des classes déduites du seul GPS. Les vues
dans l'ombre, sous les nuages ou avant le lever du soleil ne doivent pas être
traitées comme un éclairage solaire direct. Le point de vue d'août est hors
de la heightmap et ne peut pas emprunter son altitude. Les dates locales et
les noms de fichiers ne fournissent pas automatiquement une heure UTC.

| Photo | Usage privilégié | Limite principale |
| --- | --- | --- |
| `20251207_082025.jpg` | Vue proche au soleil levant, parois et neige, GPS/UTC | Lumière rasante et ombres portées |
| `20260705_105825.jpg` | Roche d'été et géométrie sans neige, GPS/UTC | Grand Veymont plus lointain que les falaises du premier plan |
| `IMG-20250927-WA0009.jpg` | Parois proches sans neige | EXIF perdu, recadrage inconnu, brouillard partiel |
| `20260221_121310.jpg` | Corniches et volumes depuis le Brisou | Câbles/pylône, nuages et neige abondante |
| `20251012_124008.jpg`, `20260308_095749.jpg` | Volumes vus depuis les crêtes | Vue oblique et éclairage peu adapté aux normales |

Les angles différents apportent des contraintes de volume et de visibilité.
Ils ne constituent une série photométrique que si la **même surface de roche**
reste identifiable après reprojection et sous un éclairage compatible avec
le modèle. La neige change avec la saison ; ne pas assimiler les pixels de
neige hivernaux aux pixels de roche estivaux.

Le profil `rock-registration-sunrise-gps.example.json` recale la photo du
7 décembre. Avec les triangles raccordés et un petit roulis ajusté, il donne
**12,45 pixels RMS**, contre 39,70 avec les anciens points isolés et sans
roulis. La comparaison inclut donc deux améliorations du modèle de caméra.
La caméra reste candidate, et les fractures ne sont pas encore des repères
indépendants. L'extraction de la paroi de 80 × 100 m donne 7 648 observations
photométriques et 348 indices de neige ; le déplacement atteint la borne de
**0,50 m**, avec une variation réelle des normales de **14,19°**, sous la limite
de 20°. Ce sont des mesures du calcul, pas une erreur de reconstruction validée.
`surface/comparison.png` présente l'analyse **hors moteur**, avec lumière de
contrôle identique sur la géométrie source et corrigée.

Pour la photo WhatsApp, l'auteur indique le sentier avant « Sous le Pas de la
Ville », puis corrige le point d'après l'arbre au premier plan :
**44°52′58,3″ N, 5°31′44,9″ E**. Cette indication est conservée comme
`location_hint`, distinctement du GPS EXIF absent. Le nouveau point est environ
255 m au nord-est du premier et correspond à `[-1322,87, 393,19]` mètres dans
le repère de la carte. La marge de recherche est resserrée à ±25 m sur chaque
axe autour de cette indication plus précise ; c'est une marge de recalage
choisie, pas une précision GPS mesurée. `rock-registration-trail.example.json`
produit une caméra candidate avec une erreur quadratique moyenne de silhouette
de **14,68 pixels**, contre 20,87 pixels avec l'ancienne indication et une
marge plus large. L'ajustement atteint les limites est et nord de cette nouvelle
fenêtre : ce résultat ne confirme donc pas une position exacte de prise de vue.
Sa focale et son roulis sont ajustés, car le recadrage original est inconnu.
Ni heure UTC ni direction
de soleil ne sont inventées, et ce profil n'effectue pas d'extraction
radiométrique. Il sert à préparer les correspondances géométriques de la
roche sans neige.

Les empreintes SHA-256 de la photo, du R16 et de sa transformation métrique
empêchent de réutiliser silencieusement une caméra après changement de source
ou de datum. Les fichiers source ne sont pas modifiés ; les rapports et
maillages vont dans `build/` et ne distribuent pas les photos originales.

## Sorties portables

- `normal-estimated.png` : orientation estimée, avec retour à l'a priori dans
  les zones rejetées.
- `normal-applied.png` : normales de la géométrie après intégration et limites.
- `displacement.r16` et `.png` : correction signée ; le JSON donne son échelle
  et son offset. Le zéro est au milieu de la plage.
- `patch-base.obj` et `patch.obj` : géométrie de référence et géométrie corrigée,
  en mètres dans le repère de la carte, avec UV et normales.
- `photometric-validity.png`, `snow-cue-mask.png` : observations de roche et
  indices de neige séparés.
- `validity.png`, `geometry-mask.png`, `photo-crop.png` : indices combinés,
  surface conservée et photographie source.
- `photo-visibility.png` et `photo_pixels`/`photo_visible` dans le NPZ :
  diagnostic de reprojection des vues sur la géométrie source.
- `surface-data.npz` : tableaux de calcul à pleine précision.
- `relit-left.png`, `relit-right.png` : prévisualisations diffuses hors moteur
  du calcaire blanc, sans réutilisation de la couleur orange photographique.
- `surface.json` : paramètres effectifs, mesures de correction et limites.

Les normales sont codées en RGB linéaire, avec `RGB = normale × 0.5 + 0.5`,
dans le repère local `[u, v, avant]`. Leur import doit adapter le repère tangent
et le sens du canal vert au matériau employé. Les prévisualisations sont des
contrôles numériques, pas des captures du jeu. Toute validation en jeu doit
continuer à employer UE4SS et l'API de capture Unreal.

## Détail procédural et Nanite

Le prototype extrait aussi le spectre spatial du déplacement estimé et en
randomise les phases avec une graine. Il produit un détail périodique et
reproductible (`procedural-displacement.r16`, `procedural-normal.png`) qui
conserve les échelles et les directions du signal estimé. Les deux sorties
de rééclairage procédural vérifient que le profil n'est pas une photographie
figée. Ce signal synthétise un style de relief ; il ne reconstitue pas les
fractures réelles ni une coupe géologique mesurée. L'amplitude et les pentes
du détail sont également bornées.

Nanite peut subdiviser un maillage compatible et le déplacer selon une
texture ou un matériau procédural, en fonction du détail visible à l'écran.
Le matériau doit fournir les normales correspondantes : le déplacement ne
modifie pas automatiquement le calcul d'éclairage. Voir
[Nanite Tessellation, documentation Epic](https://dev.epicgames.com/documentation/unreal-engine/working-with-naniteenabled-content).

Notre terrain utilise actuellement `ProceduralMeshComponent`. Ce composant
ne devient pas Nanite par activation d'une variable console. L'intégration
demande donc un chemin de préparation de maillages Nanite et un matériau dont
les shaders de normales/déplacement sont présents dans le jeu. Le matériau
de sol livré aujourd'hui ne suffit pas à ajouter ces fonctions à lui seul.
Le profil, les images, les corrections et les maillages source peuvent rester
portables ; les ressources Unreal préparées seraient un cache dérivé.

Les sources Unreal **5.8.3** dans
`/media/lycos/dev/extern/UnrealEngine` ont été préparées et compilées avec les
dépendances officielles Epic et le compilateur Clang 20.1.8. La préparation
emploie la construction complète d'éditeur : le constructeur rapide de
`UStaticMesh` disponible hors éditeur n'établit pas à lui seul une chaîne Nanite. Voir
[FBuildMeshDescriptionsParams, documentation Epic](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/UStaticMesh/FBuildMeshDescriptionsParams).

Une chaîne de préparation est ajoutée dans
[`native/SkiEONanite`](../native/SkiEONanite/README.md). Le premier test densifie
une paroi de 80 × 100 m à **25 cm**, soit **128 721 sommets et 256 000 triangles**.
Le profil de calcaire compact ajoute au plus **2,5 cm** de relief procédural ;
les hautes fréquences incompatibles avec le pas sont retirées. Les normales
sont calculées sur les positions déplacées, avec une limite de variation de
20°. Les trous du masque restent ouverts et le relief s'atténue aux bords.
`--corrected` inclut la correction photographique candidate ; sans cette
option, le relief part de la surface de référence. Subdiviser cette surface
ne crée pas de nouveaux relevés du terrain.

Le constructeur C++ utilise la construction complète de `UStaticMesh`, active
Nanite et exige des clusters non vides avant cuisson pour Windows. Le script
de construction vérifie les buffers, produit un conteneur IoStore dérivé
(`.pak`, `.utoc`, `.ucas`) et conserve un rapport. La construction et la cuisson
Windows ont réussi. `tools/preview_nanite_rock.lua` effectue le contrôle UE4SS, avec
captures par l'API Unreal et bascule vers le maillage fallback. Le matériau
du jeu doit déjà posséder sa variante Nanite cuite ; le diagnostic le vérifie.
La carte installée ne reçoit pas automatiquement le cache de ce patch de diagnostic.

Les tuiles complètes passent par `tools/export_nanite_tile.lua` et
`tools/prepare_nanite_tile.py`. La subdivision adaptative mesure les arêtes
en 3D : une cellule de 4 m dans le plan de la heightmap peut couvrir plusieurs
dizaines de mètres verticalement. Les arêtes des parois sont limitées à 3 m
dans le cache Veymont, avec propagation à travers les raccords UV. Les bords
gardent la géométrie d'origine ; le lissage des normales du terrain est
conservé, en ajoutant la variation induite par le détail.

`--surface-profile` ajoute le profil périodique synthétisé à partir du spectre
photographique, sans couleur ni ombre de la photo. Ce détail reste inférieur
à 14 cm sur les deux tuiles préparées. Il exprime un style de surface et ne
constitue pas un recalage géographique validé ni une mesure des fractures.
La correction géographique des angles reste distincte de cette synthèse.

Le chargeur utilise les `UStaticMesh` Nanite pour le rendu des sections
validées et conserve le composant procédural pour la collision. Le matériau
de calcaire déjà disponible dans le jeu est partagé. Ce chemin utilise une
géométrie préparée ; il ne dépend pas de la tessellation Nanite du matériau.
Le cache est facultatif et séparé du format portable. Son CRC32 du R16, ses
dimensions et son découpage sont contrôlés ; un cache absent, périmé ou
inutilisable conserve le rendu précédent. La procédure de construction et
d'installation est dans [`native/SkiEONanite/README.md`](../native/SkiEONanite/README.md).

Le premier cache des sections 34/42 ajoutait moins de 14 cm de relief.
L'essai dans la carte complète a montré que cette échelle ne suffisait pas
pour donner du caractère aux parois et rendait leur raccord trop visible.

**Essai rejeté après inspection du rendu.** `tools/prepare_rock_mass.py` prépare un massif continu à partir
de ces deux sections, avec le profil portable
[`maps/veymont/limestone-geometry.json`](../maps/veymont/limestone-geometry.json).
Il creuse des retraits entre bancs, forme des corniches et ajoute des fractures
verticales espacées, avec une amplitude bornée à 8 m. La partie haute garde
des piliers plus massifs ; les bancs sont plus prononcés en partie basse.
Ces formes sont une interprétation réglable des photos, sans mesure de leurs
profondeurs et sans appliquer le recalage photographique encore candidat.
Le résultat présente des bandes sombres sur une surface encore trop lisse.
Le champ de retrait principalement fonction de l'altitude ne construit pas
une structure de blocs rocheux. Augmenter le détail ou les triangles Nanite
ne corrige pas ce défaut. Ce générateur reste disponible pour reproduire
l'essai ; il ne définit plus l'approche retenue pour les falaises du Veymont.

Les sections sont réunies avant subdivision. Le champ utilise les coordonnées
du massif entier, sans retour au terrain lisse à leur limite interne. Seul
le périmètre extérieur conserve un fondu sur 80 m. Les normales tournent
avec le changement de géométrie ; elles ne sont plus limitées à une petite
variation qui empêcherait les corniches de recevoir leur éclairage propre.
La neige reçoit la même géométrie et le décalage vertical du manifeste :
l'ancienne couche lisse masquerait les retraits de la roche.

Les deux maillages restent un cache Nanite dérivé. Le R16, les collisions et
la simulation du ski restent les références portables. Le chargeur remplace
ensemble roche et neige, ou rétablit l'ensemble des sections d'origine si
une ressource échoue. La récupération des corniches réelles depuis les photos
reste une étape distincte, avec recalage et estimation des angles à valider.

## Réorientation : géométrie de blocs et fractures

[Modeling Rocky Scenery using Implicit Blocks, Paris et al., 2020](https://aparis69.github.io/public_html/projects/paris2020_Blocks.html)
propose de découper un volume par des disques de fracture, de regrouper les
points restant connectés puis de construire des blocs convexes implicites.
Une intersection lissée de demi-espaces forme les blocs ; une déformation
guidée par leur gradient ajoute ensuite le détail de surface. La réplication
sélective distribue ces blocs sur les parois du terrain initial. Le papier
permet aussi l'instanciation de maillages de blocs : la représentation
implicite n'est pas, à elle seule, une garantie de fidélité géologique.

Le [code public MIT des auteurs](https://github.com/aparis69/Rock-fracturing)
est une réimplémentation partielle. Il génère des tuiles de blocs ; la
réplication sur le terrain et le pavage périodique/apériodique n'y sont pas
implémentés. Le papier mentionne aussi les répétitions visibles sur des
parois planes et laisse les fractures à l'échelle de centaines de mètres
comme piste future. Son adoption demande donc une intégration, pas seulement
la cuisson Nanite de ses exemples.

L'adaptation pour Veymont suit les étapes ci-dessous. Un prototype local est
maintenant implémenté ; il n'est **pas intégré au cache du massif** :

1. Conserver le DEM comme référence de position, silhouette et simulation.
   Construire des volumes locaux autour des zones de roche exposée ; un champ
   `z - height(x, y)` peut servir d'ancrage implicite, mais ce n'est pas une
   distance euclidienne exacte à la surface.
2. Définir les grandes fractures et les volumes massifs à l'échelle de la
   paroi. Les photos montrent des piliers massifs en haut ; les couches plus
   fines concernent surtout le soubassement. Appliquer l'archétype tabulaire
   partout reproduirait le défaut de bandes déjà rejeté.
3. Extraire des vues recalées les orientations, espacements, longueurs et
   interruptions des fractures avec leur incertitude. Utiliser ces contraintes
   pour former les blocs et leur usure locale. La luminosité d'une photo au
   soleil levant ne donne pas directement une profondeur ni une normale
   unique ; albédo, ombres, exposition et neige doivent rester distincts.
4. Ajouter le petit relief du calcaire compact après la structure des blocs,
   puis calculer les normales à partir de la géométrie obtenue. La neige donne
   un indice de surfaces susceptibles de la retenir, pas une mesure certaine
   de pente. Elle doit suivre les nouvelles surfaces et leurs raccords.
5. Extraire le maillage par petits domaines, avec voisinage partagé aux bords
   et limites mémoire explicites. Conserver le modèle portable ; utiliser
   Nanite ensuite comme cache de rendu du maillage validé.

Un premier contrôle hors moteur du code public est conservé dans
`build/rock-surface/research/`. `run_probe.py` construit un seul échantillon
générique de 20 m, avec une grille de 96³ et deux threads, sous une limite
de mémoire virtuelle de 1 Gio. La déformation par texture est désactivée
pour observer la structure des blocs. Les adaptations locales, la licence
et l'empreinte SHA-256 de l'archive source sont consignées dans `probe.json`.
Ce test a produit **47 912 sommets et 95 724 triangles**, avec un pic RSS
de génération mesuré de **10 076 160 octets**. Ce budget décrit uniquement
ce petit générateur ; il ne prédit pas la mémoire d'une carte dans Unreal.
`blocks-preview.png` est une visualisation scientifique hors moteur, sans
contraintes photographiques du Veymont. Aucun nouveau cache n'est installé
dans le jeu par cet essai.

### Prototype local avec contraintes photographiques

`tools/extract_rock_features.py` prépare une petite portion du terrain natif
depuis un recalage photographique existant. Il utilise la diagonale des
triangles des cellules entièrement raffinées, plutôt qu'une interpolation
bilinéaire du R16. Sur la photo du 7 décembre, la portion choisie mesure
**24 × 36 m** et reste sous la crête. Le masque exclut le ciel, les surfaces
neutres assimilées à la neige et les observations inutilisables. Des crêtes
sombres cohérentes dans l'image donnent douze **traces candidates**, de
longueur finie. Elles peuvent aussi provenir d'ombres ou d'albédo ; elles ne
sont pas automatiquement des fissures reconnues. Le calcul de normales garde
la direction ambiguë du relief de référence et une limite angulaire de 25°.

`tools/implicit_rock.py` implémente un graphe de visibilité de points Poisson
coupé par des disques de fracture. Les clusters convexes deviennent des
intersections implicites de demi-espaces, puis sont unis à un noyau rocheux.
Un bloc qui ne peut pas rejoindre ce noyau est écarté. Une fonction de présence
limite les formes à proximité des traces observées : sans cette précaution,
les enveloppes convexes prolongeaient de courtes fractures en longues coupes
rectilignes. Le détail procédural de surface utilise un champ 3D et une
déformation guidée par le gradient, avec une direction lissée pour limiter
les replis de la déformation. Il ne reprend aucune couleur de la photo.

`tools/prepare_implicit_cliff.py` ajoute une correction candidate par intégration
contrainte des normales photographiques. Les composantes mal identifiées
restent attachées au prior et les hautes fréquences non résolues sont filtrées.
Le relief photographique appliqué atteint **18,7 cm** sur cet essai. Les
positions restent dans une enveloppe de **+30 cm / −60 cm** autour du terrain
d'origine. Ces valeurs sont des limites de construction, pas des profondeurs
mesurées. Le fondu s'annule avec sa première dérivée aux quatre bords.

L'extraction se fait par tétraèdres dans un volume local. Les arêtes partagées
sont soudées ; les intersections à moins de 10 µm d'un nœud sont réunies
avant suppression des triangles effondrés. La consolidation n'autorise que
128 échantillons de cavités ou fragments non résolus ; au-delà, elle refuse
le modèle. Le dernier essai a rempli un seul échantillon de cavité et n'a
supprimé aucun fragment. Le contrôle du maillage impose un seul ensemble
continu, aucun bord ouvert intérieur et aucun bord non manifold.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.extract_rock_features \
  build/rock-surface/registration/sunrise-gps/registered-surface.json \
  --window 30 80 24 36 --spacing .25 \
  --output-dir build/rock-surface/implicit-study/features

OPENBLAS_NUM_THREADS=1 python3 -B -m tools.prepare_implicit_cliff \
  build/rock-surface/implicit-study/features \
  --profile maps/veymont/limestone-blocks.json \
  --output-dir build/rock-surface/implicit-study/photo-detail

OPENBLAS_NUM_THREADS=1 python3 -B -m tools.preview_implicit_cliff \
  build/rock-surface/implicit-study/photo-detail
```

Le [profil portable](../maps/veymont/limestone-blocks.json) contient les
paramètres géométriques et les budgets, indépendamment d'Unreal. Les sorties
sont les observations et tableaux NPZ, les OBJ source/modifié, les buffers
portables et `mesh.json` compatible avec le constructeur Nanite existant.
Le contrôle de ce format réussit ; **aucun nouvel asset Nanite n'est cuit ni
installé** à ce stade. La cuisson attend une géométrie visuellement validée.

Le dernier maillage contient **81 879 sommets et 162 588 triangles**, issus
de 19 blocs. Il utilise 872 030 échantillons et un pas maximal de **25 cm**.
Le pic RSS mesuré de génération est de **161 452 032 octets** ; les CLI sont
limités à 1 Gio de mémoire virtuelle. `surface.json` conserve le profil, les
empreintes des entrées, les mesures et l'incertitude photographique.

La comparaison en jeu emploie `tools/preview_rock_patch.lua` avec
`allow_topology_change=true`, un plafond explicite de 100 000 sommets /
200 000 triangles et un albédo blanc uniforme. Les captures
`build/rock-surface/implicit-study/unreal-photo/{base,corrected,oblique}.png`
passent par UE4SS et `HighResShot`. Le diagnostic n'a chargé aucune carte
Veymont complète : il crée un composant temporaire dans une instance neuve,
compare les deux géométries, change l'angle et le soleil, restaure la vue et
supprime ses acteurs. Le dernier pic du processus et de ses auxiliaires est
de **2 284 236 800 octets (2,13 Gio)** sous une limite de 3 Gio sans swap.
Le jeu se ferme avec le code 0 après les captures. Le service termine ensuite
de force les auxiliaires Wine restants après son délai d'arrêt ; son statut
`timeout` ne correspond ni à un OOM ni à un crash du jeu.

La validation est technique et locale. Les fissures restent assez
rectilignes, la caméra reste candidate (12,45 pixels RMS sur la silhouette,
sans repères internes validés) et les normales d'une seule photo ne sont
pas uniques. Ces résultats ne valident donc ni une reconstruction fidèle
des falaises, ni les raccords entre plusieurs domaines volumiques, ni le
rendu de leur neige et de leur matériau définitif. Le massif installé utilise
encore l'ancien cache rejeté. Il faut poursuivre la calibration des formes
et du petit détail avant leur remplacement dans la carte complète.

### Sculpture des faces rocheuses

Les références rapprochées ajoutées par l'utilisateur montrent du relief
sur les faces elles-mêmes : éclats, saillies, creux et rebords cassés. Le
premier prototype de traces photographiques ne reproduit pas ce caractère.
Le profil [`limestone-sculpture.json`](../maps/veymont/limestone-sculpture.json)
sélectionne donc un second modèle, `sculpted-implicit-rock`, dans le même
outil. Ce modèle est une construction originale par ajout et soustraction
de volumes convexes ; il n'est pas le graphe de fractures du papier.

Le noyau suit les triangles du terrain natif. Des masses enracinées dans
ce noyau apportent des saillies et des sous-faces. Des outils d'enlèvement
fermés, de forme triangulaire ou de dalle irrégulière, sculptent les faces.
Ils ont plusieurs plans inclinés et un petit arrondi d'arête, plutôt qu'une
section circulaire. Trois tailles de distribution, **3,1 / 1,25 / 0,65 m**,
forment les grands creux, les cassures secondaires et les petits éclats.
Ces dimensions sont des paramètres de style ; elles ne sont pas mesurées
dans les photographies rapprochées.

Les niveaux secondaires sont projetés sur la **surface exposée du volume
parent**. Un parcours borné du champ puis une dichotomie trouvent la dernière
intersection extérieure et sa normale. Cela place les petits outils sur
les faces saillantes et au fond des creux : les laisser au niveau du DEM
laissait ces faces lisses. Aucune trace sombre photographique n'est utilisée
comme coupe, et la correction de normales candidates est désactivée pour
isoler cette sculpture. Le petit champ 3D de rugosité intervient ensuite.

L'essai utilise une portion de **12 × 18 m**, avec un pas maximal de **15 cm**,
et une enveloppe de **+1,2 / −2,2 m**. Le fondu garde les positions et la
tangente de référence aux quatre bords. La sculpture peut libérer des
fragments ; ceux qui ne rejoignent plus le noyau sont retirés. Les plafonds
explicites sont de **1 m³ retiré au total**, **0,5 m³ pour un seul fragment**,
et **0,2 m³ de cavités fermées à consolider** pour ce calcaire compact.
Dépasser un plafond refuse la génération. Le premier modèle conserve son
plafond numérique de 128 échantillons ; celui de la sculpture se mesure en
volume physique. Le maillage final doit toujours être continu, sans bord
ouvert intérieur, ni arête non manifold.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.extract_rock_features \
  build/rock-surface/registration/sunrise-gps/registered-surface.json \
  --window 36 86 12 18 --spacing .15 \
  --output-dir build/rock-surface/implicit-study/sculpture-features

OPENBLAS_NUM_THREADS=1 python3 -B -m tools.prepare_implicit_cliff \
  build/rock-surface/implicit-study/sculpture-features \
  --profile maps/veymont/limestone-sculpture.json \
  --output-dir build/rock-surface/implicit-study/sculpture-final

OPENBLAS_NUM_THREADS=1 python3 -B -m tools.preview_implicit_cliff \
  build/rock-surface/implicit-study/sculpture-final
```

`surface.json` conserve les tailles de formes, les quantités de matière
retirées, les rayons qui rencontrent plusieurs surfaces et les empreintes
du générateur, du profil et des sources. Les OBJ et buffers sont portables ;
Nanite reste un cache possible de cette géométrie. Le test local n'applique
pas encore cette sculpture au massif entier, à ses collisions ou à la neige.

Le dernier essai contient **17 masses et 315 volumes d'enlèvement**, donnant
**78 150 sommets et 155 394 triangles**. Le relief extrait atteint environ
**1,01 m en saillie et 1,69 m en creux**. Sur la grille, 597 rayons rencontrent
plusieurs surfaces : la géométrie comprend des sous-faces et ne se réduit
pas à un unique déplacement du terrain. La consolidation retire **0,801 m³**
de fragments détachés (le plus grand : **0,458 m³**) et remplit **0,155 m³**
de cavités fermées, sous les plafonds annoncés. Le contrôle trouve un seul
ensemble continu, 948 arêtes de périmètre, aucun bord ouvert intérieur, aucune
arête non manifold et aucun triangle dégénéré. Une seconde génération
produit exactement les mêmes buffers. Le pic de génération est de
**147 902 464 octets**, sous la limite CLI de 1 Gio de mémoire virtuelle.

Les captures `build/rock-surface/implicit-study/unreal-sculpture/` sont prises
via UE4SS et `HighResShot`, avec un albédo blanc uniforme, un soleil synthétique
et un faible éclairage de remplissage sans ombres. Elles comparent le terrain
natif à la sculpture, puis changent la vue et la direction du soleil. Le
composant procédural est temporaire ; aucune carte Veymont complète n'est
chargée et aucun nouvel asset Nanite n'est cuit. La vue et les réglages sont
restaurés, puis les acteurs supprimés et le jeu fermé avec le code 0.
Le pic du diagnostic et de ses auxiliaires est de **2 413 658 112 octets
(2,25 Gio)** sous un plafond de 3 Gio sans swap, sans OOM. Le statut `timeout`
du service concerne les deux auxiliaires Wine restants, terminés après le
délai d'arrêt de cinq secondes ; il ne correspond pas à un crash du jeu.

Les **47 tests** géométriques, photographiques, de recalage et de format Nanite
passent. Les nouvelles régressions vérifient le relief sur une face sans
traces de fracture, les vraies sous-faces, le raccord tangent, le placement
des petits outils au fond des creux et les budgets de fragments/cavités.
Les captures montrent la sculpture des faces, mais un caractère encore
stylisé. Elles ne valident pas une reconstruction métrique, le rendu final
du calcaire, ni les raccords entre domaines ou la neige du massif complet.

### Érosion après sculpture

`tools/erode_implicit_cliff.py` ajoute une phase indépendante au volume
sculpté existant. Elle conserve les formes CSG approuvées comme source et
prépare un autre maillage ; elle ne relance pas la génération de blocs.
Le profil [`limestone-erosion.json`](../maps/veymont/limestone-erosion.json)
règle une usure procédurale par exposition et courbure, pas une simulation
géologique ou hydraulique calibrée.

Le champ implicite évolue vers l'intérieur. Sa courbure positive accélère
le retrait des arêtes convexes, tandis qu'un faible taux de fond affecte les
faces. La direction d'exposition favorise les surfaces tournées vers le haut
et l'extérieur. La vitesse multiplie le gradient du champ : celui-ci n'est
pas une distance euclidienne exacte. Un noyau protégé, un plafond d'avance
et un pas borné limitent l'évolution. Le réglage actuel est de **22 cm
d'intensité nominale**, avec une échelle de courbure de **35 cm** et **24 passes**.
L'intensité nominale n'est pas une mesure garantie du recul géométrique.

Seuls les échantillons en contact avec l'air par une face peuvent être
érodés. Les contacts par un coin sont exclus : ils pouvaient introduire des
échantillons d'air fermés dans le volume. Le fondu du périmètre reste nul et
les normales de bord sont conservées. Les fragments libérés sont retirés
sous les budgets de la sculpture. Désactiver l'érosion conserve exactement
les quatre buffers du maillage d'origine, y compris ses normales.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.erode_implicit_cliff \
  build/rock-surface/implicit-study/sculpture-final \
  --profile maps/veymont/limestone-erosion.json \
  --output-dir build/rock-surface/implicit-study/sculpture-eroded

OPENBLAS_NUM_THREADS=1 python3 -B -m tools.preview_implicit_cliff \
  build/rock-surface/implicit-study/sculpture-eroded
```

Le fichier `patch-base.obj` est une copie exacte du `patch.obj` de la sculpture
d'origine. Le champ avant érosion est conservé pour la comparaison scientifique.
Le nouveau maillage compte **73 817 sommets et 146 768 triangles**. L'évolution
retire environ **20,10 m³ sur la grille**, puis la consolidation retire
**0,323 m³** de petits fragments (le plus grand : **0,0168 m³**). Aucune cavité
fermée n'est créée. Le maillage reste continu, sans trous intérieurs ni arêtes
non manifold, avec les **948 arêtes de périmètre** d'origine. Les **482 rayons
à intersections multiples** confirment le maintien de vraies sous-faces.
Le pic de génération est de **172 773 376 octets**, sous une limite CLI de
1 Gio de mémoire virtuelle.

Le diagnostic UE4SS accepte `compare_oblique=true` : il capture la sculpture
et sa version érodée sous la même caméra et le même éclairage de face, puis
compare les deux en vue oblique avec le soleil inversé. Il utilise un albédo
blanc uniforme et `HighResShot`. Les sorties sont conservées dans
`build/rock-surface/implicit-study/unreal-erosion/`. Ce test reste une portion
locale dans un composant temporaire ; le cache du massif n'est pas remplacé.

Les **57 tests** du périmètre passent, dont dix sur l'érosion. Les quatre
captures UE4SS ont réussi ; la caméra est restaurée, les acteurs temporaires
retirés et le jeu quitte avec le code **0**. L'instance isolée atteint
**1,92 Gio** (2 060 333 056 octets), sous une limite de **3 Gio sans swap**, sans
OOM. Deux processus auxiliaires Wine ont nécessité l'arrêt forcé après le
délai de cinq secondes : le résultat `timeout` de l'unité concerne ce nettoyage
après la sortie du jeu. Le diagnostic LiveProbe est ensuite désactivé et sa
commande habituelle restaurée. Le rapport
`build/rock-surface/implicit-study/validation-erosion.json` conserve ces contrôles,
les empreintes des sources et les comparaisons d'identité.

### Intégration de la portion sculptée au terrain

`tools/embed_rock_sculpture.py` remplace la surface native sous la portion
érodée dans les sections 34/42. Il découpe les triangles suivant les quatre
côtés de la portion et conserve leurs positions, normales et UV interpolés.
Les mêmes points de raccord sont insérés des deux côtés, y compris dans les
triangles voisins : les bords ne sont pas deux surfaces superposées. La
référence locale est recalée sur les plans des triangles natifs ; sur cette
portion, la correction maximale est de **2,14 cm** et conserve le relief sculpté.
Les normales rejoignent celles du terrain au bord. L'outil refuse les
projections repliées, les références trop éloignées et les nouveaux trous.
Le sens des triangles est propagé depuis les faces natives suivant les arêtes
partagées. Les gradients interpolés du volume peuvent donner le mauvais sens
à une petite face : le premier assemblage avait **2 960 arêtes partagées
incohérentes**, corrigées en retournant **1 910 triangles**. Le contrôle des
bords ouverts seul ne détectait pas ces faces inversées, visibles comme des
trouées depuis l'extérieur. Le maillage intégré est maintenant une seule
surface connectée, avec un sens cohérent sur toutes les arêtes partagées.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.embed_rock_sculpture \
  build/nanite/terrain-34-source build/nanite/terrain-42-source \
  --sculpture build/rock-surface/implicit-study/sculpture-eroded \
  --output-dir build/nanite/sculpture/integrated
```

Les sorties `terrain/mesh.json` et `snow/mesh.json` sont compatibles avec le
constructeur Nanite et le cache à deux couches. La neige suit la géométrie
sculptée avec son décalage natif, et ses UV conservent l'origine de la carte.
La collision du R16 reste native. Ce remplacement conserve les autres
triangles des sections ; il ne répète pas la petite sculpture sur le massif.
L'essai compte **115 330 sommets et 204 828 triangles par couche**, avec les
**534 arêtes extérieures** d'origine, sans ouverture intérieure ni arête
non manifold, y compris après export float32 de la neige. La génération
reste sous **2 Gio de mémoire virtuelle**, avec un pic résident de **441 Mio**.

Les deux ressources sont cuites pour Windows avec le constructeur
`tools.build_nanite_rock`, puis converties en IoStore. Les captures
`build/nanite/sculpture/captures/{close,wide}-{original,nanite,fallback}.png`
comparent leur rendu dans Veymont, via UE4SS et `HighResShot`, depuis la
normale extérieure de la portion. Le premier diagnostic placé derrière la
paroi ne constituait pas une validation visuelle des fronts. Les nouvelles
captures, après correction du winding, ne montrent plus les trouées bleues.
La validation conserve **73 tests Python** et le contrôle Lua du chargeur.

Le paquet `build/nanite/sculpture/distribution/` est préparé avec :

```bash
python3 -B -m tools.package_nanite_terrain \
  build/nanite/sculpture/terrain-cooked/cook-report.json \
  build/nanite/sculpture/snow-cooked/cook-report.json \
  --output-dir build/nanite/sculpture/distribution
```

Ce cache remplace l'ancien essai de corniches dans les installations locales
de Veymont. Il intègre uniquement la portion sculptée de **12 × 18 m** ; le
reste des sections 34/42 reprend leur géométrie native. Le chargement normal
du mod est contrôlé dans une nouvelle instance : les deux surfaces, leurs
matériaux et la collision native sont présents avant les six captures. Le
pic de cet essai est de **4,19 Gio**, sous une limite absolue de **5 Gio sans
swap**, sans OOM, avec une sortie du jeu de code 0. Les processus auxiliaires
Wine nécessitent l'arrêt forcé après cinq secondes à la fermeture ; le
résultat `timeout` de l'unité finale concerne ce nettoyage après la sortie.

Un essai automatique antérieur a dépassé son délai pendant la génération
du terrain, avant l'application de Nanite. Il n'est pas validé ; la reprise
avec une limite souple alignée sur les 5 Gio et un diagnostic moins fréquent
termine correctement. Un lancement intermédiaire a également quitté avec
le code 53 avant le menu, sans capture valide. Ces incidents sont conservés
dans `build/nanite/sculpture/validation.json`. Les anciens caches restent
dans `build/nanite/sculpture/installed-backup/` pour retour arrière.
La sculpture, le R16 et les sources du format portable ne sont pas modifiés.

Le premier prototype photographique n'appliquait pas automatiquement ses
corrections à la carte.
`tools/preview_rock_patch.lua` fournit un diagnostic UE4SS qui importe les OBJ
dans un composant procédural temporaire, inverse le winding pour Unreal et
compare la source et la correction sous le même éclairage. Ce diagnostic
nécessite SkiEOLiveProbe, une instance de test isolée, les dossiers de sortie
déjà créés et un PNG d'albédo blanc. Il utilise `HighResShot` via l'API Unreal,
restaure la caméra initiale et retire ses acteurs à la fin. Il valide un
maillage et ses normales dans le moteur ; il ne prépare pas de ressource Nanite.

L'essai GPS a chargé **16 384 sommets et 31 294 triangles** dans Unreal, produit
les captures source/correction et retiré les acteurs temporaires. Le pic
mémoire de l'instance isolée est resté à **1,44 Gio**, sous une limite de
12 Gio sans swap. La correction reste celle calculée, sans amplification pour
la capture ; la caméra de diagnostic est rapprochée et l'éclairage synthétique,
avec exposition fixe pour comparer. Le rapport
`build/rock-surface/registration/gps/unreal/validation.json` conserve ces
résultats. Les variations entre captures comprennent aussi l'antialiasing
temporel et ne constituent pas une mesure de fidélité géologique.

### Extension procédurale au massif

`tools/prepare_sculpted_massif.py` étend les volumes angulaires du profil
`limestone-sculpture.json` aux parois orientées vers le nord-est des sections
34/42. Les graines sont attachées aux triangles natifs et les volumes voisins
sont recherchés avec un halo ; la portion de 12 × 18 m n'est pas répétée.
Le masque combine orientation, pente et altitude, avec une transition de
12 m sur le contour extérieur. Les faces orientées à l'opposé sont épinglées
sur leur référence pour éviter de replier leur extrusion.

Cette première extension extrait **l'enveloppe extérieure** du champ CSG.
Elle peut déplacer la paroi horizontalement et produire des faces cassées,
mais conserve un seul croisement extérieur par rayon. Les cavités et replis
cachés de la sculpture volumétrique locale ne sont donc pas reproduits.
L'échantillonnage adapte les arêtes à **1,5 m**, avec des échantillons de
profondeur tous les **25 cm**. L'érosion utilise un seul pas du champ continu,
pondéré par l'exposition et la courbure, au lieu des 24 itérations du petit
volume. C'est une approximation destinée à juger le rendu général ; le
résultat n'est pas une reconstruction métrique des photographies.

Le travail est réparti en 32 portions, chacune extraite par petits groupes de
triangles. Une réduction facultative utilise
[meshoptimizer](https://github.com/zeux/meshoptimizer), sous licence MIT,
révision `823c5bf2eca8b249c3015ea36a4ea2339de0a7d7`.
Elle ne déplace pas les sommets conservés et verrouille les bords. Les UV sont
recalculés avec les projections natives après réduction.
`tools/assemble_sculpted_massif.py` retire les triangles de réduction couvrant
une aire XY de référence nulle et réinsère les subdivisions manquantes des
arêtes. Les copies UV d'un même point de référence sont ensuite réunies sur
la copie la moins déplacée, ce qui respecte les sommets épinglés. Les normales
sont calculées avec les contributions des deux côtés de chaque interface.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.prepare_sculpted_massif \
  build/nanite/terrain-34-source build/nanite/terrain-42-source \
  --profile maps/veymont/limestone-sculpture.json \
  --erosion maps/veymont/limestone-erosion.json \
  --output-dir build/nanite/massif/geometry --edge-spacing 1.5 \
  --surface-mode envelope --simplifier build/nanite/massif/rock-simplifier.so
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.assemble_sculpted_massif \
  build/nanite/terrain-34-source build/nanite/terrain-42-source \
  --geometry-dir build/nanite/massif/geometry
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.export_sculpted_massif \
  build/nanite/terrain-34-source build/nanite/terrain-42-source \
  --geometry-dir build/nanite/massif/geometry \
  --output-dir build/nanite/massif/meshes
```

L'assemblage final du 5 octobre compte **1 757 235 sommets et 3 330 454
triangles par couche**, avec les **534 arêtes extérieures** d'origine et aucun
raccord intérieur ouvert. L'export refuse les arêtes non manifold, les fronts
incohérents ou une modification du contour extérieur. Le masque inclut
746 564 m² de faces ayant un poids non nul, y compris les transitions faibles.
La correction des copies de référence concerne 6 753 sommets, avec un maximum
de 2,19 m ; cette correction conserve la copie épinglée plutôt que de moyenner
la faille entre deux surfaces. L'assemblage global a atteint **1,84 Gio** de
mémoire résidente, sous une limite de **3 Gio sans swap**. L'export a atteint
**509 Mio**. Les anciens calculs locaux restent inchangés.

La cuisson produit 64 ressources Windows : 32 portions du terrain et leur
neige, avec le décalage natif de 30 cm. `--project-stage` dans
`tools.build_nanite_rock` permet de réutiliser un projet d'éditeur compilé ;
les appels partageant ce projet doivent être séquentiels. Le cache
`mesh_algorithm=3` exige toutes les portions des deux couches avant de masquer
les sections natives. Un échec restaure le terrain d'origine et détruit les
composants partiels. La collision reste celle du R16.

Le premier essai en jeu de l'extension a montré de fines trouées entre
ressources, malgré les raccords géométriques contrôlés avant cuisson. Elles
étaient plus importantes dans le fallback, dont la réduction indépendante
modifiait les bords. Pour `mesh_algorithm=3`, le constructeur conserve donc
100 % des triangles du fallback. Une seule surface intérieure peu dense du
terrain natif, stockée dans la première ressource rocheuse, est située à
2,6 m vers l'intérieur, derrière les creux limités à 2,2 m. Elle masque les
ouvertures causées par les niveaux de détail indépendants de Nanite sans
recouvrir le relief sculpté ; elle n'ajoute aucune collision. Elle ajoute
42 244 triangles et 74 994 sommets. Le terrain totalise ainsi **1 832 229
sommets et 3 372 698 triangles** ; la neige conserve **1 757 235 sommets et
3 330 454 triangles**. Le contrôle de fermeture porte sur la surface
extérieure ; la surface intérieure est un support de rendu supplémentaire.

La préparation des enveloppes écrit des données intermédiaires et porte le
statut `requires-conforming-assembly`. Les deux étapes suivantes sont
obligatoires : l'assemblage conforme les découpes, puis l'export refuse les
raccords ouverts et crée les fichiers cuisinables. Les lots de cette étude
ont été calculés avant cette modification du contrôle de fin d'extraction ;
`build/nanite/massif/source-provenance.json` et `generation-source.py`
conservent l'empreinte et le code exacts du calcul utilisé.

Pour construire la bibliothèque facultative de réduction dans le dossier de
travail (sans installer de dépendance système) :

```bash
mkdir -p build/nanite/massif
git clone https://github.com/zeux/meshoptimizer.git build/nanite/meshoptimizer
git -C build/nanite/meshoptimizer checkout 823c5bf2eca8b249c3015ea36a4ea2339de0a7d7
g++ -O2 -std=c++11 -shared -fPIC -I build/nanite/meshoptimizer/src \
  tools/rock_simplifier.cpp build/nanite/meshoptimizer/src/simplifier.cpp \
  build/nanite/meshoptimizer/src/allocator.cpp \
  build/nanite/meshoptimizer/src/indexgenerator.cpp \
  -o build/nanite/massif/rock-simplifier.so
```

Pour réassembler les lots déjà calculés de cette étude, ajouter
`--generator-source build/nanite/massif/generation-source.py` à l'assembleur.
Les nouvelles extractions utilisent le générateur courant par défaut.

L'ancienne copie `Binaries/Win64/ue4ss/Mods/SkiEO-CustomMaps` est supprimée
à la demande de l'utilisateur. Seul le chargeur installé dans
`Content/Paks/~mods/SkiEO-CustomMaps` est conservé. Une sauvegarde de la copie
supprimée se trouve dans `build/nanite/massif/removed-legacy-loader`, hors de
l'arborescence scannée par le jeu ; le retour au cache précédent ne la
réinstalle pas.

La validation finale du 5 octobre passe par le chargeur installé, avec un
seul démarrage de `SkiEO-CustomMaps` confirmé dans `UE4SS.log`. Les 64
ressources sont chargées sur la carte complète, sans Sugar Bowl, avec les
matériaux et la collision native conservés. Les 192 fichiers de conteneurs
installés et les trois copies du cache ont été vérifiés par empreinte.
Les 83 tests Python, les contrôles Lua du chargeur et `git diff --check`
réussissent.

Neuf captures de 2560 × 1440 pixels sont obtenues par l'API Unreal
`HighResShot` via UE4SS : vues d'ensemble, rapprochée et sud, chacune en
terrain d'origine, Nanite et fallback. Elles se trouvent dans
`build/nanite/massif/captures`. Les captures finales ne montrent plus les
trouées bleues des raccords. Le jeu se ferme normalement avec le code 0,
sans crash ni OOM ; le pic du groupe de processus est de **3,50 Gio**, sous
une limite de **6 Gio sans swap**. Le résultat `timeout` du service concerne
uniquement la fermeture des processus auxiliaires Wine après la sortie du
jeu. La configuration de diagnostic est restaurée.

`build/nanite/massif/validation.json` conserve les preuves, les empreintes
et les limites de cette passe. Le chargement d'une sauvegarde et les
chargements répétés ne font pas partie de cette validation. L'extension
reste une enveloppe extérieure avec une érosion simplifiée ; elle n'inclut
pas les cavités profondes du prototype volumétrique local.

La passe suivante corrige le raccord d'éclairage et la réception de neige.
`tools/export_sculpted_massif.py --transition-width 24` mesure la distance
en 3D aux points natifs inchangés, y compris les faces inverses épinglées.
Une courbe quintique atténue la déformation sur 24 m vers ces points. Elle
atténue aussi la correction des normales : le précédent seuil de déplacement
de 2 mm activait brutalement cette correction, même sur une géométrie déjà
progressive. Les portions partagent le même champ de transition ; aucun
fondu supplémentaire n'est appliqué à leurs frontières internes.

La roche conserve les normales natives corrigées par le relief. La neige
utilise les normales géométriques de la sculpture au cœur du masque, puis
revient progressivement aux normales natives au raccord. Le matériau
`M_Snow` du jeu est conservé, avec son entrée `VertexNormalWS` et ses données
météo ; la nouvelle couche ne constitue pas une simulation volumétrique de
neige. Avec un seuil de normale verticale de 0,57, la comparaison des exports
identifie 23 117 triangles supplémentaires orientés vers le haut, représentant
environ 11 263 m². Ce comptage décrit les normales du maillage ; les captures
en jeu restent nécessaires pour juger l'enneigement visible.

Le package exige que toutes les portions des deux couches partagent
`surface_transition` et `snow_retention_normals`. Cela empêche de mélanger
des ressources cuites avec des réglages de raccord différents. Les sorties
de cette passe sont séparées dans `build/nanite/massif-snow-transition`, et
les fichiers du premier rendu restent disponibles pour comparaison.

L'essai complet a montré que les normales seules ne suffisaient pas : le
matériau `/Game/Materials/Snow/M_Snow` reste lié au relief natif et n'enneige
pas correctement les nouveaux replats. `tools/prepare_snow_deposits.py`
prépare donc deux couches visuelles complémentaires. `snow_deposits`
retient seulement les faces dont la normale **géométrique** a un Z supérieur
à 0,5, puis amincit les dépôts suivant les normales interpolées. Leurs bords
s'enfoncent jusqu'à 4 cm dans la roche au lieu de former des plaques flottantes.
Le maximum ajouté est de 10 cm. Les normales interpolées seules peignaient
également les murs voisins des replats ; le test des facettes corrige ce cas.

`snow_transition` couvre progressivement les faces raides du raccord. Sa
probabilité de couverture suit la même courbe de transition, avec un
échantillonnage déterministe en coordonnées mondiales. Cette couverture par
petites touches évite de transformer la courbe continue en une nouvelle ligne
de clipping colorée. Les couches utilisent le matériau de neige indépendant
`/Game/Materials/Backgrounds/M_Snow`, déjà compatible avec Nanite dans le jeu.
Le déplacement du matériau est désactivé. Elles partagent une instance
matérielle et conservent le fallback exact.

`nanite_snow.lua` lit neuf points du `CoarseMipReadbackFp16RT` natif toutes
les cinq secondes. Les lectures de `CoarseMipRT` directement via Kismet ne
conviennent pas : son format n'est pas accepté par `ReadRenderTargetRawPixel`.
La moyenne régionale pilote une couverture commune au massif, évitant les
variations artificielles entre partitions. C'est une approximation visuelle
de la neige disponible sur les nouveaux replats, pas une nouvelle simulation
physique locale. Les épaisseurs restent celles des couches préparées ; la
collision, le damage et la simulation de neige native utilisent toujours le
R16. Sans profondeur valide, les couches complémentaires sont masquées.
Les callbacks s'arrêtent lors du déchargement de la carte.

Le cache autorise désormais jusqu'à 128 ressources partitionnées. Les couches
complémentaires sont facultatives là où elles n'ont aucune face, mais exigent
les portions roche/neige natives correspondantes et le même nombre de
partitions. Une couche complémentaire manquante ou invalide provoque le
retour atomique au rendu d'origine. Les limites de métadonnées restent à
128 Kio. Cette passe ajoute 42 ressources, totalisant 943 066 triangles,
aux 64 ressources principales. Les sorties corrigées se trouvent dans
`build/nanite/massif-snow-transition/deposits-v2` et `deposits-v2-cooked`.

Un essai intermédiaire prolongé a atteint sa limite de mémoire de 6 Gio : le
groupe a été arrêté, puis les caches et conteneurs antérieurs ont été
restaurés. Les essais suivants utilisent une limite de 8 Gio sans swap,
une durée bornée et des sauvegardes de diagnostic sur disque. Le premier
rendu complet avec dépôts s'est fermé avec le code 0, sous cette limite. Il
confirme par `ClearSnow` que la couverture passe de 1 à 0 lorsque la
profondeur régionale native passe d'environ 157 cm à moins de 0,001 cm.
Cette observation valide le lien météo ; la sélection des facettes et le
fondu de couleur ont ensuite été affinés.

La validation finale de cette passe utilise le chargeur installé : **106
ressources**, 318 fichiers de conteneurs vérifiés par empreinte, trois caches
identiques et un seul démarrage du mod. Les 11 captures de 2560 × 1440 pixels
(vues d'ensemble, proche et sud en natif/Nanite/fallback, plus hiver/sans
neige sur un replat) sont dans
`build/nanite/massif-snow-transition/captures-coated`. Le jeu sort avec le
code 0 ; le pic mémoire est de **3,56 Gio**, sous la limite de 8 Gio sans swap,
sans OOM lors de cet essai final. Le `timeout` du service concerne les deux
processus auxiliaires Wine restés actifs après la fermeture normale du jeu.
La configuration LiveProbe est restaurée et son activation de test supprimée.
Les 166 tests Python, les 22 fichiers de tests Lua **5.4** et
`git diff --check` réussissent. Le Lua système 5.2 ne convient pas au test du
registre, qui utilise `string.pack` ; les contrôles complets utilisent
`/tmp/lua-5.4.8/src/lua`.

`build/nanite/massif-snow-transition/validation.json` conserve les résultats
et limites ; `rollback.py` restaure le cache précédent sans recréer le
second chargeur supprimé. L'enneigement complémentaire reste visuel et
régional, avec une épaisseur préparée fixe. Les parties longues et le
rechargement de sauvegardes ne sont pas couverts par cette validation.
