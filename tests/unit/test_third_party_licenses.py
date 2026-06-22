"""
Regression guards for the build-time license tooling.

These never touch a real PyInstaller bundle (the GitHub build is the final
arbiter); they pin the *policy data* that silently rots when someone edits the
copyleft lists, the native-library map, or the spec excludes:

* strong copyleft must fail the build, weak copyleft must only be noted;
* every native lib the Linux/Windows builds bundle must resolve to a notice;
* GNU Readline (GPL-3) must stay excluded from the bundle.
"""

from email.message import Message
from pathlib import Path

import pytest

from clinical_scope.build_info import generate_third_party_licenses as gen


def _dist(*, classifiers=(), license_field=None, license_expr=None) -> object:
    """Build a fake Distribution whose ``.metadata`` mimics a real wheel's."""
    msg = Message()
    if license_expr is not None:
        msg["License-Expression"] = license_expr
    if license_field is not None:
        msg["License"] = license_field
    for c in classifiers:
        msg["Classifier"] = c
    return type("FakeDist", (), {"metadata": msg})()


class TestClassifyLicense:
    """The copyleft policy that drives the build warning + exit code."""

    @pytest.mark.parametrize(
        "classifier",
        [
            "License :: OSI Approved :: GNU General Public License v2 (GPLv2)",
            "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
            "License :: OSI Approved :: GNU Affero General Public License v3",
            "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
            "License :: OSI Approved :: Eclipse Public License 2.0 (EPL-2.0)",
            "License :: OSI Approved :: Common Development and Distribution License 1.0 (CDDL-1.0)",
        ],
    )
    def test_strong_copyleft_flagged(self, classifier):
        assert gen.classify_license(_dist(classifiers=[classifier]))[0] == "strong"

    @pytest.mark.parametrize("expr", ["AGPL-3.0-or-later", "SSPL-1.0", "CC-BY-SA-4.0"])
    def test_strong_copyleft_via_expression(self, expr):
        assert gen.classify_license(_dist(license_expr=expr))[0] == "strong"

    @pytest.mark.parametrize(
        "spec",
        [
            {"license_expr": "MPL-2.0"},
            {"classifiers": ["License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)"]},
            # orjson-style dual license: weak component present -> noted, not failed.
            {"license_expr": "MPL-2.0 AND (Apache-2.0 OR MIT)"},
        ],
    )
    def test_weak_copyleft_noted_not_failed(self, spec):
        assert gen.classify_license(_dist(**spec))[0] == "weak"

    @pytest.mark.parametrize(
        "classifier",
        [
            "License :: OSI Approved :: MIT License",
            "License :: OSI Approved :: BSD License",
            "License :: OSI Approved :: Apache Software License",
            "License :: OSI Approved :: Python Software Foundation License",
            "License :: OSI Approved :: ISC License (ISCL)",
        ],
    )
    def test_permissive_not_flagged(self, classifier):
        assert gen.classify_license(_dist(classifiers=[classifier])) is None

    def test_long_license_field_is_not_scanned(self):
        """A dumped license *body* mentioning the GPL must not false-match."""
        body = "Permission is hereby granted ... this is not the GPL ..." + "x" * 80
        assert len(body) >= gen.MAX_LICENSE_ID_LEN
        dist = _dist(
            license_field=body,
            classifiers=["License :: OSI Approved :: MIT License"],
        )
        assert gen.classify_license(dist) is None


# Exact filenames the Linux and Windows CI builds reported as bundled, minus the
# deliberately-excluded libreadline. Every one must resolve to a notice.
LINUX_LIBS = [
    "libgcc_s.so.1",
    "libgfortran-83c28eba-b4027c22.so.5.0.0",
    "libpython3.12.so.1.0",  # interpreter -> folded into the PSF block
    "libquadmath-2284e583-a9307bba.so.0.0.0",
    "libscipy_openblas64_-017048f4.so",
    "libstdc++.so.6",
    "libtinfo.so.6",
    "libuuid.so.1",
]
WINDOWS_LIBS = [
    "VCRUNTIME140.dll",
    "VCRUNTIME140_1.dll",
    "api-ms-win-core-console-l1-1-0.dll",
    "api-ms-win-crt-stdio-l1-1-0.dll",
    "arrow.dll",
    "arrow_acero.dll",
    "libscipy_openblas64_-b788215d9d47792bcba3a2e2a7114320.dll",
    "msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll",
    "msvcp140_atomic_wait-a67379821634a4f3a32730b57a436c71.dll",
    "parquet.dll",
    "python3.dll",  # interpreter -> folded into the PSF block
    "python312.dll",
    "pywintypes312.dll",
    "sqlite3.dll",
    "ucrtbase.dll",
]


def _native_section_for(tmp_path, names) -> tuple[str, list[str]]:
    """Run native_section over a fake _internal/ containing empty ``names``."""
    internal = tmp_path / "_internal"
    internal.mkdir()
    for n in names:
        (internal / n).touch()
    return gen.native_section(internal)


class TestNativeLibResolution:
    """The hand-maintained NATIVE_LICENSES map vs. real per-platform builds."""

    def test_linux_libs_all_resolve(self, tmp_path):
        _, unrecognised = _native_section_for(tmp_path, LINUX_LIBS)
        assert unrecognised == []

    def test_windows_libs_all_resolve(self, tmp_path):
        _, unrecognised = _native_section_for(tmp_path, WINDOWS_LIBS)
        assert unrecognised == []

    def test_readline_is_a_tripwire(self, tmp_path):
        """If a build ever re-bundles GPL-3 readline, it must surface loudly."""
        _, unrecognised = _native_section_for(tmp_path, ["libreadline.so.8"])
        assert "libreadline.so.8" in unrecognised

    def test_missing_psf_license_is_flagged(self, tmp_path, monkeypatch):
        """A bundle whose interpreter license can't be found must fail, not ship a TODO."""
        monkeypatch.setattr(gen, "find_psf_text", lambda: gen.PSF_TODO)
        text, unrecognised = _native_section_for(tmp_path, [])
        assert any("PSF" in u for u in unrecognised)
        assert gen.PSF_TODO in text


class TestReadlineExcludedFromBundle:
    """The actual fix: readline never enters the bundle in the first place."""

    def test_spec_excludes_readline(self):
        spec = Path(gen.__file__).with_name("core_api.spec").read_text(encoding="utf-8")
        assert '"readline"' in spec
