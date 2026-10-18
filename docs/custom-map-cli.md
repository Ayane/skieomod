# skieomod — outils de création

Par **Albatar (Élie Millon)**. Le [guide anglais](getting-started.md) présente
l’installation et les premiers essais avec Veymont, carte Featured du même auteur.

`skieomod` crée et teste des cartes, des mods UE4SS et des `mapmod`. Steam
Workshop est le catalogue de cartes/mods prévu pour la sortie du jeu. Avant
son ouverture, les créateurs et testeurs utilisent aussi la CLI pour installer
et mettre à jour Custom Map depuis le VPS `skieomod.emillon.fr`.

## Installer la commande

Pour installer la dernière version publiée, utiliser cette commande stable :

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
```

Les articles peuvent pointer vers [la dernière archive des outils](https://skieomod.emillon.fr/downloads/CustomMap-Tools.zip)
et [la dernière archive du mod](https://skieomod.emillon.fr/downloads/CustomMap-Mod.zip).
Ces liens restent identiques à chaque publication. L’archive des outils contient
la wheel installable, les sources et la documentation de la version courante.

Avec Python 3.10+ et pipx, depuis les sources :

```sh
pipx install --force .
skieomod --version
```

Ou installer la wheel distribuée :

```sh
pipx install ./skieo_custom_map-1.11.0-py3-none-any.whl
```

Sans pipx, créer un environnement Python (`python -m venv .venv`), l’activer,
puis utiliser `python -m pip install .` depuis les sources, ou installer la
wheel avec `python -m pip install CHEMIN.whl`. Sous Windows, `py` peut remplacer
`python`. Python est nécessaire aux utilisateurs de cette CLI pendant les tests ;
le parcours des joueurs via Steam à la sortie n’en dépendra pas.

## Désinstaller le mod et la commande

Fermer le jeu et l’éditeur, puis lancer :

```sh
skieomod uninstall-self --check
skieomod uninstall-self
```

`--check` affiche les suppressions prévues sans modifier l’installation.
Sans option, `uninstall-self` retire Custom Map du jeu configuré, puis désinstalle
la commande avec pipx ou le pip de l’environnement Python courant.
`--mod-only` conserve la commande ; `--cli-only` conserve le mod et fonctionne
même si le jeu a déjà été supprimé. `--game-dir CHEMIN` choisit un autre jeu ;
`--ue4ss-mods CHEMIN` limite le retrait à ce dossier de mods.

Le dossier du mod, avec ses scripts, réglages et sauvegardes, est déplacé dans
`.skieomod-backups/uninstall-HORODATAGE/` à côté de son ancien emplacement.
Les entrées Custom Map de `mods.txt` sont retirées. Les cartes téléchargées,
projets sources, autres mods, UE4SS et configuration de la CLI sont conservés.
Les anciens liens `skieomod://` vers cette installation sont désenregistrés
lors du retrait de la commande. Une exécution depuis les sources conserve les
sources lorsqu’aucun paquet Python n’est installé.

## Consulter l’aide

```sh
skieomod
skieomod help
skieomod -h
skieomod --help
skieomod help create
skieomod create map --help
skieomod help publish
```

Chaque commande accepte `-h` et `--help`, avec une description de ses options
et des exemples. `help COMMANDE` affiche la même aide. Sans argument, la CLI
affiche l’aide générale. Ces commandes ne nécessitent ni jeu ni configuration.

## Créer, compiler et tester

Dans un dossier vide, choisir un modèle :

| Commande | Contenu | Exécution |
| --- | --- | --- |
| `skieomod create map` | Terrain R16 de 1 km, aperçu et script Lua commenté | Monde indépendant |
| `skieomod create mod` | Mod UE4SS, `Scripts/main.lua` commenté | Démarrage du jeu |
| `skieomod create mapmod` | Mod `runtime: map-api`, script commenté | Session d’une carte dépendante |

```sh
skieomod create map --name "Ma station" --id author.ma-station --author "Mon pseudo"
skieomod build
skieomod test
skieomod run
```

Les cartes peuvent dépasser 8 km et être rectangulaires :

