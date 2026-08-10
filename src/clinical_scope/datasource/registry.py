import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import ClassVar

import clinical_scope.constants as cst
from clinical_scope.datasource.base import DataSourceBase
from clinical_scope.datasource.sources.edf import find_load_format as _edf
from clinical_scope.datasource.sources.eit import find_load_format as _eit
from clinical_scope.datasource.sources.fluxmed_parameters import (
    find_load_format as _fluxmed_parameters,
)
from clinical_scope.datasource.sources.fluxmed_signals import (
    find_load_format as _fluxmed_signals,
)
from clinical_scope.datasource.sources.mindray_respi_numerics import (
    find_load_format as _mindray_respi_num,
)
from clinical_scope.datasource.sources.mindray_respi_waves import (
    find_load_format as _mindray_respi_waves,
)
from clinical_scope.datasource.sources.mindray_scope import (
    find_load_format as _mindray_scope,
)
from clinical_scope.datasource.sources.other import find_load_format as _other
from clinical_scope.datasource.sources.philips_numerics import (
    find_load_format as _philips_numerics,
)
from clinical_scope.datasource.sources.philips_waves import (
    find_load_format as _philips_waves,
)
from clinical_scope.datasource.sources.servo_u import find_load_format as _servo_u
from clinical_scope.datasource.sources.syringe import find_load_format as _syringe
from clinical_scope.io.file_utils import (
    folder_has_real_content,
    folder_name_matches_keywords,
    is_junk_file,
)
from clinical_scope.signal_container import Signal

# ==================================================================================================
logger = logging.getLogger(__name__)

# DataSourceBase.main: (patient_options, database_options_specific, display_fallbacks=None).
# Spelled with ... because display_fallbacks is optional and most callers omit it.
MainModule = Callable[..., list[Signal]]


# ==================================================================================================
def add_main_module(find_load_format_module: ModuleType) -> Callable[[type], type]:
    """Decorator factory: registers a datasource from its find_load_format module."""

    def decorator(cls: type) -> type:
        module = find_load_format_module

        cls.DATASOURCE_CLASS = next(
            (
                candidate
                for candidate in vars(module).values()
                if isinstance(candidate, type)
                and issubclass(candidate, DataSourceBase)
                and candidate is not DataSourceBase
            ),
            None,
        )

        options = cls.DATASOURCE_CLASS.OPTIONS_MODULE if cls.DATASOURCE_CLASS else None

        datasource_name = getattr(options, "DATASOURCE_NAME", None)
        if datasource_name is not None and datasource_name != cls.NAME:
            msg = (
                f"DataSource registry NAME={cls.NAME!r} does not match "
                f"options.DATASOURCE_NAME={datasource_name!r}"
            )
            raise ValueError(msg)

        cls.MAIN_MODULE = cls.DATASOURCE_CLASS.main
        cls.OPTIONS = options

        return cls

    return decorator


class DataSource:
    @add_main_module(_eit)
    class EIT:
        NAME = "eit"
        DESCRIPTION = "EIT - PulmoVista"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_philips_waves)
    class PhilipsWaves:
        NAME = "philips_waves"
        DESCRIPTION = "Philips scope - waves"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_philips_numerics)
    class PhilipsNumerics:
        NAME = "philips_numerics"
        DESCRIPTION = "Philips scope - numerics"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_syringe)
    class Syringe:
        NAME = "syringe"
        DESCRIPTION = "Syringe"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_fluxmed_parameters)
    class FluxmedParameters:
        NAME = "fluxmed_parameters"
        DESCRIPTION = "Fluxmed - numerics"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_fluxmed_signals)
    class FluxmedSignals:
        NAME = "fluxmed_signals"
        DESCRIPTION = "Fluxmed - waves"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_servo_u)
    class ServoU:
        NAME = "servo_u"
        DESCRIPTION = "Servo U"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_mindray_scope)
    class MindRayScope:
        NAME = "mindray_scope"
        DESCRIPTION = "Mindray scope"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_mindray_respi_num)
    class MindRayRespiNumerics:
        NAME = "mindray_respi_numerics"
        DESCRIPTION = "Mindray Respi - numerics"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_mindray_respi_waves)
    class MindRayRespiWaves:
        NAME = "mindray_respi_waves"
        DESCRIPTION = "Mindray Respi - waves"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_edf)
    class Edf:
        NAME = "edf"
        DESCRIPTION = "EDF / EDF+"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    @add_main_module(_other)
    class Other:
        NAME = "other"
        DESCRIPTION = "Other (generic)"
        MAIN_MODULE: ClassVar[MainModule]
        OPTIONS: object

    # This order is the "default" order of plot, so try to choose it a bit carefully
    AVAILABLE = (
        PhilipsWaves,
        EIT,
        PhilipsNumerics,
        Syringe,
        FluxmedParameters,
        FluxmedSignals,
        ServoU,
        MindRayRespiNumerics,
        MindRayRespiWaves,
        MindRayScope,
        Edf,
        Other,
    )

    @classmethod
    def get_subclass_by_name(cls, name: str) -> type | None:
        nested_classes = get_nested_classes(cls)
        for nested_class in nested_classes:
            if name == nested_class.NAME:
                return nested_class
        return None


