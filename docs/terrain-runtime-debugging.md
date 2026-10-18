# Diagnostic du terrain source

Inspection en jeu de la démo UE 5.8.2, via les UFunctions/UProperties exposées
par UE4SS et le dump local des classes natives. Pas de modification du binaire
du jeu ni de sauvegarde utilisateur.

Le [protocole de compatibilité](game-compatibility-testing.md) automatise les
contrôles reproductibles à effectuer après une mise à jour et précise les
preuves nécessaires avant de déclarer un nouveau build compatible.

## Compatibilité du chargement après mise à jour — 16 octobre 2026

Le build Steam **25970577** déplace les contrôles du renderer de terrain de
`+0xB8/+0xBC` à `+0xD8/+0xDC`. Le monde indépendant se créait, puis le garde
natif rejetait le renderer avec `supported terrain renderer settings were not
found`. Après ses tentatives bornées, le chargeur revenait au menu principal.

La sonde UE4SS relève toujours le propriétaire FScene à `+0x08`, la heightmap à
`+0x10`, les six bornes à `+0x18` et les quatre textures du cache à
`+0x40/+0x48/+0x50/+0x58`. Quatre références natives précèdent désormais les
contrôles. L'inspection du constructeur du binaire installé confirme une
allocation de `0xE0` octets et l'initialisation des contrôles à `+0xD8/+0xDC`.
La capture et le désassemblage sont conservés sous `build/update-25970577/`.

Le helper accepte explicitement ce troisième profil, avec un snapshot minimal
de `0xE0`, en conservant les deux profils antérieurs et leurs tailles minimales
de `0xB8` et `0xC0`. Les vérifications du monde, des identités de textures,
des bornes finies et ordonnées, de la vtable du jeu et de la mémoire restent
actives. Le test natif couvre les trois profils, les références étrangères,
les bornes et contrôles invalides, ainsi que les snapshots tronqués.

La suite de l'initialisation nécessite aussi de nouveaux profils natifs :

| Élément | Build 25970577 |
| --- | --- |
| `WalkNavSubsystem` | Tick à sous-objet `+0x38` conservé ; handler unique invalidant `+0x848/+0x69`, apparié au nouveau prologue |
| Hubs | Enregistrement bâtiments `0x04FADA50`, remontées `0x04FADC10`, rebuild `0x05045D70`, compteur de lot `+0xA60` |
| Rebuild différé | Wrapper `0x0503D2C0`, saut vérifié vers le rebuild |
| Personnel | Vivier `0x0530F7C0`, Settings `+0x508`, tableau `+0x4D8`, membre `0x518` octets |
| Noms de hubs | Getter `0x0503C070`, insertion `0x0501E3A0`, fabrique FText `0x01349260` ; map `+0x1D0` conservée |
| Skiabilité | Query `0x0538DF30`, mémo `0x0538E212` ; clé minute `+0x19C` conservée |

Chaque profil conserve ses gardes de signatures et de propriété. Les anciens
profils restent disponibles. Le test de navigation vérifie l'appariement exact
du tick et du handler, et rejette les prologues modifiés ou tronqués.

La validation UE4SS charge Super Saint-Bernard puis Veymont dans le même
processus. Les deux atteignent `is ready (terrain and station)` avec l'écran de
chargement fermé. Super Saint-Bernard possède cinq bâtiments, deux remontées,
quatre pistes, trois hubs et dix employés. Veymont possède treize bâtiments,
neuf remontées, vingt pistes, onze hubs, vingt-deux employés et 383 500 arbres
sur 47 composants. Aucun bâtiment n'est enseveli. Trois renouvellements natifs
du vivier de recrutement réussissent pendant la construction de Veymont.
Un GC forcé conserve le même monde, la heightmap, la station et les 383 500
arbres ; l'écran de chargement reste fermé.
Les captures Unreal et rapports sont dans `build/update-25970577/`.

La suite complète `tests/run_custom_map_checks.py` passe : 228 tests Python et
66 fichiers Lua, avec Lua 5.4. Le helper est compilé avec `-Wall -Wextra`.

## Test3 et lancement depuis l’éditeur — 9 octobre 2026

Le lancement Linux utilisait `proton runinprefix`. Le script du Proton installé
réserve à `setup_prefix()` les overrides natifs DXVK/VKD3D ; cette étape est
omise par `runinprefix`. Les essais de ce chemin utilisaient WineD3D / DirectX 11,
alors que le lancement Proton complet active VKD3D et la Radeon RX 6800 en
DirectX 12. La CLI 1.17 utilise désormais `proton run`, en conservant le jeton
de session propre à l’éditeur et le choix du Proton installé.

La copie isolée de test3 charge et recharge ses deux objets et ses 3 569 arbres
sans crash avec ce chemin, sous Proton Experimental. L’inventaire du monde actif
trouve un Landscape masqué et un acteur de terrain source avec quatre composants
procéduraux : sol, neige, jupe et pistes. Les positions de caméra, la génération
du terrain et celle du forest renderer restent identiques pendant 180 relevés.
Les captures Unreal successives avec et sans arbres gardent le même contour
du terrain ; le Ticket Office est visible dans les captures rapprochées.
Ces observations ne reproduisent pas deux terrains alternés. Elles ne prouvent
pas que le clignotement signalé est éliminé dans chaque configuration de rendu.
Les preuves sont sous `build/editor-update-1.17/`, dont `native-camera-frames.txt`
et `native-frames/`. Le serveur Xvfb fait planter le DXGI du Proton 9 installé
avant le chargement de la carte ; ce défaut de l’essai ne doit pas être confondu
avec le crash UE4SS du test3 utilisateur.

Le minidump utilisateur indique une lecture nulle dans `ucrtbase!strlen`, appelée
par le binding Lua d’UE4SS. Les callbacks différés des widgets et des hooks de
placement sont désormais conservés par le dispatcher du runtime jusqu’à la fin
de leur exécution. Le test force le GC pendant 500 injections de widgets et
confirme leur rétention et leur exécution sur le thread du jeu. Cette correction
supprime un défaut de durée de vie avéré ; la pile seule ne suffit pas à établir
qu’il était l’unique cause du crash utilisateur.

## Clics du menu — inspection de l'instance du 6 octobre 2026

L'instance Steam signalée comme bloquée est le PID Linux **24198**, démarré
à 12 h 22, heure de Paris. Elle a été conservée pendant toute l'inspection :
aucun redémarrage du jeu, rechargement du mod, changement de réglage ou voyage
vers une carte. La sonde Lua désactivée ne pouvait pas être démarrée par la
console UE4SS, elle-même désactivée dans cette session. Les adresses et les
dispositions détectées par UE4SS ont donc servi à lire `/proc/24198/mem` en
lecture seule ; un premier attachement GDB a également été détaché sans appel
de fonction ni écriture.

