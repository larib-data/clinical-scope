"""Shared assertion helpers for the Dash callback tests."""

from typing import Any


def patch_ops(patch: Any) -> dict[str, Any]:
    """A dash Patch flattened to {dotted location: value}, for asserting on its ops."""
    return {
        ".".join(str(part) for part in op["location"]): op["params"].get("value")
        for op in patch.to_plotly_json()["operations"]
    }