def detect_datasource_from_folder(folder: str | Path) -> type | None:
    """
    Return the DataSource registry entry whose ``FOLDER_KEYWORDS`` all appear in *folder*'s name.

    When multiple datasources match, the one with the most keywords wins (best-match).
    Matching is case-insensitive.  Returns ``None`` if no datasource matches.

    Args:
        folder: Path to a datasource subfolder (only the *name* component is inspected).

    Returns:
        The matching DataSource registry entry (with ``.NAME``, ``.DATASOURCE_CLASS``,
        ``.OPTIONS`` …), or ``None``.

    """
    folder_name = Path(folder).name
    best_match = None
    best_score = 0
    for datasource in DataSource.AVAILABLE:
        keywords = getattr(datasource.OPTIONS, "FOLDER_KEYWORDS", None)
        if not keywords:
            continue
        if folder_name_matches_keywords(folder_name, keywords):
            score = len(keywords)
            if score > best_score:
                best_score = score
                best_match = datasource
    return best_match


@dataclass
class PatientFolderScan:
    """
    Result of scanning a candidate patient folder for datasource subfolders.

    Produced by :func:`scan_patient_folder`, shared by the Dash live preview (cheap core)
    and the CLI zero-result diagnostic (deep mode) -- see ADR-0001.
    """

    path: Path
    status: str  # "ok" | "missing" | "is_file" | "unreadable"
    self_datasource: type | None = None  # set when `path` itself looks like a device subfolder
    found: list[type] = field(default_factory=list)  # device subfolders with real content
    empty: list[type] = field(default_factory=list)  # device subfolders recognized but empty
    other_subfolders: list[str] = field(default_factory=list)  # subfolders matching no datasource
    loose_files: dict[str, list[str]] | None = None  # deep=True only: location -> filenames


def scan_patient_folder(path: str | Path, *, deep: bool = False) -> PatientFolderScan:
    """
    Classify *path* as a candidate patient folder and report its datasource subfolders.

    Cheap by default -- safe to call on every Dash keystroke: classifies the path, detects
    device subfolders, and names unrecognized ones. Pass ``deep=True`` (CLI only) to
    additionally enumerate loose files matching any datasource's ``FILE_EXTENSIONS`` in the
    root and any unrecognized subfolder -- the extra ``iterdir()`` calls are kept off the
    Dash hot path.
    """
    path = Path(path)
    if not path.is_dir():
        status = "is_file" if path.is_file() else "missing"
        return PatientFolderScan(path=path, status=status)

    try:
        self_datasource = detect_datasource_from_folder(path)

        found: list[type] = []
        empty: list[type] = []
        other_subfolders: list[str] = []
        for sub in sorted(path.iterdir()):
            if not sub.is_dir() or sub.name == cst.FOLDER_NAME_OUTPUT or sub.name.startswith("."):
                continue
            matched = detect_datasource_from_folder(sub)
            if matched is None:
                other_subfolders.append(sub.name)
            elif folder_has_real_content(sub):
                found.append(matched)
            else:
                empty.append(matched)
    except OSError:
        # e.g. a restricted network share that exists but can't be listed.
        logger.warning("Could not scan patient folder %r.", str(path))
        return PatientFolderScan(path=path, status="unreadable")

    scan = PatientFolderScan(
        path=path,
        status="ok",
        self_datasource=self_datasource,
        found=found,
        empty=empty,
        other_subfolders=other_subfolders,
    )
    if deep:
        scan.loose_files = _scan_loose_files(path, other_subfolders)
    return scan


