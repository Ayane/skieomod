# Super Saint-Bernard — Le sursis

Carte Featured séparée du chargeur, téléchargée depuis le serveur lors du premier lancement et lorsqu’une nouvelle version est disponible. Nécessite skieomod 1.19.3 ou ultérieur.

Vous reprenez la station fin 2003 avec 250 000 CHF et deux installations de 1962. L’objectif est de sauver la saison 2010–2011 : deux remontées conformes, un état technique d’au moins 45 % et une trésorerie positive à la fin de l’hiver.

Les textes du scénario sont en anglais. Tous les montants représentent des francs suisses (CHF), mais l’interface conserve le symbole natif **$** pour éviter toute alternance visible. La fiche d’une installation ajoute uniquement son état, son année de mise en service et sa conformité ; le coût quotidien reste affiché par le jeu.

La barre supérieure conserve également la date native du jeu. **Year 1** correspond à l'hiver 2003–2004 et **Year 8** à l'hiver 2010–2011. Le calendrier historique reste utilisé par les objectifs, l'usure et les observations météo.

Une partie neuve commence avec un poste de secours **Ski Patrol** et son équipe de deux pisteurs, ainsi qu'un atelier **Maintenance** avec deux employés d'entretien. Avec les quatre employés des remontées et les deux conducteurs de dameuse, le domaine démarre avec dix employés. Le jeu gère leurs affectations, salaires et sauvegardes ; ces salaires s'ajoutent aux frais d'exploitation et au budget d'entretien du scénario. Les bâtiments sont repris avec la station, sans achat initial supplémentaire. Cet effectif est une hypothèse de simulation, pas un registre historique retrouvé. Une sauvegarde existante conserve ses bâtiments et son personnel.

La version 0.2.4 ajoute 14 éléments du nouveau mobilier natif aux nouvelles
parties : huit panneaux aux départs des quatre pistes, deux porte-skis doubles,
deux bancs et deux tables autour de la billetterie et du restaurant. Les
panneaux utilisent les variantes vert/bleu/noir du jeu selon la difficulté.
Ces emplacements sont des hypothèses d'aménagement. Le mobilier ne reçoit
pas les frais d'exploitation, l'usure ou les concessions des installations du
scénario. Les sauvegardes existantes conservent leur disposition.
L'[inventaire de la mise à jour](../../docs/game-update-25970577.md) décrit
les autres nouveautés disponibles.

Dans **Resort Management → Operations**, choisissez l’entretien minimum (24 000 CHF/an), préventif (60 000 CHF/an) ou renforcé (120 000 CHF/an). Ces dépenses sont distinctes de l’exploitation courante et apparaissent dans les comptes natifs. Le temps du calendrier détermine les dépenses et l’usure : mettre le jeu en pause suspend leur évolution. L’état de chaque installation apparaît dans sa fiche **Info**.

L’entretien ralentit l’usure, sans prolonger la concession. Les mises aux normes de Menouve (800 000 CHF, trois mois) et du Plan du Jeu (200 000 CHF, deux mois) permettent une autorisation de transition jusqu’à 2013. Le renouvellement coûte respectivement 10 millions et 2 millions CHF. Les travaux arrêtent la remontée et nécessitent une réception avant réouverture. Une contribution de sauvetage simulée de 500 000 CHF devient encaissable en 2009 si au moins 400 000 CHF de travaux sont engagés ; elle ne peut être encaissée qu’une fois.

Les installations historiques ne peuvent être déplacées, démolies ou revendues pour contourner la concession. Leur rénovation ou renouvellement se commande dans le panneau de gestion. Les constructions supplémentaires restent soumises au catalogue de coûts du scénario.

L’état technique, le choix d’entretien, les travaux et les objectifs sont liés à chaque sauvegarde native, y compris les sauvegardes manuelles et automatiques.

## Données et limites

