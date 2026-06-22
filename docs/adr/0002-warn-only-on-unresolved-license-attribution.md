# 2. Warn-only on unresolved third-party license attribution

Date: 2026-06-22

## Status

Accepted

## Context

The shipped redistributable is a PyInstaller bundle whose `_internal/` folder physically redistributes the full transitive dependency tree plus native shared libraries. Permissive licenses require the original notices to travel with the distribution, but PyInstaller strips them (pyinstaller/pyinstaller#5666). `build_info/generate_third_party_licenses.py` reconstructs a `THIRD_PARTY_LICENSES.txt` at build time: it harvests license texts from the build interpreter's installed distributions and matches native libs in `_internal/` against a hand-maintained map.

Two classes of gap are unavoidable and platform-dependent: a package that ships no license file upstream, and a native shared library not yet in the hand-maintained map (a new dependency, or a different platform's build pulling in libs the macOS arm build never did). The question is what the build should do when it hits one — fail-fast (block the build until the gap is resolved) or warn-only (build anyway, flag the gap).

Fail-fast guarantees no release ever ships with an attribution gap, but it blocks *every* build — including the iterative ones during development where a freshly-added dependency hasn't been mapped yet and the bundle isn't going anywhere. Pure warn-only never blocks, but a warning line scrolls past in build output and is easy to miss for the one build that matters: the release.

## Decision

**Warn-only, but exit-code-aware.** When attribution is unresolved (a package with no license file, or an unrecognised native lib), the generator still writes `THIRD_PARTY_LICENSES.txt` — with `*** TODO` markers and an `UNRECOGNISED NATIVE LIBRARIES` block — and exits **non-zero**. `build.sh` surfaces that non-zero exit as a loud red warning but does **not** fail the build.

The non-zero exit is what makes warn-only trustworthy: the gap becomes a real signal (an exit code a human or a future CI step can branch on) rather than a line of stdout. Iterative builds are never blocked; the release build's gap is impossible to scroll past.

The same policy applies to the CI build (`.github/workflows/build.yml`, which reconstructs the same artifact on a tag push / manual dispatch): the generator's non-zero exit is turned into a GitHub `::warning::` annotation rather than a failed job. Two reasons it stays warn-only there too: (1) the `NATIVE_LICENSES` map is currently populated only for the macOS-arm build, so the Windows/Linux runners will legitimately emit `*** TODO` entries until their native libs are mapped, and failing would block all releases on a known, in-progress gap; (2) CI publishes a **draft** release, so a human still reviews the artifact before it goes public — the gate is preserved.

## Consequences

- **Easier:** adding a dependency never blocks a local or CI build; the developer/maintainer sees exactly which package/lib needs a notice and resolves it before publishing.
- **Harder / accepted trade-offs:** nothing *mechanically* prevents a draft release carrying `*** TODO` markers — the gate relies on a human heeding the warning/annotation before publishing the draft. Acceptable while a maintainer reviews each draft release by hand.
- **Revisit toward fail-fast if:** release *publishing* (not just building) becomes automatic, removing the human draft-review gate; at that point wire the generator's non-zero exit to fail the release job. This becomes safe to do once `NATIVE_LICENSES` covers every CI platform, so the only remaining non-zero exits are genuine new gaps.
