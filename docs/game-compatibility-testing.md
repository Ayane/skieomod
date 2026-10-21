# Tester une nouvelle version du jeu

Ce protocole sert à qualifier un couple **build du jeu / code du chargeur**.
Il conserve les empreintes des exécutables, d'UE4SS, du chargeur, des cartes et
du catalogue IoStore. Il ne modifie pas l'installation, les profils natifs,
les sauvegardes de la partie habituelle ou les versions annoncées compatibles.
Il ne publie rien et ne télécharge aucun outil.

Depuis la racine du dépôt, le contrôle initial se lance avec :

```sh
python3 tools/check_game_compatibility.py
```

Le script utilise la configuration locale de `skieomod`. `--config chemin.json`
permet d'en choisir une autre. Les rapports vont dans un nouveau dossier sous
`build/compatibility/`. `--output dossier-vide` fixe cette destination ; un
dossier déjà utilisé est refusé pour éviter de mélanger deux essais.

## Résultat et conditions de validation

| Résultat | Code de sortie | Signification |
| --- | ---: | --- |
| `incompatible` | 1 | Au moins une assertion obligatoire a échoué : garde native, ressource, chargement, crash, état ou sauvegarde. |
| `unverified` | 2 | Des mesures ou une revue manquent, ou le contrôle n'a pas pu être exécuté. |
| `compatible` | 0 | Tous les contrôles obligatoires et les deux revues documentées passent pour les empreintes du rapport. |

Un lancement réussi n'accorde jamais à lui seul le résultat `compatible`.
Sans UE4SS, sans contrôle visuel ou sans vraie sauvegarde/reprise des deux cartes,
le résultat reste incomplet. Une erreur de démarrage ne prouve pas à elle seule
sa cause : les journaux permettent de distinguer l'échec observé du diagnostic.

Le rapport JSON contient les mesures et les candidats de relocalisation.
`report.md` présente les résultats, les ressources ajoutées/supprimées et le
nombre de ressources dont les empreintes ont réellement pu être comparées.
Un hash absent dans une ancienne capture ne signifie pas « contenu inchangé ».

## Protections du chargeur à partir de 1.23.0

Le chargeur vérifie les types et les adresses réfléchies des champs qui
encadrent ses accès privés au terrain, au Landscape, au placement et à la
session de sauvegarde. Ces contrôles ont lieu avant de modifier la demande
native de partie ou de voyager vers la carte. Une structure incompatible
produit une erreur explicite. Les accès publics continuent à utiliser la
réflexion Unreal, qui suit les déplacements de leurs propriétés.

Les hooks de hauteur vérifient aussi les types et l'ordre des paramètres.
Les erreurs de démarrage d'un module optionnel sont isolées. Un hook optionnel
qui échoue est désactivé et conserve le comportement natif ; les autres
fonctions restent installées. Le démarrage des cartes source exige les hooks
essentiels de voyage et de restauration. Les callbacks sont conservés jusqu'à
la fermeture du chargeur pour résister au ramasse-miettes Lua.

Les trois capacités de notation sont détectées séparément. Le résolveur natif
accepte les déplacements d'adresses après vérification du code complet utile,
des limites de section et des références croisées : constantes de pente finies
et ordonnées dans 0–90°, trois références au même octet de style accessible en
écriture, appel du getter de couleur vers cette palette, base d'image et sept
cibles de sa table de saut. Une recherche ambiguë est refusée. Les octets des
hooks, les constantes et la table sont revérifiés avant chaque mise à jour.
Les profils privés des hubs, du personnel, de la neige et des autres ponts
conservent leurs contrôles spécifiques ; un changement exige leur revue.

Dans la console UE4SS, `custommap_compatibility` affiche les fonctions installées
et les motifs d'indisponibilité. L'API
`api.game:get_trail_rating_capabilities()` permet au script d'une carte de
choisir un repli vers les règles natives. Une capacité détectée n'accorde pas
la qualification complète du build.

## 1. Contrôles avant lancement

