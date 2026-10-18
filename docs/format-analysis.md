# Analyse du format de Ski-E-O! et prototype Veymont

Analyse effectuée sur la démo Steam, build `25551097`, les 26–27 septembre 2026.

## Conclusion

Une carte personnalisée peut être montée avant la sortie de l'éditeur. Le test
réel a chargé `/Game/Maps/Generated/Map_veymont` dans la démo, sans
remplacer les fichiers originaux. Le relief affiché est celui du MNT de
Gresse-en-Vercors, et non une simple copie renommée du niveau source. Son nom
de carte et son package sont désormais **Veymont**.

Les hauteurs des obstacles, la distribution forestière et les 1024 heightfields
de collision Chaos ont aussi été reconstruits. Une sauvegarde initiale native
ajoute décembre et 60 cm de neige. Le script crée 20 pistes, 9 remontées et un
Ticket Office d'après OpenStreetMap, puis reconstruit le tablier périphérique.
Les huit axes de téléskis utilisent provisoirement le télésiège une place du
jeu, aucun acteur de téléski exploitable n'ayant encore été identifié.

## Conteneurs du jeu

Le jeu est un titre Unreal Engine **5.8.2**, changelist `56702186`, projet
`SkiResortSimulator`. Son contenu est distribué en IoStore :

```text
SkiResortSimulator/Content/Paks/
  SkiResortSimulator-Windows.pak
  SkiResortSimulator-Windows.ucas
  SkiResortSimulator-Windows.utoc
  global.ucas
  global.utoc
```

Le `.pak` est en version 11. L'index n'est pas chiffré. Les blocs sont compressés
avec Oodle. Le triplet d'un mod est chargé depuis `Content/Paks/~mods` et les
scripts sont découverts par UE4SS grâce à :

```ini
+ModsFolderPaths = ../../../Content/Paks/~mods
```

UE4SS expérimental est nécessaire ici : sa branche actuelle annonce le support
de UE 5.8. La sonde locale a produit un USMAP et un JMAP complets : 37 085 objets
réfléchis, 4 418 tables virtuelles et aucune alerte.

## Niveaux découverts

Le build contient trois cartes de jeu cuites :

```text
/Game/Maps/Generated/Map_sugar_bowl
/Game/Maps/Generated/Map_sugar_bowl_real
/Game/Maps/Generated/Map_mad_river_glen_real
```

Il contient aussi 43 fiches d'aperçu. Les trois niveaux partagent la même
topologie de Landscape :

- résolution : 2017 × 2017 sommets ;
- 32 × 32 composants, soit 1024 composants ;
- 63 × 63 quads par composant ;
- une section par composant ;
- 16 textures de hauteur 512 × 512, rangées en atlas 4 × 4 ;
- dix mips par texture ;
- 1024 composants de collision ;
- un `TerrainSkirtActor`, un `SnowShellActor` et 64 morceaux de coque de neige.

Cette géométrie impose naturellement une carte de 2017 sommets. Avec un pas de
4 m, l'emprise obtenue est de 8064 m, ce qui convient au secteur de Gresse.

## Encodage des hauteurs cuites

Les textures ont le format déclaré `PF_B8G8R8A8`, mais leurs cinq plus grands
mips sont sérialisés par `ULandscapeTextureStorageProviderFactory` dans un
format spécifique. La structure observée est la suivante pour un mip de côté
`N` :

1. la grille utile a `(N - 7)²` hauteurs ;
2. les sept frontières de composants sont dupliquées pour reformer une texture
   `N × N` ;
3. les hauteurs 16 bits sont parcourues par lignes ;
4. chaque valeur est stockée comme delta modulaire, big-endian, par rapport à
   la précédente ; l'accumulateur initial vaut `0x8000` ;
5. le bloc est suivi des deltas des octets de normales X/Y sur le périmètre,
   avec des accumulateurs initiaux à 128.

La taille exacte est donc :

```text
2 × (N - 7)² + 2 × (4N - 4) octets
```

Pour les mips 16, 8, 4, 2 et 1, chaque pixel est brut sur quatre octets :

```text
normal X, hauteur faible, hauteur forte, normal Y
```