Avant le premier clic de test, le contrôleur possède uniquement
`MainMenuWidget`. Ses pointeurs `NewGameDialogWidget`, `SettingsWidget`,
`SaveLoadMenuWidget` et `CrashConsentPromptWidget` sont nuls. Il n'existe
aucun `LoadingScreenWidget` actif ni panneau Custom dans l'instance.
Les cinq boutons sont `Visible`, activés et opaques. Les conteneurs du menu
sont `SelfHitTestInvisible`, ce qui conserve les clics sur leurs enfants.
Le journal ne comporte ni chargement de carte ni erreur de hook.

Une remise au premier plan X11, suivie d'un clic XTest sur Settings, ouvre
les réglages. Les clics sur Back puis New Game fonctionnent dans le même
processus. L'injection Custom est enregistrée à 12 h 47 min 05 s, donc
**après** ce premier test réussi. Le panneau affiche uniquement
Veymont 0.5.0. Son bouton Back referme le panneau ; le Back natif referme
ensuite le dialogue. Une nouvelle séquence isolée New Game → Back atteint
les états attendus avant le premier relevé à 1,102 seconde, qui inclut
0,3 seconde de survol, 0,1 seconde de pression et 0,7 seconde d'attente.
Les cinq délégués `OnClicked` contiennent encore le handler natif du menu
et le handler de son, sans `SetKeyboardFocus` ajouté par le mod.

Certaines captures immédiates affichent encore le dialogue précédent alors
que les propriétés de visibilité ont déjà changé ; une capture ultérieure
confirme le retour au menu. Ces images seules ne démontrent donc pas une
perte de clic. Les relevés se trouvent dans `build/ue-debug/menu-memory-*.json`,
`menu-button-delegates.json`, `menu-response-test.txt` et `menu-*.png`.

L'utilisateur confirme ensuite que la souris physique fonctionne à nouveau.
Il précise que les boutons réagissaient déjà au survol pendant le blocage,
mais que les clics ne déclenchaient aucune action. Le survol n'avait pas été
consigné dans les premiers relevés. Il faut donc distinguer le routage des
pressions/relâchements de celui des déplacements, et ne pas attribuer le
problème à une simple perte de focus.

Un relevé supplémentaire, **après récupération**, donne `bIgnoreInput=0`,
`MouseCaptureMode=NoCapture`, `MouseLockMode=DoNotLock` et aucun des cinq
boutons pressé. Leur `ClickMethod` est `DownAndUp` : Slate attend la séquence
pression puis relâchement pour déclencher le clic. La lecture privée de
`IsPressed` est protégée par les trois instructions natives vérifiées via
la `UFunction` UE4SS. Le relevé est dans `menu-input-recovered.json` ; le script
`menu_input_snapshot.py` ne génère aucun événement ni écriture mémoire et
est limité aux adresses et signatures de cette instance.
Référence : [SButton et les événements de souris](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Slate/SButton).

**Limite :** le blocage initial n'a pas été reproduit avant la remise au
premier plan. La capture Slate ou système, un état de pression/relâchement
incohérent et l'activation de fenêtre restent des hypothèses, pas des causes
établies. Les relevés d'entrée pris après récupération ne prouvent pas leur
état pendant le blocage. Aucun correctif automatique du focus ou du mode
d'entrée n'est installé sur cette seule base. Pour un nouvel épisode,
relever aussi le captor, les états pressés et les événements Down/Up avant
tout clic de récupération, puis comparer un clic physique et un clic injecté
sans changer de fenêtre.

## Compatibilité après mise à jour — 6 octobre 2026

Le build Steam installé est **25744336**, contre **25668054** pour la dernière
validation. Le dump UE4SS des classes et l'inspection des fonctions natives
montrent les changements suivants :

| Élément | Avant | Build 25744336 | Correction |
| --- | --- | --- | --- |
| Tick `WalkNavSubsystem` | Ancien prologue validé | Nouveau prologue tenant compte de la pause | Accepter les deux signatures vérifiées ; conserver la recherche unique du handler de changement du terrain |
| Enregistrement des hubs | Fonctions aux anciennes adresses | Nouvelles adresses, signatures conservées | Ajouter un profil exigeant les trois signatures avant tout appel |
| Vivier `StaffSubsystem` | Settings `+0x300`, pool `+0x2D0`, membre `0x310` octets | Settings `+0x508`, pool `+0x4D8`, membre `0x4F8` octets | Sélectionner le profil par prologue et garde du pointeur Settings, puis comparer avec l'état réfléchi |
| Rendu du personnel | Tableau `StaffRoleActors` | Acteur `StaffRenderingActor` | Énumérer les `CrowdRenderingActor` du monde actif par l'API publique |

L'erreur `unsupported WalkNav tick layout` interrompait l'amorçage **avant**
`map.ready` et le script de forêt. Le maillage d'arbre est toujours disponible :
la végétation manquante était une conséquence de cet arrêt du chargement.
Les anciens profils natifs restent pris en charge ; aucun contrôle de signature
n'a été supprimé et aucun patch du binaire du jeu n'est nécessaire.

La commande console `SkiResortSimulator.Snow.SetLevel` résout son monde via la
GameInstance du jeu, qui exclut le niveau neutre `/Engine/Maps/Entry`. Elle ne
modifiait donc pas la neige de Veymont : une mesure à 379,75 cm restait identique
après son invocation. Le chargeur appelle maintenant `ClearSnow` sur le
`SnowSimulationSubsystem` du monde actif, puis
`KismetRenderingLibrary.ClearRenderTarget2D` sur son `CoarseMipRT` pour créer
100 cm de neige fraîche. L'invalidation native des tuiles et des caches reste
assurée par `ClearSnow`. Ces appels publics remplacent la commande console,
sans ajouter d'adresse privée pour la neige. Ils ne s'exécutent que lors d'une
nouvelle partie : la neige d'une sauvegarde restaurée reste celle de la partie.

Le garde périodique du chargement ne conservait que son handle natif ; UE4SS
peut ne garder qu'une référence faible au rappel Lua. Après GC, ce garde
risquait de disparaître. `api:every` conserve désormais la fonction jusqu'à
son annulation, son erreur ou l'arrêt de la carte. Un test
avec une file native de références faibles et plusieurs collectes reproduit
ce cas et vérifie aussi la libération des rappels annulés.

Les deux lignes Veymont venaient de la fusion de la découverte locale avec
l'inventaire CLI : celle-ci comparait seulement les chemins, alors qu'un
dossier et une archive peuvent porter le même identifiant. La fusion des
cartes utilise désormais leur `id` et retient la version la plus récente ; à
version égale, la découverte locale est prioritaire. Les versions parallèles
des **mods** restent disponibles pour la résolution des dépendances.
L'installation conserve `Content/Paks/~mods/SkiEO-Veymont`, avec son cache
Nanite existant. Le second dossier UE4SS et l'archive identique sont sauvegardés
hors des répertoires découverts, dans
`build/ue-debug/update-25744336-backup`, et l'inventaire CLI pointe vers le
dossier conservé.