```sh
skieomod create map --output grande-carte --size 16000 12000 --spacing 8
```

`--size LARGEUR LONGUEUR` exprime les deux dimensions en mètres ; `--spacing`
choisit le pas du R16 (16 m par défaut). Chaque longueur doit être un multiple
du pas. Le modèle ajuste `sample_step` pour limiter le maillage initial ; la
création refuse les sources de plus de 32 Mio ou 16 384 sommets par axe.
Le [guide des grandes cartes](large-maps.md) explique les résolutions natives.

Les modèles fournissent le manifeste, le script commenté, `workshop.json`,
`preview.png`, un README et un `.gitignore` commenté pour `bin/` et `obj/`.
`docs/manifest.md` explique les champs JSON et les dépendances ;
`docs/scripting.md` décrit le runtime Lua du modèle ; `docs/development.md`
couvre la compilation, les tests et le dépannage ; `docs/workshop.md` guide
la préparation d’une publication. Les cartes incluent aussi `docs/terrain.md`
avec l’encodage R16, les dimensions et l’aperçu, ainsi que `docs/vegetation.md`
et une forêt JSON d’exemple à modifier directement. Cette documentation est
autonome et reste avec les sources. Les manifestes restent du JSON strict,
sans commentaires : leurs explications sont dans les guides.

Les fichiers existants ne sont pas écrasés, y compris la documentation.
`create map --output DOSSIER` choisit un autre dossier ; passer ensuite ce
dossier à `build`, `test`, `run` et `publish`, ou s’y placer.
`new` reste un alias compatible de `create`.

`build` valide le projet et produit une archive ZIP reproductible
`bin/IDENTIFIANT-VERSION.skieomap` ou `.skieomod`. Elle sert aux tests locaux ;
le contenu Workshop sera décompressé. `build --output FICHIER` choisit la
sortie. Un échec conserve la dernière archive valide. `test` accepte aussi
une archive existante. `--check-scripts` utilise Lua 5.4 / `luac5.4` ;
`--check-dependencies` vérifie les manifestes actuellement installés par Steam.

`run` reconstruit et installe le projet local, puis ouvre Steam. Un `mapmod`
démarre dans une carte de test créée dans `obj/mapmod-preview` ; sa publication
n’est pas nécessaire. Un mod UE4SS s’active au démarrage suivant : fermer le
jeu avant `run`. Les sources précédentes d’un mod remplacé sont sauvegardées.
Les dépendances externes sont lues dans leurs dossiers Workshop, gérés par
Steam. Aucun dépôt HTTP n’est interrogé.

## Construire à partir d'un heightmap

L'éditeur de bureau intégré est disponible avec une vue 3D Qt depuis la version 1.14 :

```sh
skieomod editor
skieomod editor ma-carte
```

