# Super Saint-Bernard — protocole de difficulté

Référence : carte **0.2.2**, loader **1.19.3**, scénario 2003–2011. Les tests de logique ne suffisent pas à déclarer le scénario équilibré : il faut terminer les parcours ci-dessous dans le jeu, avec ses visiteurs, sa neige et ses comptes.

## Installer la version locale

Depuis la racine du dépôt, jeu fermé :

```sh
python3 tools/custom_map.py update --archive build/release-1.19.3/CustomMap-Mod-1.19.3.zip
python3 tools/custom_map.py run mod/SkiEO-SuperSaintBernard
```

Le serveur Featured doit être publié séparément pour distribuer cette version. Une partie neuve permet de tester les bâtiments et équipes de départ ainsi que les nouvelles offres d'emprunt ; une sauvegarde conserve ses bâtiments, son personnel et les conditions des contrats déjà signés. La date affichée reste native : Year 1 correspond à l'hiver 2003–2004, Year 8 à 2010–2011. Les relevés JSON utilisent le calendrier historique pour les comparaisons.

Noter la version du jeu, d'UE4SS et du loader, le SHA-256 du paquet, le nombre de jours simulés par mois, la vitesse et les options de visiteurs. Relever aussi les dix employés et leurs salaires initiaux : les profils et salaires des candidats natifs varient d'une partie neuve à l'autre. Utiliser les mêmes paramètres et le même personnel initial pour comparer deux stratégies. Commencer à 1× ; tester ensuite 5× et 10× séparément.

## Contrôle préalable du domaine

1. Lancer une partie neuve, fermer le briefing et attendre la fin du chargement.
2. Vérifier les groupes **Bourg-Saint-Bernard**, **Col de Menouve** et **Plan du Jeu**, les deux remontées, les quatre pistes et le personnel affecté.
   Le poste Ski Patrol doit avoir deux pisteurs et le bâtiment Maintenance deux employés d'entretien. Avec quatre employés de remontée et deux conducteurs de dameuse, le total initial est de dix employés. Vérifier les salaires journaliers dans le panneau natif Staff et leur prélèvement dans les comptes. L'atelier et le poste de secours appartiennent au domaine initial : leur création ne doit pas réduire le capital de départ de 250 000. Après sauvegarde/rechargement, les mêmes bâtiments et affectations doivent rester présents sans nouvelle embauche.
3. En période d'ouverture et hors vent fort, les remontées doivent afficher **Operating** avec la neige initiale. Vérifier que des clients montent **et redescendent sur les pistes** ; un statut Operating seul ne prouve pas le fonctionnement des itinéraires.
4. Faire un contrôle de manque de neige dans une partie jetable : le moteur doit à nouveau interdire le ski. Le correctif invalide seulement le résultat calculé au chargement ; il ne force pas l'autorisation de skier.
5. Commander un chantier d'été et laisser plusieurs mois s'écouler. Le relief doit rester visible, la remontée concernée fermée pendant les travaux, puis rouvrir après réception si la météo et la neige le permettent.

Ne commencer aucune mesure de difficulté tant que ces contrôles échouent : une station sans clients ne permet pas de calibrer ses recettes.

## Sauvegarder sans laisser la neige évoluer

La pause de l'horloge et l'ouverture du menu de sauvegarde ne suffisent pas. Comme lors des essais Veymont, suspendre **aussi le monde du jeu**. Le loader fournit deux commandes dans la console du jeu :

```text
custommap_test_snapshot reference_before
```

Cette commande suspend l'horloge et le monde, garde cette suspension pendant les menus et écrit un relevé JSON dans le répertoire natif `SaveGames`, à côté des sauvegardes. Le journal du loader affiche son chemin : `CustomMap-QA-community-super-saint-bernard-reference_before.json`. Le relevé comprend date et heure, caisse, recettes et dépenses, emprunts, état du script, passages par remontée, météo et neige du cache grossier aux gares.