Le premier chargement corrigé a validé 255 667 arbres visibles, 13 bâtiments,
neuf remontées, 20 pistes, 11 hubs et 22 employés. Chaque remontée possède ses
deux agents ; les opérations natives autorisent le ski et les arrivées. Les
13 bâtiments ont `bIsBuried=false` et une profondeur mesurée de 17 à 100,312 cm,
dont 69,125 cm au guichet, sous leur seuil de 200 cm. Le nouveau profil de
recrutement a également régénéré 17 candidats. L'énumération publique des
acteurs de foule a corrigé huit instances lors du contrôle direct en jeu.
La capture Unreal est `build/ue-debug/update-25744336-base.png` ; les mesures
UE4SS sont conservées dans `build/ue-debug/results.log`.

La sauvegarde dédiée au test, créée par le menu natif avec 73,5 cm de neige,
se recharge par ce même menu en conservant la date, les 13 bâtiments,
les neuf remontées, les 20 pistes, les 11 hubs et les 22 employés. La forêt
source est reconstruite entièrement. La mesure de neige reste voisine de
73,5 cm, y compris après GC : elle n'est pas remplacée par les 100 cm prévus
pour une nouvelle partie. Les achats des visiteurs peuvent faire évoluer le
solde pendant la restauration native, même avec le calendrier en pause ;
ce test ne valide donc pas une immobilisation complète de l'économie.

Le chargement suivant d'une nouvelle Veymont dans le même processus crée un
autre identifiant de partie et initialise bien une nouvelle neige :
100,375 cm au centre, 68,75 cm au guichet et 17,656 à 100,375 cm sur les
13 bâtiments, tous non ensevelis. Les effectifs de forêt, station, hubs et
personnel sont identiques après un second GC forcé. Aucun échec du rendu de
foule ni du chargement n'apparaît dans le journal de cette séquence finale.
La capture finale est `build/ue-debug/update-25744336-final.png`.
Le journal final et les empreintes des cinq fichiers installés sont dans
`build/ue-debug/update-25744336-final-validation.log` et
`build/ue-debug/update-25744336-installed.json`. La session de diagnostic est
fermée, la sonde UE4SS désactivée et les fichiers des deux parties de test
archivés dans le dossier de sauvegarde du correctif. Les sauvegardes existantes
n'ont pas été modifiées.

Les régressions couvrent l'initialisation de la neige dans le bon monde,
l'absence de réinitialisation à la restauration, la fusion des inventaires et
les deux organisations du rendu du personnel. La suite complète
`tests/run_custom_map_checks.py` passe avec Lua 5.4 ; le helper est recompilé
avec `-Wall -Wextra`.

## Monde indépendant — 2 octobre 2026

Le chargeur ouvre maintenant `/Engine/Maps/Entry` avec le GameMode SkiResort.
Dans `RegisterInitGameStatePreHook`, il crée depuis le R16 un Landscape, ses
1 024 composants, 16 atlas de dix mips et une hauteur G16, puis
`LevelEnvironmentSettings`, le biome alpin partagé et les acteurs d'éclairage.
Le format portable passe en 1.3 ; l'ancien `game.template_level` est ignoré.
Aucun niveau ni sauvegarde Sugar Bowl n'est chargé.

Les composants doivent être attachés et configurés **avant**
`FinishSpawningActor` du Landscape. Les finir après cet appel laisse leurs
transformations locales et leur enregistrement incomplets. Le paramètre de
spawn `TransformScaleMethod` vaut 0 (OverrideRootScale), pour ne pas multiplier
le pas source par l'échelle du CDO Landscape. Les tableaux vides nécessaires
sont alloués avec l'allocateur Unreal, avant l'enregistrement des composants.

Le Landscape conserve la collision QueryOnly pour les calculs de limites du
jeu : désactiver la collision de l'acteur rend
`GetActorBounds(true, ...)` égal à zéro, même avec 1 024 composants valides.
Il n'a aucun heightfield physique cuit. La collision physique est fournie par
le maillage procédural source. Le cache CPU marque ses échantillons R16 comme
valides pour empêcher les sondes de collision différées de les remplacer.

Le Landscape neuf n'a pas les permutations de shader de ses instances cuites.
Son rendu passe donc par les maillages procéduraux utilisant les matériaux
partagés `M_StriatedRock` et `M_Snow`. Le Landscape masqué sert aux sous-systèmes
natifs. Cette séparation élimine le besoin d'un matériau ou d'un atlas hérité
d'un niveau du jeu. La résolution visible suit `terrain.runtime.sample_step`.

La simulation est suspendue pendant la construction. Décembre est défini avant
World BeginPlay ; une fois les ressources GPU disponibles, le chargeur crée
un enneigement initial indépendant. Depuis le correctif du 6 octobre, cette
initialisation emploie les fonctions publiques du monde actif décrites plus
haut. La simulation reprend à la fin de la création de la station.

`WalkNavSubsystem` calcule aussi un masque du terrain pendant BeginPlay. Sans
invalidation après installation du R16, ce masque reste vide : seuls les pads
des bâtiments sont accessibles, et les 30 membres deviennent 27 hubs isolés.
La notification des placeables ne reconstruit que leurs empreintes. Le helper
appelle donc le handler natif de changement du terrain, après validation de la
classe, du Tick et d'une signature unique dans les sections exécutables du jeu.
Le moteur reconstruit ensuite lui-même le masque et les régions connexes.
Le démarrage propre donne 11 hubs, un réseau skiable, des arrivées autorisées
et des visiteurs qui entrent dans la station.

Le chargement désactive temporairement `Slate.bAllowThrottling`, puis restaure
sa valeur à la fin. Les longues tâches signalent leur progression à l'écran ;
le watchdog échoue après cinq minutes sans progression, plutôt qu'après cinq
minutes de durée totale.

Deux crashs de l'amorçage neuf ont été identifiés et corrigés :

- `TerrainBrushSubsystem.BaseHeightTex` est une texture **PF_R32_FLOAT** que le
  moteur remplit en float32. Lui attribuer la hauteur G16 provoquait un
  débordement mémoire dans `EnsureBaseHeightTexture`. Le moteur recrée
  maintenant sa propre texture depuis le cache CPU source.
- Les mutations de `ProceduralMeshComponent` provoquaient l'assertion
  `ClearActorComponentEndOfFrameUpdate` de `LevelTick.cpp`. Le chargeur désactive
  `AllowAsyncRenderThreadUpdates` dans le monde custom et restaure sa valeur
  précédente au changement de monde. Les actions Lua différées restent aussi
  référencées jusqu'à leur exécution et passent sur le thread du jeu.

Les mesures et captures de cette branche sont conservées dans
`build/ue-debug/independent-world-*.png`. Elles proviennent exclusivement
d'Unreal (`HighResShot` demandé via UE4SS), sans capture d'écran système.
Les essais utilisent une instance, un groupe de processus limité à 12 Go et
aucun swap.

