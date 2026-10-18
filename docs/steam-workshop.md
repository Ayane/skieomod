# Steam Workshop

Le catalogue communautaire reste publié sur le web avec `skieomod publish`
et consultable directement dans **New Game → Custom Map**, avec les filtres
Local / Web et la recherche. Le domaine par défaut est `skieomod.emillon.fr`.
Les cartes Featured restent disponibles dans le même menu.

Steam Workshop est en préparation. `publish --prepare` crée le contenu hors
ligne ; `publish --steam` sélectionne explicitement le futur client natif.
Le [guide de publication web](custom-map-repository.md) décrit le parcours actuel.

## État du raccordement

Les modèles, les compilations locales, la préparation d’une publication et les
contrats de l’interface en jeu sont disponibles. Le client natif Steamworks
n’est pas livré : il reste à raccorder lorsque le développeur aura fixé son
intégration Workshop. Les tests n’effectuent aucune publication Steam réelle.
L’interface signale cette absence et peut lire le contenu déjà installé par Steam.

Le jeu complet utilise l’AppID `4493130`, la démo `5012760`. Un projet cible par
défaut le Workshop du jeu complet. Le setup lit celui du jeu détecté ;
`--workshop-app-id` permet de choisir explicitement un autre Workshop si le
développeur confirme cet accès. L’accès de la démo au Workshop du jeu complet
n’est pas supposé.

## Contenu et dépendances

Un article contient un seul `custom-map.json` ou `custom-mod.json` à sa racine
et ses ressources décompressées. `SetItemContent` reçoit ce dossier : les
archives ZIP restent des artefacts de compilation locale.

Un `mapmod` est un mod `runtime: "map-api"`, exécuté dans la session de la carte
avant son script. Un mod `runtime: "ue4ss"` doit être enregistré au démarrage ;
son téléchargement seul ne suffit pas à activer son script.

```json
{"dependencies":[{"id":"author.snow-tools","version":"^1.0.0","workshop_id":"1234567890"}]}
```

`id` identifie le paquet, `version` vérifie la compatibilité du contenu installé
et `workshop_id` identifie l’article Steam. Les identifiants 64 bits restent des
chaînes décimales dans JSON/Lua. Une dépendance requise doit posséder un ID
Workshop avant publication ; une dépendance optionnelle ne devient pas un
article obligatoire. Deux éditeurs publiant le même nom de paquet ne sont pas
interchangeables lorsqu’une dépendance désigne cet ID Steam.

Le client publie les liens `AddDependency`, qui restent des dépendances souples.
Le chargeur impose lui-même leur téléchargement et la compatibilité des paquets,
refuse les cycles et limite la fermeture à 64 articles. Il ne promet pas de
télécharger une ancienne version sémantique sur Steam.

## Informations du menu

| Champ | Source / disponibilité |
| --- | --- |
| Titre, description | `GetQueryUGCResult`, texte de l’article |
| Propriétaire | `m_ulSteamIDOwner`, indépendant des crédits libres `metadata.authors` |
| Pseudo, avatar | Facultatifs via `ISteamFriends` ; SteamID affiché si le pseudo manque. L’avatar est prévu dans le contrat, pas rendu actuellement |
| Mise à jour | `m_rtimeUpdated` |
| Votes | `m_unVotesUp` / `m_unVotesDown`, masqués si absents |
| Tags | Tags de l’article ; `map`, `mod`, `mapmod` distinguent les créations |
| Taille | Contenu Workshop / `GetItemInstallInfo`, pas la taille du ZIP |
| Articles requis | `GetQueryUGCChildren` et manifeste téléchargé |
| Abonnement, état, mise à jour | `GetItemState` |
| Progression | `GetItemDownloadInfo` |
| Terrain et aperçu filaire | Manifeste installé, masqués avant téléchargement |
| Version du paquet | Manifeste local ; cette version ne prétend pas être une version Steam |
| Commentaires et discussions | Page de l’article ouverte dans Steam |

Le menu propose **Maps / Mods**, **Refresh Workshop**, **Workshop page**, puis
**Subscribe**, **Update** ou **Play** selon l’état. Les contrôles sont désactivés
pendant le téléchargement. Une erreur conserve le dernier catalogue valide.
Sans client, l’inventaire ACF de Steam permet de lire les installations locales
mais pas d’affirmer l’abonnement ou l’absence de mise à jour : ces champs sont masqués.

## Client natif du CLI

`skieomod --steam-client CHEMIN config` mémorise un exécutable utilisant la
session Steam locale. Il lit une requête JSON sur stdin et répond sur stdout,
sans shell, ni mot de passe ni jeton du site. Steam OpenID n’est pas une session
Steamworks. Le schéma est [workshop-client.schema.json](../schemas/workshop-client.schema.json).
Si un outil Steam séparé fournit ce client, son AppID devra être autorisé dans
les paramètres « App Publish Permissions » du Workshop du jeu ; les quotas
Cloud des aperçus doivent aussi être configurés par le développeur.

