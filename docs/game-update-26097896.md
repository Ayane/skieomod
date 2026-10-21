# Mise à jour du jeu 26097896 et Custom Map 1.24.7

La démo Steam installée est le build **26097896**, branche `experts_only`,
AppID `5012760`. Les gardes de 1.24.6 refusent plusieurs points d’entrée natifs.
Le journal conservé révèle aussi un appel au bandeau avant la construction du
navigateur : les onglets existent déjà, mais pas encore `version_warning`.

## Compatibilité native

Les points d’entrée des hubs, du personnel, de la skiabilité, des noms, de la
neige CPU et des terrassements ont été relocalisés et comparés à 26071000.
Deux changements de structure nécessitent davantage qu’un déplacement d’adresse :

- le compteur de regroupement des hubs passe de `+0xB10` à `+0xB60` ;
- les candidats du personnel passent de `0x518` à `0x528` octets. Les pointeurs
  des réglages et du vivier restent à `+0x508` et `+0x4D8` ; le RNG reste à `+0x680`.

La registration des remontées est recompilée : nouveaux registres, nouvelle
pile et extraction d’un helper. Sa vraie entrée `0x4FCD150` a été retrouvée via
les références au sous-système des hubs, puis les deux descripteurs de terminaux
et les appels natifs ont été revus. Un candidat obtenu avec un préfixe trop
court a été écarté. Une garde spécifique complète les profils antérieurs.

Les ponts conservent leurs gardes d’entrée et les empreintes intégrales des
fonctions de terrassement et nettoyage. La navigation et les options conservent
leurs résolveurs contrôlés. Le contrat référence l’exécutable, les sources et
la DLL réellement utilisés dans les essais ; aucune garde n’est désactivée.

## Mises à jour depuis le bandeau

Lorsque le bandeau de version non qualifiée apparaît dans le menu principal,
le mod vérifie automatiquement le flux HTTPS officiel.
Une version stable plus récente est téléchargée automatiquement. L’URL versionnée,
les tailles, le SHA-256 de l’archive, son manifeste et chaque fichier sont vérifiés.
Les cartes, réglages, sauvegardes et fichiers hors distribution restent conservés.
Le traitement ZIP cède la main entre les fichiers ; le téléchargement et la
préparation native se font en arrière-plan.

Les fichiers chargés restent en place tant que le jeu tourne. **Restart game**
utilise la fermeture normale d’Unreal, applique la version préparée, puis relance
le même exécutable avec ses arguments et son environnement. Une fermeture normale
installe aussi la mise à jour, sans relancer. Le bouton est réservé au menu,
sans chargement ni partie en cours. Les DLL et hooks natifs empêchent de proposer
un rechargement complet fiable à chaud.

Un journal et une sauvegarde précèdent le remplacement du code ; le manifeste
est écrit en dernier. Une erreur restaure la version précédente. Au démarrage,
un petit bootstrap récupère une transaction interrompue avant de charger les
modules de jeu. Le worker lie l’opération au PID, à l’heure de création du
processus et à un nonce ; il ne termine jamais lui-même un processus.
Une autre installation ayant changé le manifeste annule la transaction préparée.

`main.lua` et le bootstrap constituent l’ABI stable de récupération : leurs
empreintes doivent rester identiques pour une mise à jour automatique. Une
évolution de cette ABI nécessite l’installateur. L’installation initiale de
1.24.7 nécessite les outils 1.24.7 ; les versions suivantes peuvent utiliser
le mécanisme intégré au jeu. Les erreurs réseau font l’objet de nouvelles tentatives automatiques.

Le bandeau est construit masqué avec du texte initial. Son titre, son détail,
sa progression et la disposition sont préparés avant affichage. Le scan ignore
les écrans dont le navigateur n’est pas construit. Les onglets et le bandeau
restent sous le panneau Options natif.

## Vérifications

Les **296 tests Python et 79 scripts Lua** passent (un test optionnel ignoré).
Les essais du worker Windows dans un préfixe Proton jetable vérifient :
préparation avec fichiers d’origine intacts et une DLL chargée, fermeture normale,
relance avec un nouveau PID et la nouvelle DLL, restauration après erreur,
récupération d’une interruption simulée avant chargement de la DLL restaurée,
refus d’un fichier préparé altéré, d’un chemin traversant et d’un mauvais digest.
Les fichiers de réglages et les anciens fichiers modifiés restent présents.

La qualification complète et les captures sont conservées sous
`build/compatibility/26097896-1.24.7-final-v2/`. Le rapport final et la revue
contrôlent le chargement des deux cartes, leurs vraies sauvegardes natives,
le rendu et le cycle de neige, les menus et les anciennes sauvegardes.
Les résultats du worker sont sous `build/update-26097896/updater-native-v4/`.

Un essai supplémentaire dans le vrai jeu utilise une version fictive **1.24.8**
strictement locale, jamais publiée. Seules les réponses du flux et de l’archive
sont remplacées par une fixture ; le parseur ZIP, la préparation native, le
bouton UMG, la fermeture d’Unreal et la relance restent ceux de la distribution.
Les fichiers d’origine restent intacts jusqu’à la fermeture. Après relance,
le module et le manifeste sont en 1.24.8, le menu fonctionne et le build réel
est reconnu. Les captures n’affichent aucune cadence de vérification. Les preuves
sont sous `build/compatibility/26097896-updater-game-v3/review/`.

Le cycle final avec les fichiers figés de 1.24.7 est **compatible : 46 contrôles
sur 46 passent**. Super Saint-Bernard et Veymont sont chargées, sauvegardées et
reprises sans écart d’état, avec leurs effectifs, objets et variantes conservés
après GC. Le cycle de neige 0 / 120 / 300 / 120 cm, le placement d’un bâtiment,
les reconstructions de terrassements et la reprise de simulation passent.
Le catalogue web réel, les filtres, la recherche, le panneau Options et le
sandbox sont validés. Une sauvegarde du build 26040817 conserve son état et ses
20 objets. Les captures du bandeau final n’affichent aucun délai de vérification.