1. Exécuter la commande, puis attendre quelques secondes pour laisser finir une éventuelle lecture GPU déjà lancée. Faire un second relevé `reference_settled` et utiliser celui-ci comme référence.
2. Sauvegarder normalement dans un emplacement réservé aux essais. Le garde de pause se réapplique après la validation du menu de sauvegarde.
3. Attendre la fin de l'écriture ; fermer le menu, sans reprendre la simulation. Exécuter `custommap_test_snapshot reference_after`.
4. Comparer les relevés settled/after : date et heure, caisse, compteurs de passages, travaux et jauges doivent rester identiques ; tolérance de 0,5 cm sur la neige grossière. Un changement au-delà de cette tolérance invalide le point de reprise.
5. Reprendre uniquement après ce contrôle :

```text
custommap_test_resume
```

6. Recharger ensuite cette sauvegarde et relever `reference_loaded` dès que le chargement est terminé. Vérifier caisse, prêts, effort, état et échéance des chantiers, noms des hubs et absence de facturation répétée. Attendre que le cache de neige soit prêt avant de comparer les profondeurs. La commande snapshot suspend de nouveau le monde ; resume le libère.

Le comparateur retourne un code d'échec en cas de dérive, de mesure manquante ou de monde non suspendu :

```sh
python3 tools/compare_scenario_checkpoints.py /chemin/vers/reference_settled.json /chemin/vers/reference_after.json
```

La neige relevée est celle du cache grossier, pas une mesure exhaustive de chaque cellule fine. Contrôler également la neige visible et la skiabilité native. Pour chaque branche, repartir du même emplacement de sauvegarde, et enregistrer sous un nouveau nom.

## Parcours à comparer

| Parcours | Décisions | Résultat à vérifier |
| --- | --- | --- |
| Préparation raisonnable | Entretien préventif ; travaux planifiés hors hiver, avant fin 2010 ; emprunts modérés | Une victoire doit être possible avec une marge de trésorerie limitée et des clients sur les deux remontées. |
| Entretien minimal | Minimum pendant plusieurs années, mêmes recettes initiales | L'usure impose un coût ou une interruption tangible ; cette stratégie ne doit pas dominer systématiquement. |
| Entretien intensif seul | Entretien intensif, aucun chantier de conformité | Échec en 2011 : l'entretien ne renouvelle pas l'autorisation. |
| Travaux tardifs | Commander Menouve en janvier 2011 | Échec : une réception en avril ne sauve pas rétroactivement l'hiver. |
| Station fermée | Deux installations agréées, fermer tout l'hiver 2010–2011 | Échec même avec une caisse positive : les deux remontées doivent avoir réellement transporté des clients pendant cet hiver. |
| Crédit maximal | Utiliser toutes les offres ; tenter remboursements et nouveaux emprunts | Aucun prêt ne crée des recettes multipliées ; le service de la dette doit peser sur la caisse. |
| Chantiers financés | Préventif, deux mises aux normes, contribution de sauvetage dès son admissibilité | Contribution unique, disponibilité seulement à partir de 2009 et après engagement d'au moins 400 000 ; fermeture de chaque chantier pendant sa durée. |
| Expansion | Construire une remontée supplémentaire et ses pistes | Investissement réellement coûteux ; mesurer si l'augmentation des clients justifie la dette. |

Exécuter au moins trois paires préparation raisonnable/minimum depuis le même point initial. La série météo est imposée, mais les visiteurs peuvent varier : conserver les valeurs individuelles, leur médiane et leur étendue. Répéter un parcours réussi à 5× puis 10× ; une différence inexpliquée impose de revenir à 1× pour calibrer.

## Relevés et critères financiers

Faire un snapshot à chaque fin de mois simulé, avant/après un emprunt, un chantier et la contribution, puis en avril de chaque saison. Garder un journal CSV : `run,checkpoint,date,cash,revenue,expenses,debt,borrowed,repaid,maintenance,investment,grant,condition_menouve,condition_plan,riders_menouve,riders_plan,closures,decision`. Les montants cumulés se comparent par différence entre relevés du même exercice ; ouvrir une nouvelle ligne de départ lors du changement d'exercice.

Séparer exploitation, investissement et financement. Les recettes natives incluent déjà la majoration de fréquentation du scénario : ne pas les multiplier une seconde fois. Les emprunts ne sont pas des recettes. Soustraire la contribution du chiffre d'affaires pour mesurer l'exploitation. Le remboursement du principal consomme de la caisse sans être nécessairement une dépense d'exploitation dans les comptes natifs.

