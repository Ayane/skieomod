# Mises à jour du jeu 26141846 / 26143813 et Custom Map 1.24.11

La démo Steam installée est le build **26143813**, branche `experts_only`,
AppID `5012760`. Son exécutable porte le SHA-256
`831667e59b6e64df1baecd543d98c719d5f8219ce1f3ac9648a641887dbe135f`.

Steam a installé la correction **26143813** pendant les essais du build
26141846. Ce dernier avait provoqué un arrêt lors de l'insertion de la forêt
de Veymont ; sa cause n'a pas été établie. Le superviseur a fermé le processus
dès l'apparition du dump, resté vide. Les preuves de ce premier passage sont
conservées dans `build/compatibility/26141846-1.24.11-final-v1/`.
La version annoncée compatible par 1.24.11 cible la nouvelle correction.

## Changements natifs introduits dans 26141846

Le précontrôle de 1.24.10 retrouve automatiquement les ponts dont les
instructions restent compatibles. Il refuse quatre points modifiés :
registration des bâtiments et remontées, vivier du personnel et notification
du changement de terrain. Cette mise à jour change des structures privées,
en plus des adresses.

- `FHubMemberInfo` reçoit un champ privé de 16 bits à `+0x80`, initialisé à
  `0xFFFF` par les méthodes natives et repris par leur constructeur de copie.
  La structure passe de `0x80` à `0x88` octets et ses entrées de conteneur de
  `0x98` à `0xA0`. La routabilité et la couverture restent à `+0x68` et `+0x69`.
- Le compteur de regroupement reste à `+0xB50`. Les diagnostics choisissent
  donc explicitement le profil de structure revu ; ce compteur ne suffit plus
  à distinguer les deux organisations mémoire.
- Les registrations des bâtiments et remontées sont recompilées. Le mod
  continue d'appeler les méthodes natives pour construire leurs membres.
  La fonction des remontées est identifiée par ses appels depuis la construction
  native et ses références au sous-système des hubs, puis revue entièrement.
- Le RNG du personnel passe de `+0x684` à `+0x6E0`. Les candidats restent à
  `0x578` octets, les réglages à `+0x508` et le vivier à `+0x4D8`.
- La navigation associe le compteur de travail `+0x590` à l'indicateur de
  terrain modifié `+0x880`. Le résolveur exige cette nouvelle paire cohérente.

Une première session UE4SS isolée lit les propriétés publiques sans charger
de carte ni appeler les ponts refusés. Elle confirme les champs réfléchis des
hubs et du personnel. Les instructions natives de copie, d'insertion et de
reconstruction confirment les tailles et les nouveaux champs privés.

Les nouvelles empreintes couvrent les fonctions revues : **445 octets** pour
les bâtiments, **943** pour les remontées et **717** pour le personnel. Seuls
les opérandes d'adresse examinés sont neutralisés. Le wrapper différé doit
toujours cibler la fonction de reconstruction résolue indépendamment. Les
17 descripteurs normalisés trouvent chacun une cible unique. Les anciens
profils restent présents et le bootstrap de mise à jour garde son ABI stable.

## Relocalisation dans 26143813

Les 17 empreintes normalisées du profil 26141846 retrouvent chacune une cible
unique dans 26143813. La navigation, la notation des pistes et les options
passent également leurs gardes. La DLL adaptée au premier build fonctionne
ainsi sur le second sans recompilation ni ajout d'adresses dans le C. Le
contrat enregistre les nouvelles adresses de référence pour le diagnostic.
Les instructions, champs privés et références croisées restent contrôlés.
La réflexion UE4SS est également relue sur cette nouvelle révision.

## Vérifications

Les **304 tests Python et 80 scripts Lua**, ainsi que les **15 essais de jobs
de terrain Windows**, passent avec les sources et la DLL finales ; un test
optionnel est ignoré.

La qualification finale du build **26143813** est **compatible : 46 contrôles
sur 46 passent**, sans crash sur ce build. Super Saint-Bernard et Veymont sont
chargées, sauvegardées puis reprises par le vrai menu. Leur état strict, leurs
20 et 75 objets, leurs variantes et les modifications du joueur sont conservés
après GC.

Les huit vues actives et le cycle de neige 0 / 120 / 300 / 120 cm sont revus.
Le placement d'un bâtiment et les reconstructions répétées des terrassements
passent. La reconstruction explicite des hubs conserve ses compteurs et lit
des identités, positions et dimensions cohérentes dans les nouvelles entrées.
Les deux remontées fonctionnent après reprise de la simulation. Les contacts
des visiteurs et leurs traces sont examinés après reprise de l'horloge ; les
vues à horloge figée peuvent conserver des positions en attente de mise à jour.

Le catalogue HTTPS réel, les rafraîchissements, filtres, recherche, auteurs,
légendes et empilement du panneau Options passent. Le sandbox, la durée du
jour et les jours par mois survivent à une sauvegarde native et à sa reprise.
Le vrai exécutable est reconnu. Une identité inconnue injectée seulement dans
la revue du bandeau vérifie le texte dès la première image visible.

La sauvegarde du build 26040817 conserve son état strict et ses 20 objets.
Les seuls ajustements verticaux sont les trois corrections déjà introduites
en 1.24.8, conformes aux écarts mesurés entre source et surface affichée.
Kitzbühel 0.1.2 est revue avec une station et trois tables à 20 / 120 / 0 cm
sans changement de position de ces objets. Tous les essais et captures utilisent
UE4SS dans Gamescope headless, sans activer de fenêtre du bureau.

Les preuves finales sont conservées dans `build/compatibility/26143813-1.24.11-final-v1/` ; la revue native et les
résultats des tests sont sous `build/update-26143813/`.
