# Releasing

Release checklist for `clinical-scope`, starting from a `main` branch you're happy with. Replace `X.Y.Z` below with the version you're releasing.

**Golden rule:** at every step, at least run `clinical-scope` and confirm the example works as intended on your machine before moving on. Bump `version` in [`pyproject.toml`](../pyproject.toml) first — that, not the git tag, is what the wheel ships — and match it with `version` + `date-released` in [`CITATION.cff`](../CITATION.cff).

1. **Build locally and install from it.**
   ```bash
   python -m build
   pip install dist/clinical_scope-*.whl
   ```
   → run `clinical-scope`, check the example.

2. **Tag and push** — this triggers [`build.yml`](../.github/workflows/build.yml), which drafts a GitHub Release with the standalone executables attached.
   ```bash
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
   → review the draft Release: executables attached, no build warnings.

3. **Dry-run on TestPyPI** — run **Publish to TestPyPI** manually from the Actions tab, then install from it (project from TestPyPI, dependencies from real PyPI):
   ```bash
   pip install -i https://test.pypi.org/simple/ \
     --extra-index-url https://pypi.org/simple/ "clinical-scope==X.Y.Z"
   ```
   → run `clinical-scope`, check the example.

4. **Publish for real** — undraft the GitHub Release (click *Publish release*). This triggers [`publish-pypi.yml`](../.github/workflows/publish-pypi.yml), which uploads the wheel + sdist to PyPI.
   ```bash
   pip install clinical-scope==X.Y.Z
   ```
   → run `clinical-scope`, check the example.

**Note:** versions can't be reused — TestPyPI and PyPI both reject re-uploading a version that already exists. Bump to a `.devN` (e.g. `X.Y.Z.dev0`) if you need to re-run the TestPyPI dry-run.

**Zenodo / DOI:** the repo is wired to [Zenodo's GitHub integration](https://zenodo.org/account/settings/github/), so publishing the GitHub Release (step 4) auto-archives it and mints a new version DOI under the concept DOI [`10.5281/zenodo.20830140`](https://doi.org/10.5281/zenodo.20830140). The README badge and [`CITATION.cff`](../CITATION.cff) track that concept DOI (always resolves to the latest release), so the DOI itself never needs editing per release.
