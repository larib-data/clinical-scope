"""
Pin the ``progress_callback`` contract ``wrapper.main`` and ``wrapper.inspect`` promise the UI.

The callback is the only thing the pipeline tells the progress bar, and it is spelled twice --
once in each entry point -- so the two can drift apart unseen. What it must report is one call
per *requested* datasource, numbered ``1..N`` against a total of ``N``, in registry order, each
raised before its datasource is read. The failure this guards is the denominator silently
becoming the whole registry: a three-datasource run would then crawl to "3/9" and stop, looking
stalled to the clinician.

The patient folder is an empty ``tmp_path``: nothing has to load for the counting contract to
hold, which keeps these runs off the shared fixtures and under a second. An empty folder cannot
show *when* the call is raised, though -- a callback moved after the read would report the same
sequence -- so the placement test patches one registry entry in place and has it record how much
progress had already been reported by the time it was entered.

The run names two of the registered datasources and one ``global`` section, spelled in the
reverse of registry order, so config order and non-datasource sections both have to be ignored
for the expected sequence to come out.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from clinical_scope import wrapper
from clinical_scope.datasource.registry import DataSource

# Registered datasources, named back-to-front: "eit" is registered before "mindray_scope".
EARLIER_IN_REGISTRY = "eit"
LATER_IN_REGISTRY = "mindray_scope"
REQUESTED_COUNT = 2


def _patient_options(data_folder: Path) -> dict:
    """A run over an empty folder: what is requested is still dispatched, it just finds no file."""
    return {"data_folder": str(data_folder), "quick_load": False}


def _database_options() -> dict:
    """Two datasources plus a section that names none, spelled against registry order."""
    return {LATER_IN_REGISTRY: {}, "global": {}, EARLIER_IN_REGISTRY: {}}


def _record_progress() -> tuple[list[tuple[int, int, str]], Callable[[int, int, str], None]]:
    """Return the list the callback fills, and the callback itself."""
    calls: list[tuple[int, int, str]] = []

    def progress_callback(current: int, total: int, name: str) -> None:
        calls.append((current, total, name))

    return calls, progress_callback


class TestProgressReporting:
    @pytest.mark.parametrize("entry_point", [wrapper.main, wrapper.inspect])
    def test_each_requested_datasource_is_reported_once_in_registry_order(
        self, entry_point, tmp_path
    ):
        # Guards the premise rather than the behaviour: the totals below only tell the requested
        # count from the registry size while the run asks for a strict subset of what is there.
        assert len(DataSource.AVAILABLE) > REQUESTED_COUNT

        calls, progress_callback = _record_progress()

        entry_point(
            _patient_options(tmp_path),
            _database_options(),
            progress_callback=progress_callback,
        )

        assert calls == [(1, 2, EARLIER_IN_REGISTRY), (2, 2, LATER_IN_REGISTRY)]

    @pytest.mark.parametrize("entry_point", [wrapper.main, wrapper.inspect])
    def test_progress_is_reported_before_the_datasource_is_read(
        self, entry_point, monkeypatch, tmp_path
    ):
        """The bar labels the datasource being worked on, so the call has to precede the read."""
        calls, progress_callback = _record_progress()
        reported_on_entry: list[int] = []

        def _record_entry(*args, **kwargs) -> list:
            del args, kwargs
            reported_on_entry.append(len(calls))
            return []

        class _ReadProbe:
            inspect = staticmethod(_record_entry)

        # Patched in place rather than appended to AVAILABLE: session-scoped fixtures read the
        # registry too, so a roster this test grew could leak into the rest of the suite.
        monkeypatch.setattr(DataSource.EIT, "MAIN_MODULE", _record_entry)
        monkeypatch.setattr(DataSource.EIT, "DATASOURCE_CLASS", _ReadProbe)

        entry_point(
            _patient_options(tmp_path),
            {EARLIER_IN_REGISTRY: {}},
            progress_callback=progress_callback,
        )

        assert reported_on_entry == [1]
