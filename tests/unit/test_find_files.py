"""
Tests for find_files() — the central file-discovery function.

Covers both multi-file mode (multi=True) and single-file mode (multi=False)
with all disambiguation tiers:
  1. Extension filtering
  2. Single-match fast-path
  3. Stem deduplication (preferred extension)
  4. Single-stem fast-path
  5. Keyword filtering (ordered, progressive narrowing)
"""

from pathlib import Path

from clinical_data_visualizer.io.file_utils import find_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create(tmp_path: Path, *names: str) -> list[Path]:
    """Touch files and return their paths in the same order."""
    paths = []
    for name in names:
        p = tmp_path / name
        p.touch()
        paths.append(p)
    return paths


# ===========================================================================
# Multi-file mode (multi=True)
# ===========================================================================


class TestFindFilesMultiMode:
    """find_files with multi=True: returns all matching files sorted, or None."""

    def test_empty_folder_returns_none(self, tmp_path):
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result is None

    def test_no_matching_extension_returns_none(self, tmp_path):
        create(tmp_path, "data.txt", "data.parquet")
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result is None

    def test_single_match_returns_list(self, tmp_path):
        (p,) = create(tmp_path, "data.csv")
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result == [p]

    def test_multiple_matches_returned_sorted(self, tmp_path):
        create(tmp_path, "c.csv", "a.csv", "b.csv")
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result is not None
        assert [f.name for f in result] == ["a.csv", "b.csv", "c.csv"]

    def test_multiple_extensions_all_included(self, tmp_path):
        create(tmp_path, "a.csv", "b.parquet", "c.txt")
        result = find_files(tmp_path, [".csv", ".parquet"], "ds", multi=True)
        assert result is not None
        names = {f.name for f in result}
        assert names == {"a.csv", "b.parquet"}
        assert "c.txt" not in names

    def test_non_matching_files_excluded(self, tmp_path):
        create(tmp_path, "data.csv", "readme.md", "config.json")
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "data.csv"

    def test_keywords_ignored_in_multi_mode(self, tmp_path):
        """Keywords parameter has no effect in multi mode."""
        create(tmp_path, "alpha.csv", "beta.csv")
        result = find_files(tmp_path, [".csv"], "ds", multi=True, keywords=["alpha"])
        assert result is not None
        assert len(result) == 2  # both returned, keyword not applied

    def test_extension_case_insensitive(self, tmp_path):
        p = tmp_path / "DATA.CSV"
        p.touch()
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result == [p]

    def test_directories_not_included(self, tmp_path):
        """Subdirectories with matching extensions must not be returned."""
        subdir = tmp_path / "data"
        subdir.mkdir()
        result = find_files(tmp_path, [], "ds", multi=True)
        assert result is None

    def test_directories_as_filename_not_included(self, tmp_path):
        """Subdirectories with matching extensions must not be returned."""
        subdir = tmp_path / "data.csv"
        subdir.mkdir()
        result = find_files(tmp_path, [".csv"], "ds", multi=True)
        assert result is None


# ===========================================================================
# Single-file mode (multi=False) — Tier 1: extension filtering
# ===========================================================================


class TestFindFilesSingleExtensionFiltering:
    """Stage 1-2 of single-file disambiguation: collect by extension, fast-path if one match."""

    def test_empty_folder_returns_none(self, tmp_path):
        result = find_files(tmp_path, [".csv"], "ds")
        assert result is None

    def test_no_matching_extension_returns_none(self, tmp_path):
        create(tmp_path, "data.txt")
        result = find_files(tmp_path, [".csv"], "ds")
        assert result is None

    def test_single_match_returned_directly(self, tmp_path):
        (p,) = create(tmp_path, "data.csv")
        result = find_files(tmp_path, [".csv"], "ds")
        assert result == p

    def test_unrelated_extension_excluded(self, tmp_path):
        path = create(tmp_path, "data.txt", "readme.md", "data.csv")
        result = find_files(tmp_path, [".csv"], "ds")
        assert result == path[-1]

    def test_extension_matching_is_case_insensitive(self, tmp_path):
        p = tmp_path / "DATA.CSV"
        p.touch()
        result = find_files(tmp_path, [".csv"], "ds")
        assert result == p

    def test_no_extensions_collects_all_files(self, tmp_path):
        (p,) = create(tmp_path, "only_file.xyz")
        result = find_files(tmp_path, [], "ds")
        assert result == p

    def test_no_extensions_multiple_files_falls_through_to_keywords(self, tmp_path):
        create(tmp_path, "alpha.xyz", "beta.xyz")
        result = find_files(tmp_path, [], "ds", keywords=["alpha"])
        assert result is not None
        assert result.name == "alpha.xyz"

    def test_directories_not_included(self, tmp_path):
        """Subdirectories with matching extensions must not be returned."""
        subdir = tmp_path / "data.csv"
        subdir.mkdir()
        result = find_files(tmp_path, [".csv"], "ds")
        assert result is None


