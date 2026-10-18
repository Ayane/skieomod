# Mise à jour du jeu 25996759

Le correctif skieomod **1.20.13** adapte le module natif et le catalogue au
build Steam de la démo `25996759`. Veymont reste en **0.7.7** et Super
Saint-Bernard en **0.2.4** : leurs archives ne changent pas.

Les points d'entrée des hubs, des noms géographiques, du personnel et de la
skiabilité ont changé. Les profils précédents restent présents ; les appels
natifs exigent toujours les signatures du profil choisi.

| Donnée native | Modification contrôlée |
| --- | --- |
| Compteur de regroupement des hubs | `0xA60` → `0xB08` |
| Mémo de skiabilité | `0x19C` → `0x1B4` |
| Entrée du cache CPU de neige | 48 → 56 octets |
| Drapeau de disponibilité de cette entrée | `0x24` → `0x28` |
| Sous-système du personnel | taille `0x680` → `0x688`, éléments de recrutement toujours de `0x518` octets |

La reprise d'une sauvegarde réenregistre les sources des hubs après l'alignement
des bâtiments et remontées sur le terrain reconstruit. Le chargeur maintient le
multiplicateur de temps à zéro pendant cette reconstruction, puis rétablit sa
valeur précédente. La pause du calendrier seule laisse des simulations natives
actives. Les mesures QA comparent le multiplicateur demandé, plutôt que sa
valeur transitoire pendant une pause.

`BP_StringLights` a disparu des ressources du jeu. Cette classe est retirée des
catalogues Python et Lua ; aucune des deux cartes ne l'utilise. L'inventaire du
nouveau conteneur comporte 2 371 assets contre 2 391 dans l'inventaire précédent.
Une partie des différences correspond à des changements de casse de chemins.

La régression comprend **248 tests Python et 68 fichiers Lua**. Les nouveaux
tests exécutent les fonctions C de production dans une mémoire de jeu simulée :
ils vérifient l'emplacement exact de l'écriture du mémo, le maintien de l'ancien
profil, le parcours des cases libres du cache de neige et le refus des gardes,
classes, bornes ou états de disponibilité incorrects. Le lecteur de neige ne
modifie pas les données inspectées.

Les essais du jeu utilisent UE4SS et un préfixe Proton distinct. Le jeu ignore
`UserDir` pour ses sauvegardes natives : le protocole vérifie donc un marqueur
unique dans son vrai dossier de sauvegarde. Les rapports et captures de travail
se trouvent dans `build/compatibility/25996759-final-validation/`.

Sur les deux cartes, le chargement, les variantes, le maintien des objets après
GC et la lecture CPU de neige passent. Les reprises natives conservent exactement
le calendrier, les finances, la dette, le scénario, le fonctionnement des remontées
et la neige aux terminaux. Les comptes de bâtiments, décorations, remontées,
pistes, hubs, employés et arbres sont également conservés.

Le contrôle strict de l'état du monde reste en échec : le jeu remplace certains
libellés de mobilier vides par leur nom de type et modifie le Z de l'origine de
certaines remontées de moins de 40 cm après reprise. Ces écarts restent visibles
dans le rapport ; le correctif du chargement ne vaut pas une qualification complète.

Le [protocole de qualification](game-compatibility-testing.md) conserve les
contrôles de rendu et de sauvegarde/reprise séparés. Une mesure manquante ne
vaut pas une validation. Le défaut de rubans noirs observé sur le build précédent
reste une réserve visuelle, et ne constitue pas une référence de rendu acceptable.
