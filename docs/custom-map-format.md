# Format de carte source SkiEO 1.5

Le format `skieo-map` décrit une carte indépendamment des packages cuits
d'Unreal Engine. Le fichier portable `.skieomap` contient les données source ;
le mod `SkiEO-CustomMaps` lit le heightmap et construit le terrain au
chargement.

Les fichiers `.pak`, `.ucas` et `.utoc` sont interdits. Cette règle est
appliquée par l'éditeur, le validateur Python et le chargeur Lua.

## Paquet portable

Un `.skieomap` est un ZIP **Store ou Deflate**, utilisable comme
un fichier unique :

```text
AlpineValley.skieomap
  custom-map.json
  Terrain/
    heightmap.r16
  Scripts/
    main.lua
  Assets/
    trails.geojson
    chalet.glb
```

Le lecteur vérifie les CRC et accepte les ZIP compressés courants. Le module
natif fourni accélère Deflate ; un lecteur Lua borné reste disponible. Les ZIP64
et archives chiffrées ne sont pas acceptés. Un dossier contenant la même
arborescence reste accepté pendant le développement.

Depuis 1.5, `dependencies` peut déclarer les mods requis ; voir le
[contrat Steam Workshop](steam-workshop.md). Les anciennes cartes 1.x restent compatibles.

## Manifeste minimal

```json
{
  "$schema": "https://skieo.community/schemas/custom-map-1.json",
  "format": { "name": "skieo-map", "version": "1.5.0" },
  "id": "example.alpine-valley",
  "metadata": {
    "name": "Alpine Valley",
    "version": "1.0.0",
    "authors": ["Example Author"],
    "description": "A small alpine sandbox.",
    "language": "en",
    "localizations": {
      "fr": { "description": "Un petit bac à sable alpin." }
    }
  },
  "terrain": {
    "size_meters": [8064, 8064],
    "elevation_meters": [850, 2310],
    "origin_centimeters": [-403200, -403200, 0],
    "source": {
      "file": "Terrain/heightmap.r16",
      "format": "r16le",
      "vertices": [2017, 2017],
      "spacing_meters": 4,
      "row_order": "north_to_south",
      "height_scale_meters": 0.025,
      "height_offset_meters": 724
    },
    "runtime": {
      "sample_step": 4,
      "tile_quads": 63,
      "uv_tile_meters": 20,
      "material": "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial",
      "material_color": [0.18, 0.20, 0.22, 1],
      "snow_material": "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial",
      "snow_color": [0.78, 0.84, 0.92, 1],
      "snow_offset_centimeters": 30
    },
    "preview": {
      "samples": [[0, 0.1, 0], [0.2, 1, 0.3], [0, 0.2, 0]]
    }
  },
  "content": { "assets": [] }
}
```

L'anglais est la langue d'affichage actuelle de Ski-E-O. Les champs principaux
de `metadata` doivent donc être en anglais et `metadata.language` vaut `en` par
défaut. `metadata.localizations` peut néanmoins préparer les traductions de
`name`, `description` et `license`, indexées par une balise de langue BCP 47
(`fr`, `fr-CA`, etc.). Le chargeur conservera ces textes jusqu'à ce que le jeu
propose une sélection de langue.

Depuis la version 1.3, aucune carte du jeu ne sert de gabarit. Le chargeur
ouvre `/Engine/Maps/Entry`, le niveau vide standard du moteur, avec le mode de
jeu SkiResort. Il crée lui-même le paysage, l'environnement alpin, le soleil
et le ciel avant le démarrage des acteurs. Ce choix appartient au mod ; le
paquet portable ne contient aucun chemin de niveau Unreal. Les anciens
manifestes 1.x avec `game.template_level` restent acceptés, mais ce champ est
ignoré. Le bloc `game` est facultatif ; une carte source n'a pas besoin de
numéro de build du jeu. `game.level` et `game.initial_save` restent interdits.

`uv_tile_meters` fixe la répétition métrique des textures, indépendamment de la
taille totale de la carte. Si `snow_material` est présent, le chargeur construit
une seconde coque sans collision, décalée verticalement de
`snow_offset_centimeters`. Pour les animaux et empreintes,
`snow_surface_bias_centimeters` calibre le contact avec la surface visuelle
du matériau de neige (défaut 0, de −100 à 100 cm ; Veymont : −12 cm).
Ce réglage ne modifie ni le maillage ni la simulation de neige. Le sol conserve son propre matériau et sa collision.
Les tableaux `material_color` et `snow_color` teintent les matériaux qui
exposent un paramètre `Color`. Sans matériau explicite, le monde indépendant
utilise `M_Prop_albtex` avec l’albédo déclaré par la carte, ou la texture
partagée `t_terrain_rock_alb` si aucun albédo n’est fourni, et `M_Snow` pour la neige. Les faces raides du sol utilisent une projection
verticale de la texture pour éviter son étirement ; les
matériaux et couleurs du manifeste sont respectés.
La jupe verticale est calculée automatiquement depuis le périmètre du R16.
Son pied se situe sous le point le plus bas de ce périmètre. La profondeur
automatique vaut le maximum de 100 m, 4 % du petit côté de la carte et 20 %
du relief du périmètre ; `skirt_depth_meters` peut remplacer ce calcul.
Le matériau par défaut est `M_StriatedRock`, également utilisé par la jupe
standard du jeu. `skirt_material` et `skirt_color` permettent de le
personnaliser, et `skirt_enabled: false` de désactiver les parois. Aucun
maillage préfabriqué ni fond horizontal couvrant la carte entière n'est requis.