# ===========================================================================
# Single-file mode — Tier 2: stem deduplication
# ===========================================================================


class TestFindFilesSingleStemDeduplication:
    """
    Stage 3-4: when multiple extension variants of the same stem exist,
    keep only the most preferred extension per stem.
    """

    def test_same_stem_picks_preferred_extension(self, tmp_path):
        """data.parquet preferred over data.csv when ['.parquet', '.csv']."""
        create(tmp_path, "data.csv", "data.parquet")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds")
        assert result is not None
        assert result.name == "data.parquet"

    def test_same_stem_csv_preferred_when_listed_first(self, tmp_path):
        create(tmp_path, "data.csv", "data.parquet")
        result = find_files(tmp_path, [".csv", ".parquet"], "ds")
        assert result is not None
        assert result.name == "data.csv"

    def test_three_extensions_same_stem_picks_highest_preference(self, tmp_path):
        create(tmp_path, "data.txt", "data.csv", "data.parquet")
        result = find_files(tmp_path, [".csv", ".txt"], "ds")
        assert result is not None
        assert result.name == "data.csv"

    def test_one_stem_after_dedup_returns_it(self, tmp_path):
        """After dedup, exactly one unique stem remains → return without keywords."""
        create(tmp_path, "data.csv", "data.parquet")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["irrelevant"])
        assert result is not None
        assert result.name == "data.parquet"

    def test_two_stems_different_ext_after_dedup(self, tmp_path):
        """a.parquet and b.csv → two distinct stems → resolve using extension"""
        create(tmp_path, "alpha.parquet", "beta.csv")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds")
        assert result.name == "alpha.parquet"

    def test_two_stems_same_kw_different_ext(self, tmp_path):
        """a.parquet and b.csv → two distinct stems → same keyword → resolve using extension"""
        create(tmp_path, "alpha_one.parquet", "beta_one.csv")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["one"])
        assert result.name == "alpha_one.parquet"

    def test_mixed_stems_dedup_then_keyword(self, tmp_path):
        """a.parquet, a.csv, b.csv → after dedup: a.parquet + b.csv → keyword 'alpha' → a.parquet."""
        paths = create(tmp_path, "alpha.parquet", "alpha.csv", "beta.csv")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["alpha"])
        assert result == paths[0]

    def test_extension_not_in_list_ignored_during_dedup(self, tmp_path):
        """A .txt file present when only .parquet/.csv listed: ignored entirely."""
        create(tmp_path, "data.txt")
        (p,) = create(tmp_path, "data.parquet")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds")
        assert result == p


# ===========================================================================
# Single-file mode — Tier 3: keyword disambiguation
# ===========================================================================


