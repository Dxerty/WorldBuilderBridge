bl_info = {
    "name": "World Builder Bridge",
    "author": "Alain BESANÇON + OpenAI",
    "version": (0, 37, 2),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > World Builder",
    "description": "Export / Import de scènes World Builder depuis Blender vers fichiers INI et FBX Unreal",
    "category": "Import-Export",
}

import bpy
import ctypes
import importlib.util
import re

from dataclasses import dataclass
from pathlib import Path
from math import degrees, radians

# ============================================================
# Constantes
# ============================================================

DEFAULT_MODE = "EXPORT"
VALID_MODES = {
    "EXPORT",
    "IMPORT",
}

COLLECTION_NAME = "Level_Imported"
CUSTOM_ID = "LevelTool_ID"
CUSTOM_PATH = "LevelTool_Path"

MAX_OBJECTS_WARNING = 100 # Seuil de nombre d'objets pour afficher un avertissement à la fin de l'export.

COLLISION_PREFIXES = (
    "UCX_",
    "UBX_",
    "USP_",
    "UCP_",
)

MB_ICONWARNING = MB_ICONEXCLAMATION = 0x30 # Valeur de MB_ICONWARNING et MB_ICONEXCLAMATION dans l'API Windows
MB_ICONINFORMATION = MB_ICONASTERISK = 0x40
MB_ICONERROR = MB_ICONSTOP = MB_ICONHAND = 0x10
MB_YESNO = 0x04
IDYES = 6

REQUIRED_CONFIG = {
    "general": ["mode"],
    "path": ["export_path", "fbx_root"],
    "options": [],
    "hidden_objects": [],
    "libraries": [],
    "positions": ["PX", "PY", "PZ"],
    "origins": ["OX", "OY", "OZ"],
}

REQUIRED_LIBRARY_GLOBALS = [
    "path_obj_s",
    "path_obj_ns",
    "tex_mat",
    "path_mat",
]

INI_SECTION = "[Next]"
INI_MESHLIST = f"{INI_SECTION}[MeshList]"
INI_CUSTOMDATA = f"{INI_SECTION}[CustomData]"


# ============================================================
# Interface Windows
# ============================================================

def modal_box(title, text, mode_1=None, mode_2=None, mode_3=None, icon=MB_ICONINFORMATION, buttons=0):
    """Affiche une boîte de dialogue Windows si disponible, sinon affiche le message dans la console.
    Retourne la valeur renvoyée par MessageBoxW (IDYES, etc.) ou None en mode console.
    """
    message = text

    if all(value is not None for value in (mode_1, mode_2, mode_3)):
        message += (
            "\n\n"
            f"Player can build upon: {mode_1}\n"
            f"Disable collision: {mode_2}\n"
            f"Huge draw distance: {mode_3}"
        )

    try:
        return ctypes.windll.user32.MessageBoxW(0, message, title, icon | buttons)
    except Exception:
        print(f"[{title}] {message}")
        return None


# ============================================================
# Dataclasses
# ============================================================

@dataclass
class TransformData:
    x: float
    y: float
    z: float

    pitch: float
    yaw: float
    roll: float

    sx: float
    sy: float
    sz: float


@dataclass
class MeshData:
    name: str
    mesh_ref: str
    unreal_path: str
    is_symmetric: bool
    transform: TransformData


@dataclass
class ImportStats:
    imported: int = 0
    duplicated: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0


# ============================================================
# Logger
# ============================================================

class Logger:
    def __init__(self, log_file: Path):
        self.log_file = log_file

    def clear(self):
        if self.log_file.is_file():
            self.log_file.unlink()

    def write(self, category: str, name: str, message: str):
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as file:
            file.write(
                f"[{category}]\n"
                f"Name   : {name}\n"
                f"Reason : {message}\n\n"
            )

    def has_errors(self) -> bool:
        return self.log_file.is_file()



# ============================================================
# Helpers Add-on
# ============================================================

def ensure_extension(path_value: str, extension: str) -> str:
    """Force une extension sur un chemin fichier Blender."""
    if not path_value:
        return path_value

    path = Path(bpy.path.abspath(path_value)).expanduser()
    if path.suffix.lower() != extension.lower():
        path = path.with_suffix(extension)
    return str(path)


