"""
Shape management utilities for Dash API visualization.

This module provides CRUD operations for shapes and annotations,
abstracting store access patterns.
"""

import re


def get_shape_from_store(store: dict, fig_name: str, shape_idx: int) -> dict | None:
    """Get a shape from the annotations store by figure name and index."""
    if not store or "by_figure" not in store:
        return None
    shapes = store.get("by_figure", {}).get(fig_name, {}).get("shapes", [])
    if shape_idx >= len(shapes):
        return None
    return shapes[shape_idx]


def parse_shape_selector_value(selected_value: str) -> tuple[str, int] | None:
    """Parse shape selector value into (fig_name, shape_idx) tuple."""
    if not selected_value:
        return None
    try:
        fig_name, shape_idx_str = selected_value.split("|")
        return fig_name, int(shape_idx_str)
    except (ValueError, AttributeError):
        return None


def parse_rgba_color(color_str: str) -> dict | None:
    """
    Parse rgba color string into color picker value dict.

    Returns dict with 'hex' and 'rgb' keys, or None if parsing fails.
    """
    if not color_str:
        return None
    match = re.match(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\s*\)", color_str)
    if match:
        r, g, b, a = match.groups()
        return {
            "hex": f"#{int(r):02x}{int(g):02x}{int(b):02x}",
            "rgb": {"r": int(r), "g": int(g), "b": int(b), "a": float(a)},
        }
    return None


def build_rgba_string(color_value: dict) -> str | None:
    """Build rgba string from color picker value dict."""
    if not color_value or "rgb" not in color_value:
        return None
    rgb = color_value["rgb"]
    return f"rgba({rgb['r']},{rgb['g']},{rgb['b']},{rgb['a']})"


def extract_shape_properties(shape: dict) -> dict:
    """
    Extract display properties from a shape.

    Returns dict with 'name', 'is_global', 'color' keys.
    """
    return {
        "name": shape.get("label", {}).get("text", ""),
        "is_global": shape.get("yref") == "paper",
        "color": shape.get("line", {}).get("color") or shape.get("fillcolor"),
    }


def build_shape_option_label(fig_name: str, shape: dict, index: int) -> tuple[str, str]:
    """
    Build label and value for shape selector dropdown.

    Returns (display_label, value) tuple.
    """
    name = shape.get("label", {}).get("text") or f"Shape {index}"
    color = shape.get("line", {}).get("color") or shape.get("fillcolor") or "gray"
    display_label = f"{fig_name} - {name}"
    value = f"{fig_name}|{index}"
    return display_label, value, color