Après `FinalizePlacement`, le chargeur contrôle aussi les bâtiments contre le
R16. Seuls ceux réellement sous le sol sont remontés à sa hauteur ; la tolérance
est réglable par `placeable_below_ground_tolerance_centimeters` et un éventuel
dégagement par `placeable_clearance_centimeters`.
Les remontées demandent un traitement distinct : les gares et pylônes ont des
coordonnées monde indépendantes de la position de l'acteur. Après les étapes
natives d'initialisation, de génération et de chargement, le chargeur recale
les `Waypoints`, les bases des `Towers` et leurs composants de maillage, puis
reconstruit le câble et les sièges. Les points déjà au-dessus du terrain sont
conservés, de même que la hauteur propre de chaque pylône.

## Présentation dans le menu et au chargement

L'extension facultative `community.skieo.presentation` accompagne les cartes
1.x sans modifier leur terrain ou leur script. Le menu affiche la vignette,
les compteurs et les difficultés. `loading_image` permet de choisir une autre
illustration pour le fond et la fiche du chargement ; sans ce champ, le
chargement réutilise `image`. Exemple :

```json
{
  "content": { "assets": ["Preview/veymont.png", "Preview/veymont-loading.png"] },
  "extensions": {
    "community.skieo.presentation": {
      "image": "Preview/veymont.png",
      "loading_image": "Preview/veymont-loading.png",
      "trails": 20,
      "lifts": 9,
      "difficulties": ["beginner", "intermediate", "expert"]
    }
  }
}
```

`image` et `loading_image` doivent aussi être déclarés dans `content.assets` pour être inclus dans
le `.skieomap`. Le chargeur importe uniquement un PNG RGB/RGBA 8 bits, limité
à 2048 pixels par dimension et 8 Mio, depuis le lecteur de paquet. Une image
absente ou illisible laisse le pictogramme de montagne et le fond natif.
Les compteurs sont des entiers positifs ou nuls déclarés par l'auteur, sans
exécution du script de la carte. Les difficultés admises sont `beginner`,
`intermediate`, `advanced` et `expert`. Les valeurs absentes s'affichent `—`
et les difficultés non déclarées « Not specified ». Les articles Workshop
sans manifeste installé n'affichent aucun compteur ni statistique de terrain.