Le contrat versionné est [game-contract.json](../compatibility/game-contract.json).

| Contrôle | Ce qu'il détecte |
| --- | --- |
| Identité Steam et PE x64 | Mauvaise installation, binaire illisible, changement de build et empreinte. |
| Garde et sources du helper | Contrat périmé après une modification du C, de ses en-têtes ou de la DLL. |
| Hubs et rebuild différé | Points d'entrée déplacés, prologues ou instructions de lot modifiés. |
| Personnel | Fonction de vivier et accès aux paramètres modifiés. |
| Skiabilité et noms géographiques | Query, mémo, FText ou insertion de noms incompatibles. |
| Navigation | Absence ou ambiguïté des signatures recherchées ; la vérification du propriétaire reste effectuée par le helper lors du chargement. |
| Empreintes de bâtiments | Point d'entrée de reconstruction des terrassements ; le helper vérifie aussi le code complet et les champs privés avant tout appel. |
| Neige CPU | Gardes d'accès aux tuiles absentes, y compris le cas où le helper retourne silencieusement « pas de mesure ». |
| Notation des pistes | Code, constantes, références, cache et table de saut incohérents ou ambigus ; relocalisation contrôlée des fonctions reconnues. |
| Ressources et paquets | Blueprint/matériau supprimé, archive invalide ou mauvaise identité/version de carte ou de dépendance. |

Les gardes sont lues dans les sections du fichier PE avec contrôle de leurs
permissions. Les gardes `rva` restent liées à leur adresse revue ; un candidat
retrouvé ailleurs est un indice de diagnostic. Les gardes `normalized_unique`
recherchent une empreinte de code dans les sections exécutables, en neutralisant
uniquement les opérandes d'adresse relatifs explicitement revus. Les instructions,
champs privés, constantes et branches internes restent vérifiés. Un résultat
absent ou ambigu est refusé ; le wrapper différé des hubs doit aussi pointer
vers la reconstruction reconnue. Le helper et le précontrôle utilisent les
mêmes descripteurs, générés depuis le contrat avec `python3 -m tools.native_layouts`.
Les gardes `unique` de navigation et `rating_semantic` de notation acceptent les
recherches prévues par leurs résolveurs, avec leurs validations supplémentaires.
Le protocole lit l'exécutable sans le modifier et ne réécrit aucun profil.

Pour les ressources, le script utilise le `retoc` local déjà construit sous
`build/nanite/retoc-target/release/retoc`, ou celui indiqué avec `--retoc` :

```sh
python3 tools/check_game_compatibility.py --retoc /chemin/retoc
```

Le catalogue courant conserve les noms des ressources du build 26019240 ;
les captures antérieures 25996759 et 25970577 restent archivées.
Les rapports suivants permettent aussi de comparer les hashes de contenu :

```sh
python3 tools/check_game_compatibility.py --previous build/compatibility/essai-precedent/report.json
```

Les limites de qualification du build 25996759 restent décrites dans
[son rapport](game-update-25996759.md), notamment pour le rendu et certaines
positions restaurées. Elles restent à vérifier lors d'une nouvelle revue.
Le [premier rapport du build 26019240](game-update-26019240.md) décrit les
obstacles de la qualification initiale. La [revue neige de 1.24.2](buildings-snow-26019240.md)
explique leurs causes, le correctif et la nouvelle qualification.
La [revue du build 26040817](game-update-26040817.md) décrit les nouveaux
profils natifs, la migration des panneaux et la qualification de 1.24.3.
La [revue du build 26056171](game-update-26056171.md) couvre les nouveaux profils,
les options de sandbox et les contrôles du navigateur de 1.24.5.
La [revue du build 26071000](game-update-26071000.md) décrit les relocalisations
de 1.24.6 et l’avertissement de version dans Custom Map.

## 2. Contrôles UE4SS dans une copie isolée

```sh
python3 tools/check_game_compatibility.py --live --output build/compatibility/mon-essai
```

