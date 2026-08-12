"""
Guard the user-facing assets under ``example/`` against silent drift.

Both assets here are shipped: ``build_info/assemble_bundle.py`` copies them into the release
bundle, and the JSON config is the entry point for library users who never launch the app.
Nothing else re-derives them, so without these checks they rot unnoticed — which is how the
template lost its ``edf/`` folder.
"""

import json

from clinical_scope.database_options_xlsx import xlsx_bytes_to_database_options
from clinical_scope.datasource.registry import DataSource, detect_datasource_from_folder

REGENERATE_HINT = (
    "Regenerate with:\n"
    "    python -c \"import json;from pathlib import Path;"
    "from clinical_scope.database_options_xlsx import xlsx_bytes_to_database_options as c;"
    "p=Path('example/demo_database');"
    "p.joinpath('database_options.json').write_text("
    "json.dumps(c(p.joinpath('database_options.xlsx').read_bytes()),indent=4,ensure_ascii=False)"
    "+chr(10),encoding='utf-8')\""
)


class TestFolderTemplate:
    """``example/template_patient_data_structure/`` is the empty scaffold users copy."""

    def test_folders_match_the_registry(self, project_root):
        template = project_root / "example" / "template_patient_data_structure"
        on_disk = {p.name for p in template.iterdir() if p.is_dir()}
        expected = {d.OPTIONS.EXPECTED_FOLDER_NAME for d in DataSource.AVAILABLE}

        assert on_disk == expected, (
            "template_patient_data_structure/ is out of sync with DataSource.AVAILABLE — "
            f"missing: {sorted(expected - on_disk)}, unexpected: {sorted(on_disk - expected)}"
        )

    def test_every_folder_is_committed(self, project_root):
        """Empty dirs vanish from git, so each one needs its .gitkeep to survive a clone."""
        template = project_root / "example" / "template_patient_data_structure"
        missing = [
            p.name for p in template.iterdir() if p.is_dir() and not (p / ".gitkeep").exists()
        ]

        assert not missing, f"template folders without a .gitkeep: {sorted(missing)}"


class TestDemoConfigParity:
    """The demo's .json is a generated twin of its .xlsx — the two must not diverge."""

    def test_json_matches_the_xlsx(self, project_root):
        demo = project_root / "example" / "demo_database"
        from_xlsx = xlsx_bytes_to_database_options((demo / "database_options.xlsx").read_bytes())
        with open(demo / "database_options.json", encoding="utf-8") as f:
            committed = json.load(f)

        assert committed == from_xlsx, (
            f"database_options.json no longer matches database_options.xlsx.\n{REGENERATE_HINT}"
        )

    def test_every_shipped_datasource_is_configured(self, project_root):
        """A source key is what activates a source, so an unconfigured folder never plots."""
        demo = project_root / "example" / "demo_database"
        with open(demo / "database_options.json", encoding="utf-8") as f:
            config = json.load(f)
        configured = {key.split("::")[0] for key in config if key != "global"}

        on_disk = set()
        for folder in (demo / "demo_patient").iterdir():
            if not folder.is_dir() or folder.name == "clinical_scope_output":
                continue
            match = detect_datasource_from_folder(folder)
            assert match is not None, f"demo_patient/{folder.name}/ matches no datasource"
            on_disk.add(match.OPTIONS.EXPECTED_FOLDER_NAME)

        assert on_disk <= configured, (
            "demo_patient/ ships data the demo config never plots: "
            f"{sorted(on_disk - configured)}. Add a section to database_options.xlsx "
            "and regenerate the json."
        )