class TestFindFilesSingleKeywordDisambiguation:
    """Stage 5: keyword list used to resolve remaining ambiguity after stem dedup."""

    def test_no_keywords_multiple_stems_returns_none(self, tmp_path):
        create(tmp_path, "alpha.csv", "beta.csv")
        result = find_files(tmp_path, [".csv"], "ds")
        assert result is None

    def test_empty_keywords_multiple_stems_returns_none(self, tmp_path):
        create(tmp_path, "alpha.csv", "beta.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=[])
        assert result is None

    def test_first_keyword_resolves(self, tmp_path):
        (p,) = create(tmp_path, "numerics_export.csv")
        create(tmp_path, "waves_export.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["numerics"])
        assert result == p

    def test_second_keyword_resolves_when_first_matches_none(self, tmp_path):
        (p,) = create(tmp_path, "numerics.csv")
        create(tmp_path, "waves.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["missing_kw", "numerics"])
        assert result == p

    def test_first_keyword_narrows_second_resolves(self, tmp_path):
        """First keyword narrows 3→2, second keyword narrows 2→1."""
        create(tmp_path, "resp_numeric_a.csv", "resp_numeric_b.csv", "unrelated.csv")
        (p,) = create(tmp_path, "resp_numeric_exact.csv")
        # keyword "resp" narrows to 3 (resp_numeric_a, resp_numeric_b, resp_numeric_exact)
        # keyword "exact" then resolves to 1
        result = find_files(tmp_path, [".csv"], "ds", keywords=["resp", "exact"])
        assert result == p

    def test_first_keyword_narrows_second_useless_third_resolves(self, tmp_path):
        """First keyword narrows 3→2, second keyword narrows 2→1."""
        create(tmp_path, "resp_numeric_a.csv", "resp_numeric_b.csv", "unrelated.csv")
        (p,) = create(tmp_path, "resp_numeric_exact.csv")
        # keyword "resp" narrows to 3 (resp_numeric_a, resp_numeric_b, resp_numeric_exact)
        # keyword "exact" then resolves to 1
        result = find_files(tmp_path, [".csv"], "ds", keywords=["resp", "anywhere", "exact"])
        assert result == p

    def test_keyword_matching_is_case_insensitive(self, tmp_path):
        (p,) = create(tmp_path, "Numerics_Export.csv")
        create(tmp_path, "Waves_Export.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["NUMERICS"])
        assert result == p

    def test_keyword_is_substring_match(self, tmp_path):
        """Keyword 'num' matches 'patient_numerics_2024.csv'."""
        (p,) = create(tmp_path, "patient_numerics_2024.csv")
        create(tmp_path, "patient_waves_2024.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["num"])
        assert result == p

    def test_all_keywords_exhausted_ambiguous_returns_none(self, tmp_path):
        create(tmp_path, "alpha_data.csv", "beta_data.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["data"])
        # "data" matches both → still ambiguous
        assert result is None

    def test_keyword_narrows_but_stays_ambiguous_returns_none(self, tmp_path):
        create(tmp_path, "resp_a.csv", "resp_b.csv", "unrelated.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["resp"])
        # "resp" matches 2 → still ambiguous, no more keywords
        assert result is None

    def test_keyword_matching_nothing_tries_next(self, tmp_path):
        (p,) = create(tmp_path, "numerics.csv")
        create(tmp_path, "waves.csv")
        result = find_files(tmp_path, [".csv"], "ds", keywords=["zzz", "numerics"])
        assert result == p

    def test_progressive_narrowing_three_keywords(self, tmp_path):
        """Each keyword narrows until one remains."""
        create(
            tmp_path,
            "mindray_resp_waves_a.csv",
            "mindray_resp_waves_b.csv",
            "mindray_resp_numeric.csv",
            "other.csv",
        )
        (p,) = create(tmp_path, "mindray_resp_waves_final.csv")
        # "mindray" → 4 (all except other); "waves" → 3 (a, b, final); "final" → 1
        result = find_files(tmp_path, [".csv"], "ds", keywords=["mindray", "waves", "final"])
        assert result == p


# ===========================================================================
# Single-file mode — combined tier interaction
# ===========================================================================


class TestFindFilesSingleCombined:
    """End-to-end disambiguation through all tiers together."""

    def test_stem_dedup_then_keyword(self, tmp_path):
        """
        Files: numerics.parquet, numerics.csv, waves.csv
        Extensions preferred: ['.parquet', '.csv']
        After dedup: numerics.parquet, waves.csv
        Keyword 'numerics' → numerics.parquet
        """
        (p,) = create(tmp_path, "numerics.parquet")
        create(tmp_path, "numerics.csv", "waves.csv")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["numerics"])
        assert result == p

    def test_single_file_no_disambiguation_needed(self, tmp_path):
        """When only one file matches the extension, returns immediately."""
        path = create(tmp_path, "data.parquet", "data.txt") # excluded by extension filter
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["waves"])
        assert result == path[0]

    def test_realistic_philips_scenario(self, tmp_path):
        """
        Simulates a folder with both Philips waves and numerics files.
        extensions=['.parquet', '.csv'], keywords=['waves']
        """
        path = create(tmp_path, "philips_numerics.parquet", "philips_waves.parquet", "philips_waves.csv")
        # Both .parquet files survive extension filter; numerics + waves unique stems
        # Stem dedup: philips_numerics.parquet, philips_waves.parquet (preferred over .csv)
        # Keyword 'waves' → philips_waves.parquet
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["waves"])
        assert result is not None
        assert result == path[1]

    def test_realistic_fluxmed_scenario(self, tmp_path):
        """
        Folder has both parameters and signals files.
        keywords=['parameters'] should select the parameters file.
        """
        create(tmp_path, "fluxmed_signals.parquet")
        (p,) = create(tmp_path, "fluxmed_parameters.parquet")
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["parameters"])
        assert result == p

    def test_no_files_at_all_returns_none(self, tmp_path):
        result = find_files(tmp_path, [".parquet", ".csv"], "ds", keywords=["data"])
        assert result is None

    def test_file_with_no_extension_excluded_when_extensions_given(self, tmp_path):
        create(tmp_path, "no_extension_file")
        result = find_files(tmp_path, [".csv"], "ds")
        assert result is None

    def test_file_with_no_extension_included_when_no_extensions(self, tmp_path):
        (p,) = create(tmp_path, "no_extension_file")
        result = find_files(tmp_path, [], "ds")
        assert result == p