def resolve_path(path_value: str) -> Path:
    if not path_value:
        raise ValueError("Chemin vide")
    return Path(bpy.path.abspath(path_value)).expanduser().resolve()


def bool_to_ini(value: bool) -> str:
    """Retourne true ou false en minuscules pour les CustomData Unreal."""
    return "true" if bool(value) else "false"


# ============================================================
# AddonConfigManager
# ============================================================

class AddonConfigManager:
    """Configuration issue du panneau Blender, sans config.ini."""

    def __init__(self, props, mode: str):
        self.props = props
        self.mode = mode
        self.py_folder = resolve_path(props.library_dir)
        self.fbx_root = resolve_path(props.fbx_dir)
        self.log_file = resolve_path(ensure_extension(props.log_file, ".log"))
        self.export_file = resolve_path(ensure_extension(props.export_file, ".ini")) if props.export_file else None
        self.import_file = resolve_path(props.import_file) if props.import_file else None

        # Valeurs héritées du script original. L'UI demandée ne les expose pas.
        self.config = {
            "positions": {"PX": "0", "PY": "0", "PZ": "0"},
            "origins": {"OX": "0", "OY": "0", "OZ": "0"},
        }

        # Dossier de travail utilisé par prepare_export_directory().
        if self.mode == "EXPORT" and self.export_file is not None:
            self.export_path = self.export_file.parent
        else:
            self.export_path = self.log_file.parent

    def validate(self) -> list[str]:
        errors = []

        if not self.py_folder.is_dir():
            errors.append(f"Dossier Librairies introuvable : {self.py_folder}")

        if not self.fbx_root.is_dir():
            errors.append(f"Dossier FBX introuvable : {self.fbx_root}")

        if not self.log_file.name.lower().endswith(".log"):
            errors.append("Le fichier log doit avoir l'extension .log")

        if self.mode == "EXPORT":
            if self.export_file is None:
                errors.append("Fichier export manquant")
            elif self.export_file.suffix.lower() != ".ini":
                errors.append("Le fichier export doit avoir l'extension .ini")

        if self.mode == "IMPORT":
            if self.import_file is None:
                errors.append("Fichier import manquant")
            elif not self.import_file.is_file():
                errors.append(f"Fichier import introuvable : {self.import_file}")

        return errors

    def get_export_file_path(self) -> Path:
        if self.export_file is None:
            raise RuntimeError("Fichier export non initialisé.")
        return self.export_file

    def get_log_file_path(self) -> Path:
        return self.log_file

    def get_import_file_path(self) -> Path:
        if self.import_file is None:
            raise RuntimeError("Fichier import non initialisé.")
        return self.import_file

    def prepare_export_directory(self, clear_export: bool):
        self.export_path.mkdir(parents=True, exist_ok=True)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        if clear_export:
            for file_path in (self.get_export_file_path(), self.get_log_file_path()):
                if file_path.is_file():
                    file_path.unlink()

    def get_options(self) -> list[str]:
        # Format attendu dans le fichier export :
        # Format attendu dans le fichier export :
        # [Next][CustomData]true / false
        # [Next][CustomData]true / false
        # [Next][CustomData]true / false
        return [
            bool_to_ini(self.props.player_can_build_upon),
            bool_to_ini(self.props.disable_collision),
            bool_to_ini(self.props.huge_draw_distance),
        ]

    def get_hidden_objects(self) -> list[str]:
        return []


# ============================================================
# LibraryManager
# ============================================================