Le script copie l'exécutable, UE4SS et le chargeur dans ce dossier, neutralise
les chemins de mods externes et conserve seulement le chargeur de test. Les
ressources volumineuses du jeu sont reliées en lecture depuis l'installation.
Les archives testées sont copiées dans `packages/`. Le lancement utilise le
Proton sélectionné pour ce jeu et un jeton de session unique.

`-UserDir` sépare les réglages. Le jeu conserve ses sauvegardes dans
`LocalAppData` même avec cette option : sous Linux, chaque essai utilise donc
son propre préfixe Proton dans `compatdata/`. Avant tout chargement de carte,
la sonde demande au jeu son **vrai dossier de sauvegarde** et vérifie le marqueur
unique créé dans ce préfixe pour cet essai. Un marqueur absent ou périmé bloque
les chargements. Sous Windows, un dossier natif hors de `userdata/` reste bloquant.
La fermeture et les délais ne ciblent que le processus créé
par cet essai ; aucune partie déjà ouverte n'est arrêtée.

La sonde vérifie d'abord les classes, les types de propriétés et les paramètres
des UFunctions utilisés. Elle écrit un heartbeat et un inventaire de réflexion.
Si le contrôle natif préalable a échoué, elle reste dans ce mode diagnostic :
les cartes ne sont pas lancées avec des adresses périmées.

Lorsque les prérequis passent, Super Saint-Bernard puis Veymont sont chargées
dans le même processus. Pour chacune :

1. Attendre la fin réelle du chargement et la fermeture de son écran.
2. Compter bâtiments, décorations, remontées, pistes, hubs, employés et arbres.
3. Vérifier les variantes des panneaux, leurs maillages et leur sérialisation native.
4. Capturer l'état et une image, puis forcer le GC Unreal.
5. Attendre 15 secondes et vérifier le monde, la heightmap, les effectifs,
   les GUID, les noms, les positions et les variantes ; capturer à nouveau.

Les effectifs de référence sont déclarés avec la version exacte de chaque carte
dans le contrat. Un délai dépassé, un retour au menu, une exception, un dump de
crash ou un résultat manquant reste un échec. Le processus est fermé à la fin.
`--timeout` borne l'essai complet (900 secondes par défaut).

## 3. Revue du rendu et sauvegarde/rechargement

Après correction des prérequis, garder la copie de test ouverte :

```sh
python3 tools/check_game_compatibility.py --live --interactive --output build/compatibility/revue
```

Elle ne reste ouverte que si les contrôles automatiques ont réussi. Dans sa
console UE4SS, `compatibility_map community.veymont` et
`compatibility_map community.super-saint-bernard` sélectionnent les archives
figées de l'essai. Attendre chaque chargement complet avant les captures.

Pour **chaque carte**, vérifier le relief, les bâtiments, le mobilier, les
panneaux colorés, les lignes de piste et le masquage des arbres. Tester aussi
le menu Custom Map et le retour au menu. Conserver des captures rapprochées
et des vues générales. Une image de relief seule ne valide pas le mobilier.

Piloter l'instance par UE4SS sans activer sa fenêtre. `HighResShot` permet
de capturer le monde ; pour inclure les panneaux UMG, exécuter `Shot ShowUI`
par `KismetSystemLibrary:ExecuteConsoleCommand`, puis récupérer l'image dans
le dossier isolé `userdata/Saved/Screenshots/Windows`. Ne pas utiliser de
capture qui force le focus du bureau.

Pour les bâtiments sous la neige, comparer la même vue avant/après reprise,
avec la profondeur native mesurée et la même position de bâtiment. Garder le
moteur actif, à vitesse de simulation nulle, assez longtemps pour que la
caméra et les déformations GPU se stabilisent avant de figer le checkpoint.
Une forte épaisseur peut masquer normalement le bas d'un bâtiment : une carte
native sert de témoin. Les contours sombres des hubs et les panneaux Expert
peuvent être noirs par choix natif ; un diagnostic de couleur permet de les
identifier. Vérifier séparément leur géométrie et leur occultation.