- **Terrain** : swissALTI3D 2024 à 2 m, rééchantillonné à 4 m, complété par swissALTIRegio à 10 m sur le versant italien. Carte jouable de **9,6 × 8 km**, du Mont Vélan aux Monts Telliers, avec le centre d’origine conservé. Le raccord des couvertures est fondu sur 80 m. Les systèmes altimétriques étrangers sont ceux du produit régional, sans prétendre à une transformation LN02 qui n’a pas été réalisée par le fournisseur. © swisstopo / TINITALY 1.1 INGV.
- **Paysage** : relief régional réel sur **30 × 30 km**, rééchantillonné à 100 m et raccordé au périmètre jouable. Ce paysage est purement visuel : aucune collision, navigation ou extension fictive des surfaces constructibles. Attribution complète du produit régional dans `Data/sources.json`.
- **Remontées** : axes OpenStreetMap 1093148125 et 1093148124. Menouve : quatre places, 600 personnes/heure ; Plan du Jeu : 900 personnes/heure. Le moteur représente le téléski avec un télésiège à une place disponible dans le jeu.
- **Pistes** : quatre parcours sur le versant suisse, avec fragments historiques OSM et raccordements reconstitués. Le tunnel de Tscholaire est représenté en surface. La descente italienne avec retour routier n’est pas reproduite ; les 27 km annoncés historiquement ne sont pas intégralement modélisés.
- **Météo** : 3 287 observations quotidiennes MeteoSwiss GSB de 2003 à 2011. Température moyenne, précipitations et rafale maximale d’une seconde. Le calendrier comprimé rejoue les dates selon la progression du mois. La température de base est corrigée de +3,2 °C entre le col à 2 472 m et le départ à 1 932 m. Les précipitations utilisent le système neige/pluie natif. Les rafales d’au moins 20 m/s imposent l’arrêt des remontées ; une mesure de vent absente ne provoque aucune fermeture fictive. La météo native ne reproduit pas la quantité exacte de précipitation ni toute la physique des avalanches.
- **Économie** : capital, prix du forfait à 38 CHF, travaux urgents à 1 million CHF et estimation du remplacement de Menouve à 10 millions CHF proviennent du document de crise. Les jauges d’état, l’usure, les délais, les coûts courants, le prix des autres constructions et l’aide conditionnelle constituent une calibration jouable. Une représentation visuelle de client compte pour douze visiteurs journaliers dans les recettes. Les comptes exacts de la station n’ont pas été retrouvés : ces budgets ne sont pas présentés comme des comptes historiques.

## Modifier le scénario dans l’éditeur

Le déclencheur **Starting economy · 2003** est maintenant un graphe dans
`Triggers/triggers.json`. Il configure 250 000 CHF, le forfait de 38 CHF, la
devise et l’année de référence avant les autres callbacks `map.ready`. Le
module `Scripts/economy.lua` conserve les coûts, les prêts et le suivi des
remontées ; `Scripts/main.lua` conserve les règles de partie. Le même
déclencheur contient son équivalent Lua, seul le mode choisi est compilé.

Le [tutoriel illustré](https://skieomod.emillon.fr/tutorials/scripts/) explique
comment lire et modifier ce graphe, puis créer un scénario d’exercice.
Après modification : **Apply to project → Save → Build → Test → Play**.
Utiliser `skieomod build mod/SkiEO-SuperSaintBernard` pour compiler les graphes
avant l’empaquetage. Les sauvegardes existantes conservent leur trésorerie et
leur prix du forfait.

## Reconstruction des données

Depuis la racine du dépôt :

```sh
python3 tools/prepare_super_saint_bernard.py --fetch
```

Le cache des sources brutes est sous `build/super-st-bernard`. Ensuite, la même commande sans `--fetch` reconstruit le terrain, la météo, la géométrie et les illustrations hors ligne. Les empreintes SHA-256, licences et sources sont conservées dans `Data/sources.json`.

Référence historique : [étude de la crise](../../docs/super-st-bernard-crisis.md). Source climatique : [MeteoSwiss GSB](https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items/gsb).