class LibraryManager:
    def __init__(self, library_folder: Path, logger: Logger):
        self.library_folder = library_folder
        self.logger = logger
        self.modules = []

    def import_libraries(self):
        library_files = sorted(self.library_folder.glob("*.py"))

        if not library_files:
            self.logger.write("LIBRARY", str(self.library_folder), "aucune bibliothèque .py trouvée")
            return

        for library_file in library_files:
            library_name = library_file.stem

            try:
                spec = importlib.util.spec_from_file_location(library_name, library_file)
                if spec is None or spec.loader is None:
                    self.logger.write("LIBRARY", library_name, "impossible de créer le module")
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.modules.append(module)

                for name in REQUIRED_LIBRARY_GLOBALS:
                    if hasattr(module, name):
                        globals()[name] = getattr(module, name)

            except Exception as exc:
                self.logger.write("LIBRARY", library_name, f"erreur d'import : {exc}")

    def validate(self) -> bool:
        valid = True

        for variable_name in REQUIRED_LIBRARY_GLOBALS:
            if variable_name not in globals():
                self.logger.write(
                    "VARIABLE",
                    variable_name,
                    "variable globale manquante après import des bibliothèques",
                )
                valid = False

        return valid

# ============================================================
# BlenderUtils
# ============================================================

class BlenderUtils:
    @staticmethod
    def hide_objects(object_names: list[str]):
        hidden_names = set(object_names)

        for obj in bpy.context.scene.objects:
            base_name = obj.name.split(".")[0]
            if obj.name in hidden_names or base_name in hidden_names:
                obj.hide_set(True)

    @staticmethod
    def get_visible_meshes():
        return [obj for obj in bpy.context.visible_objects if obj.type == "MESH"]

    @staticmethod
    def get_import_collection(collection_name: str):
        collection = bpy.data.collections.get(collection_name)

        if collection is None:
            collection = bpy.data.collections.new(collection_name)
            bpy.context.scene.collection.children.link(collection)

        return collection

    @staticmethod
    def collection_exists(collection_name: str) -> bool:
        return bpy.data.collections.get(collection_name) is not None

    @staticmethod
    def link_to_collection(obj, collection):
        """
        Déplace réellement un objet dans la collection demandée.
        """
        if obj.name not in collection.objects.keys():
            collection.objects.link(obj)

        for other_collection in list(obj.users_collection):
            if other_collection != collection:
                try:
                    other_collection.objects.unlink(obj)
                except Exception:
                    pass

    @staticmethod
    def is_collision_mesh(obj) -> bool:
        """
        Détecte les meshes de collision Unreal.
        """
        return obj.name.upper().startswith(COLLISION_PREFIXES)

    @staticmethod
    def remove_collision_meshes(objects):
        """
        Supprime les meshes de collision Unreal sans jamais réutiliser
        les références Blender supprimées.

        Retourne une nouvelle liste d'objets valides.
        """
        valid_imported_objects = []
        removed = 0

        for obj in list(objects):
            try:
                obj_type = obj.type
                obj_name = obj.name
            except ReferenceError:
                continue

            if obj_type == "MESH" and obj_name.upper().startswith(COLLISION_PREFIXES):
                bpy.data.objects.remove(obj, do_unlink=True)
                removed += 1
                continue

            valid_imported_objects.append(obj)

        return valid_imported_objects, removed

    @staticmethod
    def link_imported_objects_to_collection(objects, collection):
        """
        Déplace tous les objets importés utiles dans la collection cible.
        Ignore les références invalidées par Blender.
        """
        for obj in list(objects):
            try:
                obj_name = obj.name
            except ReferenceError:
                continue

            if obj_name in bpy.data.objects:
                BlenderUtils.link_to_collection(obj, collection)

    @staticmethod
    def duplicate_object(source, collection):
        obj = source.copy()

        if source.data:
            obj.data = source.data.copy()

        collection.objects.link(obj)
        return obj

    @staticmethod
    def find_by_level_id(level_id: str):
        return [
            obj for obj in bpy.data.objects
            if obj.get(CUSTOM_ID) == level_id
        ]


# ============================================================
# ExportFileWriter
# ============================================================