Les instantanés comptent les acteurs via `GetAllActorsOfClass`, comme le
chargeur. `FindAllOf` énumère aussi des enveloppes d'acteurs déjà détruits,
encore valides comme UObjects avant le GC. Leur exclusion ne doit pas masquer
la disparition d'un acteur vivant ni assouplir les contrôles de GUID/position.

Pour chaque cycle de sauvegarde :

1. Dans la copie isolée, produire un état reconnaissable : variant de panneau,
   objet déplacé ou retiré, règle de scénario ou avancement enregistré.
2. Exécuter `compatibility_snapshot community_veymont_before` (ou
   `community_super_saint_bernard_before`). La sonde gèle la partie et écrit
   `review/<label>.json` ainsi qu'une image.
3. Enregistrer réellement un **nouveau slot natif de test** dans le menu du jeu,
   relever son nom, revenir au menu et charger ce slot. Ne pas se contenter
   d'appeler `GetSaveData` : cela ne teste pas l'écriture ni la reprise.
4. Après restauration complète, exécuter le même nom terminé par `_after`.
   Vérifier notamment que l'objet supprimé ne réapparaît pas et que les données
   du scénario sont toujours présentes.

Les JSON avant/après doivent conserver le calendrier gelé, les finances, prêts,
état Lua, remontées et neige (tolérance 0,5 cm), ainsi que les effectifs, GUID,
classes, noms, variantes et positions des objets (tolérance 1 cm). Le comparateur
rejette les champs manquants. Les deux cartes sont obligatoires.

Copier `review-template.json` en `review.json`. Pour les deux entrées
`rendering` et `native_save_roundtrip`, renseigner `status` (`pass` ou `fail`),
une note précise et les fichiers de preuve avec leur SHA-256. Les chemins sont
relatifs au dossier de l'essai ; les sorties de ce dossier sont refusées.
Pour les sauvegardes, compléter aussi `roundtrips` avec les deux paires de JSON
et les noms réels des slots natifs. Exemple de référence de fichier :

```json
{"path": "review/community_veymont_before.json", "sha256": "empreinte SHA-256 du fichier"}
```

`sha256sum review/*` permet d'obtenir les empreintes depuis le dossier de
l'essai. Le modèle contient déjà le jeton et les empreintes des binaires :
une revue d'un ancien essai ne peut pas valider le nouveau.

```sh
python3 tools/check_game_compatibility.py --output build/compatibility/revue --review build/compatibility/revue/review.json
python3 tools/check_game_compatibility.py --output build/compatibility/revue --close
```

La seconde commande demande à UE4SS de fermer uniquement cette copie du jeu.

## 4. Décision avant une publication

Corriger les incompatibilités détectées, revoir les signatures et le contrat,
puis refaire un essai neuf. Ne pas changer `TESTED_GAME_BUILDS` sur la seule base
d'un lancement réussi ou d'une signature retrouvée à une autre adresse.
La qualification vise les contrats testés ; elle ne prouve pas l'absence de
tout défaut possible dans le jeu.

Le framework du protocole est contrôlé par la régression habituelle :

```sh
python3 -m unittest tests.test_game_compatibility
python3 -m unittest tests.test_native_rating_resolver
lua5.4 tests/test_runtime_compatibility.lua
lua5.4 tests/test_compatibility_probe.lua
python3 tests/run_custom_map_checks.py
```

Ces tests simulent notamment des signatures déplacées/ambiguës, une ressource
supprimée, un rapport ancien ou incomplet, un crash, une perte d'objet après GC,
des GUID remplacés et un mauvais maillage de variante. Ils vérifient aussi la
séparation des sauvegardes et des chemins de mods. Ils ne remplacent pas la
qualification réelle du build installé.

La [revue du build 26097896](game-update-26097896.md) documente la qualification
avec 1.24.7 et les essais du téléchargement, de l’installation différée et de la
récupération des mises à jour automatiques.
La [revue du build 26111862](game-update-26111862.md) décrit la relocalisation
automatique contrôlée introduite en 1.24.9.