L'encodeur [`encode_cooked_heightmaps.py`](../tools/encode_cooked_heightmaps.py)
reproduit ce format. Après patch, les seize tuiles ont été redécodées et
recomposées en 2017 × 2017 : égalité octet par octet avec le R16 source et
aucune discontinuité aux coutures.

## Terrain Gresse-en-Vercors

L'ancienne collecte Grenoble fournit un contexte à 32 m mais ne couvre pas
Gresse avec assez de précision. Le prototype prélève directement une fenêtre
du COG public LiDAR HD Isère :

```text
centre Lambert-93 : E 901000, N 6424000
bounds             : 896968, 6419968, 905032, 6428032
centre WGS84       : 44.88601663, 5.54604349
pas de travail     : 4 m
résolution         : 2017 × 2017
altitude min/max   : 745.268066 / 2341.106934 m
```

La station HydroPortail de la Gresse, E 902788,566 / N 6428576,374 en
EPSG:2154, sert de contrôle indépendant de position. L'emprise comprend le
village, le front de neige, les pentes de la station et le secteur du Grand
Veymont.

Encodage Unreal choisi :

```text
Landscape scale XY : 400 cm
Landscape scale Z  : 320
Actor location     : (-403200, -403200, 154318.75) cm
erreur de hauteur  : <= 0.0125 m
```

Le système Landscape représente les valeurs 16 bits sur l'intervalle local
approximatif -256 à +256, multiplié par l'échelle Z. Les 1024 `CachedLocalBox`
ont été recalculées à partir du R16 afin que le frustum culling corresponde au
nouveau relief.

## Texture auxiliaire du rendu neigeux

Le décalage des bandes de neige ne venait pas des seize textures du Landscape,
mais d'une seconde donnée : le niveau source référence
`/Game/Materials/Terrain/Generated/sugar_bowl/H_sugar_bowl_Out`. Cet asset est
une texture `PF_B8G8R8A8` de 2017 × 2017 pixels, à un seul mip. Ses canaux B, G
et R contiennent tous l'octet fort de la hauteur R16 correspondante et son canal
alpha vaut 255.

[`patch_snow_height_texture.py`](../tools/patch_snow_height_texture.py) conserve
la structure cuite de l'asset, remplace ses pixels par l'octet fort du R16
Veymont, puis le patcher renomme son package en `H_veymont_Out` et remplace la
référence dans la carte. La texture produite couvre les valeurs 3 à 252 et sa
relecture redonne exactement les octets forts du R16. Cette correction concerne
le relief échantillonné par le matériau ; la coque héritée reste masquée.

## Sauvegarde et tuiles de neige

L'asset `/Game/InitialSaves/IS_Map_sugar_bowl` contient un SaveGame GVAS brut.
Sa propriété `SnowData` sérialise une texture globale 1008 × 1008 en RG16F et
un tableau de `SnowTileSaveEntry`. Chaque entrée contient une coordonnée
virtuelle, une résolution 256 × 256 et des pixels RG16F compressés par zlib. Les
deux canaux observés représentent les profondeurs compactée et fraîche.

Le monde couvre 8064 m avec des tuiles de 32 m : l'origine Landscape
`-403200 cm` correspond à l'indice virtuel 0 et donne un offset de 126 par
rapport aux coordonnées monde divisées par 3200. La tuile du front de neige est
ainsi `(173,71)`. Le cache accepte au plus 256 tuiles ; 246 entrées détaillées
sont fournies en plus de la grille globale. Les deux niveaux sont initialisés à
`20 / 40 cm` — neige compactée puis fraîche — pour éviter le gradient inversé
observé entre le front de neige et le haut de la station. La racine `GameTime`
est patchée d'octobre à décembre.

[`embed_initial_save.py`](../tools/embed_initial_save.py) remplace le GVAS dans
l'asset cuit, tandis que [`patch_save_snow.py`](../tools/patch_save_snow.py),
[`seed_snow_corridor.py`](../tools/seed_snow_corridor.py) et
[`patch_save_month.py`](../tools/patch_save_month.py) rendent la reconstruction
reproductible.

## Construction du prototype

Le pipeline effectivement exécuté est :

1. requête spatiale du COG, sans télécharger les 77 Go du raster complet ;
2. rééchantillonnage à 4 m et production du R16 little-endian ;
3. extraction Legacy du niveau Sugar Bowl avec `retoc` ;
4. renommage du package, passage au biome Alpes, transformation du Landscape,
   altitudes et bornes avec UAssetAPI ;