Validation finale sur le build 25668054 : un démarrage propre, puis un second
chargement de Veymont dans le même processus créent deux mondes distincts.
Après chaque ramasse-miettes Unreal forcé, le monde actif conserve exactement
un Landscape (1 024 composants, aucun StreamingProxy), neuf remontées,
12 bâtiments, 20 pistes, 11 hubs et 255 667 arbres. Les neuf remontées gardent
leurs deux extrémités. La texture du pinceau natif alloue bien le float32 ;
la navigation autorise le ski et les arrivées. Aucun crash pendant ces essais.
Le contrôle ultérieur constate 15 visiteurs présents et le spawner actif.
Le retour au menu principal arrête le runtime custom et restaure les valeurs
précédentes d'`AllowAsyncRenderThreadUpdates` et de `Slate.bAllowThrottling`.
Le pic mémoire du groupe de processus est de 2 989 244 416 octets (2,78 Gio)
sur la séquence chargement/rechargement, avant les captures.

La capture d'ouverture après rechargement et GC est
`build/ue-debug/independent-world-gameplay.png`. Elle vérifie la géométrie et
le rendu source ; elle ne valide pas les trajets effectifs des visiteurs ni
le fonctionnement des remontées avec du personnel affecté. L'économie et le
vivier de recrutement démarrent avec les valeurs natives d'une nouvelle partie.
Les matériaux partagés du jeu restent utilisés, et leur rendu sur le maillage
procédural pourra être affiné indépendamment du chargement de Sugar Bowl.

Le runtime charge aussi son module `vegetation` avant d'ajouter le dossier de
scripts de la carte au chemin Lua. Une ancienne copie de ce helper dans le
dossier Veymont ne peut ainsi masquer la progression du chargeur actuel.

### Éclairage, altitude et jupe

Le monde neuf crée aussi `ClayEnvironmentController`, avec un soleil, une
lune, une lumière ambiante et le PostProcessVolume qui lui appartiennent. Les
valeurs communes observées dans les assets du jeu servent de réglages initiaux
(soleil diurne 5, exposition diurne EV100 0–1), sans charger `Map_Shared` ou
Sugar Bowl dans le chemin du chargeur. Le contrôleur natif suit ensuite la
date, le cycle jour/nuit et la météo. Une `DaylightAmbientCubemap` du moteur
remplace la capture de ciel vide qui laissait les ombres noires.

Le matériau `M_Terrain` suppose les données d'un Landscape et donnait un rendu
mal adapté au maillage visible. Le sol et la jupe utilisent maintenant la
roche générique `M_StriatedRock`, qui révèle les strates des falaises ; la coque
reste en `M_Snow`. Les choix explicites de matériau et de couleur du manifeste
sont à nouveau respectés. Veymont ne fournit plus de couleur plate ou de
profondeur imposée pour sa jupe. Le périmètre R16 donne 2 016 segments ; la
profondeur automatique vaut 322,56 m et le pied est à Z = 422,70 m.

La conversion native d'altitude est linéaire entre `BaseElevationMeters` et
`PeakElevationMeters`, sur l'étendue verticale de quantification du Landscape
(512 × son échelle Z). Ces champs calibrent donc la conversion, et ne doivent
pas réappliquer le décalage absolu déjà présent dans les positions R16. La base
est `-origin_z / 100`, et l'écart base/pic conserve la plage de quantification
R16. Les vraies limites du relief restent dans `terrain.elevation_meters`.
Une position Z = 126 200 cm donne bien 1 262 m, et la conversion inverse revient
à cette même position. La billetterie actuelle est à **1 242,54 m**, d'après sa
position OSM et le MNT livré ; l'ancien affichage lui ajoutait **723,9875 m**.
L'écart résiduel avec une billetterie attendue à 1 262 m concerne les données de
placement, et n'a pas été compensé en déplaçant artificiellement le terrain.

Les flocons proches sont des sprites Niagara éclairés. Leur composant ne
projetait déjà pas d'ombre, mais leur matériau pouvait devenir noir en zone
ombragée. Le chargeur règle le paramètre `snowEmissive` de leur propre MID selon
l'intensité ambiante native (facteur 0,4), réapplique le réglage après un changement
de preset météo et confirme `CastShadow = false`. Aucun matériau partagé ni
shader cuit n'est modifié. Les valeurs HDR ambiantes natives peuvent être plus
élevées la nuit ; l'exposition nocturne du contrôleur assure l'adaptation finale.

Validation en jeu du démarrage corrigé, puis GC forcé : géométrie, graphe skiable,
conversions d'altitude, matériaux et références d'éclairage passent. Les essais
jour, nuit et blizzard montrent les flocons blancs et des versants éclairés en
zone d'ombre. Un dernier GC, puis le retour au menu, confirment aussi la
restauration des réglages de rendu et de throttling. Le pic du groupe de
processus sur cet essai, captures et retour au menu inclus, est de
6 658 088 960 octets (6,20 Gio), sous la limite de 12 Go sans swap.
Captures Unreal via UE4SS : `environment-final-day.png`,
`environment-final-night.png`, `environment-final-storm.png` et
`environment-final-skirt.png`, dans `build/ue-debug/`. Tests Lua dédiés :
`test_world_bootstrap.lua` et `test_terrain_skirt.lua`. L'archive distribuée
`dist/Veymont-0.5.0.skieomap` est régénérée au format 1.3 avec ces matériaux.

Les sections suivantes décrivent les essais antérieurs avec le gabarit Sugar
Bowl et leurs limites ; elles ne décrivent plus le chemin de chargement actuel.

## Falaises et durée de vie des textures — 2 octobre 2026

Les dix mips du Landscape ne suffisaient pas à corriger les falaises. Une
extension native de rendu conserve sa propre texture de hauteur et ses bornes
de normalisation, indépendamment des propriétés des sous-systèmes. Ses bornes
étaient encore celles de Sugar Bowl : XY ±184 908,28 cm et Z 0–61 359,06 cm.
Cette dépendance conserve une normalisation propre au gabarit. Pour Veymont,
le chargeur remplace aussi cette référence de hauteur et les bornes
XY ±403 200 cm, Z 72 398,75–236 238,75 cm. Cela ne suffit pas à supprimer les
bandes de falaise observées avec la neige : leur origine reste à déterminer.

Le helper retrouve cette extension à partir du `FScene` du monde courant
(`UWorld + 0x250` sur le build UE 5.8.2 inspecté), puis de ses conteneurs
natifs immédiats. Il valide son propriétaire, la hauteur précédente ou
nouvelle, les identités WindExposure/Canopy/Morphology/PlacementSlope, les
bornes et une table virtuelle appartenant au module du jeu. La recherche est
bornée à 4 096 blocs ; les lectures utilisent `ReadProcessMemory` pour tolérer
la libération concurrente d'un bloc exploré. Toutes les validations précèdent
la mutation. Un échec de détection arrête le chargement avec une erreur.
Il ne faut pas utiliser une adresse de tas ou un RVA de table virtuelle fixe :
Steam est passé du build 25612747 au build 25668054 pendant ces essais.
Les deux redémarrages sur le nouveau build ont retrouvé une seule extension,
avec respectivement 214 et 213 blocs explorés.

