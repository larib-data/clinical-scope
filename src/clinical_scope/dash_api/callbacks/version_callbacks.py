"""
Renders the version badge once the release check has an answer.

The badge is server-rendered with the running version alone; this replaces it a moment later, so
nothing about app start or first paint waits on the network. What to say is decided in
``version_check``; all that is left here is wrapping the link half in an anchor.
"""

import logging

from dash import Input, Output, callback, html

import clinical_scope.constants as cst
from clinical_scope.dash_api.styles import VERSION_BADGE_LINK
from clinical_scope.dash_api.version_check import badge_content

logger = logging.getLogger(__name__)


@callback(
    Output("version-badge", "children"),
    Input("version-check-interval", "n_intervals"),
    prevent_initial_call=True,
)
def annotate_version_badge(_n_intervals: int) -> str | list:
    """
    Redraw the badge, appending a link to the release page when there is a reason to.

    Runs once per page load rather than once per process: a refresh re-asks PyPI, which costs a
    CDN-cached response, and the bookkeeping to avoid it would outweigh what it saves.
    """
    text, link_label = badge_content()
    if link_label is None:
        return text
    return [
        text,
        html.A(
            link_label,
            href=cst.LATEST_RELEASE_PAGE_URL,
            target="_blank",
            rel="noopener noreferrer",
            style=VERSION_BADGE_LINK,
        ),
    ]