Les nouvelles offres conservent le montant calculé par le moteur d'après les recettes récentes :

| Offre | Recettes journalières prises en compte | Taux annuel nominal | Durée |
| --- | --- | --- | --- |
| Working capital | 1,5 jour | 6 % | 24 mois |
| Safety upgrades | 4 jours | 5 % | 60 mois |
| Infrastructure loan | 8 jours | 4,5 % | 120 mois |

Le moteur applique ses seuils et arrondis. La colonne Principal de la table d'offres ne fixe pas le capital accordé ; ne pas annoncer un prêt forfaitaire de 1 million. Le taux stocké est le taux annuel divisé par douze. Ces valeurs sont des **hypothèses d'équilibrage**, pas les contrats historiques retrouvés de la station.

Pour chaque parcours, relever la caisse minimale, la date de rupture, les recettes nettes d'aides, les coûts d'exploitation, les annuités effectivement prélevées, les fermetures et les passages de l'hiver final. Une couverture du service de la dette supérieure à 1,15 constitue une cible de conception pour le parcours raisonnable, pas une donnée historique. Une caisse positive obtenue uniquement par emprunt ne démontre pas une exploitation viable.

Si le parcours raisonnable échoue systématiquement, vérifier d'abord fréquentation, fonctionnement des pistes et calendrier des prélèvements. Ajuster ensuite un seul paramètre à la fois dans `Scripts/finance.lua`, `Scripts/survival.lua` ou les coûts du constructeur : durée/taux de crédit, fréquentation représentée, exploitation, entretien, usure. Rejouer les mêmes branches. Conserver le million de mises aux normes et les remplacements de plusieurs millions comme repères narratifs ; justifier tout changement séparément.

## État de validation

Les tests automatisés contrôlent les prélèvements uniques, l'usure, la conformité, les chantiers, la contribution et l'impossibilité de gagner sans exploitation de l'hiver final. Les vérifications dans le moteur contrôlent les noms géographiques, la skiabilité et les offres natives. Les parcours complets 2003–2011 restent nécessaires pour conclure sur la difficulté et les montants de crédit accessibles avec la fréquentation réelle.

Contrôle local du 9 octobre 2026, démo build 25808900, UE4SS 3.0.1-1152 : les deux remontées passent à Operating avec 100 cm tassés et 20 cm frais ; le contrôle sans neige les bloque. Le moteur accorde un prêt Medium de 40 000 sans augmenter les recettes. Le fichier de sauvegarde relu contient les noms français, les 40 000 de dette, le taux mensuel 0,05/12 et les 60 mois. Sous météo neigeuse forcée, les deux relevés séparés par une sauvegarde native et quinze secondes sont identiques, neige comprise. La reprise remet bien l'horloge en mouvement ; la conservation de la vitesse courante est couverte par le test automatisé. Après deux minutes à 10×, les compteurs natifs indiquent 19 embarquements à Menouve et 14 au Plan du Jeu. Ce dernier essai vérifie le transport ; il n'a pas encore constaté de descente terminée et ne remplace pas le contrôle des itinéraires ni les parcours complets.

Complément avec la carte 0.2.2 et le loader 1.19.3 : sept éléments de départ, dont cinq bâtiments, et dix employés affectés (quatre Liftie, deux Groomer, deux SkiPatrol, deux Maintenance). La lecture du fichier de sauvegarde natif confirme les deux nouveaux bâtiments et les affectations aux GUID terminant par 06 et 07 ; les salaires sont également enregistrés. La caisse sauvegardée reste à 250 000, sans achat des bâtiments hérités. Les relevés avant/après sauvegarde, séparés d'au moins quinze secondes avec le monde suspendu, sont identiques selon le comparateur ; la date native reste « Nov Year 1, 8:00 AM ». Un contrôle séparé de la paie native a prélevé 2 125 et ajouté exactement 2 125 aux dépenses, dont 759 pour les quatre nouveaux employés dans ce tirage. Ces montants varient selon les candidats. Ce contrôle porte sur l'enregistrement natif ; il ne constitue pas un parcours complet ni un nouvel essai de rechargement en jeu de cette sauvegarde.
