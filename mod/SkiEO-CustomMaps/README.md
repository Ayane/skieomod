# Custom Map

Par **Albatar (Élie Millon)**. La distribution inclut le guide anglais
`getting-started.md`. Veymont, du même auteur, est proposée comme carte Featured.

Contributions de **[ReymanHG](https://github.com/ReymanHG)** : corrections des
textures du sol et de l’éclairage nocturne, publiées dans la version 1.24.4.

Chargeur générique de cartes personnalisées pour la démo de Ski-E-O!.
Le protocole de compatibilité vérifie les ponts natifs, le rendu et les
sauvegardes à chaque mise à jour du jeu ; voir `docs/game-compatibility-testing.md`.
Il découvre les dossiers `custom-map.json` et les archives
`.skieomap`, ajoute la section **Custom Map** au dialogue **New Game**, puis
construit leur terrain directement depuis le heightmap R16 source.

Le catalogue communautaire utilise l’API web du projet, alimentée par
`skieomod publish`. Les filtres All / Local / Web / Steam et la recherche
sont intégrés au menu. Steam Workshop reste en préparation. Les cartes Featured du
projet utilisent `https://skieomod.emillon.fr/downloads/featured-maps.json`.
Le menu utilise les métadonnées locales et mises en cache. Le catalogue est
actualisé automatiquement à l’ouverture, puis au plus toutes les cinq minutes
pendant la consultation, sans bloquer la sélection ni les cartes installées.
Les cartes web téléchargées restent dans **Web**, avec une coche ; **Local**
regroupe les projets locaux et les cartes installées manuellement.
**Options** ouvre les réglages natifs : sandbox, durée du jour et jours par mois.
Le sandbox supprime les coûts et déverrouille tout, désactive les succès ainsi
que les objectifs et dépenses des scénarios scriptés. Les sauvegardes natives
conservent ce mode. Les terrains gardent leurs dimensions d’origine.
**Play** lance directement une carte et ses dépendances déjà présentes, sans
requête réseau. Les archives manquantes sont téléchargées et vérifiées par
SHA-256 dans l’écran de chargement, avant la création du monde. Les mises à jour
Featured sont facultatives : **Update map** les télécharge dans ce même écran.
Le menu distingue
les cartes et mods, les titres/propriétaires/votes/dates Steam et les informations
du terrain installé. Les dépendances `map-api` se chargent avant la carte ;
les mods UE4SS nécessitent leur enregistrement au démarrage.
Le client natif Steamworks reste à raccorder avec le jeu. Sans ce client,
les cartes locales et les articles déjà installés par Steam sont disponibles.
Voir `docs/steam-workshop.md` pour les contrats et leurs limites.

## Forêts JSON

Depuis la version 1.8, un script ordinaire peut appeler
`api:load_forest_json("Vegetation/forest.json")` dans `map.ready`. Déclarer
le fichier dans `content.assets` et fournir une liste de points `{ "x": 10,
"y": -20 }`, en mètres. Le chargeur calcule l’altitude et crée les arbres par
lots ; les nouveaux projets `skieomod create map` incluent cet exemple et son
guide. Veymont conserve son fichier SKXY.

## Installation provisoire

Installer la CLI depuis les sources puis lancer `skieomod setup`. Le jeu,
les dossiers de cartes/mods et le contenu Workshop des bibliothèques Steam
sont détectés et mémorisés. Choisir **New Game → Custom Map → Veymont [Featured] → Play**
pour télécharger la carte et lancer la première partie.
`skieomod run` teste les créations locales.
Avant l’ouverture du Workshop, les testeurs peuvent lancer `skieomod update`
pour télécharger le dernier chargeur sur `skieomod.emillon.fr` et
`skieomod update --check` pour afficher leur version et les changements disponibles.
Fermer le jeu avant la mise à jour. Les paramètres et cartes sont conservés,
et les fichiers remplacés sont sauvegardés dans `.skieomod-backups/`.
`skieomod update --archive CustomMap-Mod-VERSION.zip` permet de tester une
version précise ou de revenir à une version précédente. Les joueurs utiliseront
Steam à la sortie.

Pour une installation manuelle, installer UE4SS compatible UE 5.8 puis copier
`SkiEO-CustomMaps` dans `SkiResortSimulator/Binaries/Win64/ue4ss/Mods`, avec un
fichier `enabled.txt`. Les cartes `.skieomap` se placent dans
`SkiResortSimulator/Content/Paks/~mods`.
Les distributions ne contiennent aucune carte. Les téléchargements Featured
sont mis en cache à côté des scripts sous des noms contenant leur SHA-256 ;
les cartes locales et les anciennes versions téléchargées sont conservées.

Veymont 0.6.1 contient déjà un manifeste compatible. Le premier élément de la
liste est sélectionné automatiquement. Une carte présente à plusieurs endroits
ne produit qu'une ligne par identifiant ; la version la plus récente est retenue.

Le sélecteur Custom Map présente une liste recherchable avec vignettes, une
carte de localisation, un aperçu filaire du terrain et une fiche crème sur fond
bleu glacier. Les onglets World/Scenarios conservent leurs boutons natifs ;
Back ferme New Game. L'écran de chargement reprend la fiche de la carte,
ses dimensions, ses altitudes, ses compteurs déclarés et la progression réelle,
avec une barre corail. Les compositions s'adaptent à la résolution sans étirement.
L'extension facultative `community.skieo.presentation` fournit l'illustration,
les compteurs et les difficultés ; voir `docs/custom-map-format.md`.
Le bouton Custom Map est ajouté avant la construction du panneau et des aperçus.
L’inventaire lit les manifestes et les tailles des fichiers ; la décompression
et la vérification des gros fichiers de la carte choisie ont lieu pendant le
chargement. Un téléchargement échoué rend la main au sélecteur Custom Map.

Le chargeur ouvre un monde vide et initialise son Landscape, son cache natif,
ses textures de neige/overlay, sa collision procédurale et l'environnement
directement depuis le même R16, sans charger Sugar Bowl. Les `.pak`, `.ucas` et `.utoc` sont refusés
dans les paquets de carte.

Les 16 atlas 512², leurs dix niveaux de mip, leurs coordonnées par composant et
le paramètre de heightmap des matériaux Landscape sont tous reconstruits
ensemble. Les falaises et normales suivent donc le relief source au lieu de
conserver les masques d'un niveau existant. Le rendu procédural emploie une
texture de roche pour le sol et le matériau de neige du jeu. La roche striée
reste réservée à la jupe, calculée depuis
les bords du relief. Soleil, lune et exposition suivent le contrôleur natif.

Le chargement d'une sauvegarde custom reconstruit aussi ce monde, puis conserve
la station et l'état de partie restaurés par le jeu. Le fichier
`SkiEO-CustomMap-<GUID>.json`, voisin des sauvegardes, identifie la carte à
réinstaller. Les anciennes sauvegardes sans ce fichier sont reconnues si une
seule carte custom est installée. La plage d'altitude native inclut le décalage
du MNT, sans déplacer le terrain visible.

Les ressources portables déclarées dans `content.assets` sont accessibles aux
scripts par `api:read_asset`. Le helper SKXY fourni reconstruit notamment les
forêts sous forme d'instances ISM natives, avec une altitude dérivée du R16.
Les ajouts traitent au plus 512 points par callback et les composants contiennent
au plus 8 192 arbres chacun, afin de borner le coût des mises à jour de leurs
tampons de rendu. Veymont libère sa forêt avant le changement de monde lors
du chargement d'une sauvegarde ; tous les arbres sont reconstruits ensuite.

L'écran de chargement natif couvre la génération du terrain, de la neige, du
tablier et l'initialisation de la station. Les scripts asynchrones utilisent
`api:hold_loading()` pour le maintenir jusqu'à la fin de leur construction.

Commandes de diagnostic :

```text
custommaps                 liste et revalide les cartes
custommap                  charge la carte sélectionnée
custommap community.veymont
custommap_workshop         actualise le catalogue Steam via le client du jeu
custommap_install          abonne et télécharge l’article sélectionné
custommap_reload           rescane les manifestes et reconstruit le panneau
custommap_status           indique le module chargé, le relief et la progression
```

Le format, l'API Lua et l'outil `.skieomap` sont documentés dans
`docs/custom-map-format.md` à la racine du dépôt.

Les cartes peuvent définir leurs images de sol dans `terrain.textures`
(format 1.4), avec une chaîne de niveaux de détail PNG complète. Le canal
`albedo` est appliqué au sol ; les autres canaux se relient aux paramètres
d'un matériau compatible par `terrain.runtime.texture_parameters`.
La forêt portable suit l'état du bouton de masquage natif des arbres.

Custom Map warns above the browser when the running game executable is not a
qualified build, or its version cannot be verified. For 1.24.8, the qualified
Steam demo build is 26097896. See https://skieomod.emillon.fr for installation.
The check runs once in the background and works offline. Existing native
compatibility guards remain active when starting a map.

While the warning is shown in the main menu, Custom Map checks automatically for a newer mod. It downloads and verifies the official
release automatically, without replacing files loaded by the running game.
**Restart game** closes the game, installs the prepared update and starts the
same game again. Closing normally also applies the update, without relaunching.
The update preserves maps, settings and saves, and keeps a backup of changed
code. Interrupted installation is recovered before gameplay modules load.
A complete hot reload is unavailable because native DLLs and hooks remain loaded.
This feature becomes available after installing 1.24.7 with the normal installer.
