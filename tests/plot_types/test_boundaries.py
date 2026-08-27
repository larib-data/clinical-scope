"""A plot type is a module: nothing outside ``plot_types/`` may know one by name.

Two rules, both read off the AST rather than left to review, in the style of
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


def test_every_registered_type_declares_both_halves():
    """The import-time guard's own test: the registry refuses a half-declared plot type."""
    for schema in registry.DERIVED:
        assert schema.SECTION_KEY == schema.NAME
        assert (PACKAGE_ROOT / schema.NAME / "plot.py").is_file()
        assert (PACKAGE_ROOT / schema.NAME / "schema.py").is_file()
