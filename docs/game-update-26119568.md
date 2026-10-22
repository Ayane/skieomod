# Mise à jour du jeu 26119568 et Custom Map 1.24.10

La démo Steam installée est le build **26119568**, branche `experts_only`,
AppID `5012760`. Son exécutable porte le SHA-256
`5418c1ae2d0b8d8a12c37af5dae528635bc6f3f96038d4708ab10a534d4f805a`.

## Changements natifs

Le précontrôle de 1.24.9 retrouve automatiquement les noms des hubs, la neige
CPU, les terrassements, les options et la notation des pistes. Il refuse les
fonctions dont le code ou les champs ont changé. Cette mise à jour demande
donc une adaptation de structures, au-delà d'un déplacement d'adresse.

- Le compteur de regroupement des hubs passe de `+0xB60` à `+0xB50`.
  L'indicateur de couverture est désormais à `FHubMemberInfo +0x69`, juste après
  la routabilité. La structure fait `0x80` octets et ses entrées de conteneur
  passent de `0xA0` à `0x98` octets. Les identités, positions, dimensions,
  propriétaires, noms et identifiants de hub gardent leurs champs réfléchis.
- Les registrations des bâtiments et remontées sont recompilées avec des piles
  plus petites. Le mod continue d'utiliser ces fonctions natives pour construire
  leurs membres, au lieu de fabriquer les nouvelles structures lui-même.
- Les candidats du personnel passent de `0x528` à `0x578` octets et le RNG de
  `+0x680` à `+0x684`. Les réglages restent à `+0x508`, le vivier à `+0x4D8`.
- La navigation déplace son compteur de travail à `+0x580` et son indicateur
  de terrain modifié à `+0x870`. Le résolveur exige cette paire cohérente.
- La requête de skiabilité utilise les nouveaux champs des membres de hubs ;
  son mémo reste à `+0x1B4`.

La lecture des propriétés UE4SS confirme les champs réfléchis des membres de
hubs et du personnel dans une première session isolée, sans chargement de carte
ni appel aux ponts refusés. Les instructions de copie, d'insertion et de
reconstruction confirment les tailles et les champs privés modifiés.

Les gardes de registration couvrent les fonctions complètes revues : 436 octets
pour les bâtiments, 914 pour les remontées et 717 pour le vivier du personnel.
Les opérandes d'adresse examinés sont toujours les seuls éléments neutralisés.
La cible du wrapper différé est vérifiée indépendamment. Les anciens profils
restent disponibles ; le bootstrap de mise à jour garde son ABI stable.

Les 17 descripteurs du nouveau profil retrouvent chacun une cible unique. Le
précontrôle de changement de terrain utilise désormais, comme le helper, une
recherche unique pour le handler reconnu, sans imposer son ancienne adresse.

## Vérifications

Les **304 tests Python et 80 scripts Lua**, ainsi que les **15 essais de jobs
de terrain Windows**, passent avec les sources et la DLL finales ; un test
optionnel est ignoré.

La qualification finale est **compatible : 46 contrôles sur 46 passent**.
Super Saint-Bernard et Veymont sont chargées, sauvegardées sur disque puis
reprises par le vrai menu, avec leur état, leurs 20 et 75 objets respectifs,
leurs variantes et les modifications du joueur conservés après GC.

Les huit vues actives et le cycle de neige 0 / 120 / 300 / 120 cm sont revus.
Le placement d'un bâtiment et les reconstructions répétées des terrassements
passent. Un appel explicite au wrapper de reconstruction des hubs conserve les
compteurs, avec les identités, positions et dimensions correctement lues dans
les nouvelles entrées. Les deux remontées fonctionnent après reprise de la
simulation. Les contacts des visiteurs et leurs traces sont examinés après
reprise de l'horloge : une vue à horloge figée après restauration peut encore
montrer des positions de visiteurs en attente de mise à jour native.

Le catalogue HTTPS réel, les rafraîchissements, filtres, recherche, auteurs,
légendes et empilement du panneau Options passent. Le sandbox, la durée du
jour et les jours par mois survivent à une sauvegarde native et à sa reprise.
Le vrai exécutable est reconnu ; une identité inconnue injectée seulement dans
la revue du bandeau confirme son texte dès la première image visible.

La sauvegarde du build 26040817 conserve son état strict et ses 20 objets.
Seuls les trois ajustements verticaux déjà introduits en 1.24.8 sont présents,
exactement conformes aux différences mesurées entre source et terrain affiché.
Kitzbühel 0.1.2 est également revue avec une station et trois tables à
20 / 120 / 0 cm de neige. Tous les essais utilisent UE4SS dans Gamescope
headless, sans activer de fenêtre du bureau.

La qualification et les captures sont conservées dans
`build/compatibility/26119568-1.24.10-final-v1/` ; la revue native et les
résultats des tests sont sous `build/update-26119568/`.