Les pointeurs de textures mis en cache par ce rendu natif ne sont pas tous
des références Unreal réfléchies. Remplacer les propriétés du cache par de
nouveaux objets laissait des pointeurs vers les anciens objets après GC ;
les essais précédents clignotaient puis échouaient sur le thread de rendu.
Les cartes dérivées conservent désormais leur identité `UTexture2D` : leurs
données de plateforme sont échangées avec les objets importés, puis leur
ressource GPU est recréée. Les deux allocations restent propriété d'Unreal.
Un panneau UMG transitoire, raciné et jamais affiché, conserve également les
textures et les donneurs de mips au moyen de références réfléchies de brushes.
Ses enfants sont libérés au chargement d'un autre monde.

Un autre crash, juste après `map.ready` pendant le chargement de la station,
provenait d'une lecture de bulk data dans la chaîne de streaming des textures.
L'ancien assemblage récupérait le tableau de dix mips d'une texture cuite,
puis lui laissait un tableau d'un seul mip. Son fournisseur de streaming
conservait pourtant ses métadonnées de dix mips. Le job `SKTM` v3 agrandit
maintenant le tableau de la texture importée avec `FMemory::Realloc`, résolu
par les exports de UE4SS, et transfère les mips des autres imports. Les
textures cuites et leurs tableaux restent intacts. Les imports donneurs
conservent leurs allocations vides ; seul l'atlas actif possède les objets
de mip déplacés, ce qui évite leur double libération. Le rollback restitue
ces objets aux donneurs avant toute reconstruction des ressources GPU.

La morphologie native est `PF_A16B16G16R16` (19), quatre canaux UNORM16, et
non `PF_FloatRGBA`. Le PNG RGBA16 arrive en `PF_R16G16B16A16_UNORM` (62),
équivalent en mémoire ; le helper valide ce cas et préserve le format natif.
Slope et Redistribution restent `PF_R16F` avec leurs échantillons binary16.