class ExportFileWriter:
    def __init__(self, export_file: Path):
        self.export_file = export_file

    def write(self, data: str):
        self.export_file.parent.mkdir(parents=True, exist_ok=True)
        with self.export_file.open("a", encoding="utf-8") as file:
            file.write(data)

    def initialize_header(self, name: Path, x, y, z, px, py, pr):
        self.write(f"{INI_SECTION}{name.stem}\n")
        self.write(f"{INI_SECTION}X={x:.3f} Y={y:.3f} Z={z:.3f} \n")
        self.write(f"{INI_SECTION}P={px:.3f} Y={py:.3f} R={pr:.3f}\n")

    def write_mesh_name(self, path: str, name: str):
        self.write(f"{INI_MESHLIST}{path}.{name}\n")

    def write_position(self, position_type: str, x, y, z):
        if position_type == "T":
            self.write(f"{INI_MESHLIST}Translation: X={x:.3f} Y={y:.3f} Z={z:.3f}")
        elif position_type == "R":
            self.write(f" Rotation: P={x:.3f} Y={y:.3f} R={z:.3f}")
        elif position_type == "S":
            self.write(f" Scale: X={x:.3f} Y={y:.3f} Z={z:.3f}\n")

    def write_option(self, option: str):
        self.write(f"{INI_CUSTOMDATA}{option}\n")

    def write_texture_slot(self, cn_mat: int, subkey: str):
        self.write(f"{INI_CUSTOMDATA}{cn_mat}/{subkey}\n")

    def write_texture_path(self, material_path: str, material_name: str):
        self.write(f"{INI_CUSTOMDATA}{material_path}.{material_name}\n")


# ============================================================
# ExportFileReader
# ============================================================

class ExportFileReader:
    TRANSFORM_RE = re.compile(
        r"Translation:\s*X=([-0-9.]+)\s*Y=([-0-9.]+)\s*Z=([-0-9.]+)\s*"
        r"Rotation:\s*P=([-0-9.]+)\s*Y=([-0-9.]+)\s*R=([-0-9.]+)\s*"
        r"Scale:\s*X=([-0-9.]+)\s*Y=([-0-9.]+)\s*Z=([-0-9.]+)"
    )

    def __init__(self, export_file: Path, logger: Logger):
        self.export_file = export_file
        self.logger = logger

    def parse(self) -> list[MeshData]:
        meshes = []
        current = None

        if not self.export_file.is_file():
            self.logger.write("IMPORT", str(self.export_file), "fichier d'import introuvable")
            return meshes

        with self.export_file.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if line.startswith(INI_MESHLIST) and "Translation:" not in line:
                    mesh_ref = line.replace(INI_MESHLIST, "", 1)
                    object_name = mesh_ref.split(".")[-1]
                    current = {
                        "mesh_ref": mesh_ref,
                        "name": object_name,
                    }

                elif current and "Translation:" in line:
                    match = self.TRANSFORM_RE.search(line)

                    if not match:
                        self.logger.write("IMPORT", current["name"], "ligne de transformation invalide")
                        current = None
                        continue

                    values = list(map(float, match.groups()))
                    transform = TransformData(
                        x=values[0],
                        y=values[1],
                        z=values[2],
                        pitch=values[3],
                        yaw=values[4],
                        roll=values[5],
                        sx=values[6],
                        sy=values[7],
                        sz=values[8],
                    )

                    name = current["name"]
                    unreal_path, is_symmetric = self.resolve_unreal_path(name)

                    if unreal_path is None:
                        self.logger.write("IMPORT", name, "objet absent de path_obj_s et path_obj_ns")
                        current = None
                        continue

                    meshes.append(
                        MeshData(
                            name=name,
                            mesh_ref=current["mesh_ref"],
                            unreal_path=unreal_path,
                            is_symmetric=is_symmetric,
                            transform=transform,
                        )
                    )

                    current = None

        return meshes

    @staticmethod
    def resolve_unreal_path(object_name: str) -> tuple[str | None, bool]:
        if object_name in globals().get("path_obj_s", {}):
            return globals()["path_obj_s"][object_name], True

        if object_name in globals().get("path_obj_ns", {}):
            return globals()["path_obj_ns"][object_name], False

        return None, False


# ============================================================
# Exporter
# ============================================================

