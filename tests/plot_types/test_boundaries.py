"""A plot type is a module: nothing outside ``plot_types/`` may know one by name.

Read off the AST rather than left to review, in the style of
``tests/datasource/test_load_config_independence.py``.

``signal_container`` imports no ``plot.py`` is the load-bearing rule here, and it is what a
written decision record would otherwise have to hold up. ``signal_container`` is reachable
from a half-initialised ``datasource`` package, so a ``plot.py`` importing ``Signal`` back out
of it raises ImportError for some entry points and not others -- a non-deterministic failure
invisible at the point of violation. It is why rendering is pushed onto a Signal at
construction rather than pulled at draw time; break the rule and the reason for that is gone.
"""

import ast
from pathlib import Path

from clinical_scope.plot_types import registry

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "clinical_scope"
PACKAGE_ROOT = SRC_ROOT / "plot_types"


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
