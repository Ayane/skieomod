# Remontées de Veymont et mapmod de téléskis

Veymont 0.8.0 distingue le Blanchon, télésiège fixe deux places, des huit
remontées à perches. Le mapmod `community.surface-lifts` est distribué dans
une archive séparée, comme les renards.

## Sources et précision

Les axes et points de support viennent de l'extrait OpenStreetMap utilisé
par Veymont ; les altitudes sont échantillonnées dans son R16 IGN. Les altitudes
et longueurs du jeu peuvent donc différer des fiches historiques. Le générateur
conserve maintenant tous les points intermédiaires de chaque axe.

| Installation | Modèle | Vitesse | Débit | Pylônes | Source des caractéristiques |
| --- | --- | --- | --- | --- | --- |
| Pré Levé | Perches débrayables, gare couverte | 3,54 m/s | 720 p/h | 12 | [Reportage 8978](https://www.remontees-mecaniques.net/bdd/reportage-tkd-du-pre-leve-poma-8978.html) |
| Pras 1 et 2 | Perches débrayables | 3 m/s | 720 p/h chacun | 9 chacun | [Reportage 8986](https://www.remontees-mecaniques.net/bdd/reportage-tkd-des-pras-1-2-poma-8986.html) |
| Pierre Blanche | Perches débrayables | 3,9 m/s | 720 p/h | 9 | [Reportage 3502](https://www.remontees-mecaniques.net/bdd/reportage-tkd-pierre-blanche-poma-3502.html) |
| Blavet | Perches débrayables | 3,5 m/s | 900 p/h | 5 | [Reportage 3582](https://www.remontees-mecaniques.net/bdd/reportage-tkd-du-blavet-poma-3582.html) |
| Alleyrons | Perches débrayables | 4 m/s | 720 p/h | 12 | [Reportage 8992](https://www.remontees-mecaniques.net/bdd/reportage-tkd-des-alleyrons-poma-8992.html) |
| Blanchon | Deux places natif, gares originales | 2 m/s | 900 p/h | 6, natifs | [Reportage 3194](https://www.remontees-mecaniques.net/bdd/reportage-tsf2-du-blanchon-poma-3194.html) |
| Bessards 1 et 2 | Perches fixes | 2 m/s | 514 p/h chacun | 4 chacun | Débit, vitesse et supports : valeurs de modélisation ; axes OSM |

Pré Levé conserve ses virages aux P6 et P9, Pierre Blanche celui du P8.
Les supports du Pré Levé, des Pras et de Pierre Blanche sont localisés dans
OSM. Les positions manquantes du Blavet, des Alleyrons et des Bessards sont
ajustées au profil du terrain sans changer le nombre de supports. Les faibles écarts de direction dus au relevé OSM ne créent pas
artificiellement de portiques de virage.

Les photographies servent uniquement à l'observation. La géométrie des pièces,
les matériaux et les textures livrés sont originaux, sous BSD-3-Clause.
Le script Blender produit vingt-quatre modèles `.skpm`, une palette et une scène
éditable dans `build/surface-lifts/models.blend` :

```sh
blender --background --threads 2 --python tools/build_surface_lift_models.py
```

La gare des Pras utilise des colonnes carrées et des roues inclinées.
Blavet et Pierre Blanche partagent la famille de portiques ouverts ; les Alleyrons
ont un retour à mât en treillis. Les retours flottants comportent une suspension
et un contrepoids. Les Bessards ont une petite gare fixe sans stock de perches.
Le Blanchon reçoit une salle des machines vitrée sur portique et un retour ouvert ;
ses sièges et les positions des supports restent natifs. Les cadres, les trains de galets inclinés et leurs axes sont séparés. Le câble conserve une tangente continue au passage des pylônes.
La page de Gresse du site de référence ne comporte pas de reportage des Bessards :
leur géométrie reste une interprétation, et le débit de 514 p/h est corroboré par
[la liste Skiresort](https://www.skiresort.fr/domaine-skiable/gresse-en-vercors/remontees-mecaniques/).

## API du chargeur

`api:configure_surface_lifts(definitions, assets)` demande la permission
`gameplay` et s'appelle sur le thread du jeu après la création des remontées.
Il retourne un objet avec `snapshot()` et `dispose()`. Un appel par session
est permis. Une erreur de préparation restaure les objets déjà modifiés.

`max_snow_cm` permet de régler la limite d'accumulation (110 à 300 cm).
La valeur par défaut est de 150 cm pour une perche fixe et de 250 cm pour
une perche débrayable, selon la garde disponible sous le câble.

Chaque définition accepte `ascent_side` (`left` ou `right`, vu depuis le départ vers le sommet). Les Pras et les Bessards sont en miroir : les montées sont vers la piste centrale et les retours à l’extérieur. Pré Levé, Blavet et Alleyrons montent à gauche ; Pierre Blanche et Blanchon montent à droite.

Chaque définition contient `name`, `route` (points `[x,y,z]` en cm), `kind`
(`detachable_platter`, `fixed_platter` ou `fixed_chair`), `speed_mps`, `capacity_per_hour`,
`pylons`, `drive` (`covered`, `modern` ou `open`) et `return_station` (`release`,
`floating` ou `lattice`). Le mode `fixed_chair` conserve les sièges et la simulation natifs ; il remplace les cadres des pylônes et les galets et lisse le câble au passage des supports. Les repères natifs d’embarquement et de débarquement suivent ce nouveau profil, y compris lorsque l’embarquement précède le bouclage de la spline.
`assets` associe `palette`, `platter`, `platter_upper`, `platter_shaft`, `platter_lower`,
`poles_bundle`, `tower`, `angle_tower`, `return_support`, `return_angle`,
`fixed_return_support`, `inclined_wheel`, `guide_wheel`, `motor`, `chair_tower`, `chair_head`, `drive`, `covered`,
`return_station`, `release`, `fixed`, `modern`, `lattice`, `chair_drive`,
`chair_return` à des ressources déclarées par le paquet. Les fichiers SKPM sont bornés et validés avant tout appel Unreal.

Les corps natifs restent enregistrés : gestion, billets, employés, entretien
et sérialisation ne sont pas remplacés par une simulation parallèle. Un
maillage de sockets transitoire, propre à chaque acteur, fournit une place
`Standing_0` sans modifier les ressources natives communes. Les perches
visibles suivent les positions des transporteurs natifs. Le relief et la neige
sont interrogés via le chargeur, tous les deux mètres le long du trajet.
La hauteur de neige est rafraîchie toutes les trente secondes, par lots de
huit lectures au maximum par image, boucles des gares comprises. Le profil
complet est appliqué une fois prêt ; seules les hauteurs modifiées de plus
de 2,5 mm provoquent une mise à jour de la spline. Les appuis réutilisent
ce profil de neige avec la hauteur locale précise du terrain.
Les passagers utilisent le skieur ou snowboardeur équipé du jeu : les skis sont
attachés aux pieds par son rendu natif. Le pont de rendu conserve l'activité
`RidingLift` du passager. Une copie des positions est transmise au collecteur
natif des empreintes avec la vitesse mesurée, pour produire les mêmes traces
que la descente. Une remontée arrêtée, la pause et les téléportations ne créent
pas d'empreintes artificielles. La perche en charge s'incline pour placer
l'assiette derrière les cuisses et son coude sous l'entrejambe. Sur les TKD,
le tube fin supérieur coulisse dans le fourreau de plus gros diamètre placé en bas ; le joint de coulissement reste au-dessus de la main. Le rappel amorti du ressort
le rétracte après le lâcher. Le fourreau, la pince et l'assiette gardent leurs
dimensions. Les TKF utilisent une perche rigide : la position de la pince sur
le câble, sa flexion entre supports et l’angle de la perche assurent le contact, sans variation de longueur. Les perches fixes mesurent 3 m dans cette modélisation.
À proximité, le squelette natif équipé reçoit une pose de traction, main droite
sur la perche, deux bâtons regroupés dans la main gauche. Les bras utilisent
une cinématique à deux segments qui conserve la longueur des os. Les jambes
ont leur propre résolution : les skis restent attachés aux pieds, le buste
s’incline depuis la taille lorsque la prise le demande, et chaque semelle reçoit
un appui indépendant sur la neige. Les snowboardeurs utilisent leur propre squelette natif, en travers de la pente : la main avant tient la perche, l’assiette appuie sous la cuisse avant et la planche reste rigide avec ses deux fixations. Ils ne portent pas de bâtons.
Le matériau natif utilisé est compatible avec le squelette ; les normales
animées de la foule ne sont pas réutilisées sur une pose différente.
Seul le rendu
du passager concerné est remplacé ; sa simulation, ses skis et ses empreintes
restent natifs. Les composants de l'ancien télésiège, y compris
ses chapeaux de neige, sont masqués avec restauration à la libération.

Le cache CPU de neige ne distingue pas toujours les sillons étroits. Une
capture de profondeur, limitée au terrain et à la neige, mesure donc la
surface affichée près du passager détaillé le plus proche : 128² pixels sur
32 m, au plus deux fois par seconde, avec une précision de 25 cm par pixel.
La grande vue 1024² a été supprimée. Un déplacement de caméra ne contourne
pas la limite de fréquence. La lecture Kismet reste synchrone, après l'image
de capture ; différer son appel ne la rend pas asynchrone. Son volume maximal
passe de 1 310 720 à 32 768 pixels par seconde. Le helper retourne des nombres
flottants compacts, sans objet Lua par pixel ; cible et buffers sont libérés
à la fermeture de la carte. Hors de ce petit relevé, les appuis utilisent le
profil de neige en cache. La pose squelettique concerne au plus 16 passagers
à moins de 60 m de la caméra ; au-delà, le rendu équipé natif reprend.
Le calcul tient compte de la semelle située sous l'origine du squelette.

La boucle Lua s'exécute sur le thread du jeu. La découverte des passagers ne
parcourt tous les visiteurs que quatre fois par seconde ; les positions des
passagers connus restent lues à chaque image, avec contrôle du GUID et des
bornes des tableaux natifs. Les associations skieur/perche restent stables
entre les mises à jour de la simulation et des instances graphiques.
La progression de sortie de gare utilise la distance totale parcourue par le
câble, y compris hors champ, et garde la pince devant le skieur. Les recherches
de proximité projettent sur les segments OSM d'origine puis retrouvent la
distance exacte sur le profil détaillé. Les roues éloignées et immobiles
n'envoient plus de transformations à Unreal ; les stocks visibles sont
limités à 64 perches dans un rayon de 180 m, en plus des 64 en ligne.

UE4SS **1181** corrige la rétention des tables de sortie des appels natifs
présente dans la version 1152 précédemment installée. Le programme d'installation
conserve une sauvegarde de cette ancienne DLL avant son remplacement. Les essais
isolés disposent en plus d'une limite mémoire de 7,75 Gio, indépendante du bureau,
avec arrêt préventif à 6,75 Gio. La réserve de démarrage vaut 8 Gio par défaut ; les essais de cette correction utilisent explicitement 6 Gio, avec arrêt si la mémoire disponible descend sous 4 Gio. Le plafond et la réserve effectifs sont enregistrés avec les mesures.

Les trois distances privées du composant natif (longueur de boucle, embarquement,
débarquement) doivent suivre le nouveau trajet. Le pont est réservé au binaire
Steam **26143813** et **26178224**, reconnus par SHA-256, avec vérification des
champs réfléchis voisins et des distances d’origine avant écriture. Une version
sans profil relu est refusée.
Il faut le chargeur de cette branche ; une ancienne installation 1.24.11 ne
contient pas encore cette API.

Les perches libres restent verticales. Leur coude est arrondi et la rondelle reste perpendiculaire à la perche, sans rotation indépendante ni étirement. Le brin retour des TKD possède un profil distinct, plus haut que la montée. Il franchit les supports bas sans galet de retour, mais conserve les supports de changement de direction. La roue motrice est un cercle rigide incliné ; la roue supérieure reste horizontale. Des roues de guidage relient chaque brin à la grande roue, avec continuité de position et de tangente, flèche du câble comprise. Le câble passe dans une gorge ouverte entre les flasques. Les guides tubulaires accompagnent la descente des perches vers le stock. Les hauteurs et les supports sautés sont calculés sur le relief du jeu : ils ne constituent pas un relevé dimensionnel des installations réelles. Le modèle limite à 250 m les portées obtenues en sautant des supports et augmente la flèche du câble de retour avec la portée.

Les TKD conservent chaque perche pendant son tour : retour, passage sur le guide, file d’attente et départ. Les emplacements de transport natifs vides n’emmènent aucune perche. Une prise par un passager déclenche le départ lorsque la perche précédente a parcouru la distance de sécurité correspondant au débit configuré. Le retour entre à l’arrière du stock et progresse sans remplacement instantané par une perche à l’avant. Le mouvement du stock suit le déplacement du câble ; la pause et l’arrêt le figent. Les deux Bessards restent à pinces fixes, sans stockage.

Les identités, l’ordre du stock, les perches en ligne et leurs passagers utilisent une sauvegarde compacte dans l’état du mapmod. Les repères graphiques temporaires et les références Unreal n’y figurent pas. Les mâchoires des pinces ne sont pas animées séparément. Toutes les roues de transport sont séparées de leurs paliers et tournent selon le déplacement mesuré du câble et leur rayon. Les supports des téléskis portent deux poulies successives, sous puis sur le câble. Le retour est de l’autre côté du montant. Les trains de galets du Blanchon sont inclinés selon la tangente réelle du câble ; les passerelles sont placées au-dessus de leur volume de rotation.

Trois sons originaux sont synthétisés par `ModularSynthComponent` : ronflement
du moteur, choc métallique des perches en gare, roulement au passage d'un
support. Les impacts suivent le passage réel des transporteurs. Ils utilisent
la classe audio SFX et l'atténuation spatiale natives ; l'arrêt et la pause
coupent le moteur. Aucun enregistrement tiers n'est redistribué.

L'enneigement est contrôlé tous les deux mètres sur toute la ligne de montée,
par lots de 16 échantillons répartis entre les remontées, au plus vingt lots
par seconde. Un échantillon sous
3 cm arrête le câble, interdit l'embarquement et affiche « Manque de neige sur
la ligne de montée ». La réouverture exige un tour complet de mesures connues
à au moins 5 cm, pour éviter les oscillations au seuil. La vitesse demandée
est également suspendue en cas d'accumulation supérieure à la limite du
téléski. L'état affiche alors « Excès de neige sur la ligne de montée —
damage nécessaire ». Toutes les mesures doivent redescendre au moins
20 cm sous cette limite avant la réouverture. La vitesse demandée
par le joueur est conservée dans l'état du mapmod, y compris en sauvegarde ;
un arrêt manuel reste un arrêt après le retour de la neige. Les remontées
éloignées de la caméra sont elles aussi contrôlées. Le contrôle est périodique,
sa latence dépend du nombre d'échantillons et de la cadence du jeu.

Les huit couloirs de montée, de 20 m de large, sont enregistrés dans le système
de damage natif et fermés aux descentes des clients. Leur identité suit le
GUID de la remontée et leur géométrie suit les virages et le terrain. Les
demandes d'entretien utilisent le même chemin que le bouton natif « Damer
maintenant » ; le garage, les employés, les horaires et les trajets des
dameuses restent gérés par le jeu. Une demande ne change pas la neige.
Lorsqu'une dameuse native parcourt effectivement le couloir en entretien,
sa lame écrête localement le surplus à 80 cm, sans apporter de neige aux
portions dénudées. Les caches et le rendu lisent le plan de neige natif
modifié. La réouverture dépend toujours des mesures de toute la ligne.
Le pont natif emploie l'opération de déneigement du moteur, bornée à 256
empreintes par appel et protégée par les empreintes des deux fonctions
complètes revues sur le build Steam 26178224. Les textures de lecture ne
sont pas utilisées pour modifier la neige.

Les poulies ordinaires Poma sont verticales et alignées sur la pente du
câble. Les câbles mobiles utilisent le matériau sans accumulation de neige.
Le maillage du câble du télésiège échantillonne sa spline native continue,
avec des anneaux partagés et des normales continues, y compris au bouclage.

## Vérification

`tests/test_surface_lift_geometry.lua` vérifie les huit axes sur le R16 réel,
les virages documentés, la garde au sol des câbles, le retour indépendant, les roues inclinées et la validation des vingt-quatre modèles.
`tests/test_surface_lift_native.lua` vérifie le refus des versions/dispositions
inconnues, les contrôles de distances et la restauration du cache.
`tests/test_surface_lift_cycle_snow.lua` vérifie la continuité du transfert,
les pinces fixes, le contact de l'assiette avec le passager et la détection
d'une portion déneigée au milieu du parcours, avec hystérésis à la réouverture.
`tests/test_surface_lift_pose.lua` vérifie l'appui des semelles sur des pentes
et dévers, la longueur des jambes, l'échantillonnage de profondeur et la rigidité
des pièces télescopiques. Les huit axes réels servent aussi à vérifier la portée
des perches fixes pour plusieurs épaisseurs de neige.
`tests/test_surface_lift_runtime.lua` vérifie les budgets de lecture sur un
long trajet et 10 000 visiteurs, les positions entre deux scans, les tableaux
réordonnés ou raccourcis, les associations malgré un décalage de phase natif,
les roues hors champ, la pause et le plafond de capture pendant les déplacements
de caméra. Les tests de cycle couvrent aussi une sortie de gare hors champ.
Les archives se construisent avec `skieomod build --check-scripts` lorsque `luac` 5.4 est installé ; les tests Lua utilisent également Lua 5.4.
Les essais visuels et les cycles de sauvegarde utilisent UE4SS dans une copie
isolée du jeu, avec Gamescope headless ; aucune touche ni activation de fenêtre
n'est nécessaire.