class Exporter:
    def __init__(self, config: AddonConfigManager, logger: Logger):
        self.config = config
        self.logger = logger
        self.writer = ExportFileWriter(config.get_export_file_path())
        self.cn_obj = 0
        self.cn_mat = 0

    @staticmethod
    def normalize_rotation(rotation: float) -> float:
        return ((rotation + 180) % 360) - 180

    def initialize_header(self):
        cfg = self.config.config

        self.writer.initialize_header(
            self.config.get_export_file_path(),
            int(cfg["positions"]["PX"]),
            int(cfg["positions"]["PY"]),
            int(cfg["positions"]["PZ"]),
            int(cfg["origins"]["OX"]),
            int(cfg["origins"]["OY"]),
            int(cfg["origins"]["OZ"]),
        )

    def export_object(self, obj) -> bool:
        name = obj.name.split(".")[0]

        if name in path_obj_s:
            coefficient_x = 1
            mesh_path = path_obj_s[name]
        elif name in path_obj_ns:
            coefficient_x = -1
            mesh_path = path_obj_ns[name]
        else:
            self.logger.write("OBJECT", obj.name, "non disponible dans la bibliothèque des objets")
            return False

        self.cn_obj += 1

        x, y, z = map(float, obj.location)
        a, b, c = map(degrees, obj.rotation_euler)
        sx, sy, sz = map(float, obj.scale)

        self.writer.write_mesh_name(mesh_path, name)
        self.writer.write_position("T", round(x, 3), round(y * -1, 3), round(z, 3))
        self.writer.write_position(
            "R",
            round(coefficient_x * self.normalize_rotation(b), 3),
            round(self.normalize_rotation(c) * -1, 3),
            round(self.normalize_rotation(a), 3),
        )
        self.writer.write_position("S", round(sx, 3), round(sy, 3), round(sz, 3))

        return True

    def set_options(self, options: list[str]):
        for option in options:
            self.writer.write_option(option)

    def set_textures(self, obj):
        obj_name = obj.name.split(".")[0]

        if obj_name not in tex_mat:
            self.logger.write("TEXTURE", obj_name, "non déclaré dans la bibliothèque des textures")
            return

        for subkey, subvalue in tex_mat[obj_name].items():
            if path_mat.get(subvalue):
                self.writer.write_texture_slot(self.cn_mat, subkey)
                if subvalue:
                    self.writer.write_texture_path(path_mat[subvalue], subvalue)
            else:
                self.logger.write(
                    "MATERIAL",
                    f"{subvalue} ({obj.name})",
                    "non disponible dans la bibliothèque des matériaux",
                )

        self.cn_mat += 1

    def finish(self, options: list[str]):
        if self.cn_obj < 1:
            modal_box("Erreur", "Aucun objet à exporter", icon=MB_ICONSTOP)
            return

        if self.logger.has_errors():
            modal_box("Erreur", "Des erreurs ont été détectées. Voir le fichier de log du mode courant.", icon=MB_ICONSTOP)
            return

        if self.cn_obj > MAX_OBJECTS_WARNING:
            modal_box(
                "Avertissement",
                f"Le nombre d'objets est supérieur à {MAX_OBJECTS_WARNING} ({self.cn_obj})",
                icon=MB_ICONWARNING,
            )
            return

        option_values = options + ["", "", ""]
        modal_box(
            "Succès",
            f"L'exportation s'est terminée avec succès [{self.cn_obj} objets]",
            option_values[0],
            option_values[1],
            option_values[2],
            MB_ICONINFORMATION,
        )

    def run(self):
        export_file = self.config.get_export_file_path()
        if export_file.exists():
            result = modal_box(
                "Confirmation",
                f"Le fichier existe déjà :\n{export_file}\n\nVoulez-vous l'écraser ?",
                icon=MB_ICONWARNING,
                buttons=MB_YESNO,
            )
            if result not in (IDYES, None):
                return

        self.config.prepare_export_directory(clear_export=True)

        options = self.config.get_options()
        hidden_objects = self.config.get_hidden_objects()

        BlenderUtils.hide_objects(hidden_objects)

        self.initialize_header()

        exported_objects = []

        for obj in BlenderUtils.get_visible_meshes():
            if export_object := self.export_object(obj):
                exported_objects.append(obj)

        self.set_options(options)

        for obj in exported_objects:
            self.set_textures(obj)

        self.finish(options)


