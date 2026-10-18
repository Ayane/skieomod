# Inventaire local du jeu 25970577 — 16 octobre 2026

Comparaison de la liste des ressources du jeu conservée le 8 octobre avec
`SkiResortSimulator-Windows.utoc` du build Steam 25970577, puis inspection des
classes et objets par UE4SS dans une session de test séparée. Les fichiers
de travail sont dans `build/game-content-25970577/` : `asset-diff.json`,
`new-placeables.json`, le SDK et les validations des cartes. Cette comparaison
porte sur les données locales, sans prétendre reconstituer un changelog officiel.

Les listes contiennent 2 322 puis 2 391 ressources `.uasset`. Le différentiel
brut compte 95 ajouts et 26 suppressions, dont 14 changements de casse :
81 ajouts et 12 suppressions après rapprochement de ces noms.

## Objets et variantes

Quatorze nouvelles classes de décoration sont présentes et plaçables :

| Classe `BP_…` | Usage / variantes natives vérifiées |
| --- | --- |
| `ParkBench` | Banc |
| `SkiRack` | `OneSided`, `TwoSided` |
| `FrenchTable` | Table |
| `UmbrellaTable` | Table avec parasol |
| `Planter` | `LowBox`, `TallBox`, `Cylinder` |
| `TrailMarkers` | `Beginner` (vert), `Intermediate` (bleu), `Expert` (noir) |
| `TrashPile` | Sacs, cartons, tas divers |
| `BlackCatStandee`, `WitchStandee` | Décors saisonniers |
| `Gravestone`, `HangingGhost` | Plusieurs variantes |
| `Pumpkin`, `JackOLantern`, `PumpkinPile` | Formes et couleurs |

Les trois anciennes classes de panneaux `TrailMarkersBlack/Blue/Green`
ont disparu ; le panneau unique utilise maintenant `BuildingActor.ApplyVariant`.
Le chargeur applique cette fonction avant la finalisation du placement,
et le format de scène accepte une propriété `variant`. Les modifications
de `VariantId` passent également par cette fonction native.
Le catalogue de l'éditeur est actualisé à partir des valeurs réelles des CDO.
Leurs valeurs brutes ne constituent pas un tarif historique : les décorations
n'héritent pas des charges d'installation propres au scénario Saint-Bernard.

## Autres systèmes observés

- Peinture des chemins : nouveaux sous-systèmes et `DA_PathStyles` avec terre,
  gravier, pavés et briques chauffées. L'asset est bien configuré dans le monde
  source des cartes personnalisées. Aucun chemin n'a été peint artificiellement
  par une fonction native privée ; les tracés restent à réaliser avec les outils
  du jeu. Les raccords de hubs existants sont conservés.
- Neige : `DA_SnowLook`, tableaux de textures et nouvelles couvertures de neige
  pour certains meubles. Les objets placés conservent leur comportement natif.
- Ciel : matériau en couches et composant de ciel du contrôleur d'environnement.
- Personnel : nouvelles données de véhicules et d'état de pause dans les classes
  natives. Les cartes continuent de laisser le jeu gérer leurs employés.
- `BP_LitterProp`, animation de marche et nouvelles actions d'entrée figurent
  aussi dans le différentiel. Leur présence ne suffit pas à attribuer un nouveau
  comportement complet à chaque carte.

Aucune nouvelle classe de remontée ni nouveau type de téléski n'a été trouvé.
Le Plan du Jeu conserve donc sa représentation avec le siège à une place.

## Intégration aux cartes

| Carte | Version | Panneaux de piste | Autre mobilier | Total |
| --- | --- | ---: | ---: | ---: |
| Veymont | 0.7.7 | 40 | 14 | 54 |
| Super Saint-Bernard | 0.2.4 | 8 | 6 | 14 |

Le mobilier est placé près des ancres géographiques existantes : billetterie,
restauration, abri et départs des pistes. Il s'agit d'un aménagement proposé,
pas d'un relevé historique. Les décorations Halloween restent disponibles dans
le catalogue sans être imposées aux stations d'hiver.

Chaque objet reçoit un identifiant stable propre à la carte. La création est
réservée aux parties neuves : une sauvegarde ne recrée pas le mobilier supprimé
par le joueur. Les variantes sont sérialisées par le jeu dans `CustomData.Variant`.

L'inspection répétée des CDO a aussi révélé un crash natif pendant les essais.
Le chargeur conserve désormais des références Unreal fortes sur les classes et
leurs CDO avant leur lecture. Un export répété après collecte mémoire a réussi
avec ce correctif. Cela corrige le cas reproduit, sans établir que le crash
signalé par l'utilisateur avait nécessairement la même origine.

## Validation et limite de rendu

Les deux cartes ont été chargées jusqu'à la fin de la création du terrain et
de la station via UE4SS : 54 décorations, 13 bâtiments et neuf remontées pour
Veymont ; 14 décorations, cinq bâtiments et deux remontées pour Saint-Bernard.
Le contrôle des emprises du mobilier hors panneaux ne trouve pas d'intersection
avec les bâtiments. Les variantes natives et leurs données de sauvegarde ont
été lues en jeu. La régression comporte 229 tests Python et 67 fichiers Lua,
ainsi qu'une installation de distribution dans un environnement isolé.

Un défaut visuel reste ouvert : certains rubans de piste apparaissent noirs
sur la neige avec ce build. `TrailLineActor.MeshComponent` utilise maintenant
`SurfaceRiderMeshComponent`, à la place du composant procédural précédent.
Les essais de matériau, visibilité et géométrie dans la session de test n'ont
pas permis de résoudre ce rendu. Ces essais ne sont pas livrés dans le code.
Ce défaut n'a pas empêché les validations de chargement et de mobilier.
