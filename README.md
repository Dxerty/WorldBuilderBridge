<p align="center">
  <picture>
    <img src="https://www.relentlessworld.fr/wbb_logo.png" alt="Logo WorldBuilderBridge" width="900">
  </picture>
</p>

![Windows](https://img.shields.io/badge/Windows-10-blue) ![Windows](https://img.shields.io/badge/Windows-11-blue) ![Blender](https://img.shields.io/badge/Blender-4.x-orange) ![Blender](https://img.shields.io/badge/Blender-5.x-red) ![Python](https://img.shields.io/badge/Python-3.x-blue) ![Status](https://img.shields.io/badge/Status-Active-success)

## Vue d'ensemble

World Builder Bridge est un add-on Blender pour éditer de manière visuelle les fichiers .ini du mod World Builder.

Cet outil vous permet de créer des scènes dans Blender et de générer automatiquement un fichier `.ini` compatible avec World Builder.

Le fichier exporté peut ensuite être importé directement dans le mod afin de reconstruire la scène en jeu sans avoir à placer chaque objet manuellement dans la limite de 100 objets.

---

## Fonctionnalités

- Exportation des scènes Blender au format World Builder (`.ini`)
- Importation de fichiers World Builder (`.ini`) dans Blender
- Importation automatique des ressources FBX
- Réutilisation automatique des ressources FBX
- Gestion de la bibliothèque d'objets Unreal Engine
- Suppression automatique des maillages de collision Unreal (`UCX_`, `UBX_`, `USP_`, `UCP_`)
- Flux de travail intégré à Blender
- Validation automatique des fichiers de configuration et des bibliothèques
- Journalisation des erreurs pour l'exportation et l'importation

> [!NOTE]
Les ressources FBX doivent être exportées à partir du DevKit.
---

## Importation

World Builder Bridge peut recréer directement dans Blender une scène à parir d'un fichier au format `.ini` World Builder .

Pendant l'importation :

- Les ressources FBX sont importées automatiquement depuis la bibliothèque configurée.
- Les maillages de collision Unreal (`UCX_`, `UBX_`, `USP_`, `UCP_`) sont supprimés automatiquement.
- Les objets importés sont placés dans une collection Blender dédiée nommée :

```text
Level_Imported_<ini_filename>
```

- L'importation est annulée si cette collection existe déjà, afin d'éviter les doublons accidentels.

### Importation

L'option d'importation ne permet pas de fusion dans une scène sous Blender. Chaque fichier `.ini` doit donc être importé indépendamment.

> [!NOTE]
World Builder stocke les coordonnées des objets relativement à l'origine de la scène plutôt qu'en coordonnées absolues. La fusion de plusieurs importations modifie donc le référentiel et entraîne un mauvais positionnement des objets.



---

## Limitation du mod World Builder

> [!IMPORTANT]  
Le mod World Builder est actuellement limité à **100 objets par exportation**.

Pour garantir un fonctionnement correct, il est recommandé de :

- Limiter chaque fichier `.ini` à 100 objets maximum.
- Diviser les grandes scènes en plusieurs exportations.
- Effectuer plusieurs importations dans World Builder si nécessaire.

---

## Options d'exportation

### Player Can Build Upon

Permet aux joueurs de construire ou de placer des structures supplémentaires sur l'objet en jeu.

Exemples :

- Sols
- Fondations
- Plateformes
- Toits accessibles

### Disable Collision

Désactive les surfaces de collision de l'objet en jeu.

Lorsque cette option est activée :

- Les joueurs peuvent traverser l'objet.
- Les créatures peuvent le traverser.
- Les véhicules peuvent le traverser.
- L'objet reste visible mais n'interagit plus physiquement avec le monde.

### Huge Draw Distance

Augmente considérablement la distance de visibilité des objets.

Cette option est recommandée pour :

- Bâtiments
- Tours
- Monuments
- Repères visuels
- Grandes structures visibles de loin

> [!CAUTION]
> Une utilisation excessive peut affecter les performances.

---

## Compatibilité

- Blender 4.x / 5.x
- Windows 10 / 11

---

## Licence

[![Licence : GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