# ============================================================
# Importer
# ============================================================

class Importer:
    def __init__(self, config: AddonConfigManager, logger: Logger):
        self.config = config
        self.logger = logger
        self.reader = ExportFileReader(config.get_import_file_path(), logger)
        self.fbx_cache = {}
        self.stats = ImportStats()

        self.collection_name = self.get_import_collection_name()
        self.collection = None

    def get_import_collection_name(self) -> str:
        import_file = self.config.get_import_file_path()
        safe_name = import_file.stem.replace(" ", "_")
        return f"{COLLECTION_NAME}_{safe_name}"

    def collection_already_exists(self) -> bool:
        return BlenderUtils.collection_exists(self.collection_name)

    @staticmethod
    def unreal_path_to_fbx_path(unreal_path: str, fbx_root: Path) -> Path:
        """
        Convertit un chemin Unreal / mod en chemin disque .fbx.

        Exemples :
            /Game/Packs/A/B/SM_Test       -> <fbx_root>/Packs/A/B/SM_Test.fbx
            Game/Packs/A/B/SM_Test        -> <fbx_root>/Packs/A/B/SM_Test.fbx
            /RR_Mod/Test/Mesh/SM_Test     -> <fbx_root>/RR_Mod/Test/Mesh/SM_Test.fbx
            /KAWoodS/Test/Mesh/SM_Test    -> <fbx_root>/KAWoodS/Test/Mesh/SM_Test.fbx
        """
        relative_path = unreal_path.strip().replace("\\", "/")

        if relative_path.startswith("/Game/"):
            relative_path = relative_path[len("/Game/"):]
        elif relative_path.startswith("Game/"):
            relative_path = relative_path[len("Game/"):]
        else:
            relative_path = relative_path.lstrip("/")

        return fbx_root / f"{relative_path}.fbx"

    def find_fbx_file(self, mesh: MeshData) -> Path | None:
        if self.config.fbx_root is None:
            self.logger.write("IMPORT_FBX", mesh.name, "fbx_root non initialisé")
            return None

        return self.unreal_path_to_fbx_path(mesh.unreal_path, self.config.fbx_root)

    def import_fbx(self, mesh: MeshData):
        fbx_file = self.find_fbx_file(mesh)

        if fbx_file is None:
            self.stats.errors += 1
            return None

        if not fbx_file.is_file():
            self.logger.write("IMPORT_FBX", mesh.name, f"fichier introuvable : {fbx_file}")
            self.stats.errors += 1
            return None

        before_objects = set(bpy.data.objects)

        try:
            bpy.ops.import_scene.fbx(filepath=str(fbx_file))
        except Exception as exc:
            self.logger.write("IMPORT_FBX", mesh.name, f"échec import FBX : {exc}")
            self.stats.errors += 1
            return None

        after_objects = set(bpy.data.objects)
        imported_objects = list(after_objects - before_objects)

        imported_objects, removed_collisions = BlenderUtils.remove_collision_meshes(imported_objects)
        if removed_collisions:
            print(f"[IMPORT_FBX] {mesh.name}: {removed_collisions} mesh(es) de collision ignoré(s)")

        imported_objects = [
            obj for obj in imported_objects
            if obj.name in bpy.data.objects
        ]

        # Déplacer tous les objets utiles importés dans Level_Imported.
        # Important pour les FBX Unreal qui créent un Empty parent.
        BlenderUtils.link_imported_objects_to_collection(imported_objects, self.collection)

        mesh_objects = []

        for obj in imported_objects:
            try:
                if obj.type == "MESH" and not BlenderUtils.is_collision_mesh(obj):
                    mesh_objects.append(obj)
            except ReferenceError:
                continue

        if not mesh_objects:
            self.logger.write("IMPORT_FBX", mesh.name, "aucun mesh visuel importé")
            self.stats.errors += 1
            return None

        obj = max(
            mesh_objects,
            key=lambda candidate: len(candidate.data.vertices) if candidate.data else 0,
        )
        obj.name = mesh.name

        obj[CUSTOM_ID] = mesh.unreal_path
        obj[CUSTOM_PATH] = mesh.unreal_path

        self.fbx_cache[mesh.unreal_path] = obj
        self.stats.imported += 1

        extra_index = 0

        for extra_obj in mesh_objects:
            extra_obj[CUSTOM_ID] = mesh.unreal_path
            extra_obj[CUSTOM_PATH] = mesh.unreal_path

            if extra_obj != obj:
                extra_obj.name = f"{mesh.name}_extra_{extra_index:02d}"
                extra_index += 1

        for imported_obj in imported_objects:
            if imported_obj.type != "MESH":
                imported_obj[CUSTOM_ID] = mesh.unreal_path
                imported_obj[CUSTOM_PATH] = mesh.unreal_path

        return obj

    def get_or_import_object(self, mesh: MeshData):
        if mesh.unreal_path in self.fbx_cache:
            source = self.fbx_cache[mesh.unreal_path]
            obj = BlenderUtils.duplicate_object(source, self.collection)
            obj.name = mesh.name
            obj[CUSTOM_ID] = mesh.unreal_path
            obj[CUSTOM_PATH] = mesh.unreal_path
            self.stats.duplicated += 1
            return obj

        return self.import_fbx(mesh)

    def apply_transform(self, obj, mesh: MeshData):
        t = mesh.transform

        coefficient_x = 1 if mesh.is_symmetric else -1

        obj.location = (
            t.x,
            t.y * -1,
            t.z,
        )

        obj.rotation_euler = (
            radians(t.roll),
            radians(coefficient_x * t.pitch),
            radians(t.yaw * -1),
        )

        obj.scale = (
            t.sx,
            t.sy,
            t.sz,
        )

    def run(self):
        self.config.prepare_export_directory(clear_export=False)

        if self.collection_already_exists():
            modal_box(
                "Import annulé",
                f"La collection existe déjà :\n{self.collection_name}\n\n"
                "Import ignoré pour éviter les doublons.",
                icon=MB_ICONWARNING,
            )
            return

        self.collection = BlenderUtils.get_import_collection(
            self.collection_name
        )

        meshes = self.reader.parse()

        for mesh in meshes:
            obj = self.get_or_import_object(mesh)

            if obj is None:
                self.stats.skipped += 1
                continue

            self.apply_transform(obj, mesh)

        self.show_result("Import terminé")

    def show_result(self, title: str):
        message = (
            f"Imported  : {self.stats.imported}\n"
            f"Duplicated: {self.stats.duplicated}\n"
            f"Updated   : {self.stats.updated}\n"
            f"Skipped   : {self.stats.skipped}\n"
            f"Errors    : {self.stats.errors}"
        )

        if self.logger.has_errors():
            modal_box(title, message + "\n\nVoir le fichier de log du mode courant.", icon=MB_ICONWARNING)
        else:
            modal_box(title, message, icon=MB_ICONINFORMATION)




