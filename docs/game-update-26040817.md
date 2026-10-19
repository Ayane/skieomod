# Mise à jour du jeu 26040817

La démo Steam installée le 19 octobre 2026 est le build **26040817**, branche
`experts_only`. La revue porte sur le chargeur **1.24.3** et les archives
Super Saint-Bernard 0.2.4, Veymont 0.7.7 et Foxes 0.4.0 du contrat.

## Changements natifs

Le contrôle initial de 1.24.2 refuse dix-sept gardes à leurs anciennes
adresses. Les points d'entrée revus concernent les hubs, leur reconstruction
différée, le personnel, la skiabilité, les noms géographiques, la neige CPU
et les empreintes de terrassement des bâtiments. Les profils précédents sont
conservés ; les gardes ne sont pas remplacées par une recherche permissive.

La comparaison du code désassemblé conserve les instructions et les accès aux
champs privés en neutralisant les déplacements des appels et références RIP.
Le générateur de personnel déplace son état aléatoire de `+0x67c` à `+0x680` ;
le mod appelle toujours la routine native, sans écrire cet état. Les champs de
réglages et du vivier gardent leurs positions revues. Le wrapper différé des
hubs conserve le compteur `+0xb08` et pointe vers la nouvelle reconstruction.

Les **2 088 octets** d'enregistrement des terrassements et les **267 octets**
de nettoyage gardent leur code normalisé ; leurs nouvelles empreintes exactes
sont enregistrées dans le helper. La navigation et les trois fonctions de
notation des pistes suivent déjà leurs résolveurs contrôlés, sans modification.

Le catalogue de ressources contient **2 379 entrées**. Aucune ressource exigée
par le contrat n'a disparu. Par rapport à 26019240, quatorze renommages ne
changent que la casse des dossiers de textures, deux maillages de panneaux
sont ajoutés et dix-huit ressources communes ont une empreinte différente.

## Variantes de panneaux et anciennes sauvegardes

Le premier chargement réel révèle une incompatibilité que les seuls points
d'entrée ne détectent pas : les anciens identifiants de panneaux ont été
remplacés dans le Blueprint natif.

| Ancien identifiant des cartes | Identifiant natif de 26040817 |
| --- | --- |
| `Beginner` | `GreenCircle` |
| `Intermediate` | `BlueSquare` |
| `Expert` | `BlackDiamond` |

Le chargeur consulte les variantes réellement disponibles sur l'acteur et ne
traduit ces noms que pour la classe des panneaux, lorsque l'ancien nom est
absent et son remplacement présent. Sur les anciens builds, les identifiants
natifs précédents restent utilisés. Une variante inconnue reste une erreur.

La même résolution sert aux scènes et aux modifications d'instances. Lors
d'une reprise, le chargeur copie aussi la variante du `CustomData` natif avant
le changement de monde, puis la réapplique à l'acteur restauré. La lecture
couvre le TMap réfléchi des vraies sauvegardes et les tables retournées par les
fonctions de sérialisation. Aucun identifiant d'acteur, maillage ou contenu
de sauvegarde n'est réécrit par accès mémoire privé.

## Liste des cartes inaccessible

L'installation habituelle utilisait encore **1.23.0**, avec
`https://skieomap.emillon.fr` dans `repositories.json`. La requête de catalogue
reçoit un HTTP **308** vers le domaine canonique. Le helper WinHTTP installé
refuse les redirections, d'où l'échec de la liste ; le serveur et son certificat
HTTPS fonctionnent normalement.

Un exécutable de diagnostic appelle la même DLL sous le Proton sélectionné :
l'ancienne URL échoue sur une réponse différente de 200, tandis que l'API et
le catalogue fourni sur `https://skieomod.emillon.fr` réussissent. Le test dans
le jeu charge ensuite une configuration des deux catalogues avec l'ancien
domaine : la migration déjà présente depuis 1.24.2 utilise le domaine canonique,
sans erreur, et retrouve les trois cartes publiées et les trois paquets fournis.
Le panneau réel **New Game > Custom Map** est ensuite contrôlé : neuf entrées
dans All, quatre dans Web, et la recherche `kitz` sélectionne uniquement
`reyman.kitzbuehel`. Les assertions UMG et une capture de la fenêtre du jeu
confirment le filtre, la recherche et la fiche, sans erreur de dépôt.

La mise à jour du chargeur conserve la configuration, les cartes et les
sauvegardes, avec une copie des fichiers remplacés. Elle s'effectue jeu fermé :

```sh
skieomod update
```

## Preuves

Les diagnostics et désassemblages restent sous `build/update-26040817/`.
Les essais interrompus restent séparés ; leur existence ne valide pas le build.
Le dernier cycle utilise
`build/compatibility/26040817-1.24.3-final-v2/`, avec son propre préfixe Proton,
ses sauvegardes, son jeton et ses empreintes. Le
[protocole complet](game-compatibility-testing.md) donne **compatible** :
**45 contrôles passent**, avec deux reprises natives et huit vues actives
contrôlées. Les comparaisons strictes avant/après ne trouvent aucun écart.
Veymont conserve notamment ses **383 500 arbres**.

Le cycle de neige **0 / 120 / 300 / 120 cm** conserve la position du bâtiment.
Le placement d'un nouveau bâtiment passe par le callback de production ; trois
reconstructions supplémentaires ne dupliquent ni terrassement ni bloqueur.
La simulation reprend ensuite avec des remontées opérationnelles. Les gardes,
les exigences de preuves et les tolérances du protocole restent inchangées.

Une sauvegarde native supplémentaire, créée avec 1.24.2 sur **26019240**, est
rechargée dans ce même préfixe isolé. Son calendrier, ses finances, son état Lua,
sa neige et ses vingt objets restent identiques ; les trois identifiants de
panneaux sont traduits comme prévu. Les preuves sont
`review/legacy-26019240.json` et `review/legacy-save-verification.json`.

La régression passe **290 tests Python** et **73 scripts Lua**, dont les tests
de migration des URL et des variantes anciennes, ainsi que le contrôle natif
qui refuse chaque mutation d'un octet du code des terrassements.