Il ouvre directement le dossier source, importe les heightmaps, permet de
sculpter le terrain et de peindre les arbres, règle le biome et l'érosion, puis
appelle les commandes Build/Test/Play. Voir le [guide de l'éditeur](editor.md).
Les dépendances Qt/OpenGL sont installées avec le paquet. La barre d'outils
ouvre aussi les éditeurs de déclencheurs (graphe ou Lua), ressources et objets.
Le build compile leurs JSON et CSV en Lua. Les autres commandes fonctionnent
sans écran graphique.

Le [tutoriel illustré en anglais](https://skieomod.emillon.fr/tutorials/heightmap/)
présente le parcours sans éditeur graphique. Depuis la CLI 1.10, le JSON définit
la source et ses unités ; `skieomod build ma-carte` prépare le terrain :

```json
"build": {
  "heightmap": {
    "file": "Terrain/source-heightmap.png",
    "spacing_meters": 8,
    "elevation_meters": [800, 2200]
  }
}
```

Ajouter cette propriété au premier niveau de `custom-map.json`. Le PNG doit
être en niveaux de gris 16 bits, sans alpha et sans entrelacement ; ses dimensions
sont lues automatiquement et aucune dépendance supplémentaire n'est nécessaire.
Pour du R16 brut, le format par défaut est `r16le` ; utiliser `"format": "r16be"`
pour du big-endian. Les données doivent être des entiers non signés 16 bits sans en-tête.
Depuis la version 1.12, `vertices` est facultatif : si le nombre d'échantillons
est un carré parfait, le build suppose une grille carrée et signale cette hypothèse.
Pour un terrain rectangulaire, préciser `[largeur, hauteur]`, ou `[largeur, null]`
ou `[null, hauteur]` pour déduire l'autre côté. La taille du fichier ne permet pas
de prouver qu'une grille est carrée ; les dimensions connues restent prioritaires.
Les chemins sont relatifs au projet. Conserver l'entrée sous un nom distinct de
`Terrain/heightmap.r16`, réservé à la sortie générée.

`elevation_meters` contient les altitudes réelles des échantillons les plus bas
et les plus hauts. Si l'exporteur fournit l'encodage, utiliser plutôt
`height_scale_meters` et `height_offset_meters`. `row_order` vaut
`north_to_south` par défaut ; `south_to_north` inverse l'ordre des lignes.
Les colonnes vont d'ouest en est, avec un pas identique sur les deux axes.

Depuis la version 1.12, les champs d'altitude sont également facultatifs pour un
premier essai : sans `elevation_meters` ni encodage, les échantillons les plus bas
et les plus hauts sont ramenés à un relief relatif de **0 à 1 000 m**. Le terminal
et `Terrain/Generated/build-report.json` signalent ce repli. Les pixels seuls ne
permettent pas de déduire les altitudes réelles ; renseigner ensuite l'étendue
réelle ou l'encodage complet pour retrouver l'échelle du terrain. Un encodage
partiel est rejeté. `spacing_meters` reste nécessaire pour la taille horizontale.

Le build calcule les sommets, l'emprise, l'origine centrée, les altitudes,
l'échelle et l'aperçu normalisé, puis crée un paquet avec un R16LE portable.
Après validation, il met à jour les champs dérivés de `terrain` dans le JSON et
le R16 généré ; les fichiers remplacés sont sauvegardés dans `.heightmap-backups/`.
L'entrée originale et la configuration `build` sont conservées dans le projet ;
elles ne sont pas incluses dans le paquet. Un échec laisse la dernière archive
valide et les fichiers du projet intacts. `test` prépare le même terrain sans
modifier les sources. `run` reconstruit avec la même configuration.

La source est limitée à 32 Mio d'échantillons et 16 384 sommets par axe.
Le build choisit un pas de rendu initial pour limiter le nombre de cellules ;
`build.heightmap.sample_step` permet de le remplacer pour ajuster le détail.

## Configurer temporairement le jeu

```sh
skieomod setup
skieomod config
```

`setup` installe temporairement Custom Map/UE4SS et mémorise les chemins du
jeu, de la démo et des bibliothèques Steam secondaires. Un choix est demandé
si une installation manque ou est ambiguë. Les chemins sont enregistrés dans
`%APPDATA%/skieomod/config.json` ou `~/.config/skieomod/config.json`
(`XDG_CONFIG_HOME` respecté). Aucun chemin de carte n’est nécessaire ensuite.
Veymont apparaît comme carte **Featured** ; elle ne fait pas partie des distributions.
**Play** la télécharge depuis le serveur si elle est absente ou dépassée, puis
réutilise sa copie à jour, y compris hors ligne.
Relancer le jeu dans Steam, puis choisir **New Game → Custom Map → Veymont**
pour découvrir son terrain, sa neige, sa forêt et sa station.

`--game-dir`, `--maps-dir`, `--ue4ss-mods`, `--app-id` corrigent la détection.
`setup --workshop-app-id APPID` sélectionne explicitement un autre Workshop
si le développeur confirme cet accès pour la démo. `setup` n’enregistre plus
le protocole `skieomod://`.

Sous Linux, lancer une première fois le jeu avec Steam pour créer le préfixe
Proton, puis le fermer. Le setup conserve les overrides existants et ajoute
`dwmapi=native,builtin` avec sauvegarde du registre. Windows et Linux/Proton
sont pris en charge ; les outils de création fonctionnent sur macOS, mais pas
le lancement du jeu Windows.

## Mettre à jour avant Workshop

Fermer le jeu avant d’appliquer une mise à jour : les scripts et DLL seront
chargés au lancement suivant. Après une première installation avec `setup` :

```sh
skieomod update --check
skieomod update
```

La commande lit [la dernière version du chargeur](https://skieomod.emillon.fr/downloads/loader-latest.json),
télécharge son archive versionnée en HTTPS et vérifie sa taille, son SHA-256,
son manifeste et l’empreinte de chaque fichier avant toute modification du jeu.
`--check` lit seulement les métadonnées, affiche les versions
installée/disponible et les changements, puis laisse l’installation intacte.
Avec `--archive`, la vérification utilise l’archive locale fournie.
La CLI vérifie aussi les mises à jour en arrière-plan une fois par jour,
et immédiatement lorsqu’elle détecte une nouvelle révision Steam du jeu.
L’éditeur affiche le résultat et propose une vérification manuelle dans le menu Game.
Le chargeur 1.17 ajoute au manifeste les révisions Steam vérifiées et nécessite
la CLI 1.17 ou plus récente. Mettre d’abord à jour le paquet Python ; le flux
indique ce minimum aux anciens clients avant tout téléchargement d’archive.
Le mod et la CLI peuvent ensuite évoluer séparément tant que le protocole reste
compatible.

La configuration de la CLI, les chemins Workshop, les demandes de lancement,
les cartes et les autres mods sont conservés. Les fichiers remplacés ou supprimés
sont sauvegardés dans `SkiEO-CustomMaps/.skieomod-backups/`. Les modules obsolètes
connus sont supprimés lorsqu’ils n’ont pas été modifiés localement ; les fichiers
personnels sont conservés. Une erreur d’écriture restaure les fichiers déjà
remplacés. Une installation ancienne sans suivi de version peut être migrée ;
sa version initiale est affichée comme inconnue.

Pour une version particulière envoyée à un testeur, ou pour revenir à une
version précédente après une régression :

```sh
skieomod update --archive ./CustomMap-Mod-1.5.0.zip --check
skieomod update --archive ./CustomMap-Mod-1.5.0.zip
```

Ces archives contiennent le chargeur, ses DLL, ses guides,
`loader-release.json`. Les cartes Featured sont téléchargées séparément par
le jeu au premier lancement ou lors d’une mise à jour. `setup` et `update`
conservent les cartes existantes. Elles ne mettent pas à jour UE4SS lui-même. Une archive
ancienne sans manifeste de version est refusée. `update --bundled` applique
hors ligne le chargeur livré avec la CLI installée.

Pour installer ou actualiser la CLI avec la wheel du VPS :

```sh
pipx install --force --index-url https://skieomod.emillon.fr/downloads/pypi/ skieo-custom-map
```

Joindre la sortie de `skieomod --version` et `skieomod update --check` aux retours
utilisateurs pour identifier la CLI et le chargeur testés.

## Préparer la publication Workshop

```sh
skieomod publish --prepare
```

Cette commande fonctionne sans client Steamworks et produit :

- `bin/workshop/content/` : manifeste et ressources décompressées ;
- `bin/workshop/preview.png` : image séparée ;
- `bin/workshop/publish-request.json` : requête de publication native ;
- `bin/workshop/workshop.vdf` : configuration de test SteamCMD.

Remplacer l’aperçu du modèle par une capture de votre création. `workshop.json`
définit l’AppID consommateur, l’ID d’article (`"0"` pour créer), la visibilité
initialement privée et l’image. `--item-id`, `--app-id`, `--preview`,
`--visibility`, `--changenote` les ajustent. L’ID retourné par Steam est
mémorisé afin de mettre à jour le même article à la publication suivante.

Les dépendances requises doivent préciser leur `workshop_id`. La contrainte de
version vérifie le paquet installé ; elle ne sélectionne pas une ancienne
version Steam. Voir le [contrat Workshop](steam-workshop.md).

## Commandes raccordables au client Steamworks

Le client natif n’est pas encore livré : `publish` sans `--prepare`, `list`,
`install` et `play` signalent son absence. Ils n’appellent aucun ancien dépôt.
Quand le jeu fournira le client :

```sh
skieomod --steam-client CHEMIN config
skieomod publish
skieomod list --kind map --search neige
skieomod install 1234567890
skieomod play 1234567890
```

Ces identifiants sont des articles Workshop. Il n’y a plus de `--repository`,
de `CUSTOM_MAP_TOKEN`, de `login` ou de sélection distante `--version`.
`list --installed` fonctionne hors ligne avec l’inventaire local de Steam.
L’enregistrement des mods UE4SS téléchargés au démarrage reste à raccorder
avec le développeur du jeu ; un téléchargement seul ne les active pas.

## English

`skieomod create map`, `create mod` and `create mapmod` scaffold working projects
with commented Lua scripts, a README and self-contained guides in `docs/`.
`new` remains an alias. `skieomod help COMMAND` and `COMMAND --help` explain
every command with examples; invoking the CLI without arguments shows help.
`build`, `test` and `run` validate and test them locally. A mapmod runs in an
automatically generated preview map. `setup` temporarily installs Custom
Map/UE4SS and remembers detected Steam paths; it no longer registers a URI handler.
Veymont, also by Albatar (Élie Millon), appears as **Featured**. Choose
**New Game → Custom Map → Veymont → Play** to check the latest version and
download it if missing or outdated. Current downloaded maps work offline.
Before Workshop opens, `update` downloads a versioned loader release from the VPS
and verifies its SHA-256. `update --check` fetches only release metadata and
reports versions and planned changes;
`--archive FILE` applies a specific test release, and `--bundled` works offline.
Close the game first. Settings and maps are preserved; replaced files are backed up.

Web publication with `skieomod publish PROJECT` uses `CUSTOM_MAP_TOKEN` from
https://skieomod.emillon.fr/account. Published maps appear directly in the
in-game catalogue, alongside local and Featured maps, with source filters and
search. See [the publication guide](custom-map-repository.md).
Steam Workshop integration is in preparation. `publish --prepare` creates
unpacked content, a separate preview, a native publication request and a VDF
for SteamCMD testing. The native Steamworks client is not shipped yet. Steam publication uses `publish --steam`; remote Steam
`list`, `install` and `play` require that separate client. `list --installed`
reads Steam’s local inventory. Required dependencies pin a decimal-string
`workshop_id`; semantic versions describe installed package compatibility,
not historical Workshop release selection.

## Construire la distribution

Depuis les sources :

```sh
python3 tools/build_custom_map_release.py --tools-only
```

Les fichiers sont produits dans `build/custom-map-downloads/` : la wheel
`skieo_custom_map-1.11.0-py3-none-any.whl` et `CustomMap-Tools.zip`. L’archive
contient la wheel, les sources installables, les guides, les schémas et l’éditeur.
La wheel embarque les modèles de projet, la documentation et le chargeur avec
ses DLL de téléchargement et de terrain natif. Les cartes sont distribuées séparément.
Le guide anglais est aussi disponible sous le lien stable
[`getting-started.md`](https://skieomod.emillon.fr/downloads/getting-started.md). Les ressources installées se trouvent
dans `share/skieomod/` sous le préfixe de l’environnement Python.

Pour une compilation hors ligne, si `setuptools>=77` et `wheel` sont déjà
installés, ajouter `--no-build-isolation`. Le script produit également
`CustomMap-Mod-1.11.0.zip`, son alias `CustomMap-Mod.zip` et `loader-latest.json`.
Le script produit séparément `community.veymont-VERSION.skieomap` et
`featured-maps.json` ; le catalogue est publié après les archives de cartes.
`--tools-only` conserve le catalogue Featured déjà publié. Aucun paquet
CLI, outils ou chargeur ne contient les ressources de Veymont. `--loader-ref REVISION` choisit
une révision Git du chargeur. La distribution utilise sinon les fichiers du
répertoire de travail. `--loader-archive ARCHIVE` permet de reprendre le code
vérifié d’une publication existante pour une mise à jour de la CLI,
sans embarquer des changements du jeu encore en cours.

UE4SS utilise le build testé `UE4SS_v3.0.1-1152-ge3ba1016.zip`, conservé sous
une URL versionnée sur `skieomod.emillon.fr`. `setup` vérifie son SHA-256 ;
une rotation du tag GitHub `experimental-latest` ne change pas le build installé.
La construction exige cette archive locale et la copie dans les téléchargements
ainsi que dans les sources du ZIP des outils. Pour la première construction :

```sh
python3 tools/build_custom_map_release.py --tools-only \
  --ue4ss-archive /chemin/vers/archive-UE4SS-testee.zip
```

Les constructions suivantes réutilisent le fichier versionné présent dans
`build/custom-map-downloads/`. `--output-dir` permet de préparer les fichiers
dans un autre répertoire. Le script ne sélectionne pas automatiquement un
nouveau build amont. Un changement de build UE4SS exige des tests dans le jeu,
puis la mise à jour volontaire du nom et de son empreinte dans `skieo_install.py`.

Vérifier la wheel dans un environnement isolé, sans accéder au jeu ni à Steam :

```sh
python3 tests/check_skieomod_distribution.py \
  build/custom-map-downloads/skieo_custom_map-1.11.0-py3-none-any.whl \
  --loader-archive build/custom-map-downloads/CustomMap-Mod-1.11.0.zip
```

Ce contrôle installe uniquement la wheel fournie, vérifie l’aide et les ressources
du chargeur, puis crée, compile, teste et prépare les trois modèles pour Workshop.
Il simule aussi une installation ancienne et vérifie la mise à jour hors ligne
du mod, la conservation des paramètres et les sauvegardes.

## Publier une itération sur le VPS

Le script `deployment/release_custom_map.py` automatise la préparation et la
publication via `root@skieomod.emillon.fr`. Depuis la racine du projet, avec
Python, `pip` et SSH disponibles, choisir une nouvelle version :

Ajouter d'abord ses notes dans une section `## [VERSION]` du
[`CHANGELOG.md`](../CHANGELOG.md). Une copie versionnée est publiée avec les
paquets. Les annonces automatiques dans le fil Discord se configurent avec un
webhook créé par un membre disposant de **Gérer les webhooks** ; le
[guide](discord-releases.md) décrit la configuration, l'aperçu sans envoi et
la reprise après un échec. `--skip-discord` désactive l'annonce pour une
publication. Sans webhook configuré, la publication fonctionne normalement.

```sh
python3 deployment/release_custom_map.py 1.17.1
```

Le script vérifie l'accès SSH et la version en ligne, met à jour les versions
dans `pyproject.toml` et `tools/skieo_loader.py`, construit les outils et le mod
avec Veymont, vérifie les paquets dans un environnement isolé, publie, puis
contrôle que le flux HTTPS correspond à la publication locale. Il s'arrête
au premier échec. Les fichiers du répertoire de travail sont utilisés, y compris
les modifications non committées. Il ne crée ni commit ni tag Git.

Les paquets sont conservés dans `build/release-VERSION/`. Le build UE4SS testé
est pris dans `build/custom-map-downloads/` ; `--ue4ss-archive CHEMIN` permet
d'en fournir une autre copie, dont l'empreinte est toujours vérifiée.
`--no-build-isolation` construit sans téléchargement si `setuptools>=77` et
`wheel` sont déjà installés dans le Python utilisé.

Le dépôt GitHub publie automatiquement les nouvelles versions de `main` après
réussite des tests. Les versions de `pyproject.toml` et `tools/skieo_loader.py`
doivent correspondre et avoir une entrée dans `CHANGELOG.md`. Le workflow
construit les paquets et le site, publie une version GitHub `vX.Y.Z`, puis le
serveur l'installe sous cinq minutes environ. Un push sans augmentation de
version ne déclenche pas de déploiement. Voir
[`deployment/README.md`](../deployment/README.md) pour le suivi et la reprise.

Pour tester d'abord dans le jeu, préparer sans contacter le serveur, puis
committer et pousser la nouvelle version. Pour une publication SSH manuelle
des mêmes paquets après le test :

```sh
python3 deployment/release_custom_map.py 1.17.1 --prepare-only
# Tester dans le jeu le paquet build/release-1.17.1/CustomMap-Mod-1.17.1.zip.
python3 deployment/release_custom_map.py 1.17.1 --publish-only
```

Le mode `--publish-only` relance les vérifications des paquets avant l'envoi,
sans reconstruire ni modifier les versions des sources. Le test dans le jeu
reste manuel. Après un échec de construction, les versions des sources restent
à la version demandée pour permettre de corriger puis relancer la commande.

Les options `--host`, `--remote-directory`, `--output-dir`, `--ssh-config` et
`--known-hosts` permettent d'adapter le serveur et les chemins. La vérification
de la clé SSH reste active ; une première connexion doit être validée avec
`ssh root@skieomod.emillon.fr`. Si la vérification HTTPS échoue après l'envoi,
le message précise que la publication a déjà eu lieu.

Pour publier directement des paquets déjà vérifiés avec le script existant :

```sh
python3 deployment/publish_loader_updates.py
```

Le script utilise SSH vers `root@skieomod.emillon.fr` et le dossier déjà servi
en HTTPS `/opt/custom-map/current/downloads`. Il vérifie et publie d'abord
l'archive UE4SS testée, puis la wheel, le ZIP du mod
et les sources sous des noms versionnés, puis remplace `loader-latest.json`
en dernier par renommage atomique. Le pointeur précédent est conservé dans
`loader-latest.previous.json`. Le ZIP des outils est limité à 128 Mio ; les
autres fichiers envoyés restent limités à 64 Mio. Les tailles sont vérifiées
localement avant l'envoi et à la réception sur le serveur.
Une version publiée ne peut pas être remplacée
par des octets différents : augmenter la version avant de republier une modification.
Les anciennes archives restent disponibles pour tester une régression.
`CustomMap-Tools.zip` et `CustomMap-Mod.zip` suivent automatiquement les nouveaux
fichiers par des liens symboliques remplacés atomiquement. L’index
`/downloads/pypi/skieo-custom-map/` expose uniquement la wheel courante, avec son
SHA-256, pour que la commande `pipx` publiée dans un article reste valable.
Nginx impose la revalidation des liens stables, du flux de mise à jour et de
l’index Python afin de ne pas servir une ancienne version depuis un cache HTTP.

La CLI 1.6 a introduit les archives d’exemple vérifiées dans `Examples/`.
Le minimum est passé à 1.7.0 avec Veymont 0.6 : son archive dépasse l’ancienne
limite de téléchargement de 16 Mio. Les nouvelles limites sont 64 Mio pour
l’archive du chargeur et 128 Mio décompressés. Les testeurs utilisant une CLI antérieure
doivent réexécuter la commande d’installation stable une fois. Ce minimum ne
doit augmenter seulement si le protocole change. La version 1.17 exige la CLI
1.17 pour lire les révisions Steam vérifiées dans le manifeste du chargeur.
Aucun redéploiement de l’ancien
catalogue HTTP ni raccordement Workshop n’est nécessaire pour publier ces fichiers.

## Traitement et végétation au build

`build.heightmap.processing` configure le lissage, l’érosion thermique,
l’érosion suivant le drainage et le bruit facultatif. `build.vegetation`
configure la limite des arbres, l’humidité, la température, le vent, les pentes,
la densité, l’espacement et la couverture herbe/roche. Chaque build repart
de la source et recalcule les altitudes ainsi que l’aperçu.

Pour les arbres placés à la main, `build.forest.file` désigne le JSON source.
Le build le compile en SKXY ; le chargeur 1.11 ne lit plus les forêts JSON.
La forêt automatique produit directement du SKXY et prend la priorité.
Le [guide](vegetation.md) et le [tutoriel](https://skieomod.emillon.fr/tutorials/heightmap/#bake)
contiennent la configuration complète et les limites des modèles.
