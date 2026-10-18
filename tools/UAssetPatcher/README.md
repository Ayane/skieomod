# UAssetPatcher

Petit outil ciblé sur le niveau 2017 × 2017 du build Steam 25551097. Il sait
patcher deux types de packages :

- `extract-initial-save` extrait l'archive `GVAS` embarquée dans un
  `InitialSaveAsset`, qui contient notamment remontées, pistes et bâtiments ;
- `patch-map` renomme la carte, choisit le biome Alpes, applique l'échelle de
  Veymont, recalcule les 1024 bornes de composants et référence le nouvel asset
  d'obstacles ;
- `patch-obstacles` décode les enregistrements `SKOB`, échantillonne le R16 par
  interpolation bilinéaire et remplace l'altitude des 255 667 obstacles avant
  de renommer leur package ;
- `redistribute-obstacles` remplace aussi leurs X/Y depuis un flux `SKXY`
  généré à partir des polygones forestiers OSM, avec les emprises des pistes,
  remontées et de la billetterie déjà déboisées ;
- `patch-collision` reconstruit les 1024 heightfields Chaos 64 × 64, leurs
  niveaux de bornes 11 × 11 et les `CachedLocalBox` depuis le R16 ;
- `rename-package` renomme un asset cuit et `replace-reference` remplace une
  référence de package, notamment pour installer la texture de hauteur
  grossière propre au Veymont qu'utilise le matériau de neige.

Il dépend de la révision UAssetAPI indiquée dans l'analyse :

```bash
git clone https://github.com/atenfyr/UAssetAPI third_party/UAssetAPI
dotnet build tools/UAssetPatcher/UAssetPatcher.csproj -c Release
```

Utilisation :

```text
UAssetPatcher extract-initial-save ASSET MAPPINGS OUTPUT
UAssetPatcher patch-map ASSET MAPPINGS OUTPUT R16 OLD_PACKAGE NEW_PACKAGE
UAssetPatcher patch-obstacles ASSET MAPPINGS OUTPUT R16 OLD_PACKAGE NEW_PACKAGE
UAssetPatcher redistribute-obstacles ASSET MAPPINGS OUTPUT R16 SKXY OLD_PACKAGE NEW_PACKAGE
UAssetPatcher patch-collision ASSET MAPPINGS OUTPUT R16
UAssetPatcher rename-package ASSET MAPPINGS OUTPUT OLD_PACKAGE NEW_PACKAGE
UAssetPatcher replace-reference ASSET MAPPINGS OUTPUT OLD_REFERENCE NEW_REFERENCE
```

L'asset d'obstacles utilise un en-tête `SKOB` de 48 octets suivi
d'enregistrements de 19 octets. Les positions X/Y/Z y sont quantifiées au
dixième de centimètre relativement aux minima stockés dans l'en-tête.

La lecture des propriétés non versionnées exige le fichier USMAP généré avec
UE4SS sur ce build. Voir `docs/format-analysis.md` pour le pipeline complet.
