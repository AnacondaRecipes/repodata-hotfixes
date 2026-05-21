"""Tests for .conda format support (PKG-14894).

Verifies that _patch_repodata processes both repodata["packages"] and
repodata["packages.conda"], and that REMOVALS/REVOKED patterns match
across package formats.
"""

from __future__ import annotations

from main import (
    _matches_pkg_pattern,
    _patch_repodata,
    _strip_pkg_ext,
    is_removed,
    is_revoked,
)


class TestStripPkgExt:
    def test_tar_bz2(self):
        assert _strip_pkg_ext("tk-8.6.15-h54e0aa7_0.tar.bz2") == ("tk-8.6.15-h54e0aa7_0", ".tar.bz2")

    def test_conda(self):
        assert _strip_pkg_ext("tk-8.6.15-h54e0aa7_0.conda") == ("tk-8.6.15-h54e0aa7_0", ".conda")

    def test_no_extension(self):
        assert _strip_pkg_ext("some-pattern-*") == ("some-pattern-*", "")


class TestMatchesPkgPattern:
    def test_exact_match_same_format(self):
        assert _matches_pkg_pattern("pkg-1.0-h0_0.tar.bz2", "pkg-1.0-h0_0.tar.bz2")

    def test_exact_match_cross_format(self):
        assert _matches_pkg_pattern("pkg-1.0-h0_0.conda", "pkg-1.0-h0_0.tar.bz2")

    def test_glob_without_extension(self):
        assert _matches_pkg_pattern("pkg-1.0-h0_0.conda", "pkg-*")
        assert _matches_pkg_pattern("pkg-1.0-h0_0.tar.bz2", "pkg-*")

    def test_glob_with_tar_bz2_matches_conda(self):
        assert _matches_pkg_pattern("numpy-1.11.3-py27_6.conda", "numpy-*1.11.3-*_6.tar.bz2")

    def test_no_false_positive(self):
        assert not _matches_pkg_pattern("other-1.0-h0_0.conda", "pkg-1.0-h0_0.tar.bz2")


class TestPatchRepodataCondaFormat:
    def _make_repodata(self, *, tar_bz2_records=None, conda_records=None):
        repodata = {"packages": {}, "packages.conda": {}}
        if tar_bz2_records:
            repodata["packages"] = tar_bz2_records
        if conda_records:
            repodata["packages.conda"] = conda_records
        return repodata

    def test_conda_only_package_gets_zlib_hotfix(self):
        repodata = self._make_repodata(conda_records={
            "tk-8.6.15-h54e0aa7_0.conda": {
                "name": "tk",
                "version": "8.6.15",
                "build": "h54e0aa7_0",
                "build_number": 0,
                "depends": ["zlib >=1.2.13,<1.3.0a0"],
                "subdir": "linux-64",
            }
        })
        instructions = _patch_repodata(repodata, "linux-64")
        tk_fix = instructions["packages.conda"].get("tk-8.6.15-h54e0aa7_0.conda", {})
        assert "depends" in tk_fix
        assert "zlib >=1.2.13,<2.0.0a0" in tk_fix["depends"]

    def test_tar_bz2_package_still_patched(self):
        repodata = self._make_repodata(tar_bz2_records={
            "tk-8.6.15-h54e0aa7_0.tar.bz2": {
                "name": "tk",
                "version": "8.6.15",
                "build": "h54e0aa7_0",
                "build_number": 0,
                "depends": ["zlib >=1.2.13,<1.3.0a0"],
                "subdir": "linux-64",
            }
        })
        instructions = _patch_repodata(repodata, "linux-64")
        tk_fix = instructions["packages"].get("tk-8.6.15-h54e0aa7_0.tar.bz2", {})
        assert "depends" in tk_fix
        assert "zlib >=1.2.13,<2.0.0a0" in tk_fix["depends"]

    def test_instructions_has_both_buckets(self):
        repodata = self._make_repodata()
        instructions = _patch_repodata(repodata, "linux-64")
        assert "packages" in instructions
        assert "packages.conda" in instructions

    def test_empty_packages_conda_handled(self):
        repodata = {"packages": {}}
        instructions = _patch_repodata(repodata, "linux-64")
        assert instructions["packages.conda"] == {}

    def test_removal_pattern_matches_conda_filename(self):
        assert is_removed("cffi-1.14.6-py36h7f8727e_0.conda", "linux-64")

    def test_revoke_pattern_matches_conda_filename(self):
        assert is_revoked("anaconda-navigator-2.6.0-py311h06a4308_1.conda", "any")
