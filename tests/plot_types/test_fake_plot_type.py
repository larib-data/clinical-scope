"""Register a fourth plot type and drive it through every path a real one takes.

This is the acceptance criterion of #83 as a test: *adding a plot type is a package plus its
registry lines*. Nothing in `constants.py`, `database_options_parser.py`,
`database_options_xlsx.py`, `other/find_load_format.py`, `plot_assembly.py` or
`signal_container.py` knows `fake` exists, and all six still handle it.

The fake type's config entry is a bare string, a shape none of the real three use, so each
hook is exercised on a case the production types do not cover. Its workbook is built to a
BytesIO here rather than committed: a golden .xlsx for a plot type that does not exist would
be a fixture nobody could read.
"""

import io

import pandas as pd
import pytest

from clinical_scope.database_options_parser import validate_database_options
from clinical_scope.database_options_xlsx import xlsx_bytes_to_database_options
from clinical_scope.plot_assembly import assemble_plot_groups
from clinical_scope.plot_types import builders, registry
from clinical_scope.signal_container import PlotModel

from tests.plot_types.fake.plot import BUILDER as FAKE_BUILDER
from tests.plot_types.fake.schema import FakeSchema

CAPABILITIES = (
    "TIME_AXIS",
    "UNIFIED_HOVER",
    "RESAMPLED",
    "GRID_LAYOUT",
    "HAS_COLORBAR",
    "POINT_TIMESTAMPS",
)


@pytest.fixture
def fake_plot_type(monkeypatch):
    """
    Register FakeSchema for the duration of one test.

    Mirrors how ``registry`` derives its collections from AVAILABLE. The duplication is the
    point: production registers at import, so a runtime registration has to restate the
    derivation, and this test fails the day the two disagree.
    """
    available = (*registry.AVAILABLE, FakeSchema)
    derived = tuple(schema for schema in available if schema.SECTION_KEY)

    monkeypatch.setattr(registry, "AVAILABLE", available)
    monkeypatch.setattr(registry, "PAGE_ORDER", tuple(s.NAME for s in available))
    monkeypatch.setattr(registry, "DERIVED", derived)
    monkeypatch.setattr(registry, "SECTION_KEYS", frozenset(s.SECTION_KEY for s in derived))
    monkeypatch.setattr(registry, "NAMES", frozenset(s.NAME for s in available))
    for capability in CAPABILITIES:
        monkeypatch.setattr(
            registry,
            capability,
            frozenset(s.NAME for s in available if getattr(s, capability)),
        )
    monkeypatch.setattr(
        builders, "BUILDERS", {**builders.BUILDERS, FakeSchema: FAKE_BUILDER}
    )
    return FakeSchema


class TestValidation:
    def test_the_section_key_is_accepted(self, fake_plot_type, make_signal):
        """A registered type's section must not read as an unknown key."""
        del fake_plot_type, make_signal
        issues = validate_database_options({"eit": {"fake": {"F": "sig_a"}}})
        assert issues == []

    def test_an_unregistered_section_key_still_warns(self):
        """Without the fixture, `fake` is nobody's section -- the check still bites."""
        issues = validate_database_options({"eit": {"fake": {"F": "sig_a"}}})
        assert [issue.severity for issue in issues] == ["warning"]
        assert "fake" in issues[0].message

    def test_a_malformed_entry_is_reported_by_its_own_schema(self, fake_plot_type):
        del fake_plot_type
        issues = validate_database_options({"eit": {"fake": {"F": ["not", "a", "string"]}}})
        assert [(i.severity, i.path) for i in issues] == [("error", "eit.fake.F")]


class TestReferenceScoping:
    def test_a_bare_reference_is_qualified_to_its_datasource(self, fake_plot_type, make_signal):
        """ADR-0013 desugaring reaches a shape the real three never produce."""
        del fake_plot_type
        signal = make_signal(raw_name="sig_a")
        signal.metadata.datasource_name = "eit"

        groups = assemble_plot_groups([signal], {"eit": {"fake": {"F": "sig_a"}}})

        fake_groups = [g for g in groups if g.plot_options.plot_type == FakeSchema.NAME]
        assert [g.name for g in fake_groups] == ["F"]

    def test_map_refs_scopes_a_per_file_reference(self, fake_plot_type):
        del fake_plot_type
        scoped = FakeSchema.map_refs("Paw", lambda ref: f"waves::{ref}")
        assert scoped == "waves::Paw"


class TestXlsxSheet:
    def test_its_own_sheet_is_read_into_its_own_section(self, fake_plot_type):
        del fake_plot_type
        workbook = io.BytesIO()
        with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
            pd.DataFrame(
                [{"datasource": "eit", "signal": "sig_a", "label": "Sig A"}]
            ).to_excel(writer, sheet_name="signals", index=False)
            pd.DataFrame(
                [{"datasource": "eit", "fake_name": "F", "signal": "sig_a"}]
            ).to_excel(writer, sheet_name="fakes", index=False)

        options = xlsx_bytes_to_database_options(workbook.getvalue())

        assert options["eit"]["fake"] == {"F": "sig_a"}


class TestBuildAndRender:
    def test_it_builds_a_signal_and_reaches_a_figure(self, fake_plot_type, make_signal):
        del fake_plot_type
        signal = make_signal(raw_name="sig_a")
        signal.metadata.datasource_name = "eit"

        groups = assemble_plot_groups([signal], {"eit": {"fake": {"F": "sig_a"}}})
        models = PlotModel.assign_plot_model(groups)

        fake_model = next(m for m in models if m.plot_type == FakeSchema.NAME)
        assert fake_model.figure.data
        assert fake_model.figure.data[0].hovertemplate == "<b>F</b> fake<extra></extra>"

    def test_its_capabilities_reach_the_figure(self, fake_plot_type, make_signal):
        """GRID_LAYOUT is declared on the schema alone, and n_cols honours it."""
        del fake_plot_type
        signals = []
        for raw_name in ("sig_a", "sig_b"):
            signal = make_signal(raw_name=raw_name)
            signal.metadata.datasource_name = "eit"
            signals.append(signal)

        groups = assemble_plot_groups(
            signals, {"eit": {"fake": {"F1": "sig_a", "F2": "sig_b"}}}
        )
        models = PlotModel.assign_plot_model(groups)

        fake_model = next(m for m in models if m.plot_type == FakeSchema.NAME)
        assert fake_model.n_cols > 1