def _scan_loose_files(path: Path, other_subfolders: list[str]) -> dict[str, list[str]]:
    """Files matching any datasource's FILE_EXTENSIONS, grouped by location (deep mode only)."""
    all_extensions = {
        ext.lower()
        for ds in DataSource.AVAILABLE
        for ext in getattr(ds.OPTIONS, "FILE_EXTENSIONS", [])
    }
    locations = {".": path} | {name: path / name for name in other_subfolders}

    loose_files: dict[str, list[str]] = {}
    for location, folder in locations.items():
        try:
            matches = sorted(
                entry.name
                for entry in folder.iterdir()
                if entry.is_file()
                and entry.suffix.lower() in all_extensions
                and not is_junk_file(entry)
            )
        except OSError:
            continue
        if matches:
            loose_files[location] = matches
    return loose_files


def format_zero_result_diagnostic(scan: PatientFolderScan) -> str:
    """Render *scan* (ideally ``deep=True``) as a plain-text diagnostic for a zero-result run."""
    lines = [f"No datasource produced any data from: {scan.path}"]

    if scan.status == "missing":
        lines.append("This folder doesn't exist.")
    elif scan.status == "is_file":
        lines.append("That's a file, not a folder.")
    elif scan.status == "unreadable":
        lines.append("This folder couldn't be read (permission or path issue).")
    else:
        if scan.found:
            names = ", ".join(ds.DESCRIPTION for ds in scan.found)
            lines.append(
                f"Device folder(s) with content were found ({names}), but none produced data -- "
                "check that your database_options configuration includes them, and check the "
                "error(s) logged above for load failures."
            )
        if scan.self_datasource is not None:
            lines.append(
                f"This folder itself looks like a '{scan.self_datasource.DESCRIPTION}' device "
                f"folder, not a patient folder -- try its parent ({scan.path.parent})."
            )
        if scan.empty:
            names = ", ".join(ds.DESCRIPTION for ds in scan.empty)
            lines.append(f"Recognized device folder(s), but empty: {names}.")
        if scan.other_subfolders:
            names = ", ".join(scan.other_subfolders)
            lines.append(f"Unrecognized subfolder(s): {names}.")
        if scan.loose_files:
            lines.append("Data file(s) found outside any recognized device folder:")
            for location, files in scan.loose_files.items():
                where = "patient root" if location == "." else f"'{location}/'"
                lines.append(f"  {where}: {', '.join(files)}")
        nothing_found = not (
            scan.found
            or scan.self_datasource
            or scan.empty
            or scan.other_subfolders
            or scan.loose_files
        )
        if nothing_found:
            lines.append("No device subfolders or recognizable data files found.")

    lines.append(
        "A patient folder holds one subfolder per device (monitor, ventilator, ...); the "
        "'organize-patient-folder' helper can sort loose files into place."
    )
    return "\n".join(lines)


def emit_zero_result_diagnostic(patient_folder: str | Path) -> None:
    """
    Log a diagnostic for a zero-result CLI run of *patient_folder*.

    CLI-only, bakes in the deep scan (``deep=True``) so callers don't have to know that
    detail. Not called for batch runs, to avoid flooding a large run -- see issue #53.
    """
    diagnostic = format_zero_result_diagnostic(scan_patient_folder(patient_folder, deep=True))
    logger.warning(diagnostic)


def generate_default_database_options() -> dict:
    """Generate database options with all available datasources using their defaults."""
    database_options = {}
    for data_source in DataSource.AVAILABLE:
        default = getattr(data_source.OPTIONS, "DEFAULT_DATABASE_OPTIONS", {})
        database_options[data_source.NAME] = dict(default)
    return database_options


def get_nested_classes(cls: type) -> list[type]:
    return [
        value
        for name, value in vars(cls).items()
        if isinstance(value, type) and issubclass(value, object)
    ]
