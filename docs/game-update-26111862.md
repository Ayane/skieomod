# Mise à jour du jeu 26111862 et Custom Map 1.24.9

La démo Steam installée est le build **26111862**, branche `experts_only`,
AppID `5012760`. Son exécutable porte le SHA-256
`8eb1215bcf56172822974b2c98a629e200afce22f4e57cc061a90b241e878a79`.

## Relocalisation automatique

Les points d'entrée des hubs, du personnel, de la skiabilité, des noms, de la
neige CPU et des terrassements ont changé d'adresse depuis 26097896. La revue
des instructions ne révèle pas de changement des champs privés utilisés :
compteur des hubs `+0xB60`, réglages du personnel `+0x508`, vivier `+0x4D8`,
candidats de `0x528` octets, mémo de skiabilité `+0x1B4`, cellules de neige de
56 octets et indicateur prêt `+0x28`.

Le helper recherche désormais ces fonctions dans les sections exécutables à
partir d'empreintes du code revu. Seuls les opérandes d'adresse relatifs
individuellement examinés sont neutralisés. Les opcodes, accès aux champs,
tailles de pile, constantes et branches internes doivent rester identiques.
Les fonctions de terrassement et de nettoyage conservent une couverture de
2 088 et 267 octets. Un déplacement seul peut ainsi être accepté au lancement,
sans attendre une publication contenant de nouvelles adresses.

La recherche exige un résultat unique. Deux wrappers possèdent le même code
normalisé dans ce build : celui utilisé pour les hubs est identifié en vérifiant
que sa branche vise la fonction de reconstruction reconnue indépendamment.
Un wrapper allant vers une autre fonction est rejeté.

Les 17 descripteurs trouvent chacun leur cible dans **26097896 et 26111862**
avec les mêmes empreintes. Le helper Windows et le précontrôle Python partagent
ces données via [le contrat](../compatibility/game-contract.json) et l'en-tête
généré par `python3 -m tools.native_layouts`. La navigation, les options et la
notation des pistes conservent leurs résolveurs contrôlés.

Les contrôles de classes, de mémoire et de propriétés réfléchies restent actifs.
Une instruction ou une disposition interne différente, une cible absente ou
une ambiguïté provoque un refus. Le bandeau continue de signaler un exécutable
non qualifié, même si ses fonctions sont retrouvées : la relocalisation ne
remplace pas les essais de chargement, de sauvegarde et de rendu.

## Vérifications

Les **304 tests Python et 80 scripts Lua** passent ; un test optionnel est
ignoré. Les tests de relocalisation déplacent le code et les opérandes d'adresse,
refusent les changements d'instructions ou de champs privés, les ambiguïtés,
les sections non exécutables et les fenêtres débordant d'une section. Le
scanner C portable est comparé au précontrôle Python sans modifier son entrée.
Les **15 essais de jobs de terrain** passent avec la DLL distribuée dans un
préfixe Windows/Proton jetable ; un job refusé laisse les caches intacts.

La qualification finale est **compatible : 46 contrôles sur 46 passent**.
Super Saint-Bernard et Veymont sont chargées puis reprises depuis de vraies
sauvegardes natives, sans écart d'état, perte d'objet ou de variante après GC.
Les suppressions, noms modifiés et données de scénario persistent. Le cycle de
neige 0 / 120 / 300 / 120 cm, le placement d'un bâtiment, les reconstructions
répétées de terrassements et la reprise des deux remontées passent.

Les huit vues actives des deux cartes et les captures de contact des visiteurs
et des traces ne montrent pas de régression du terrain. Kitzbühel 0.1.2 est
également chargée avec une station et trois tables, puis revue à 20 / 120 / 0 cm.
Le catalogue HTTPS réel, les rafraîchissements automatiques, les filtres, la
recherche, les auteurs, les légendes et l'ordre du panneau Options sont vérifiés.
Un vrai cycle de sauvegarde conserve le sandbox, la durée du jour et les jours
par mois. Le build réel est reconnu ; une identité inconnue injectée seulement
dans la revue d'interface fait apparaître un bandeau rempli dès sa première
image visible, puis la restauration de l'identité reconnue retire ce bandeau.

Une sauvegarde du build 26040817 conserve son état strict et ses 20 objets.
Les trois ajustements verticaux des bâtiments correspondent exactement à la
différence mesurée entre données source et terrain affiché, correction déjà
introduite en 1.24.8. Les positions horizontales, identités et variantes restent
conservées. Les captures sont produites par UE4SS dans Gamescope headless,
sans activer une fenêtre du bureau.

Les résultats détaillés de la qualification sont conservés dans
`build/compatibility/26111862-1.24.9-final-v3/`. La revue de relocalisation et
les essais natifs sont sous `build/update-26111862/`.
