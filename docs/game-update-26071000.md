# Mise à jour du jeu 26071000 et Custom Map 1.24.6

La démo Steam installée est le build **26071000**, branche `experts_only`,
AppID `5012760`. Le journal de 1.24.5 montre des objets créés, mais la
registration native des hubs refuse l’exécutable. Le réseau de la station
reste vide et le chargement de Veymont est abandonné.

## Correction

Les ponts des hubs, du personnel, de la skiabilité, des noms géographiques,
de la neige CPU et des terrassements ont changé d’adresse. La comparaison
des instructions utiles avec 26056171 ne montre pas de changement des champs
privés utilisés. Les nouveaux profils conservent les contrôles des points
d’entrée, les signatures exactes et les empreintes complètes des fonctions de
terrassement et de nettoyage. Les profils antérieurs restent présents.

La navigation, la notation et le transfert des options conservent leurs
résolveurs contrôlés. Le contrat de qualification référence le nouvel
exécutable et les sources et DLL réellement testées.

## Avertissement dans Custom Map

Un cadre apparaît au-dessus du navigateur lorsque l’exécutable ne correspond
pas à un build qualifié. Il indique le build pris en charge et où mettre le mod
à jour. Une vérification indisponible est signalée séparément. Le cadre réserve
sa propre place ; les contrôles du navigateur et le panneau Options restent
accessibles, avec les couches Custom Map sous le panneau natif.
Le cadre est masqué avant son ajout à l’arbre UMG et ses libellés sont initialisés
immédiatement. Le texte et sa disposition sont préparés avant de le rendre
visible, pour éviter l’apparition temporaire d’un panneau vide.

L’identification compare le SHA-256 de l’exécutable réellement lancé, calculé
une seule fois dans un thread distinct. Elle fonctionne hors ligne et ne
s’appuie ni sur la version du moteur ni sur un ancien résultat du processus
précédent. Elle ne remplace pas les gardes natives exécutées au chargement.

## Qualification

Le cycle final, exécuté dans une nouvelle copie isolée avec les fichiers
figés de 1.24.6, est **compatible** : **46 contrôles passent**. Les **294 tests
Python et 78 scripts Lua** passent également. Les résultats et leurs empreintes
sont conservés sous `build/compatibility/26071000-1.24.6-final-v4/`.

- Super Saint-Bernard 0.2.4 et Veymont 0.7.7 se chargent avec leurs effectifs,
  variantes et objets conservés après GC. Leurs vraies sauvegardes natives sont
  écrites et reprises depuis le menu ; les comparaisons d’état n’ont aucun écart.
- Huit vues actives des stations, du mobilier, des panneaux et du relief ; cycle
  de neige 0 / 120 / 300 / 120 cm, placement d’un bâtiment, reconstruction des
  terrassements sans doublons, puis reprise normale de la simulation.
- Catalogue web réel avec six cartes, filtres, recherche, rafraîchissement
  initial et échéance périodique. Auteur et icônes des lignes vérifiés.
- Reconnaissance du véritable exécutable par le helper natif. Pour l’essai du
  bandeau, un résultat de version inconnue est injecté uniquement dans le poll
  de l’interface. Un résultat en attente ne réserve aucun espace vide. Un hook
  observe le moment où le cadre devient visible et confirme que son titre et
  son texte sont déjà renseignés. Les captures vérifient le cadre, son retrait
  et le panneau Options au-dessus de celui-ci, avec le navigateur désactivé.
- Une sauvegarde sandbox conserve le mode, une durée de jour de **1,5×** et
  **3 jours par mois** après reprise ; les objectifs et charges scriptés restent
  désactivés. Une ancienne sauvegarde de 1.24.3 sur 26040817 conserve ses
  20 objets, leurs GUID, noms, variantes et positions, ainsi que son état de
  scénario et son économie. Elle reprend en mode normal après le sandbox.

Les essais interrompus par la coupure de courant et les captures intermédiaires
restent distincts de cette qualification finale, réalisée sans interruption.
