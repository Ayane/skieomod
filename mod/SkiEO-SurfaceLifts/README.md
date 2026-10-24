# Téléskis à perches

Mapmod `community.surface-lifts` 0.1.0 pour Veymont et les autres cartes.
Il ajoute des gares Poma, des pylônes simples et de virage, les câbles et les
perches à assiette. Les modèles sont originaux, générés dans Blender par
[build_surface_lift_models.py](../../tools/build_surface_lift_models.py).
Les photographies de référence ne sont pas redistribuées.

```sh
skieomod build mod/SkiEO-SurfaceLifts --check-scripts
skieomod run mod/SkiEO-Veymont --dependency mod/SkiEO-Foxes --dependency mod/SkiEO-SurfaceLifts
```

Le chargeur doit inclure `api:configure_surface_lifts`. Le mapmod utilise
uniquement la permission `gameplay`. Les modèles SKPM et leur palette PNG sont
des fichiers portables ; aucun niveau Unreal cuit ni logiciel Blender n'est
nécessaire pour jouer.

La carte déclare la dépendance `community.surface-lifts =0.1.0` et les lignes
sous `extensions.community.surface-lifts.lifts`. Les gares du Blanchon sont
décrites séparément dans `extensions.community.surface-lifts.chairlifts`. Chaque ligne identifie une
remontée native existante par son nom et son départ, puis mémorise son GUID.
Une remontée supprimée dans une sauvegarde n'est pas recréée. Les files,
affectations, tarifs, usure, compteurs et sauvegardes restent gérés par le jeu.
La cabine native invisible fournit une place debout ; le trajet suit la neige.
Les modèles et la représentation du câble sont recréés à la reprise.
Les skis et snowboards natifs restent fixés aux pieds et produisent les traces natives.
Les perches en charge s’inclinent pour tracter le passager.
À proximité, le squelette équipé du jeu place le coude sous l'entrejambe et
l'assiette derrière les cuisses : une main saisit la perche et l'autre porte
les deux bâtons. Les snowboardeurs gardent leur planche rigide, saisissent la
perche de la main avant et placent l'assiette sous la cuisse avant, sans bâtons.

Le retour des TKD reste haut et franchit les pylônes bas. Deux roues de guidage
raccordent les brins à la grande roue motrice inclinée, par des tangentes communes.
Le câble passe dans les gorges, entre les flasques. Les perches libres restent
verticales et leurs rondelles restent perpendiculaires à la tige. La tige fine
coulisse dans le gros fourreau inférieur des TKD ; les TKF restent rigides.
Les têtes Poma portent une poulie sous le câble puis une au-dessus, avec le
retour sur l’autre côté du mât. Les poulies de guidage restent verticales et
leurs plans suivent la pente du câble ;
les trains de galets du télésiège sont inclinés de la même façon.

Les coordonnées des routes sont en centimètres ; vitesse et débit sont en m/s
et personnes/heure. `kind` distingue `detachable_platter` de `fixed_platter`.
Les points intermédiaires OSM sont conservés. Lorsque les pylônes ne sont pas
cartographiés, leur répartition est une approximation qui conserve les virages.
Les câbles sont relevés si nécessaire pour éviter de traverser le terrain.
Le retour des perches est vide ; le transport descendant est désactivé.

Le nom affiché dans le jeu est « Surface lifts ». Le rendu limite les perches
en ligne aux 64 plus proches, dans un rayon de 180 m, et les perches en stock
aux 64 plus proches dans le même rayon, sans limiter les passagers simulés.
La pose squelettique détaillée concerne au plus 16 passagers à moins de 60 m ;
les autres conservent le rendu équipé natif.
Les TKD conservent un stock de perches identifié et sauvegardé : chaque retour glisse
sur les guides tubulaires jusqu’à sa place dans la file. Le départ attend un skieur
et la distance minimale avec la perche précédente, sans lancement à vide. La commande native arrêt/vitesse et la pause contrôlent
le déplacement par le moteur du jeu.
La sortie de gare suit la distance totale parcourue par le câble, même hors
champ. Chaque skieur conserve sa perche, qui tracte depuis l'avant.

La reconstitution n'est pas un relevé industriel : dimensions des pièces,
flèche des câbles et équipements sans mesure publiée sont interprétés. Le
Pré Levé possède sa couverture allongée et son retour à débrayage ; les Pras ont leur portique carré, les Alleyrons leur retour à treillis et
les Bessards une gare fixe sans stockage. Les gares vitrées/ouvertes du Blanchon
complètent son télésiège natif. Voir les sources et les
hypothèses dans [surface-lifts.md](../../docs/surface-lifts.md).

Compatibilité : chargeur de cette branche, jeu Steam **26178224**
vérifiés par empreinte, avec UE4SS **1181**. Toutes les roues de transport tournent
selon le déplacement réel du câble. Les mâchoires des pinces ne sont pas animées.
Le moteur, l'arrivée des perches et le passage aux supports disposent de sons
synthétisés, spatialisés et soumis au volume SFX du jeu.
Une portion de montée sous 3 cm de neige ferme le téléski ; la réouverture
requiert au moins 5 cm sur toute la ligne et respecte l'arrêt manuel. L'excès
de neige ferme aussi la remontée : au-delà de 150 cm pour les TKF et 250 cm
pour les TKD, avec une marge de 20 cm avant réouverture.

Chaque montée possède un couloir d'entretien de 20 m, fermé aux descentes.
Les tâches de damage utilisent les dameuses et employés natifs du garage.
Le passage réel d'une dameuse écrête le surplus à 80 cm sous sa lame ; une
demande de travail seule ne modifie pas la neige. L'absence de dameuse ou
de personnel laisse la remontée fermée tant que la ligne reste impraticable.
Les câbles mobiles utilisent un matériau sans accumulation de neige ; celui
du télésiège suit une courbe continue sur tout son parcours.