5. remplacement des 16 fournisseurs de textures de hauteur ;
6. lecture des forêts, pistes, remontées, lieux et contours OpenStreetMap avec
   reprojection EPSG:4326 → EPSG:2154 ;
7. rasterisation de 33,72 km² de forêt, ouverture de couloirs de 36 m autour
   des pistes et de 24 m autour des remontées, puis redistribution des 255 667
   enregistrements `SKOB` ;
8. reconstruction des 1024 `CookedCollisionData` Chaos depuis le R16 ;
9. reconstruction de la texture de hauteur neige
   `/Game/Materials/Terrain/Generated/veymont/H_veymont_Out` ;
10. fabrication d'un SaveGame natif : décembre, 20 cm de neige compactée,
    40 cm de neige fraîche, grille globale, 246 tuiles détaillées, 9 remontées,
    20 pistes, 5 bâtiments fonctionnels et 7 Warming Hut de liaison ;
11. injection de ce GVAS dans `IS_Map_sugar_bowl` et création d'un second
    conteneur IoStore prioritaire ;
12. conversion Legacy vers Zen/IoStore avec la branche UE 5.8 de `retoc` ;
13. ouverture du niveau par `GameplayStatics.OpenLevel` depuis Lua ;
14. chargement natif du Ticket Office, des 9 télésièges de substitution, des
    20 pistes OSM et du hub frontal unifié ;
15. reconstruction du tablier avec 504 échantillons du périmètre et un fond
    fermé.

Le mod distribue deux conteneurs validés par `retoc verify` :

- `pakchunk999-Veymont_P` : niveau, obstacles, collision et texture auxiliaire ;
- `pakchunk998-VeymontInitial_P` : sauvegarde initiale native et données neige.

SHA-256 de la version 0.4.0 :

```text
pakchunk998: pak  75e7144577253917f6da7312ef5e585b12fb728226a22b0938323751a6b555cd
             ucas c63a9b7cf5243b3f3fe39b50d98f6b884ac186bd71876f8fc23fc1e6a59022ca
             utoc d64a3287b124e9d23dcb9d5fbc48ad1a0a92859f64a25d32b18d3fcec223a059
pakchunk999: pak  75e7144577253917f6da7312ef5e585b12fb728226a22b0938323751a6b555cd
             ucas 0e7c5d8cf94e6e0a9790267f1662d1186ab85bf69070641eb319c53b583b0323
             utoc e4ef9a8cea4de5bdf83de56a8b2240bf637a8d0cd12e3eba692305e9c4d12070
archive:          44639728fea47005cebdf72addc4e7e0e2fc3bb9c620ee776c681cd9ca1b591f
```

## Validation dans le jeu

Le test automatisé a produit les événements suivants :

```text
chargement de /Game/Maps/Generated/Map_veymont
monde actif: World /Game/Maps/Generated/Map_veymont.Map_veymont
1 coque neige source masquee
tablier Veymont reconstruit: 504 echantillons de bord
collision et foret OSM Veymont actives
inspection de la station chargee: registre=9 remontee(s), 12 batiment(s)
7 liaison(s) native(s) du hub frontal deja chargee(s)
station Veymont native preservee: 9 remontees, 5 batiments, 0 liaisons ajoutees, 20 pistes
graphe natif: 11 hub(s)
cache neige restaure: grille=1008
reseau ski: disponible=true, blocage=0; arrivees: autorisees=true, blocage=0
```

Le test de non-régression reconstruit les hubs rectangulaires depuis les
extrémités des remontées, les nomme avec les lieux-dits Veymont puis ouvre la
station seulement après l'enregistrement des pistes. Il ne déclenche plus le
message `No Complete Ski Run`.

## Format des obstacles et cause du décalage visuel

`LevelEnvironmentSettings_1.BakedObstacleData` référence un
`BakedObstacleDataAsset`. Sa propriété `RawData` commence par un en-tête de
48 octets :

```text
SKOB | version:u32 | count:u32 | record_size:u32
min_x:f64 | min_y:f64 | min_z:f64 | min_scale:f32 | max_scale:f32
```

Dans ce build, la version vaut 1, le nombre d'obstacles 255 667 et la taille
d'un enregistrement 19 octets :

