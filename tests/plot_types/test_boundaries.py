"""A plot type is a module: nothing outside ``plot_types/`` may know one by name.

Three rules, all read off the AST rather than left to review, in the style of
``tests/datasource/test_load_config_independence.py``.

**No module outside the package names a plot type.** The failure this package exists to kill
is a plot type that validates cleanly and renders nothing, and a forgotten branch in a shared
module is what that looks like from the inside. The Dash callbacks are the point of this
check: the least-tested layer, and the easiest place for a type branch to grow back.

**``signal_container`` imports no ``plot.py``.** The load-bearing one, and what a written
decision record would otherwise have to hold up. ``signal_container`` is reachable
from a half-initialised ``datasource`` package, so a ``plot.py`` importing ``Signal`` back out
of it raises ImportError for some entry points and not others -- a non-deterministic failure
invisible at the point of violation. It is why rendering is pushed onto a Signal at
construction rather than pulled at draw time; break the rule and the reason for that is gone.

**No datasource imports ``plot_types`` at all.** A datasource reads a device's files; which
plot a signal ends up on is nobody's business at load time. ``other`` broke this by scoping
each file's plot-type sections itself, which is how a forgotten ``psd`` row let that section
validate cleanly and render nothing. Reference scoping lives in ``plot_assembly`` now, at
every level -- a stem is a namespace exactly as a datasource is.

What the first rule does **not** catch, so a green run is not read as more than it is: a name
reached through the registry (``registry.LoopSchema.NAME``) rather than written out, and any
string merely *containing* a type's name rather than equal to it -- ``loops_per_row``,
``loop_time_axis``, ``spectrogram_freq_axis``. Those are the shared display and payload
mechanisms, which a plot type uses rather than owns.
"""

import ast
from pathlib import Path

import pytest

from clinical_scope.plot_types import registry

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "clinical_scope"
PACKAGE_ROOT = SRC_ROOT / "plot_types"

# Every spelling of a plot type: its name, and the config section it reads. The two are
# required to be equal, but a module could hardcode either.
PLOT_TYPE_LITERALS = frozenset(registry.NAMES | registry.SECTION_KEYS)


def _modules_outside_the_package() -> list[Path]:
    return sorted(
        path for path in SRC_ROOT.rglob("*.py") if PACKAGE_ROOT not in path.parents
    )


@pytest.mark.parametrize("module_path", _modules_outside_the_package(), ids=lambda p: p.name)
def test_no_module_outside_plot_types_names_a_plot_type(module_path):
    """A capability answers "does it behave this way?"; a name answers "which one is it?"."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    named = sorted(
        {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        & PLOT_TYPE_LITERALS
    )

    assert not named, (
        f"{module_path.relative_to(SRC_ROOT)} spells plot type(s) {named} literally. Branch on "
        f"a capability from plot_types.registry instead, or move the code into that plot "
        f"type's own package."
    )


def test_signal_container_imports_no_plot_module():
    """The rule that keeps the datasource import cycle survivable."""
    tree = ast.parse((SRC_ROOT / "signal_container.py").read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)

    offending = sorted(name for name in imported if name.endswith(".plot"))
    assert not offending, (
        f"signal_container imports {offending}. A plot.py imports Signal, so importing one "
        f"back makes Signal's own module depend on Signal already existing -- push the "
        f"rendering onto the Signal from build() instead (see plot_types.base.RenderSpec)."
    )


@pytest.mark.parametrize(
    "module_path",
    sorted((SRC_ROOT / "datasource").rglob("*.py")),
    ids=lambda p: str(p.relative_to(SRC_ROOT)),
)
def test_no_datasource_imports_plot_types(module_path):
    """Loading a device's files is decided by the format, never by what will be drawn."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    offending = sorted(name for name in imported if "plot_types" in name)
    assert not offending, (
        f"{module_path.relative_to(SRC_ROOT)} imports {offending}. A datasource that reads a "
        f"plot type's config shape has to be edited when a type is added, and forgetting it is "
        f"a section that validates and renders nothing -- let plot_assembly scope the "
        f"references instead."
    )


def test_every_registered_type_declares_both_halves():
    """The import-time guard's own test: the registry refuses a half-declared plot type."""
    for schema in registry.DERIVED:
        assert schema.SECTION_KEY == schema.NAME
        assert (PACKAGE_ROOT / schema.NAME / "plot.py").is_file()
        assert (PACKAGE_ROOT / schema.NAME / "schema.py").is_file()
