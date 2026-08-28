"""A plot type nobody can read about is a feature only its author can use.

``registry`` refuses a plot type missing a half of its code, and ``test_example_assets``
refuses one the demo config never plots. Neither notices the last gap: a type that imports,
validates, renders, ships — and is described nowhere a reader would look. That gap is the
whole periphery a new plot type has to land in, and it is the only part of it left to prose.

Two audiences, so two documents, neither substituting for the other. The **tutorial** is where
a clinician learns the config key exists at all; ``CONTEXT.md`` is where the word the team says
out loud is pinned to one meaning, so ``psd`` in a config file and "PSD" in a corridor
conversation are the same thing.

Deliberately anchored on *headings* and *glossary terms* rather than a search of the prose:
"loop" appears all over the tutorial for unrelated reasons -- the datasource loop, a loop
subplot's height, multi-cycle loops -- so a body search would pass for a plot type nobody had
written a word about. A heading is a place in the document; a mention is not.

What that costs, so a green run is not read as more than it is: a heading that merely *contains*
the name satisfies this, and nothing here reads what sits under it. It catches the type
documented nowhere, not the one documented badly.
"""

import re
from pathlib import Path

import pytest

from clinical_scope.plot_types import registry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TUTORIAL = PROJECT_ROOT / "docs" / "user_guide" / "tutorial.md"
CONTEXT = PROJECT_ROOT / "CONTEXT.md"

# A glossary entry is a bold term at the start of a line, followed by its definition.
GLOSSARY_TERM = re.compile(r"^\*\*(.+?)\*\*:", re.MULTILINE)


def _spellings(definition):
    """Every name a type answers to: its own, its config section, its xlsx sheet.

    Taken off the definition rather than pluralized here, so the sheet's name is whatever the
    type actually declares -- ``loops`` for ``loop``, and nothing at all for a type with no
    sheet of its own.
    """
    return {name for name in (definition.NAME, definition.SECTION_KEY, definition.SHEET_NAME) if name}


@pytest.mark.parametrize("definition", registry.DERIVED, ids=lambda s: s.NAME)
def test_the_tutorial_gives_it_a_heading(definition):
    """Where a clinician finds out the key exists -- a config block, a sheet, or a section."""
    headings = [
        line for line in TUTORIAL.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    ]
    spellings = _spellings(definition)

    found = [
        heading
        for heading in headings
        if any(re.search(rf"\b{re.escape(name)}\b", heading, re.IGNORECASE) for name in spellings)
    ]

    assert found, (
        f"No heading in docs/user_guide/tutorial.md names the {definition.NAME!r} plot type "
        f"(looked for {sorted(spellings)}). Add the section a reader would need to configure "
        f"one -- the '`spectrogram` Block' and '`spectrograms` sheet' headings are the shape."
    )


@pytest.mark.parametrize("definition", registry.DERIVED, ids=lambda s: s.NAME)
def test_the_glossary_defines_it(definition):
    """Where the word gets one meaning, so the config key and the corridor word agree."""
    terms = {term.casefold() for term in GLOSSARY_TERM.findall(CONTEXT.read_text(encoding="utf-8"))}
    spellings = {name.casefold() for name in _spellings(definition)}

    assert terms & spellings, (
        f"CONTEXT.md defines no term for the {definition.NAME!r} plot type (looked for "
        f"{sorted(spellings)}). Add a '**{definition.NAME.title()}**:' entry under Core concepts, "
        f"with the _Avoid_ line naming the words it should not be called."
    )