L'illustration de Veymont est une image de menu générée, et non une capture
du terrain en jeu. Sa provenance et son prompt figurent dans
[la documentation Veymont](../mod/SkiEO-Veymont/README.md#illustration-du-menu).

## Textures du terrain

Depuis le format 1.4, `terrain.textures` déclare les images portables du sol.
Les fichiers sont inclus automatiquement dans le paquet ; il ne faut pas les
répéter dans `content.assets`. Le canal `albedo` utilise le paramètre `Albedo`
du matériau de sol par défaut. Les autres canaux, par exemple `reflection`,
se déclarent de la même façon et nécessitent un matériau exposant le paramètre
correspondant dans `terrain.runtime.texture_parameters`.

```json
"textures": {
  "albedo": {
    "file": "Terrain/limestone-albedo.png",
    "mips": [
      "Terrain/limestone-albedo-mip01.png",
      "Terrain/limestone-albedo-mip02.png",
      "Terrain/limestone-albedo-mip03.png",
      "Terrain/limestone-albedo-mip04.png",
      "Terrain/limestone-albedo-mip05.png",
      "Terrain/limestone-albedo-mip06.png",
      "Terrain/limestone-albedo-mip07.png",
      "Terrain/limestone-albedo-mip08.png",
      "Terrain/limestone-albedo-mip09.png"
    ],
    "color_space": "srgb"
  }
}
```

Les images sont des PNG RGB/RGBA 8 bits, carrés, de taille puissance de deux
jusqu'à 512². `mips` contient tous les niveaux suivants, dans l'ordre,
jusqu'à 1² ; pour une image 512², les neuf niveaux vont donc de 256² à 1².
Le jeu importe les images puis assemble leur chaîne de détail complète,
sans modifier une texture cuite. `color_space` vaut `srgb` pour les couleurs,
`linear` pour les données, comme une carte de rugosité. Le matériau choisi
doit exposer les paramètres indiqués ; déclarer une réflexion ne crée pas
un shader de réflexion dans un matériau qui en est dépourvu.

```sh
python3 tools/build_texture_mips.py source.png Terrain/limestone-albedo.png
```

Cet outil de préparation utilise Pillow. Le paquet résultant et le chargeur
restent indépendants de Python et d'Unreal Editor. Une carte sans `textures`
conserve le comportement précédent, avec la roche partagée du jeu.


## Encodage du terrain

La version 1.2 accepte `r16le` et `r16be`. Chaque échantillon non signé est
converti en altitude par :

```text
altitude_m = valeur_r16 × height_scale_meters + height_offset_meters
Z_unreal_cm = origin_centimeters.z + altitude_m × 100
```

Les colonnes vont de l'ouest vers l'est. `row_order` précise si la première
ligne va du nord vers le sud ou l'inverse. Les deux premiers éléments de
`origin_centimeters` positionnent le sommet `[0, 0]` dans le monde Unreal.

Le R16 reste à sa résolution d'origine dans le paquet. Les systèmes natifs
utilisent une grille de 2017 × 2017 échantillons, rééchantillonnée sur toute
l’emprise : ce nombre ne limite pas la carte à 8 km. Le pas natif vaut
`size_meters[axe] / 2016` et peut différer entre X et Y. La source peut être
rectangulaire et atteindre 16 384 sommets par axe. `sample_step` fixe la grille
de base des maillages procéduraux à partir de la source : Veymont 0.6 utilise
2017 × 3025 points à 4 m, soit 505 × 757 points à 16 m avec une valeur de 4.
Son cache natif est à 4 × 6 m. Voir le [guide des grandes cartes](large-maps.md). Dans le monde indépendant, les cellules dont la pente dépasse
45° sur un axe sont subdivisées jusqu'au pas source, avec au maximum quatre
subdivisions par axe et 16 384 cellules raffinées. Si cette limite est atteinte,
les cellules les plus pentues sont prioritaires. Les raccords partagent les
échantillons des arêtes, y compris entre sections, et la neige utilise le même
plan de raffinement. Les normales sont calculées au pas source. `tile_quads`
découpe les maillages en sections pour limiter le coût de création et de
collision. Ce raffinement conserve les altitudes du R16 ; il ne crée pas de
surplombs ni de relief absent des données.

`preview.samples` est une grille normalisée de 3 à 33 points par axe, utilisée
uniquement dans le menu. L'éditeur la recalcule depuis le R16.

## Localisation et ressources

Le bloc facultatif `location` accepte `latitude`, `longitude`, un libellé et
`world_map_uv`. Ce dernier est un repère `[x, y]` normalisé sur la mappemonde
illustrée du menu et donne un placement visuel plus précis qu'une projection
géographique automatique.

`content.assets` énumère les autres sources empaquetées. Les blocs
`editor.layers` et `editor.asset_catalog` peuvent les décrire. Une ressource
référencée par ces blocs doit aussi figurer dans `content.assets`. Les versions
futures pourront importer des modèles de bâtiments depuis cette zone sans
changer la définition du terrain.

Un script peut lire une de ces ressources avec `api:read_asset(path)`. Le
chargeur refuse tout chemin absent de `content.assets`, ce qui conserve la même
isolation dans un dossier de développement et dans une archive. Veymont utilise
ainsi `Vegetation/forest.skxy`, un flux portable composé de l'en-tête `SKXY`,
de sa version et du nombre de points, puis de couples `float32` X/Y. Le
chargeur recalcule Z depuis le R16 et reconstruit progressivement un ISM natif ;
aucune instance d'arbre cuite par Unreal n'est transportée par la carte.

## Forêts : JSON source, SKXY dans le package

Depuis Custom Maps 1.11, le chargeur accepte uniquement des arbres SKXY.
`skieomod build` compile le JSON de positions défini par
`build.forest.file` dans `Vegetation/Generated/forest.skxy`, déclare cet asset et
prépare son chargement avec `api:load_forest_skxy` dans `map.ready`.
Le JSON reste dans le projet et ne figure pas dans le package.

```json
"build": {"forest": {"file": "Vegetation/forest.json"}}
```

Le fichier source contient un tableau de points `{ "x": 10, "y": -20 }` en
mètres du monde, X vers l’est et Y vers le sud. Il est limité à 32 Mio et un
million de points finis. Le build refuse les champs supplémentaires et les
clés dupliquées. SKXY encode les coordonnées en centimètres float32.
Le chargeur recalcule Z depuis le R16 et reconstruit les instances par lots.
Le bouton de visibilité agit sur ces arbres, sans collision de gameplay.

`build.heightmap.processing` configure le lissage, l’érosion thermique,
l’érosion par drainage et le bruit. `build.vegetation` configure le biome,
la forêt automatique et la texture de couverture herbe/roche. Le build dérive
les métadonnées du relief traité et écrit directement les arbres en SKXY.
La forêt automatique prend la priorité sur `build.forest`.
Les paramètres `build` restent locaux et sont retirés du package.

Le [guide anglais](vegetation.md) précise les algorithmes, unités, limites
et valeurs par défaut ; le [schéma](../schemas/custom-map.schema.json)
décrit la configuration. `load_forest_json` a été supprimé du chargeur.

## Chargement par le mod

Le chargeur suit cette séquence :

1. validation du manifeste et de tous les chemins ;
2. affichage de l'écran de chargement et lecture du R16 ;
3. génération des textures de hauteur et des atlas Landscape avant le voyage ;
4. ouverture du monde vide avec le mode de jeu habituel ;
5. création du paysage, de ses composants, de l'environnement et de l'éclairage
   dans le hook UE4SS `RegisterInitGameStatePreHook`, avant World BeginPlay ;
6. initialisation du cache de hauteur et des overlays depuis la source,
   construction du terrain visible, de sa collision et de la coque de neige,
   puis ouverture de la saison, création d'un enneigement initial natif et
   invalidation de la navigation calculée avant installation des hauteurs ;
7. émission de `map.terrain_loaded`, puis de `map.ready` ;
8. exécution des actions de la carte ;
9. vérification finale des hauteurs et retrait de l'écran de chargement après
   achèvement des tâches de création de la station.

L'écran reste affiché pendant la construction asynchrone. Une erreur ou cinq
minutes sans progression produisent un diagnostic sans annoncer un succès.

Les 16 atlas 512², leurs dix niveaux de mip, les 1024 composants Landscape et
la texture de simulation sont des objets transitoires créés depuis le R16.
Chaque composant reçoit son propre rectangle UV, ses limites et le paramètre
matériel `Heightmap` correspondant. Leurs tableaux sont alloués par Unreal ;
aucun fournisseur de stockage, composant ou cache de Sugar Bowl n'est repris.
La végétation et la station sont créées ensuite depuis les sources portables.

Le Landscape sert à initialiser les limites et les caches natifs. Le terrain
visible et sa coque de neige sont des maillages procéduraux qui utilisent les
matériaux partagés `M_Prop_albtex` (texture de roche) et `M_Snow` du jeu ; la jupe
utilise séparément `M_StriatedRock`. Les permutations de shader
Landscape nécessaires ne sont disponibles que dans les niveaux cuits. Le pas
de base de ces maillages reste contrôlé par `sample_step` du manifeste ; les
pentes fortes bénéficient du raffinement local décrit ci-dessus. Le mod initialise
décembre avec 100 cm de neige tassée et 20 cm de poudreuse, à −5 °C, via
`SkiResortSimulator.Snow.SetLevel`, sans charger de sauvegarde. La simulation
native poursuit ensuite l'évolution de cet enneigement.

Le contrôleur natif `ClayEnvironmentController` anime le soleil, la lune,
l'exposition et les couleurs selon le calendrier et la météo. Une cubemap
diurne du moteur fournit l'éclairage ambiant du monde neuf. Le matériau
instancié des flocons suit cette lumière, y compris la nuit et pendant les
tempêtes, et leurs composants ne projettent pas d'ombres. Le décalage vertical
du R16 est appliqué une seule fois : la conversion native d'altitude est
calibrée sur l'origine du monde et l'étendue de quantification du Landscape.
Les textures natives sont réencodées à partir de zéro lorsque la source a un
décalage positif. Leur plage inclut ainsi ce décalage et ne plafonne plus
l'altitude affichée à la seule amplitude du R16. Les données portables et les
positions visibles restent inchangées ; seule la quantification native change.

Les sauvegardes natives conservent `/Engine/Maps/Entry` comme niveau. Le chargeur
associe chaque identifiant de partie à la carte dans un fichier
`SkiEO-CustomMap-<GUID>.json` voisin des sauvegardes. Une nouvelle partie custom
reçoit un GUID neuf, distinct de la partie précédente et de ses autosaves. Au
chargement, le monde, le terrain, l'éclairage et la forêt sont reconstruits ;
la station, l'économie, le calendrier et l'enneigement sauvegardés sont conservés.
La simulation reste suspendue pendant toute la reconstruction.

Les anciennes sauvegardes `Entry` sans association peuvent être migrées si une
seule carte custom est installée. Le chargeur refuse de deviner entre plusieurs
cartes ou de remplacer une carte absente. Une sauvegarde native d'un autre niveau
ne déclenche pas ce chemin de restauration. Le fichier d'association doit
accompagner les sauvegardes lorsqu'une partie est transférée sur une autre machine.

Après l'ajout par lots d'une forêt SKXY, le chargeur force une mise à jour d'une
instance existante. Ce rafraîchissement publie le buffer de rendu de l'ISM sans
modifier les positions : le nombre d'arbres dessiné correspond alors au nombre
d'instances de gameplay, au lieu de n'afficher qu'un petit lot intermédiaire.

## Scripts Lua

Un point d'entrée facultatif se déclare ainsi :

```json
{
  "script": {
    "language": "lua",
    "api": "1.0",
    "entry": "Scripts/main.lua",
    "permissions": ["gameplay"]
  }
}
```

Exemple :

```lua
return function(api)
    api:on("map.ready", function(event)
        api:log("La carte " .. event.map.id .. " est prête")
        api.game:set_time_rate(1)
    end)
end
```

Événements de cycle de vie :

| Événement | Moment |
|---|---|
| `map.before_load` | avant la préparation du monde indépendant |
| `map.after_load` | juste après `OpenLevel` |
| `map.terrain_loaded` | après création complète du terrain et des collisions |
| `map.ready` | lorsque le script peut créer pistes, remontées et bâtiments |
| `map.load_failed` | si la construction du terrain échoue |
| `map.unloading` | avant le chargement d'une autre carte |

Les événements de cycle de vie portent `event.restored = true` lorsqu'ils
concernent une sauvegarde. Dans ce cas, le script doit reconstruire ses éléments
transitoires (par exemple la forêt) et préserver les pistes, bâtiments et
remontées que le jeu a restaurés. Veymont applique cette distinction.

Un script qui construit des objets de façon asynchrone doit réserver une tâche
**pendant** son callback `map.ready`, puis signaler sa fin :

```lua
api:on("map.ready", function()
    local done = api:hold_loading()
    api:after(100, function()
        -- Construire la station ici, puis :
        done() -- ou done("message d'erreur") en cas d'échec
    end)
end)
```

Plusieurs tâches peuvent coexister ; toutes doivent être terminées. Les appels
répétés à `done()` et les callbacks d'une ancienne carte sont ignorés. Veymont
signale la fin après création des bâtiments, remontées et pistes ; le chargeur
attend ensuite la sortie de la pile de finalisation native avant de vérifier
les positions et de retirer l'écran.

Les tâches longues peuvent appeler `api:loading_progress("Création de la forêt", 0.75)`
pour mettre à jour l'écran et signaler leur avancement (fraction de 0 à 1).
Le chargement échoue après cinq minutes sans progression. Une forêt qui avance
continue à se charger même si la durée totale dépasse cinq minutes.

L'API expose aussi les événements de calendrier, météo, pistes et objets
constructibles documentés dans `api.lua`. L'environnement par défaut ne donne
pas accès à `io`, `os`, `debug`, `package`, `require`, `load` ou aux objets
Unreal. `skieo.unrestricted` est réservé aux conversions historiques et ne doit
jamais être activé automatiquement par l'éditeur.

## Éditeur et outils

`skieomod editor` ouvre l'éditeur de bureau intégré à Python. Il accède au
dossier source, importe les R16/PNG16, sculpte le terrain, peint les arbres et
configure les traitements du build. Les boutons Build/Test/Play utilisent les
mêmes commandes que la CLI. Le [guide de l'éditeur](editor.md) décrit le parcours.
L'ancienne application HTML autonome a été retirée.

Les mêmes opérations sont disponibles en ligne de commande :

```bash
python3 tools/custom_maps.py validate mod/SkiEO-Veymont/custom-map.json
python3 tools/custom_maps.py pack mod/SkiEO-Veymont/custom-map.json dist/Veymont.skieomap
python3 tools/custom_maps.py inspect dist/Veymont.skieomap
```

Le schéma de référence est
[`schemas/custom-map.schema.json`](../schemas/custom-map.schema.json). Le
validateur vérifie en plus la sécurité des chemins, l'absence de contenu cuit,
la taille exacte du R16, l'unicité des références et la présence de chaque
fichier.

## Sources d’édition compilées au build (CLI 1.14)

Les fichiers d’édition restent dans le projet. Le build les compile dans le
script Lua du paquet, en conservant le script d’origine et la forêt générée :

```json
"build": {
  "triggers": { "file": "Triggers/triggers.json" },
  "resources": { "file": "Resources/assets.json" },
  "objects": { "file": "Objects/overrides.csv" },
  "scene": { "file": "Scene/objects.json" }
}
```

Les déclencheurs JSON `version: 1` contiennent un tableau `triggers`. Chaque
entrée définit `id`, `name`, `event`, `enabled` et `mode` (`graph` ou `lua`).
Le booléen facultatif `before_script` (faux par défaut) enregistre le callback
avant ceux du script d’initialisation ; l’action attend toujours son événement.
Un graphe contient `nodes` (`id`, `kind`, `params`, `position`) et `edges`
(`source`, `port`, `target`, `input`). La compilation vérifie les types des
broches, les entrées uniques et l’absence de cycles. Chaque entrée de données
doit être reliée : une valeur numérique comme 50000 appartient à un nœud
`number` (`params.value`) relié à `funds.amount`, pas aux paramètres de l’action. Le mode Lua fournit le
corps du callback dans `lua` ; `api` et `event` sont disponibles. Voir
[triggers.schema.json](../schemas/triggers.schema.json) et le
[guide de l’éditeur](editor.md).

Le nœud `scenario_configure` reçoit les connexions `currency` (texte),
`start_year`, `starting_balance` et `ticket_price` (nombres), ainsi que
`in`/`then` pour l’exécution. Son paramètre facultatif `rules_module` nomme un
module Lua local d’API 1.1, sans extension, déclaré dans `content.assets` avec
ses dépendances. Il fournit `costs`, `class_costs`, `loans` et
`track_lift_rides`. Un module vide suffit à un scénario simple. Cette action
appelle `api.game:configure` une seule fois par session ; la configuration
initiale de Super Saint-Bernard utilise `map.ready` et `before_script: true`.
Le [tutoriel scripts et scénarios](https://skieomod.emillon.fr/tutorials/scripts/)
privilégie le graphe pour les débutants, avec captures réelles et onglets Lua.

La bibliothèque JSON `version: 1` contient `assets`. Une entrée définit `id`
et `kind` : `model`, `image`, `sound` avec `file`, ou `game` avec le chemin
complet d’un objet déjà cuit (`/Game/Dossier/Asset.Asset`). Le modèle portable
est un OBJ statique (50 000 triangles, 32 Mio), avec `units` (`meters` ou
`centimeters`) et `up_axis` (`z` ou `y`). La géométrie est compilée en Lua pour
remplacer un composant StaticMesh individuel. Le matériau et la collision
originaux sont conservés. Les ressources de foule/sons nécessitent des objets
cuits compatibles, fournis par le jeu ou un mod installé. Les images et sons
sources peuvent être ajoutés au contenu du paquet, sans conversion en objets
Unreal. Voir [resources.schema.json](../schemas/resources.schema.json).

Le CSV UTF-8 utilise `object,field,type,value`, avec une colonne `instance`
optionnelle depuis le chargeur 1.16. Une cellule `instance` vide définit une
valeur pour le type dans cette carte ; une cellule non vide contient l'`id`
d'un objet placé de `Scene/objects.json`. Le build vérifie la classe de cet
objet et compile son GUID stable. Les différences de type s'appliquent avant
celles de l'instance. Supprimer une instance dans l'éditeur supprime aussi ses
différences ; Annuler restaure les deux. `object` est le
chemin de la classe, `field` une propriété ou `composant.propriété`, `type` est
`integer`, `number`, `boolean`, `string`, `name`, `text`, `model`, `asset` ou
`sound`. `value` est un littéral JSON avec l’échappement CSV habituel. Une
ressource de bibliothèque est référencée par `asset:identifiant` ; une
ressource cuite peut être un chemin complet. Les différences s’appliquent aux
instances de la classe dans le monde de la carte, y compris les instances
construites ultérieurement, puis sont restaurées au déchargement. Les valeurs
par défaut des classes du jeu ne sont pas modifiées. Le chargeur 1.14 est
nécessaire pour `api:apply_object_edits` ; permission `gameplay` requise.

Le [tutoriel Ticket Office](https://skieomod.emillon.fr/tutorials/ticket-office/)
montre le parcours avec captures et exemple OBJ.

La scène JSON `version: 1` définit un tableau `objects` (1 024 éléments maximum).
Chaque instance a `id`, `class`, `kind`, `name`, `position: [est, sud]` en mètres
relatifs au centre, `rotation_degrees` et `height_offset_meters` optionnels.
Une remontée (`kind: "lift"`) a aussi `end_position`. Le build calcule les
coordonnées du monde, les identifiants stables et les hubs ; le runtime déduit
Z de la surface finale et crée les acteurs par le cycle de construction natif.
Les sauvegardes du jeu conservent ces acteurs sans les recréer au chargement.
Un `name` vide ou identique au nom initial du type hérite du nom de ce type
dans la carte. Un nom personnalisé reste propre à l'instance et est appliqué
après la finalisation native du placement.
Voir [scene.schema.json](../schemas/scene.schema.json).

## Script API 1.1 : propriétés et scénarios

Depuis skieomod 1.19.0, une carte avec la permission `gameplay` peut ajouter des propriétés dans la fiche Informations des bâtiments et remontées, et des commandes dans Gestion de la station → Exploitation. Les modules Lua déclarés dans la carte peuvent être chargés avec `require`; le module `json` est également accessible sans permission unrestricted. Les scripts API 1.0 conservent leur environnement existant.

```lua
return function(api)
    local state = api:state({maintenance = 2, condition = 65})
    api:scenario({title = 'Sauver la station',
        objectives = {{label = 'Conserver les installations', progress = function()
            return {value = state.condition .. ' %', fraction = state.condition / 100}
        end}}, status = function() return 'active' end})
    api:building_properties(function(actor)
        return {{label = 'État', value = state.condition .. ' %',
                 fraction = state.condition / 100}}
    end)
    api:resort_panel({
        title = 'Entretien',
        properties = function()
            return {{label = 'Budget annuel', value = '60 000 CHF'}}
        end,
        controls = {{id = 'maintenance', label = 'Effort',
            options = {'Minimum', 'Préventif', 'Renforcé'},
            get = function() return state.maintenance end,
            set = function(index) state.maintenance = index end}},
        actions = {{label = 'Travaux — 800 000 CHF',
            run = function()
                if api.game:charge(800000, 0, false) then
                    state.works_ordered = true
                end
            end}}
    })
end
```

`api:state(defaults)` fournit une table JSON mutable, restaurée avant l’exécution du script. Elle est conservée dans chaque sauvegarde native du scénario déclaré avec `api:scenario` (limite : 32 KiB de JSON). Elle ne doit contenir ni fonction ni objet Unreal. Les panneaux sont reconstruits par le script au rechargement ; leurs callbacks n’appartiennent pas à l’état sauvegardé.

`api:scenario{title, tracker_title, briefing, goal, deadline, objectives, status}` utilise les panneaux natifs de briefing, d’objectifs et de résultat. `tracker_title` permet un titre court pour le suivi dans le HUD. Le panneau accepte un à quatre objectifs. Chaque objectif fournit `label` et `progress()` retournant `{value = texte, fraction = 0..1}`. `status()` retourne `active`, `completed` ou `failed`. Les règles de succès et d’échec appartiennent au script.

Les opérations synchrones suivantes s’exécutent dans les callbacks de carte, sur le thread de jeu :

- `api.game:configure{currency, start_year, starting_balance, ticket_price, costs, class_costs, loans, track_lift_rides}` configure une session. `currency` est le code ISO de l’unité économique du scénario. Le format monétaire natif reste celui du jeu : remplacer les textes après leur affichage provoquerait un clignotement. Le solde et le forfait de départ ne sont pas réappliqués lors d’une restauration. `costs` cible les lignes du catalogue économique natif ; leurs valeurs partagées sont restaurées en quittant la carte. `class_costs` cible les classes de previews et d’instances de la session.
- `loans` cible les offres natives `Small`, `Medium`, `Large` avec `{name, income_days, annual_rate, months}`. Le taux nominal annuel est divisé par douze. Le capital reste calculé par le jeu d'après ses recettes récentes et `income_days`, avec ses seuils et arrondis ; la colonne Principal du catalogue ne permet pas de fixer ce capital. Les offres partagées sont restaurées à la sortie ; les contrats existants ne sont pas réécrits.
- `api.game:snapshot()` renvoie la date historique calculée à partir de `start_year`, les mois écoulés, le solde, les recettes et charges annuelles natives, et la compression du calendrier. La barre supérieure conserve la date native du jeu ; `start_year` ne réécrit pas son affichage. Avec `track_lift_rides=true`, `lift_rides` associe chaque GUID de remontée à son compteur natif cumulatif de clients transportés.
- `api.game:charge(montant, catégorie, obligatoire)` débite et enregistre une dépense. Un achat facultatif retourne `false` si le solde est insuffisant ; une dépense obligatoire peut rendre le solde négatif. Les catégories natives 0 et 1 correspondent à la construction et à l’entretien.
- `api.game:record_revenue(montant)` crédite une recette et l’inscrit dans les comptes.
- `api.game:set_weather(type, température)` impose la météo native : 0 soleil, 1 nuages, 2 précipitations, 3 blizzard.
- `api.game:placeables()` retourne les identifiants GUID, noms, classes, positions et type des objets placés de la session.
- `api.game:set_installation(id, {disabled, operating_cost, no_refund})` fixe un arrêt, le coût natif quotidien ou protège une installation historique contre démolition, déplacement et remboursement.
- `api.game:place_resort(objets, pistes)` crée une station lors d’une nouvelle partie et enregistre les hubs, pistes et employés dans les systèmes natifs. Une restauration conserve les objets et employés sauvegardés.
- `api.game:set_hub_names({{name, x, y}, ...})` nomme chaque nouveau hub d'après l'ancre géographique la plus proche. Les noms sont stockés dans la table native utilisée par les panneaux et sauvegardes, sans réécriture périodique des textes. Les noms sont limités à 32 caractères ; un hub déjà traité dans la session n'est pas renommé à chaque appel.

### Couleurs et seuils de notation des pistes

`api.game:set_trail_rating_system(options)` configure la notation pour la carte
active (permission `gameplay`, chargeur **1.21.0**). La palette et les seuils sont
indépendants. Exemple de trois niveaux bleu, rouge et noir :

```lua
return function(api)
    api:on('map.ready', function()
        api.game:set_trail_rating_system({
            style = 'european',
            thresholds_percent = {25, 40},
        })
    end)
end
```

Ces seuils sont un exemple à adapter à la station reproduite, pas une règle
universelle pour toutes les pistes autrichiennes. Ici, une pente inférieure à
25 % est débutante (bleu), de 25 % inclus à 40 % exclu intermédiaire (rouge), et
à partir de 40 % experte (noir). Le pourcentage est `100 × dénivelé / distance
horizontale` : 25 % correspondent à environ 14,04°, pas à 25°.

- `style` choisit les couleurs et symboles natifs : `european`,
  `north_american` ou `japanese`. Sans `style`, le choix du joueur est conservé.
- `colors` (chargeur **1.22.0**) remplace les couleurs de certains ou de tous
  les niveaux. Les clés sont `beginner` (0), `intermediate` (1), `expert` (2)
  et `extreme` (3). Chaque valeur est une chaîne hexadécimale sRGB `#RRGGBB`
  opaque, insensible à la casse. Les niveaux omis utilisent la palette du
  `style` choisi, ou celle du joueur si `style` est absent. Au moins une couleur
  est nécessaire si `colors` est fourni. Les symboles restent ceux du style.
- `thresholds_percent` ou `thresholds_degrees` donne **deux ou trois** seuils
  strictement croissants, positifs et finis. Les degrés doivent être au plus 90.
  Deux seuils calculent trois niveaux (0, 1, 2) ; trois seuils calculent quatre
  niveaux (0, 1, 2, 3). Exemple : `thresholds_degrees = {12, 25, 35}`.
  À l'égalité, la pente passe dans le niveau supérieur. Ne pas fournir les deux
  unités simultanément. Sans seuils, le calcul natif reste actif.
- `api.game:get_trail_rating_system()` renvoie une copie de la configuration,
  ou `nil` si la carte n'impose aucune notation.
- `api.game:get_trail_rating_capabilities()` (chargeur **1.23.0**, permission
  `gameplay`) renvoie `{style=bool, colors=bool, thresholds=bool, detail=texte}`.
  Cette sonde ne change pas la partie. Les trois capacités sont vérifiées
  séparément : un calcul de pente modifié peut laisser les couleurs disponibles.
  L'auteur peut choisir de conserver la notation native si une capacité manque.
- `api.game:set_trail_rating_system(nil)` rétablit immédiatement le système
  antérieur. La fermeture, le changement de carte et l'échec de son chargement
  le rétablissent également ; les préférences du joueur ne sont pas enregistrées
  ni modifiées par cette API.

Exemple avec des couleurs définies par l'auteur de la station :

```lua
api.game:set_trail_rating_system({
    style = 'european',
    thresholds_percent = {25, 40},
    colors = {
        beginner = '#0080FF',
        intermediate = '#E60000',
        expert = '#000000',
        extreme = '#FF8000',
    },
})
```

L'exemple garde trois niveaux calculés automatiquement ; `extreme` définit
aussi la couleur des pistes auxquelles le niveau 3 est attribué manuellement.
On peut fournir uniquement `colors = {expert = '#8844CC'}` pour changer un seul
niveau sans modifier les seuils ni les symboles. Un nouvel appel remplace toute
la configuration précédente : omettre `colors` restaure la palette native.
Les valeurs sRGB sont converties en couleurs linéaires pour le moteur.

Les seuils modifient le calcul natif `CalculateDifficultyFromSlope`, dont
l'entrée est l'angle de pente natif `P90SlopeAngle`. Les effets de la neige,
des bosses et des obstacles restent gérés par le jeu. Les notes déjà attribuées
par l'auteur ou le joueur ne sont pas réécrites ; elles prennent la nouvelle
palette. Les futures évaluations natives utilisent les nouveaux seuils.

Le rappel dans `map.ready` applique les mêmes règles à une partie neuve et à
une sauvegarde reprise. Pour des règles modifiables pendant la partie, conserver
leur configuration dans `api:state`, puis la réappliquer au rechargement.
On peut aussi fournir `trail_rating_system = {...}` à `api.game:configure`
depuis le script Lua de la carte.
Le module natif contrôle les signatures du jeu avant tout changement ; un
exécutable non reconnu est refusé explicitement. Le premier profil vérifié est
celui de la démo Steam `25996759`.

Depuis le chargeur 1.23.0, les fonctions de notation peuvent être relocalisées
si leur code et leurs références satisfont le contrat vérifié. La sonde refuse
les correspondances ambiguës et les changements de structure. Un appel à
`set_trail_rating_system` qui demande une capacité absente échoue explicitement
sans remplacer la configuration active. Exemple de repli choisi par la carte :

```lua
local available = api.game:get_trail_rating_capabilities()
if available.style and available.thresholds then
    api.game:set_trail_rating_system({
        style = 'european', thresholds_percent = {25, 40},
    })
else
    api:log('Notation native conservée : '..available.detail)
end
```

La console UE4SS `custommap_compatibility` indique les fonctions disponibles et
les contrôles en échec. Ces contrôles locaux ne remplacent pas la qualification
complète d'une nouvelle version du jeu.

La devise est une unité économique du scénario, sans conversion de change automatique. Le scénario doit définir ses prix et calibrer ses recettes et charges en conséquence. Super Saint-Bernard fournit un exemple complet de ces interfaces, avec des règles pures séparées du moteur dans `Scripts/survival.lua`.

Le [protocole Super Saint-Bernard](super-st-bernard-test-protocol.md) décrit les relevés de difficulté et les commandes explicites `custommap_test_snapshot <nom>` / `custommap_test_resume`. Le premier relevé suspend le monde du jeu en plus de son horloge pour empêcher l'évolution de la neige pendant les sauvegardes de test. Cette suspension n'est activée que sur demande de test.

### Paysage autour du terrain jouable

L’extension `community.skieo.scenery` décrit un relief R16 visuel autour de la carte : `size_meters`, `origin_centimeters`, `elevation_meters`, `source` au même format que le terrain principal, et un `material` natif facultatif. Son fichier doit être déclaré dans `content.assets`. La grille est limitée à 513 × 513 sommets avec un pas d’au moins 10 m et doit englober le terrain jouable. Le chargeur découpe le centre et raccorde les deux périmètres ; il n’ajoute aucune collision ni surface constructible à la simulation.