La validation complète a également montré que les timers de l'API des cartes
appelaient Unreal depuis `ExecuteWithDelay`, qui est asynchrone. Le host utilise
désormais `ExecuteInGameThreadWithDelay`, avec une redirection explicite par
`ExecuteInGameThread` pour les versions sans cette fonction. Les closures
restent référencées jusqu'à leur exécution. Le test
`tests/test_runtime_timers.lua` couvre les deux chemins, le GC Lua entre
dispatches et l'annulation d'une carte. Voir la documentation UE4SS de
[ExecuteWithDelay](https://docs.ue4ss.com/lua-api/global-functions/executewithdelay.html)
et des [actions différées](https://docs.ue4ss.com/dev/lua-api/global-functions/delayedactions.html).

La collection `LevelEnvironmentSettings.WeatherMPC` conserve elle aussi des
paramètres `WorldBoundsMin`/`WorldBoundsMax` propres à Sugar Bowl. Le chargeur
met leurs composantes XY à jour par les UFunctions de KismetMaterialLibrary,
sans modifier leurs composantes B/A. Cette correction de coordonnées ne
supprime pas, à elle seule, les bandes hivernales.

La mise à jour Steam a également déplacé les fonctions privées des hubs. Les
profils inspectés des builds 25612747 et 25668054 sont maintenant acceptés
uniquement après vérification des trois signatures de fonction. Sur le nouveau
build, le démarrage complet compte 30 membres actifs, 11 clusters, 9 remontées,
20 pistes et 255 667 arbres, puis atteint `Veymont is ready`. Le réseau skiable
et les arrivées sont disponibles. Le GC Unreal forcé conserve 1 024 matériaux
sans discordance de heightmap et 16 atlas de dix mips, 1 441 792 octets chacun.
Le dernier essai est resté actif jusqu'à sa limite de 30 minutes, sans nouveau
crash, avec un pic du groupe de processus d'environ 5,1 Go.

**Limite actuelle : les bandes sombres étirées persistent dans la capture
hivernale `build/ue-debug/recovery-complete-winter.png`.** Leur disparition
après `ClearSnow` ne valide pas le rendu hivernal. Les modifications privées
des bornes neige, des outils, des altitudes de LevelEnvironmentSettings et des
flags du renderer sont restées des expériences dans `build/ue-debug/` ; elles
ne sont pas incluses dans le chargeur. La chasse au rendu est suspendue pour
évaluer un monde d'amorçage indépendant de Sugar Bowl.

Les captures de ces essais passent exclusivement par Unreal via UE4SS :
`SceneCapture2D.CaptureScene`/`ExportRenderTarget`, ou `HighResShot` demandé
par `KismetSystemLibrary.ExecuteConsoleCommand`. Les processus de test sont
limités à une instance et à 12 Go de mémoire, sans swap, pour ne pas reproduire
l'OOM qui avait fermé VSCode. Les diagnostics restent dans `build/ue-debug/`.

## Causes observées

- Le niveau gabarit crée ses acteurs avant la génération des tuiles source.
  Cette phase existe réellement ; elle est désormais couverte par l'écran
  de chargement natif. Veymont remplace ensuite ces acteurs, une fois le
  terrain construit, et signale explicitement la fin de la station.
- Les post-hooks natifs de hauteur reçoivent
  `(self, return_value, world_context, x, y)` et
  `(self, return_value, world_context, location)`. La valeur de retour
  supplémentaire était oubliée : les paramètres étaient décalés.
- Certaines opérations C++ des remontées continuent à utiliser les hauteurs
  du Landscape gabarit. Leurs `Waypoints`, `Towers.BasePosition` et composants
  de maillage sont en coordonnées absolues. Déplacer l'acteur seul ne suffit
  donc pas : il faut corriger ces données et reconstruire câble et sièges.
- Les racines des bâtiments finalisés sont statiques. Le déplacement exige
  une mobilité temporairement modifiable, suivie d'une relecture du résultat.
- `FindAllOf` conserve temporairement des objets détruits. Les vérifications
  finales utilisent `GameplayStatics.GetAllActorsOfClass`, qui les exclut.

## Mesures

À la billetterie, le helper public de hauteur renvoyait **19 942,43 cm**
(gabarit), contre **124 234,07 cm** après correction (relief source).
Au moment exact du premier `LiftActor.Initialize`, un rayon vertical touche
déjà le `ProceduralMeshComponent` source à **133 802,12 cm**. L'enfouissement
persistant n'était donc pas expliqué par un terrain encore absent à cette
seconde création.

Vérification des acteurs vivants après chargement : **5 bâtiments,
9 remontées, 18 extrémités, 128 pylônes**, sans position sous le R16 au-delà
de la tolérance. Bâtiments à +20 cm ; garde minimale des câbles échantillonnés
(201 positions par remontée) : environ **4,98 m**. Ces mesures se rapportent
au R16 ; le maillage décimé peut différer légèrement entre ses sommets.

Après retour sur Sugar Bowl classique dans le même processus, le helper
renvoie à nouveau une hauteur native (**20 823,94 cm** au point de contrôle),
et non celle du R16 Veymont : les surcharges sont limitées au monde source.

Le tablier comprend **2 016 segments double face et un fond**. L'écran natif
affiche une progression par phase et reste présent jusqu'à la fin de la
station, avec délai maximal et traitement des erreurs.

## Reconstruction du Landscape

Les positions des 18 extrémités de remontées coïncident avec le R16 à moins de
la précision d'affichage. Elles sont donc des altitudes monde, et non des
offsets relatifs au sol. Le décalage visuel venait du Landscape reconstruit :
`ImportFileAsTexture2D` créait les atlas BMP 8 bits avec `SRGB=true`. Modifier
ensuite cette propriété ne recréait pas la ressource GPU ; les deux octets de
hauteur étaient décodés comme des couleurs gamma et le relief rendu se trouvait
des dizaines ou centaines de mètres trop bas.

Le helper produit désormais :

- 16 atlas PNG RGBA 8 bits linéaires (`gAMA=1`) de 512², importés dans le même
  format BGRA8 que les heightmaps natives, pour les hauteurs R/G et les
  normales B/A du Landscape ;
- une texture PNG niveaux de gris 16 bits de 2017² pour la neige, les outils de
  terrain et les overlays ;
- les minima et maxima R16 des 1024 composants pour reconstruire chaque
  `CachedLocalBox` et éviter leur disparition intermittente.

Le marqueur gamma linéaire documente correctement les données empaquetées,
mais `ImportFileAsTexture2D` crée malgré tout une ressource GPU sRGB dans ce
build. Après avoir mis `SRGB=false`, le chargeur invoque donc immédiatement le
thunk natif `UpdateResource` avec chaque `UTexture2D` comme contexte. Les 16
atlas sont recréés avant leur affectation au Landscape : R/G conservent les
octets R16 exacts et les bordures dupliquées restent dans le format BGRA8
attendu. La texture R16 de simulation n'offre elle-même pas de vue sRGB.

Un atlas limité au mip 0 paraît correct de près, mais le Landscape sélectionne
des niveaux plus petits avec la distance. Le helper reconstruit donc les dix
mips (512 à 1) de chaque atlas. La texture cuite du gabarit ne peut pas servir
de destination : son `ULandscapeTextureStorageProviderFactory` recharge les
blocs compressés de Sugar Bowl et produit alors des plaques sombres ou des
trous. Le chargeur conserve comme texture active l'objet transitoire importé,
lui attribue une allocation Unreal de dix entrées et y installe les dix objets
de mip transitoires. La validation en mémoire donne 10 mips, 1 441 792 octets
et aucun `AssetUserData` sur chacun des 16 atlas actifs.

Chaque atlas contient 8 × 8 composants de 64 × 64 texels. Le chargeur
reconstruit donc aussi `HeightmapScaleBias` avec une échelle de `1 / 512` et
des offsets par multiples de `64 / 512`. Ce champ ne suffit toutefois pas :
les `LandscapeMaterialInstanceConstant` cuits gardent une copie du paramètre
`Heightmap`. Le relief pouvait ainsi utiliser Veymont dans le vertex shader
alors que les falaises utilisaient encore l'atlas de Sugar Bowl dans le pixel
shader. Pour chaque composant masqué, le chargeur crée maintenant une instance
dynamique, lui affecte exactement le même atlas transitoire que
`HeightmapTexture`, puis remplace l'entrée **déjà allouée** de
`MaterialInstances`. Les proxies de rendu ne sont recréés qu'une fois les
1 024 composants configurés. La validation en jeu compte 1 024 instances
dynamiques et **0 discordance d'atlas**.

Le remplacement de `HeightmapTexture_GPU` conserve la couche de neige déjà
initialisée par le niveau gabarit : appeler `ClearSnow` à cet endroit rendait
les pistes temporairement non skiables jusqu'à l'accumulation d'une tempête.
Validation finale en jeu : **5 bâtiments, 9 remontées, 18 extrémités et 128
pylônes, 0 élément enterré** ; le heatmap Snow Quality affiche la nature, la
profondeur et la température de la neige sur le Landscape reconstruit. Après
changement de monde, le Landscape Sugar Bowl retrouve sa texture, sa position
et son échelle natives.

## Crash pendant le diagnostic

Le dump `crash_2026_09_28_21_31_50.8094698.dmp` contient une violation d'accès
`0xC0000005` dans `UE4SS.dll+0xC712C0`, lecture à `0xFFFFFFFFFFFFFFFF`.
Les erreurs immédiatement précédentes portent sur le hook d'altitude appelé
par les anciennes liaisons du mode Veymont cuit. La signature est corrigée
et cette branche n'est plus utilisée pour les cartes source. La boucle de
rafraîchissement indépendante de l'écran a également été retirée : le
rafraîchissement suit les événements du jeu et la progression des tuiles.

Sans symboles PDB, ce dump ne prouve pas à lui seul la cause exacte de la
violation d'accès. Les démarrages suivants ont abouti sans nouveau dump.
Un second essai de diagnostic redimensionnait directement le `TArray`
`MaterialInstancesDynamic` d'un composant vivant et a également provoqué un
crash. Cette opération n'est pas utilisée par le chargeur : il masque les
composants, remplace seulement l'élément existant de `MaterialInstances`, puis
recrée leurs proxies de rendu.
Le dump, son journal et les captures d'inspection sont conservés localement
dans `build/ue-debug/` (non distribués avec le mod).

Tests exécutés : modules Lua et cycle de vie de l'écran, 9 tests Python,
tests du noyau de l'éditeur, compilation syntaxique Lua et empaquetage de
validation dans `/tmp/Veymont-runtime-validated.skieomap`.

## Avertissement transitoire de skiabilité

La suppression de la station gabarit émet brièvement l'événement natif de
skiabilité avant la reconstruction des 30 membres de hubs et des 20 pistes.
Le jeu pouvait conserver le panneau `No Complete Ski Run` derrière l'écran de
chargement alors que le graphe final comptait déjà 11 hubs fonctionnels. Après
finalisation, le script ferme uniquement un `CallToActionWidget` visible dont
le titre correspond exactement à ce message ou à
`No Way Back to the Ticket Office`, et seulement si le sous-système natif
confirme que le ski et les arrivées sont disponibles. Cette fermeture reste
limitée aux premières secondes après le chargement ; les avertissements
ultérieurs et les autres appels à l'action du jeu ne sont pas masqués.

## Sauvegardes custom et altitude du curseur — 2 octobre 2026

La limite de 1 638,4 m venait de la plage verticale native, calculée à partir
des 65 536 niveaux R16 de 2,5 cm sans inclure le datum source de 723,9875 m.
Le calcul d'altitude monde était correct, mais le widget bornait son résultat
à cette plage. Le chargeur réencode maintenant les seules textures natives
avec un datum nul et un pas de 3,6047176 cm. La plage native atteint ainsi
2 362,38745 m et contient le sommet réel de 2 341,107 m. Les données portables,
le terrain visible et les positions de la station gardent leur datum et leur
pas d'origine ; l'erreur de quantification du cache natif est au plus de 1,81 cm.
La conversion utilise des blocs de 4 096 échantillons pour borner la mémoire Lua.

Le contrôle en jeu a placé la caméra et le curseur au sommet par l'API Unreal :
`TopStatusBarWidget.ElevationText` affiche **`2,341 m`**. Les conversions natives
ont aussi été contrôlées à 1 242,54 m, 1 638,4 m et 2 100 m. La capture du terrain
au sommet est `build/ue-debug/altitude-summit-final.png` ; les captures Unreal
`HighResShot` n'incluent pas le widget Slate, dont le texte est enregistré dans
`build/ue-debug/results.log`.

L'écran noir après rechargement était un défaut de reconstruction du monde :
la sauvegarde native indique `/Engine/Maps/Entry` et conserve la station, mais
ne sérialise pas le Landscape, les lumières et les arbres transitoires du mod.
Le chargeur intercepte désormais le voyage demandé par le menu natif, identifie
la carte par le GUID de la partie, puis réinstalle ces ressources au démarrage
d'Entry. Il conserve les bâtiments, remontées, date, économie, neige et caméra
restaurés par le jeu, sans recréer la station source ni ouvrir une nouvelle saison.
La simulation reste en pause pendant la reconstruction et reprend à sa fin.

L'association est enregistrée à côté des sauvegardes natives dans
`SkiEO-CustomMap-<guid>.json`. Une ancienne sauvegarde Entry sans association
est migrée seulement s'il existe une unique carte custom installée. Avec plusieurs
cartes, ou si la carte associée manque, le chargeur ne choisit pas arbitrairement
un autre terrain. Chaque nouvelle partie custom reçoit son propre GUID après
la fin du démarrage natif, qui écrasait un identifiant attribué trop tôt.

Validation par le menu natif : une partie neuve a été sauvegardée avec
173 456 $, l'année 3, une phase mensuelle de 0,68, un hangar fermé et une
remontée à la vitesse 1. Après retour au menu, rechargement et GC Unreal forcé,
ces valeurs et la position de caméra sont conservées ; le calendrier reste
figé pendant la reconstruction. Le monde final compte 1 Landscape de
1 024 composants, 12 bâtiments, 9 remontées, 20 pistes, 11 hubs et 255 667
arbres. Ski et arrivées sont disponibles et aucun monde Sugar Bowl n'est chargé.
Le retour au menu rétablit également les réglages de rendu et de throttling Slate.
Le groupe de test, limité à 12 Gio sans swap, a atteint environ 3,85 Gio au pic.
La capture `build/ue-debug/save-restored-final.png` et le journal
`build/ue-debug/save-final-validation.log` conservent ce contrôle. Une sauvegarde
Entry antérieure sans association a aussi été rechargée avec son terrain visible.

Les tests Lua couvrent l'encodage natif (datum, ordre des octets et des lignes,
quantification), les associations persistantes de sauvegarde, les GUID neufs,
les sauvegardes legacy ambiguës, l'isolation des cartes natives et le démarrage
restauré sans remise à zéro du calendrier ou de la neige. Les tests Python,
le noyau de l'éditeur, la syntaxe Lua et l'archive Veymont ont également été vérifiés.

## Veymont : sol, poste de secours et personnel — 2 octobre 2026

Le sol procédural utilise maintenant une instance de `M_Prop_albtex` avec
`t_terrain_rock_alb`. `M_StriatedRock` reste réservé à la jupe automatique.
Les quads dont la pente dépasse 45° projettent leurs UV sur un plan vertical,
sans modifier les hauteurs, les normales ni les triangles de collision. La
neige garde ses UV XY. Le marqueur `independent_world` doit être propagé aussi
au heightmap source : sa copie quantifiée native ne suffit pas à sélectionner
les matériaux du maillage visible.

Le générateur place le `Ski Patrol Hut` 14 m au sud de la billetterie, dans le
sens +Y du monde. Une nouvelle partie affecte deux pisteurs, deux dameurs et
18 agents de remontée, un à chaque terminal. Les deux employés initiaux sont
réutilisés après libération des affectations pointant vers des bâtiments
absents. Les commerces n'ont pas de postes de personnel dans la table native
d'économie. La restauration d'une sauvegarde ne relance pas ce recrutement.

La commande console de renouvellement du personnel ne trouve pas le sous-système
du monde Entry. Le pont `skieo_refresh_staff_pool` appelle la même fonction
native sur le sous-système du monde courant ; les signatures de code, les
pointeurs de settings et le nombre de candidats sont contrôlés avant l'appel.
Ce nouvel export est vérifié sur le build **25668054**. Un layout incompatible
échoue explicitement. Embauche, affectations, salaires et sérialisation passent
par les UFunctions du jeu. Reconstruction du DLL livré :

```bash
x86_64-w64-mingw32-gcc -shared -O2 -s -Wall -Wextra \
  native/SkiEONativeTerrain/native_terrain.c \
  -o mod/SkiEO-CustomMaps/Scripts/skieo_native_terrain.dll
```

Le message exact `Nothing reaches the Ticket Office` rejoint les deux anciens
titres de notification de réseau. La fermeture attend la disparition de
l'écran de chargement, puis contrôle huit fois les messages en attente. Elle
nécessite que les opérations natives autorisent le ski et les arrivées.

Le test UE4SS a confirmé 13 bâtiments, neuf remontées, 20 pistes, 11 hubs,
255 667 arbres et 22 employés. Après une sauvegarde et un rechargement par le
menu natif, les 22 identifiants, rôles et bâtiments d'affectation sont identiques,
et les deux terminaux de chaque remontée sont occupés. Ces contrôles ainsi que
les matériaux ont passé un `CollectGarbage` explicite.

Un widget natif construit avec le titre exact de l'alerte a été fermé par la
fonction de la carte ; une autre notification et une alerte avec réseau
invalide restent visibles. La capture du rendu provient de `HighResShot` via
l'API Unreal, dans `build/ue-debug/veymont-ground-final.png`. Le journal du test
est conservé dans `build/ue-debug/veymont-staff-final-validation.log`. L'instance
a été isolée avec une limite de 12 Gio sans swap ; le pic mesuré est d'environ
2,8 Gio. Le rendu en arrière-plan descend à un tick par seconde ; maintenir la
fenêtre de test active accélère la reconstruction.

Les données de contour de jupe et de lieux non consommés ont été retirées du
générateur, du module Lua et du manifeste Veymont. Le bloc `game` est maintenant
facultatif dans le schéma et les trois validateurs ; l'éditeur ne génère plus de
numéro de build par défaut. L'archive portable inclut le module de personnel.

## Portable albedo, autosaves and the native tree view

Veymont now declares `terrain.textures.albedo` in format 1.4. Its white
limestone PNG and nine subsequent mip PNGs are packed automatically. The
loader stages each image through `map.__read`, imports it, retains its UObject
and assembles a complete BGRA8 chain using `SKTM` version 5. This accepts
square power-of-two images up to 512²; the Landscape's existing version 4
512²/ten-mip jobs remain valid. Donor mip ownership is transferred once,
without changing cooked textures. The ground MID receives the result through
`Albedo`. Other channels require an explicit material parameter mapping.

The reported autosave error was `supported terrain renderer settings were
not found`. The bounded scene scan now permits readable containers smaller
than 4 KiB at a committed region's end and follows a second native container
level when the direct scan finds no matching renderer. `SKTR` version 2 also
recognizes the simulation's previous height texture, when present. The scene
owner, cache texture identities, bounds and native vtable remain mandatory.
Missing registration is retried forty times at 100 ms intervals; invalid
jobs/layouts fail immediately. Pending callbacks are retained and cancelled
on world changes. The original intermittent failure did not recur in the
baseline runs; these changes address the strict lookup and registration
conditions rather than assuming the save association was missing.

The portable forest queries the current world's
`TerrainOverlaySubsystem.GetObstacleFadeLevel` every 250 ms and changes
`SetActorHiddenInGame` only when the state changes. It also applies the
initial state before inserting trees and drops the old subsystem on unload.

Native validation on build 25668054 loaded `AutoSave_59DCD54C_1` from startup
and `AutoSave_59DCD54C_3`/`_4` after returning to the menu. All reconstructed
the terrain, white albedo, full forest and saved 22-member staff roster. The
actual toolbar's `OnRow0Clicked` hid and showed all 255,667 portable trees.
The imported 512² texture reported 1,441,792 bytes; it and the render survived
an explicit Unreal garbage collection. The native game booked guest revenue
at restoration (+24 and +16 in the latter two slots); exact economic equality
is therefore not asserted by these rendering checks. No test saved over the
user's slots. Test logs and API capture are kept in `build/ue-debug/`; the
white limestone image is `veymont-white-limestone.png`, generated by
`HighResShot` invoked through UE4SS, with no system screenshot.

## Raffinement local des falaises — 3 octobre 2026

Le R16 portable de Veymont contient un échantillon tous les 4 m, mais les
maillages visibles utilisaient partout `sample_step=4`, soit 16 m. Les
normales étaient également calculées avec des différences à 16 m. Le nouveau
module `terrain_mesh.lua` garde cette grille de base et subdivise les cellules
dont la pente moyenne dépasse 45° sur au moins un axe. Veymont raffine ainsi
10 140 cellules sur 254 016 jusqu'à 4 m. Les normales du monde indépendant
utilisent maintenant les différences à 4 m.

Le plan est partagé entre sol et neige. Les cellules voisines d'une cellule
raffinée utilisent un éventail de triangles raccordé à tous les échantillons
de son arête, y compris lorsqu'elle appartient à une autre section. La limite
de 16 384 cellules et de quatre subdivisions par axe borne la densification ;
les pentes les plus fortes sont prioritaires si une autre carte atteint cette
limite. Les altitudes sont celles du R16, avec interpolation bilinéaire pour
les centres de raccord situés entre deux échantillons. Aucun relief n'est
inventé et le format de carte reste inchangé.

Les tests vérifient les arêtes communes sur toute une grille, les frontières
des sections, les cellules finales de tailles inégales, les pas impairs,
l'absence de triangles dégénérés ou inversés, l'alignement de la neige et la
limite de raffinement. La génération hors moteur mesure 872 887 triangles
par couche, contre 508 032 auparavant. Le sol comporte 1 012 688 sommets,
dont les duplications nécessaires à ses projections UV ; la neige en comporte
445 863. Une section de sol atteint au maximum 79 147 sommets sur Veymont.

La validation native recharge `AutoSave_59DCD54C_1`, reconstruit la station et
les 255 667 arbres, puis compare les deux maillages à caméra identique depuis
l'est du Grand Veymont. Les captures `veymont-cliffs-coarse.png` et
`veymont-cliffs-adaptive.png` sont produites par `HighResShot` via UE4SS.
Le rendu raffiné est rétabli après la comparaison et survit au ramasse-miettes
d'Unreal. La météo native forcée sur `Sunny` donne un ciel bleu ; les grandes
parois restent lisses malgré le gain local, ce qui confirme la limite des
données actuelles. Le pic mémoire du groupe de test atteint 6 708 424 704
octets pendant les reconstructions de comparaison, puis 7 732 379 648 octets
sur l'ensemble de l'essai, fermeture comprise, sous sa limite de 12 Go. Aucun
crash Unreal n'est observé et aucune sauvegarde utilisateur n'est écrasée.
Wine dépasse le délai d'arrêt de quinze secondes et le groupe de test est
terminé automatiquement ; aucune instance du jeu ne reste ouverte.

Le diagnostic confirme `r.SkyAtmosphere=1`, `r.SupportSkyAtmosphere=1`,
`r.ForwardShading=0` et `r.Nanite=1`. Cette dernière variable ne transforme
pas les `ProceduralMeshComponent` en maillages Nanite. Des falaises réellement
verticales ou avec surplombs demanderont une géométrie 3D supplémentaire,
relevée ou modélisée, conservée dans un format portable. Une normal map peut
compléter les petits détails si le matériau chargé dispose du shader et du
paramètre correspondants ; elle ne remplace pas cette géométrie. Les essais
de température solaire et d'intensité ambiante sont temporaires dans la
sonde de diagnostic et ne changent pas les réglages livrés du monde.

Dans cet essai, changer `ClayEnvironmentController.DefaultColorTemperature`
ne suffit pas : la lumière garde 8 830 K. Désactiver temporairement le tick
du contrôleur puis appeler `SunLight.LightComponent:SetTemperature(3500)`
et réduire la SkyLight à 1 produit bien un éclairage chaud sur les parois
orientées à l'est. La capture `veymont-cliffs-warm-sun-proof.png` confirme
cette capacité du moteur. Le remplacement des réglages astronomiques et
météorologiques doit donc tenir compte du contrôleur qui réapplique ses
valeurs ; ce diagnostic n'installe pas une température fixe dans le jeu.

Références moteur : [Sky Atmosphere](https://dev.epicgames.com/documentation/en-us/unreal-engine/sky-atmosphere-component-in-unreal-engine)
et [géométrie et composants pris en charge par Nanite](https://dev.epicgames.com/documentation/en-us/unreal-engine/nanite-virtualized-geometry-in-unreal-engine).