# ============================================================
# Add-on UI / Operators
# ============================================================

class WBB_Properties(bpy.types.PropertyGroup):
    library_dir: bpy.props.StringProperty(
        name="Dossier Librairies",
        subtype="DIR_PATH",
        description="Dossier contenant les bibliothèques Python d'assets",
    )
    fbx_dir: bpy.props.StringProperty(
        name="Dossier FBX",
        subtype="DIR_PATH",
        description="Racine des FBX Unreal",
    )
    log_file: bpy.props.StringProperty(
        name="Fichier log (.log)",
        subtype="FILE_PATH",
        description="Fichier de log, extension .log forcée au lancement",
    )
    mode: bpy.props.EnumProperty(
        name="Mode",
        items=(
            ("EXPORT", "Export", "Afficher les paramètres d'export"),
            ("IMPORT", "Import", "Afficher les paramètres d'import"),
        ),
        default="EXPORT",
    )
    export_file: bpy.props.StringProperty(
        name="Fichier export (.ini)",
        subtype="FILE_PATH",
        description="Fichier INI généré, extension .ini forcée au lancement",
    )
    player_can_build_upon: bpy.props.BoolProperty(
        name="Player can build upon",
        default=False,
    )
    disable_collision: bpy.props.BoolProperty(
        name="Disable collision",
        default=False,
    )
    huge_draw_distance: bpy.props.BoolProperty(
        name="Huge draw distance",
        default=False,
    )
    import_file: bpy.props.StringProperty(
        name="Fichier import (.ini)",
        subtype="FILE_PATH",
        description="Fichier INI à importer",
    )


