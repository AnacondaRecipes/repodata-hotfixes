# -*- coding: utf-8 -*-

"""Ensure libgomp hotfix constants stay in sync with openmp-research linkage audits."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENMP_RESEARCH = REPO_ROOT.parent / "openmp-research"
MANIFEST = OPENMP_RESEARCH / "inspect" / "libgomp_hotfix_manifest.json"
AUDIT_CSVS = (
    OPENMP_RESEARCH / "inspect" / "openmp_linux64_libgomp_audit.csv",
    OPENMP_RESEARCH / "inspect" / "openmp_linuxaarch64_libgomp_audit.csv",
)
FALLBACK_AUDIT_CSVS = (
    OPENMP_RESEARCH / "inspect" / "openmp_linux64_all.csv",
    OPENMP_RESEARCH / "inspect" / "openmp_linuxaarch64.csv",
)
VERIFY_SCRIPT = OPENMP_RESEARCH / "scripts" / "verify_libgomp_hotfix_coverage.py"


@pytest.fixture(scope="module")
def hotfix_main():
    return runpy.run_path(str(REPO_ROOT / "main.py"), run_name="hotfix_main")


def _audit_paths() -> list[Path]:
    if all(path.exists() for path in AUDIT_CSVS):
        return list(AUDIT_CSVS)
    if all(path.exists() for path in FALLBACK_AUDIT_CSVS):
        return list(FALLBACK_AUDIT_CSVS)
    return []


def _audit_available() -> bool:
    return bool(_audit_paths())


@pytest.mark.skipif(not _audit_available(), reason="openmp-research audit CSVs not present")
def test_hotfix_covers_all_audited_broken_builds(hotfix_main) -> None:
    """Delegate to openmp-research verifier (single source of truth for coverage logic)."""
    assert VERIFY_SCRIPT.exists(), f"Missing verifier: {VERIFY_SCRIPT}"
    sys.path.insert(0, str(VERIFY_SCRIPT.parent))
    import verify_libgomp_hotfix_coverage as verifier

    broken = verifier.collect_broken_rows(_audit_paths())
    missed = [
        row
        for row in broken
        if not verifier.hotfix_covers(row["name"], row["version"], row["subdir"], hotfix_main)
    ]
    assert not missed, (
        "Hotfix rules miss linkage-audited builds. Re-run "
        "openmp-research/inspect/inspect.py --libgomp-audit, refresh "
        "MISSING_LIBGOMP_EXACT_VERSIONS, or extend LIBTORCH_MISSING_LIBGOMP_UPPER_BOUND. "
        f"First misses: {missed[:5]}"
    )


@pytest.mark.skipif(not MANIFEST.exists(), reason="libgomp_hotfix_manifest.json not generated")
def test_exact_versions_match_manifest(hotfix_main) -> None:
    assert VERIFY_SCRIPT.exists()
    sys.path.insert(0, str(VERIFY_SCRIPT.parent))
    import verify_libgomp_hotfix_coverage as verifier

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = verifier.manifest_to_exact_versions(manifest, skip_names={"libtorch"})
    actual = verifier.hotfix_exact_versions(hotfix_main)
    issues = verifier.compare_exact_dict(expected, actual)
    assert not issues, "Hotfix version tables diverge from audit manifest:\n" + "\n".join(
        f"  - {line}" for line in issues
    )
