# Mise à jour du jeu 26019240

Le correctif skieomod **1.24.1** adapte les ponts natifs au build Steam de la
démo **26019240**. Le verdict de qualification reste **incompatible** tant que
le contrôle visuel échoue. Le démarrage réussi ne suffit pas à annoncer cette
révision comme entièrement compatible ; `TESTED_GAME_BUILDS` reste inchangé.

Les archives de Super Saint-Bernard **0.2.4**, Veymont **0.7.7** et Foxes
**0.4.0** ne changent pas. Les essais emploient une copie du jeu, un préfixe
Proton distinct et un marqueur vérifié dans le vrai répertoire des sauvegardes
natives. Ils ne modifient pas les sauvegardes de la partie habituelle.

## Ponts natifs

Les adresses des fonctions des hubs, du personnel, des noms géographiques,
de la neige et de la skiabilité ont changé. Les profils précédents restent
présents. Les signatures ne sont pas élargies et les gardes de classe,
de taille et de disponibilité restent obligatoires.

La revue compare les corps de fonctions avec le binaire précédent, en
neutralisant seulement les déplacements des appels, des branches et des
références RIP. Les lectures de champs conservent les mêmes offsets :
compteur des hubs `0xB08`, mémo de skiabilité `0x1B4`, entrée du cache CPU
de neige de 56 octets et drapeau prêt à `0x28`, sous-système du personnel
de `0x688` octets et éléments de recrutement de `0x518` octets.

La navigation et les couleurs/difficultés des pistes continuent d'utiliser
leurs résolveurs sémantiques. Les gardes statiques passent sur le nouveau
binaire. Les tests C vérifient aussi que les anciens profils fonctionnent
et qu'un mauvais profil ne lit ou n'écrit pas les données visées.

| Empreinte SHA-256 | Valeur |
| --- | --- |
| Exécutable du jeu | `209da968636fc41034da8e74805c9419636d446c0a13a2e70dbc706835e9a3e6` |
| Conteneur UTOC | `7900826a4dabc357eb8cb22a065c19f44d1e73b2413c72c482ef2c9b32a39e32` |
| Module natif du chargeur | `6e64722cf6867b663678fcec6799e4c91d70414c08d816efae34204c6ec7ff3b` |

L'inventaire passe de **2 371 à 2 377 ressources** : 20 ajouts, 14 suppressions
et 357 contenus modifiés. Aucune ressource requise par le contrat ne manque.
Les inventaires versionnés contiennent des noms et empreintes, aucun asset du jeu.

## Résultats des essais

La régression exécute **272 tests Python** (dont un test Qt ignoré faute de
PySide6 dans l'environnement) et **70 scripts Lua**, sans échec. La distribution
1.24.1 passe aussi l'installation isolée, la construction des projets modèles,
la préparation Workshop, la vérification de l'archive du chargeur et la désinstallation.

Les contrôles automatiques de la session isolée passent : réflexion native,
isolation des sauvegardes, chargement des deux cartes, variantes des panneaux,
maintien des identifiants et des objets après GC et absence d'erreur des ponts natifs.
Le menu intégré passe également les filtres All / Local / Web / Steam, la
recherche de Veymont, l'état vide sans bouton Play actif et le retour de la
liste après effacement du texte. Les capacités natives de difficulté, de
style et de couleur des pistes répondent toutes positivement.
Les comptes initiaux sont les suivants, avant la suppression volontaire d'un
banc par carte pour tester sa persistance :

| Carte | Bâtiments | Décorations | Remontées | Pistes | Hubs | Employés | Arbres |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Super Saint-Bernard 0.2.4 | 5 | 14 | 2 | 4 | 3 | 10 | 0 |
| Veymont 0.7.7 | 13 | 54 | 9 | 20 | 11 | 22 | 383 500 |

Les deux reprises passent les comparaisons du calendrier figé, des finances,
de la dette, des prêts, de l'état Lua, des remontées et de la neige aux
terminaux. Tous les objets placés conservés ont les mêmes identifiants,
libellés, variantes et positions. Le contrôle brut du monde et la revue
visuelle gardent néanmoins le verdict défavorable décrit ci-dessous.

Le rapport final local est conservé dans
`build/compatibility/26019240-qualification/report.md`, avec ses JSON,
captures rapprochées et larges, sauvegardes natives et empreintes d'artefacts.
Il contient **41 contrôles passants et deux revues en échec**. Le contrat
de qualification et les tolérances n'ont pas été assouplis.

## Sauvegardes

Le premier essai reproduit les écarts déjà signalés sur 25996759 : le jeu
remplace les libellés vides de meubles par leur nom de type, et recale
l'origine de certaines remontées sur son heightfield quantifié.

Le chargeur copie désormais les libellés et les origines depuis les données
réfléchies de la sauvegarde sélectionnée, avant leur libération. Il rétablit
les libellés après la reconstruction du terrain. Il restitue également
l'origine des remontées en préservant les transformations mondiales de leurs
composants : les terminaux, câbles, files et pylônes déjà alignés ne bougent pas.
Les noms personnalisés, identifiants et suppressions du joueur restent ceux
de la sauvegarde ; le script de scène ne recrée pas les meubles supprimés.

La comparaison brute de la session finale relève aussi un acteur de banc
désenregistré, avec identifiant et position nuls, encore énuméré après sa
destruction avant le départ vers le menu. Il disparaît après reprise. Ce
résidu ne doit pas être confondu avec un meuble placé perdu ; les mesures
brutes sont conservées et le contrôle strict n'est pas déclaré passant.

## Rendu et verdict

Les vues rapprochées montrent un recouvrement excessif de la station par la
couche de neige procédurale. Masquer cette couche dans la copie de diagnostic
fait réapparaître les parties inférieures des bâtiments. Ce diagnostic n'est
pas un correctif : supprimer la couche sans vérifier les effets sur la neige,
les pistes et leur simulation ne permettrait pas de valider le rendu.

Les rubans noirs autour des pistes/hubs restent également visibles.
Les captures et mesures sont conservées sous `build/compatibility/` ; elles
ne constituent pas une référence de rendu acceptable.

Le [protocole](game-compatibility-testing.md) exige une revue visuelle positive
et deux reprises natives complètes avant le verdict `compatible`. Les seuils
de comparaison restent **1 cm** pour les positions et **0,5 cm** pour la neige.
