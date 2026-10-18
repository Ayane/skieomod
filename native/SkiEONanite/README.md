# Constructeur de falaises Nanite

Ce projet d'outil Unreal 5.8 construit un `UStaticMesh` Nanite depuis les
buffers portables des générateurs de falaises. Il active la construction
complète, vérifie la présence de clusters et prépare une ressource pour
**Windows**, même lorsque l'outil de géométrie s'exécute sous Linux. La cuisson
utilise l'API réfléchie `UnrealEd.CookFunctionLibrary.CookAsset` d'Epic 5.8,
encore expérimentale. Le projet a été compilé avec les sources Epic 5.8.3 ;
les caches Windows sont contrôlés dans le jeu 5.8.2 avant distribution.

Le maillage est centré en mètres dans le fichier portable, puis converti en
centimètres Unreal. Le rapport conserve l'origine est/sud/haut de la carte.
Le winding est inversé à l'import. Les normales géométriques sont conservées,
les tangentes recalculées, sans UV d'éclairage précalculé ni collision ajoutée.
La collision et la simulation du terrain restent assurées par le chargeur.

Les fichiers Unreal et le conteneur IoStore sont un cache dérivé. Le R16, les photos et le
manifeste portable restent les sources. Aucune ressource du jeu n'est copiée
dans le pak : le matériau blanc est assigné depuis le jeu à l'exécution.
Le diagnostic refuse ce matériau si sa variante Nanite n'est pas disponible.

## Essai de massif Veymont avec corniches — rendu rejeté

