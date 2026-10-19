# Mise à jour du jeu 26056171 et Custom Map 1.24.5

La démo Steam installée est le build **26056171**, branche `experts_only`,
AppID `5012760`. La qualification porte sur le chargeur **1.24.5**,
Super Saint-Bernard 0.2.4, Veymont 0.7.7 et Foxes 0.4.0.

## Ponts natifs

Le contrôle initial refuse les anciens points d’entrée. La revue compare les
instructions des deux exécutables, en distinguant les déplacements d’appels
des changements de champs privés :

| Fonction | Adaptation |
| --- | --- |
| Hubs | Nouveaux points d’entrée et compteur de lot déplacé de `+0xB08` à `+0xB10`. |
| Navigation | Compteur de travail à `+0x570`, drapeau terrain à `+0x860`. Le résolveur vérifie aussi l’instruction du compteur pour distinguer deux builds ayant le même prologue. |
| Personnel, skiabilité, noms et neige CPU | Points d’entrée revus ; les accès utiles aux champs restent identiques. |
| Terrassements | Nouveaux points d’entrée et empreintes exactes des 2 088 et 267 octets de reconstruction/nettoyage. |

Les anciens profils sont conservés. La notation des pistes garde son résolveur
contrôlé. Aucune garde n’est remplacée par une recherche permissive.

Le nouveau transfert des options vérifie la classe du sous-système de session,
ses champs réfléchis et une signature exacte et unique de l’affectation native.
Il écrit seulement les réglages revus de la prochaine partie. Des tests C
vérifient les bornes, les valeurs invalides et la conservation des octets voisins.
La signature est aussi présente dans les copies conservées de 26040817 et 26019240.

## Options et navigateur

**Options** réutilise le panneau du jeu pour le sandbox, la durée du jour et le
nombre de jours par mois. Les valeurs sont copiées avant un éventuel téléchargement.
Les terrains personnalisés gardent leurs dimensions ; le réglage de génération
Diorama des cartes natives n’est donc pas proposé.

Le sandbox active le mode natif et désactive les objectifs, les dépenses et les
restrictions d’installation des scénarios scriptés. Le mode est relu depuis la
vraie sauvegarde native lors d’une reprise. Les autres parties conservent leurs
objectifs et leur économie.

Les couches Custom Map et les onglets restent sous le panneau Options, et leurs
contrôles sont désactivés pendant son ouverture. La revue visuelle vérifie aussi
les titres des prévisualisations, les noms et icônes des lignes et l’auteur placé
directement sous le titre de la carte.

Le catalogue est consulté automatiquement à l’ouverture, puis au plus toutes les
cinq minutes pendant la consultation. Une requête déjà active ou un lancement
de carte reste prioritaire. Les échecs conservent le cache et respectent le même
délai. Les cartes web téléchargées restent dans **Web**, avec une coche ; **Local**
regroupe les projets locaux et les installations manuelles.

## Vérifications

Le [protocole](game-compatibility-testing.md) est exécuté dans une copie isolée,
avec un préfixe Proton, un identifiant et des sauvegardes propres à chaque essai.
Le résultat est **compatible** : **46 contrôles passent**, complétés par les
essais du navigateur, du sandbox et de l’ancienne sauvegarde. Les **293 tests
Python et 76 scripts Lua** passent également. Le cycle final est conservé sous
`build/compatibility/26056171-1.24.5-final-v2/`.

- Chargement des deux cartes, effectifs et variantes, puis GC Unreal.
- Sauvegardes natives écrites sur disque et rechargées par le menu du jeu.
  État du scénario, économie, neige, remontées, GUID, positions et noms comparés ;
  un banc supprimé reste absent et un porte-skis renommé conserve son nom.
- Huit vues actives rapprochées et générales des bâtiments, du mobilier,
  des panneaux et du relief. Cycle de neige 0 / 120 / 300 / 120 cm,
  placement d’un bâtiment, reconstructions répétées sans doublons et reprise
  de la simulation avec des remontées opérationnelles.
- Catalogue web réel, rafraîchissement initial puis échéance périodique,
  filtres Local/Web et recherche d’une carte publiée.
- Panneau Options réel, puis lancement sandbox depuis Custom Map. Une troisième
  sauvegarde native conserve le sandbox, une durée de jour de **1,5×** et
  **3 jours par mois**, également vérifiés après reprise.

Une sauvegarde créée avec **1.24.3 sur 26040817** est aussi rechargée : les
20 acteurs, leurs GUID, noms, variantes et positions ainsi que l’état du scénario
et de l’économie sont conservés. Elle reste une partie normale après le sandbox.

Les premières captures de travail sont conservées séparément du cycle final.
La publication utilise les mêmes fichiers Lua et DLL que la version figée.