```text
x:u32 | y:u32 | z:u32 | rotation:u16 | scale_xy:u16 | scale_z:u16 | variant:u8
```

Les trois coordonnées sont quantifiées au dixième de centimètre relativement
aux minima de l'en-tête. `redistribute-obstacles` remplace X/Y par les points
générés dans les polygones forestiers OSM, échantillonne Z dans le R16 et
conserve la rotation, l'échelle et la variante des 255 667 enregistrements.

Les premiers tests ont montré que la construction asynchrone du cluster tree
d'un HISM pouvait planter UE5 vers 8 192 instances. Le chargeur utilise donc
le même type `InstancedStaticMeshComponent` que le rendu d'obstacles du jeu,
alimente les instances par petits lots, et calcule leur altitude depuis le R16.
Après le dernier lot, une mise à jour sans déplacement de la première instance
force la publication du buffer de rendu. Sans cette invalidation, les 255 667
instances existaient bien côté CPU et bloquaient correctement les pistes, mais
seul un sous-ensemble ancien restait visible.

## Limites actuelles du prototype skiable

- la coque de neige héritée reste masquée ; le tablier, lui, est reconstruit à
  l'exécution ;
- la position des arbres suit les forêts OSM, mais les modèles et variantes
  d'essences restent ceux de Sugar Bowl ;
- les huit téléskis réels utilisent temporairement `BP_FixedChair1` ;
- sept Warming Hut visibles servent provisoirement de membres de liaison du hub
  frontal, en attendant une API ou un éditeur permettant de définir directement
  son emprise ;
- UE4SS surcharge les réponses de disponibilité uniquement pour les neuf
  remontées créées par Veymont ;
- le chargeur générique `SkiEO-CustomMaps` injecte désormais un choix
  `Custom`, une fiche d'aperçu et le manifeste versionné de Veymont ; cette
  adaptation UE4SS doit être requalifiée après chaque changement de l'UI
  native du jeu ;
- les données de navigation et le comportement de visiteurs sur une partie
  longue doivent encore être qualifiés.

Le mod n'utilise ni `ClearSnow` ni canon à neige. `HandleMonthAdvanced` a été
retiré car il ouvrait inutilement le bilan de novembre ; décembre est encodé
directement dans la sauvegarde initiale.

## Passage à l'éditeur officiel

Le R16 généré est déjà dans un format officiellement importable par Unreal. À
la publication de l'éditeur, il faudra créer un Landscape 2017 × 2017 avec 32 ×
32 composants, section de 63 quads, échelle XY 400 et Z 320, puis importer le
R16. L'éditeur permettra de remplacer la reconstruction binaire actuelle,
recuire la coque, la navigation et les caches neige, et supprimer la surcharge
de skiabilité.

## Sources et outils

- [Documentation Epic : import/export des heightmaps](https://dev.epicgames.com/documentation/unreal-engine/importing-and-exporting-landscape-heightmaps-in-unreal-engine)
- [Guide technique Landscape UE 5.8](https://dev.epicgames.com/documentation/unreal-engine/landscape-technical-guide-in-unreal-engine)
- [API Epic : collision de Landscape](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Landscape/ULandscapeHeightfieldCollisionCo-)
- [MNT LiDAR HD Isère 2021–2022](https://www.data.gouv.fr/datasets/modele-numerique-de-terrain-mnt-grille-au-pas-de-50-cm-isere-2021-2022/)
- [HydroPortail : station de la Gresse](https://www.hydro.eaufrance.fr/stationhydro/W280402001/fiche)
- [OpenStreetMap : copyright et licence](https://www.openstreetmap.org/copyright)
- [Gresse-en-Vercors : livret d'accueil hiver](https://gresse-en-vercors.fr/wp-content/uploads/2024/12/Livret-daccueil-hiver-24-25-BAT-1.pdf)
- [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS/releases)
- [retoc](https://github.com/trumank/retoc)
- [UAssetAPI](https://github.com/atenfyr/UAssetAPI)

Versions utilisées pour la reconstruction : `retoc 0.1.5`, puis la branche UE
5.8 de la PR 75 au commit `f82df25` pour le conteneur final ; UAssetAPI commit
`3228c1e86261aa08131f7ec0ff1a395f5d0b2a84`.