L'inspection visuelle a rejeté ce générateur : il forme des bandes sur une
paroi qui reste trop lisse. Les commandes ci-dessous documentent l'essai,
pas une solution validée pour Veymont. Le constructeur Nanite reste utilisable
avec une géométrie issue de blocs et fractures ; voir la
[réorientation et ses limites](../../docs/rock-surface-extraction.md#réorientation--géométrie-de-blocs-et-fractures).

Un nouveau [prototype local volumique](../../docs/rock-surface-extraction.md#prototype-local-avec-contraintes-photographiques)
génère 19 blocs avec des contraintes photographiques candidates, puis prépare
des buffers compatibles avec ce constructeur. Le maillage de 24 × 36 m est
testé via UE4SS dans un composant temporaire. Sa fidélité visuelle reste à
affiner : il n'est pas encore cuit ni installé comme cache Nanite du massif.

Les nouvelles références rapprochées ont conduit à un second modèle de
[sculpture des faces](../../docs/rock-surface-extraction.md#sculpture-des-faces-rocheuses).
Des masses enracinées et des enlèvements de matière à trois tailles forment
des faces cassées et des sous-faces. Le détail secondaire suit les faces
déjà sculptées. Les premiers essais de cette portion de 12 × 18 m étaient
des diagnostics locaux, indépendants de la cuisson Nanite.

Une [phase d'érosion après sculpture](../../docs/rock-surface-extraction.md#érosion-après-sculpture)
retire de la matière selon l'exposition et la courbure, en conservant les
grandes faces et les sous-faces. Elle prépare un autre maillage portable et
garde la sculpture d'origine pour la comparaison UE4SS de face et en vue oblique.

`tools/embed_rock_sculpture.py` prépare ensuite son
[intégration au terrain et à la neige](../../docs/rock-surface-extraction.md#intégration-de-la-portion-sculptée-au-terrain)
avec des bords partagés avec les triangles natifs. Les deux maillages dérivés
de `build/nanite/sculpture/integrated/` utilisent le constructeur ci-dessus ;
ils conservent la collision R16 et le cache à deux couches. Les captures UE4SS
de `build/nanite/sculpture/captures/` vérifient le rendu de près et à distance,
y compris après chargement par le mod. Le cache local intègre la portion de
12 × 18 m, sans la répéter sur le massif, et remplace l'ancien essai de
corniches ; le reste garde sa géométrie native.

Le profil réglable [`limestone-geometry.json`](../../maps/veymont/limestone-geometry.json)
décrit des bancs plus marqués en partie basse, de grands piliers en partie
haute et des fractures verticales espacées. `tools/prepare_rock_mass.py`
réunit les sections 34/42 avant subdivision et déplace réellement leurs
sommets à l'échelle du mètre. L'amplitude maximale est de 8 m. Les valeurs
décrivent une interprétation des photos ; les profondeurs des fissures ne
sont pas mesurées et la correction photographique candidate n'est pas appliquée.
`surface_scale_meters` et `surface_recession_meters` règlent les cassures
locales sur les piliers. Leur champ continu utilise trois échelles, au moins
trois fois la longueur cible des arêtes pour éviter le sous-échantillonnage.
Les retraits des bancs varient aussi localement, au lieu de former des bandes
uniformes sur toute la paroi.

```bash
mkdir -p build/nanite/terrain-34-source build/nanite/terrain-42-source
lua tools/export_nanite_tile.lua mod/SkiEO-Veymont/custom-map.json 34 \
  build/nanite/terrain-34-source
lua tools/export_nanite_tile.lua mod/SkiEO-Veymont/custom-map.json 42 \
  build/nanite/terrain-42-source
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.prepare_rock_mass \
  build/nanite/terrain-34-source build/nanite/terrain-42-source \
  --profile maps/veymont/limestone-geometry.json \
  --output-dir build/nanite/character/mass

python3 -B -m tools.build_nanite_rock build/nanite/character/mass/terrain/mesh.json \
  --engine /media/lycos/dev/extern/UnrealEngine \
  --toolchain build/nanite/toolchain/v26_clang-20.1.8-rockylinux8 \
  --output-dir build/nanite/character/terrain-cooked --jobs 3 \
  --retoc build/nanite/retoc-target/release/retoc
python3 -B -m tools.build_nanite_rock build/nanite/character/mass/snow/mesh.json \
  --engine /media/lycos/dev/extern/UnrealEngine \
  --toolchain build/nanite/toolchain/v26_clang-20.1.8-rockylinux8 \
  --output-dir build/nanite/character/snow-cooked --jobs 3 \
  --retoc build/nanite/retoc-target/release/retoc
```

Les deux surfaces comptent chacune 817 466 sommets et 1 292 130 triangles
avec ce profil. La densité est bornée à un million de sommets et deux
millions de triangles. La cuisson s'effectue sous une limite de 6 Gio,
sans swap. Les arêtes des parois sont raffinées à 3 m dans l'espace.
Les sommets partagés entre projections UV reçoivent les mêmes déplacements
et normales. Les normales d'origine sont tournées selon le changement
géométrique, y compris sur les sous-faces des corniches.

Le champ procédural utilise les coordonnées du massif entier. Il ne
s'atténue pas à l'ancienne limite des tuiles ; le raccord avec le terrain
extérieur est fondu sur 80 m et garde exactement les positions du périmètre.
La couche de neige est reconstruite sur la même géométrie avec le décalage
vertical défini par la carte. Garder l'ancienne neige aurait masqué les
creux sculptés dans la roche. Ses UV et son matériau natif restent associés
à la simulation de neige du jeu.

Après validation UE4SS des deux ressources et inspection du rendu complet :

```bash
python3 -B -m tools.package_nanite_terrain \
  build/nanite/character/terrain-cooked/cook-report.json \
  build/nanite/character/snow-cooked/cook-report.json \
  --output-dir build/nanite/character/distribution
```

Le cache `mesh_algorithm=2` déclare pour chaque ressource sa couche
(`terrain` ou `snow`) et ses `source_sections`. Le chargeur exige que les
deux couches couvrent les mêmes sections et vérifie le décalage de neige.
Si l'une échoue, il rétablit les deux surfaces d'origine. Les matériaux
restent ceux de la carte et la collision reste celle du terrain R16 :
ces corniches visuelles ne modifient pas les trajets des skieurs.

Les captures de la carte complète sont dans
`build/nanite/character/captures/final-full-{original,nanite,fallback}.png`.
Elles passent exclusivement par UE4SS et `HighResShot`. L'option Unreal
`-RenderOffScreen` évite de dépendre de la visibilité de la fenêtre ; borner
également `t.MaxFPS` pour les diagnostics. Un essai de deux chargements
successifs dans le même processus a atteint sa limite de 6 Gio après un
échec de contrôle du solde sauvegardé. Il ne valide pas la consommation
mémoire des rechargements répétés. Le rapport conserve cet incident ;
les contrôles isolés doivent charger une seule carte et se fermer même
si une assertion échoue.
Le contrôle suivant, dans un processus neuf limité à 5 Gio et 20 images/s,
charge la sauvegarde native, confirme les deux maillages et leurs matériaux
après collecte mémoire, puis se ferme. Le pic journalisé est d'environ
4 Gio. Les captures `final-wide-restored-*` montrent ce rechargement.
Le contrôle financier ne passe pas : le solde gagne 484 dans ce processus
et 1 168 dans l'essai successif, tandis que la date sauvegardée est conservée.
La persistance des surfaces est vérifiée ; cela ne valide pas l'ensemble
du cycle de sauvegarde ni la mémoire de plusieurs chargements successifs.

## Premier diagnostic et anciens caches par tuile

Les commandes ci-dessous conservent le premier essai de détail fin. Son
déplacement inférieur à 14 cm était trop faible pour donner du caractère
aux falaises vues à distance ; le massif ci-dessus le remplace dans Veymont.

```bash
OPENBLAS_NUM_THREADS=1 python3 -B tools/prepare_nanite_rock.py \
  build/rock-surface/registration/sunrise-gps/surface \
  --output-dir build/nanite/proof --corrected

python3 -B tools/build_nanite_rock.py build/nanite/proof/mesh.json \
  --engine /media/lycos/dev/extern/UnrealEngine \
  --toolchain build/nanite/toolchain/v26_clang-20.1.8-rockylinux8 \
  --output-dir build/nanite/cooked --jobs 2 \
  --retoc build/nanite/retoc-target/release/retoc
```

`--corrected` inclut explicitement la correction photographique candidate.
Sans cette option, la géométrie de référence est utilisée. Le détail de
calcaire ajouté est une synthèse paramétrique, pas une mesure de fissures.
Sa fréquence minimale tient compte du pas du maillage pour éviter les stries
produites par le sous-échantillonnage.

La construction nécessite les dépendances officielles Epic et le compilateur
correspondant au moteur. `build_nanite_rock.py` copie ce projet dans `build/`
avant compilation et vérifie les empreintes des buffers. Les journaux et
`state.json` indiquent les étapes ; `cook-report.json` n'est accepté que si la
cuisson confirme la plateforme Windows et des clusters Nanite non vides.

Pour éviter l'OOM, lancer la construction sous une limite de mémoire, avec
deux compilations simultanées par défaut. Après le premier passage limité à
6 Gio, la machine de développement emploie quatre tâches et une limite de
8 Gio sans swap. La cuisson limite également les cœurs déclarés au moteur.
Le contrôle des matériaux peut s'effectuer dans une session séparée limitée
à 3 Gio, fermée avant les essais des maillages. Les essais de rendu passent exclusivement par UE4SS et
`tools/preview_nanite_rock.lua`, qui capture le maillage et son fallback sous
le même éclairage, puis restaure la vue et retire ses acteurs temporaires.

La présence de clusters dans le cache ne valide pas à elle seule le rendu du
jeu, ses shaders, ni la compatibilité entre les versions 5.8.3 des sources et
5.8.2 du jeu. Le cache de diagnostic ne s'applique pas automatiquement à toute
la carte. Chaque tuile doit passer la validation en jeu avant installation.

Pour conserver exactement les raccords et la collision d'une tuile du
terrain, l'export utilise le même générateur Lua que le chargeur :

```bash
mkdir -p build/nanite/terrain-42-source
lua tools/export_nanite_tile.lua mod/SkiEO-Veymont/custom-map.json 42 \
  build/nanite/terrain-42-source
OPENBLAS_NUM_THREADS=1 python3 -B -m tools.prepare_nanite_tile \
  build/nanite/terrain-42-source --output-dir build/nanite/terrain-42 \
  --levels 0 --edge-spacing 3 \
  --surface-profile build/rock-surface/registration/sunrise-gps/surface
```

La tuile 42 contient le sommet. La subdivision adaptative limite les arêtes
des parois à 3 m de longueur **dans l'espace**, pas seulement dans le plan XY
de la heightmap. Elle produit 1 112 466 triangles sur cette tuile et 179 664
sur la tuile voisine 34. Les subdivisions propagent leurs décisions à travers
les raccords UV afin de garder un maillage fermé. Le budget est plafonné à
un million de sommets et deux millions de triangles par tuile ; une densité
trop élevée est refusée avant écriture.

`--surface-profile` reprend le spectre périodique du déplacement estimé sur
les photos, avec ses phases synthétiques, son amplitude bornée et son repère.
Il ne colle pas la couleur orange ni la neige de la photo sur les parois et
ne corrige pas leur position géographique. Sur ces tuiles, le déplacement
final reste inférieur à 14 cm. Sans cette option, seul le détail de calcaire
compact est utilisé. Les normales gardent le lissage du terrain et ajoutent
la variation produite par le relief. Aux bords, positions et normales restent
raccordées au terrain d'origine. Le `ProceduralMeshComponent` conserve la
collision ; seules ses sections visibles sont remplacées.

Le contrôle UE4SS du 3 octobre 2026 confirme `r.Nanite=1`,
`r.Nanite.ProjectEnabled=1`, et `bUsedWithNanite=true` sur `M_Prop_albtex`,
le matériau de sol utilisé par le chargeur. `M_StriatedRock` n'a pas cette
variante. Le diagnostic de maillage vérifie aussi `GetNumNaniteTriangles()` :
les réglages d'éditeur `NaniteSettings` sont absents du jeu Shipping.
Cette vérification a lieu avant l'initialisation du composant : le gestionnaire
de streaming libère ensuite les pages racines CPU, et cette fonction peut
retourner zéro malgré un rendu Nanite actif. Le chargeur conserve la validation
pour le même objet Unreal encore vivant afin de permettre les rechargements.

## Conteneurs et chargement

Le jeu utilise `pak.AllowMissingUToc=0`. Une `.pak` traditionnelle seule est
ignorée ; le cache distribue ensemble `.pak`, `.utoc` et `.ucas`.
La conversion utilise [retoc](https://github.com/trumank/retoc), revision
`885a8dae740cb1ce1e41ff2e74f67f9f0c118237`, avec
[`retoc-unreal58.patch`](retoc-unreal58.patch). Le format 1018 des sources
5.8 écrit aussi `PackageName` dans les imports cuits filtrés. La correction
adapte cette lecture/écriture ; le profil `UE5_7` de retoc correspond aux
versions Zen 3 et ContainerHeader 5 utilisées ici.

```bash
git -C build/nanite/retoc-src apply \
  "$PWD/native/SkiEONanite/retoc-unreal58.patch"
CARGO_TARGET_DIR="$PWD/build/nanite/retoc-target" \
  cargo build --manifest-path build/nanite/retoc-src/Cargo.toml \
  --release --locked -p retoc_cli -j 2
```

UE4SS `LoadAsset` interroge uniquement l'AssetRegistry préexistant. Le chargeur
emploie donc `MakeSoftObjectPath`, `Conv_SoftObjPathToSoftObjRef` et
`LoadAsset_Blocking` d'Unreal, dans des appels séparés, et vérifie le chemin
obtenu. Les noms `SM_Terrain_T42` évitent la perte de suffixe numérique observée
avec les noms de paquets finissant par `_42` lors de ce passage UE4SS.

Après contrôle des captures, `cook-report.json` conserve la preuve de rendu
et `game_render_verified=true`. La conversion ou une nouvelle cuisson
réinitialise cette validation. `tools/package_nanite_terrain.py` refuse les
sources modifiées, les conteneurs altérés et les rapports non validés :

```bash
python3 -B -m tools.package_nanite_terrain \
  build/nanite/terrain-cooked/cook-report.json \
  build/nanite/terrain-34-cooked/cook-report.json \
  --output-dir build/nanite/distribution
```

Les six fichiers IoStore vont dans `Content/Paks/~mods`. Le `cache.json` va
à côté de l'archive sous le nom `<carte>.skieomap.nanite-5.8.json`, ou dans
`Runtime/Nanite/cache.json` pour une carte en dossier. Le chargeur contrôle
le CRC32 du R16, l'origine, le découpage et les dimensions. En cas de cache
absent/incompatible ou d'échec d'une section, il conserve le rendu d'origine.
`tools/preview_nanite_terrain.lua` compare ensuite la surface d'origine, Nanite
et son fallback dans la carte complète, par captures Unreal, puis restaure
la caméra, la simulation et le rendu installé.

Le contrôle du 4 octobre 2026 a chargé Veymont dans `/Engine/Maps/Entry`,
sans carte Sugar Bowl, et installé les deux sections 34/42. Les captures
`build/nanite/captures/veymont-{original,nanite,fallback}.png` comparent le même
point de vue ; la série `veymont-close-*` montre la surface de près. La
collision procédurale reste active. Les 255 667 arbres, 20 pistes,
9 remontées et 13 bâtiments sont présents et les systèmes natifs autorisent
l'arrivée des clients et le ski. À distance, le gain de ce détail borné est
discret : Nanite ne restitue pas les corniches absentes des données source.
Le cycle sauvegarde/rechargement par le menu natif conserve les deux tuiles,
l'argent, la date, les réglages des bâtiments et remontées et la caméra,
y compris après une collecte mémoire Unreal. Le maximum observé pour
l'instance de test est de 3,91 Gio, sous une limite de 6 Gio, sans OOM.
Les tests Python Nanite et l'ensemble des contrôles du format de carte,
de l'éditeur et des modules Lua passent.

Les temporisations du lancement, de l'interface et de la reconstruction
native utilisent les timers du thread du jeu lorsqu'UE4SS les fournit. Les
callbacks asynchrones partageaient l'état Lua avec la génération du terrain
et pouvaient le corrompre pendant les allocations. Les anciennes versions
d'UE4SS gardent le chemin de compatibilité. La résolution des modules ignore
aussi une ancienne copie du chargeur dont le `main.lua` a été désactivé.

Le cache partitionné `mesh_algorithm=3` permet l'extension sculptée du Grand
Veymont : 16 portions pour chacune des sections 34/42, avec terrain et neige,
soit 64 ressources. Le chargeur conserve les sections procédurales visibles
pendant l'initialisation, puis active l'ensemble complet en une seule étape.
Il restaure les sections natives si une portion ou son matériau échoue.
La préparation, ses limites et les contrôles sont décrits dans
[Extraction des surfaces rocheuses](../../docs/rock-surface-extraction.md#extension-procédurale-au-massif).
`tools/build_nanite_rock.py --project-stage <projet-compilé>` réutilise un projet
compilé entre ces ressources ; ces cuissons doivent rester séquentielles.

Pour ces ressources partitionnées, le fallback conserve tous les triangles
du maillage portable. La surface rocheuse comporte aussi une peau intérieure
continue, à 2,6 m derrière la référence, pour masquer les trouées entre niveaux
de détail indépendants ; les creux de cette étude sont bornés à 2,2 m.

Le raccord progressif et les dépôts de neige sont dérivés par
`tools/export_sculpted_massif.py --transition-width 24` et
`tools/prepare_snow_deposits.py`. Les couches optionnelles `snow_deposits` et
`snow_transition` sont des maillages à un matériau, cuits avec le même
commandlet et le fallback exact. Elles utilisent au runtime le matériau
neige du jeu et `nanite_snow.lua`, à installer avec `nanite_terrain.lua`.
Leur activation reste atomique avec les portions roche/neige principales ;
le budget est de 128 ressources et 128 Kio de métadonnées. Le générateur
filtre la pente géométrique des facettes et amincit les bords dans la roche.
Les détails de réception de neige, du fondu de couleur et des contrôles
mémoire sont décrits dans `docs/rock-surface-extraction.md`.