def build_context(mode: str):
    props = bpy.context.scene.world_builder_bridge
    config = AddonConfigManager(props, mode)
    errors = config.validate()

    logger = Logger(config.get_log_file_path())
    logger.clear()

    if errors:
        for error in errors:
            logger.write("CONFIG", "World Builder Bridge", error)
        return None, logger, errors

    library_manager = LibraryManager(config.py_folder, logger)
    library_manager.import_libraries()

    if not library_manager.validate():
        return None, logger, ["Bibliothèques incomplètes. Voir le fichier log."]

    return config, logger, []


class WBB_OT_export(bpy.types.Operator):
    bl_idname = "wbb.export"
    bl_label = "Lancer Export"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.world_builder_bridge
        props.export_file = ensure_extension(props.export_file, ".ini")
        props.log_file = ensure_extension(props.log_file, ".log")

        config, logger, errors = build_context("EXPORT")
        if config is None:
            message = "\n".join(errors) if errors else "Erreur inconnue"
            self.report({"ERROR"}, message)
            modal_box("Erreur Export", message, icon=MB_ICONERROR)
            return {"CANCELLED"}

        try:
            Exporter(config, logger).run()
        except Exception as exc:
            logger.write("EXPORT", "Exception", str(exc))
            self.report({"ERROR"}, str(exc))
            modal_box("Erreur Export", str(exc), icon=MB_ICONERROR)
            return {"CANCELLED"}

        self.report({"INFO"}, "Export terminé")
        return {"FINISHED"}


class WBB_OT_import(bpy.types.Operator):
    bl_idname = "wbb.import"
    bl_label = "Lancer Import"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.world_builder_bridge
        props.log_file = ensure_extension(props.log_file, ".log")

        config, logger, errors = build_context("IMPORT")
        if config is None:
            message = "\n".join(errors) if errors else "Erreur inconnue"
            self.report({"ERROR"}, message)
            modal_box("Erreur Import", message, icon=MB_ICONERROR)
            return {"CANCELLED"}

        try:
            Importer(config, logger).run()
        except Exception as exc:
            logger.write("IMPORT", "Exception", str(exc))
            self.report({"ERROR"}, str(exc))
            modal_box("Erreur Import", str(exc), icon=MB_ICONERROR)
            return {"CANCELLED"}

        self.report({"INFO"}, "Import terminé")
        return {"FINISHED"}


class WBB_PT_panel(bpy.types.Panel):
    bl_label = "World Builder Bridge"
    bl_idname = "WBB_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "World Builder"

    def draw(self, context):
        layout = self.layout
        props = context.scene.world_builder_bridge

        layout.label(text="Général")
        box = layout.box()
        box.prop(props, "library_dir")
        box.prop(props, "fbx_dir")
        box.prop(props, "log_file")
        box.prop(props, "mode")

        layout.separator()

        if props.mode == "EXPORT":
            layout.label(text="EXPORT")
            box = layout.box()
            box.prop(props, "export_file")
            box.prop(props, "player_can_build_upon")
            box.prop(props, "disable_collision")
            box.prop(props, "huge_draw_distance")
            box.operator("wbb.export", text="Lancer Export", icon="EXPORT")

        elif props.mode == "IMPORT":
            layout.label(text="IMPORT")
            box = layout.box()
            box.prop(props, "import_file")
            box.operator("wbb.import", text="Lancer Import", icon="IMPORT")


classes = (
    WBB_Properties,
    WBB_OT_export,
    WBB_OT_import,
    WBB_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.world_builder_bridge = bpy.props.PointerProperty(type=WBB_Properties)


def unregister():
    if hasattr(bpy.types.Scene, "world_builder_bridge"):
        del bpy.types.Scene.world_builder_bridge
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
