"""
Cover the demo download: the one code path a pip user hits before anything else works.

Nothing here touches the network — ``urlopen`` is replaced by a fake serving bytes built in
the test, which is the whole reason :mod:`clinical_scope.demo_data` keeps itself Dash-free and
takes its URL from a constant.
"""

import io
import urllib.error
import zipfile

import pytest

import clinical_scope.constants as cst
from clinical_scope import demo_data
from clinical_scope.demo_data import DemoDownloadError, demo_folder, fetch_demo_data


def _zip_bytes(members: dict[str, str]) -> bytes:
    """A zip archive holding ``{name: text}``, as the release asset would be."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, text in members.items():
            bundle.writestr(name, text)
    return buffer.getvalue()


DEMO_ARCHIVE = _zip_bytes(
    {
        "demo_database/database_options.json": "{}",
        "demo_database/demo_patient/edf/eeg_001.edf": "fake",
        "template_patient_data_structure/eit/.gitkeep": "",
    }
)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirect ``Path.home()`` so the real ``~/.clinical_scope`` is never touched."""
    monkeypatch.setattr(demo_data.Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def served(monkeypatch):
    """Serve fixed bytes from ``urlopen`` and record every call made to it."""

    def serve(payload: bytes | Exception):
        calls = []

        def fake_urlopen(url, timeout=None):
            calls.append(url)
            if isinstance(payload, Exception):
                raise payload
            return io.BytesIO(payload)

        monkeypatch.setattr(demo_data.urllib.request, "urlopen", fake_urlopen)
        return calls

    return serve


class TestDemoFolder:
    """Where the demo lands, given it has to be somewhere a pip install can write."""

    def test_sits_beside_the_other_app_state(self, home):
        folder = demo_folder()

        assert folder == home / ".clinical_scope" / "example"


class TestSuccessfulFetch:
    """The happy path: an archive arrives and becomes a usable folder."""

    def test_archive_is_unpacked(self, home, served):
        served(DEMO_ARCHIVE)

        folder = fetch_demo_data()

        assert (folder / "demo_database" / "database_options.json").is_file()
        assert (folder / "demo_database" / "demo_patient" / "edf" / "eeg_001.edf").is_file()

    def test_no_staging_folder_is_left_behind(self, home, served):
        served(DEMO_ARCHIVE)

        folder = fetch_demo_data()

        assert not folder.with_name("example.part").exists()

    def test_an_existing_demo_is_not_downloaded_again(self, home, served):
        calls = served(DEMO_ARCHIVE)
        fetch_demo_data()

        fetch_demo_data()

        assert len(calls) == 1

    def test_force_downloads_again(self, home, served):
        calls = served(DEMO_ARCHIVE)
        fetch_demo_data()

        fetch_demo_data(force=True)

        assert len(calls) == 2

    def test_force_replaces_what_was_there(self, home, served):
        served(DEMO_ARCHIVE)
        folder = fetch_demo_data()
        stale = folder / "demo_database" / "left_over.json"
        stale.write_text("{}", encoding="utf-8")

        fetch_demo_data(force=True)

        assert not stale.exists()


class TestFailuresAreReadable:
    """Every way this can fail leaves by one exception, with something a user can act on."""

    def test_offline_names_the_url(self, home, served):
        served(urllib.error.URLError("no route to host"))

        with pytest.raises(DemoDownloadError, match="releases/latest/download"):
            fetch_demo_data()

    def test_missing_release_asset_is_not_a_traceback(self, home, served):
        served(urllib.error.HTTPError(cst.DEMO_ARCHIVE_URL, 404, "Not Found", {}, None))

        with pytest.raises(DemoDownloadError):
            fetch_demo_data()

    def test_a_response_that_is_not_a_zip_is_rejected(self, home, served):
        served(b"<!DOCTYPE html><html>404</html>")

        with pytest.raises(DemoDownloadError, match="could not be unpacked"):
            fetch_demo_data()

    def test_an_oversized_response_stops_early(self, home, served, monkeypatch):
        monkeypatch.setattr(cst, "DEMO_MAX_ARCHIVE_BYTES", 8)
        served(DEMO_ARCHIVE)

        with pytest.raises(DemoDownloadError, match="larger than"):
            fetch_demo_data()

    def test_a_failure_leaves_no_demo_folder(self, home, served):
        served(b"not a zip")

        with pytest.raises(DemoDownloadError):
            fetch_demo_data()

        assert not demo_folder().exists()
        assert not demo_folder().with_name("example.part").exists()


class TestArchiveCannotEscapeItsFolder:
    """A release asset is fetched over the network, so its member names are not trusted."""

    @pytest.mark.parametrize(
        "member",
        [
            "../escaped.json",
            "demo_database/../../escaped.json",
            "/etc/passwd",
            "..\\escaped.json",
        ],
    )
    def test_escaping_members_are_refused(self, home, served, member):
        served(_zip_bytes({member: "x"}))

        with pytest.raises(DemoDownloadError, match="unsafe path"):
            fetch_demo_data()

    def test_nothing_is_written_when_a_member_escapes(self, home, served):
        served(_zip_bytes({"../escaped.json": "x"}))

        with pytest.raises(DemoDownloadError):
            fetch_demo_data()

        assert not (home / "escaped.json").exists()
