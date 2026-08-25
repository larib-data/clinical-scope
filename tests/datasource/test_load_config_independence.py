"""`_load` must transcribe the source file only — no option may reach the parquet cache.

See ADR-0010: whatever a load resolves is frozen into `clinical_scope_output/`, so a later
run with a different setting silently reads a cache built under the old one. The base class
now writes that cache from whatever `_load` returns, which leaves the rule two channels, each
checked here:

- *arguments* — closed by the signature. `_load(file_path)` has no option in scope at all.
- *module globals* — a signature cannot close these, so this is ADR-0010's own "mechanical
  and greppable" clause, run as a test rather than left to review.

Running a load twice under two configs would catch neither: both runs now take an identical
code path, and a module-level constant does not vary between them.

Both checks read the definition as written, via the AST. `@time_it` is not `functools.wraps`ed,
so introspecting the bound attribute would describe the decorator's wrapper instead.
"""

import ast
import inspect
from pathlib import Path

import pytest

from clinical_scope.datasource.registry import DataSource

# Sources that write a parquet cache; the rule binds exactly these.
CACHING_SOURCE_NAMES = [
    entry.NAME for entry in DataSource.AVAILABLE if entry.DATASOURCE_CLASS.ALLOW_QUICK_LOAD
]

# Referencing either inside `_load` means an option got frozen into the cache.
FORBIDDEN_IN_LOAD = frozenset({"DATA_SOURCE_DEFAULT_TIMEZONE", "apply_timezone_to_dataframe"})


def _load_definition(source_name: str) -> ast.FunctionDef:
    """Return the `_load` definition of *source_name*'s datasource class, as written."""
    datasource_class = DataSource.get_subclass_by_name(source_name).DATASOURCE_CLASS
    source_file = inspect.getsourcefile(datasource_class)
    module = ast.parse(Path(source_file).read_text(encoding="utf-8"))

    for class_node in ast.walk(module):
        if not isinstance(class_node, ast.ClassDef):
            continue
        if class_node.name != datasource_class.__name__:
            continue
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_load":
                return node
    pytest.fail(f"no `_load` definition found for '{source_name}' in {source_file}")


@pytest.mark.parametrize("source_name", CACHING_SOURCE_NAMES)
def test_load_takes_only_the_file_path(source_name):
    """No option can be resolved from an argument that is not there."""
    node = _load_definition(source_name)
    positional = [argument.arg for argument in node.args.args]

    assert len(positional) == 2, (
        f"'{source_name}'._load takes {positional}; only (cls, file_path) may be in scope"
    )
    assert node.args.vararg is None and node.args.kwarg is None, (
        f"'{source_name}'._load accepts *args/**kwargs — an option can reach the cache through them"
    )
    assert not node.args.kwonlyargs, (
        f"'{source_name}'._load takes keyword-only {[a.arg for a in node.args.kwonlyargs]}"
    )


@pytest.mark.parametrize("source_name", CACHING_SOURCE_NAMES)
def test_load_resolves_no_option_from_module_scope(source_name):
    """The channel the signature cannot close: a default reached for directly."""
    node = _load_definition(source_name)
    referenced = {
        inner.id if isinstance(inner, ast.Name) else inner.attr
        for inner in ast.walk(node)
        if isinstance(inner, (ast.Name, ast.Attribute))
    }

    leaked = sorted(referenced & FORBIDDEN_IN_LOAD)
    assert not leaked, (
        f"'{source_name}'._load references {leaked}: a default frozen into the cache is "
        f"indistinguishable at read time from a user's choice frozen into it"
    )