Toutes les requêtes et réponses incluent `format: "skieomod-workshop"`,
`version: 1` et `app_id` sous forme de chaîne. Les réponses incluent `ok` et le
même AppID ; les erreurs incluent `error`. Le client attend la fin des opérations
asynchrones avant de répondre et respecte le délai de 15 minutes du CLI.

| Méthode | Requête | Réponse / responsabilités |
| --- | --- | --- |
| `query` | `kind`, `search`, `page` à partir de 1 | `items`, `has_more`, métadonnées et enfants |
| `install` | `published_file_id`, `include_required_items: true` | Abonner, télécharger, valider la fermeture et enregistrer les mods au démarrage ; signaler le redémarrage nécessaire |
| `play` | Mêmes champs | Installer la carte et ses dépendances puis lancer le jeu ; refuser un article qui n’est pas une carte |
| `publish` | ID (`"0"` pour créer), chemins absolus, titre, description, tags, métadonnées, visibilité, note, articles requis | ID publié, `needs_legal_agreement` ; attendre la création/mise à jour et la synchronisation des liens requis |

Les réponses `install` et `play` retournent aussi le `published_file_id` demandé,
pour éviter de valider par erreur l’opération d’un autre article.

Le publisher utilise `CreateItem`, `StartItemUpdate`, les méthodes `SetItem…`,
`SubmitItemUpdate`, puis `AddDependency` / `RemoveDependency` pour synchroniser
la liste requise. Il attend les résultats et vérifie les droits du compte. Un
nouvel ID est conservé même si l’accord Workshop doit encore être accepté ;
un échec de mise à jour ne doit pas créer un nouvel article.

`SetItemMetadata` contient un résumé inférieur à 5000 octets, pas le terrain :

```json
{"format":"skieomod","version":1,"kind":"mod","id":"author.tools","package_version":"1.0.0","runtime":"map-api"}
```

L’image PNG/JPG/GIF de moins de 1 Mio est séparée du contenu. La visibilité
initiale est privée. Le VDF fourni aide aux tests SteamCMD pour développeurs :
il ne publie pas les métadonnées UGC, les tags ni les dépendances, et ne remplace
donc pas le client complet. Les joueurs utilisent Steam.

## Adaptateur en jeu

Le jeu ou un module natif expose `_G.SkiEOWorkshop` avant le chargement du mod,
ou appelle `require("workshop").bind(adapter)`. Il fournit `version = 1`,
`app_id` et les méthodes suivantes, appelées avec `self` :

| Méthode | Contrat |
| --- | --- |
| `query(options, callback)` | `page`, `kind`, `search`, `return_metadata`, `return_children` ; callback `(result, error)` avec `app_id`, `items`, `has_more` |
| `get_details(id, callback)` | Callback `(item, error)` pour une dépendance absente du catalogue |
| `subscribed_items()` | Tableau d’IDs abonnés et activés localement, obtenu via Steam |
| `get_item_state(id)` | Booléens `subscribed`, `installed`, `needs_update`, `downloading`, `download_pending` ; octets facultatifs `bytes_downloaded`, `bytes_total` |
| `get_install_info(id)` | `{folder, size_bytes, updated_at}`, installation complète uniquement |
| `subscribe_item(id, callback)` | Attendre `RemoteStorageSubscribePublishedFileResult_t`, puis `{app_id, published_file_id, result}` (`1` pour succès) |
| `download_item(id, callback)` | Attendre `DownloadItemResult_t` ; vérifier AppID/ID/résultat ; le booléen de `DownloadItem` n’est pas une fin de téléchargement |
| `open_workshop(id)` | Facultatif, article ou catalogue dans l’overlay Steam |

Un article contient `published_file_id`, `app_id` consommateur, `result`, `kind`,
`title`, `description`, et éventuellement `metadata`, `banned`, `owner_steam_id`,
`owner_name`, `avatar_url`, `updated_at`, `votes_up`, `votes_down`, `size_bytes`,
`tags`, `required_items`.

L’adaptateur gère les handles, `ReleaseQueryUGCRequest`, les délais d’expiration
et la livraison des callbacks sur le thread du jeu. Il respecte les articles
désactivés localement. L’enregistrement au démarrage des mods UE4SS reste à
raccorder ; le mod indique cette nécessité au lieu d’annoncer une activation.

Références : [ISteamUGC](https://partner.steamgames.com/doc/api/ISteamUGC),
[guide Workshop](https://partner.steamgames.com/doc/features/workshop/implementation).
