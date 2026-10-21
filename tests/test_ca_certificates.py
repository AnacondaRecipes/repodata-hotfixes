"""Tests for CA bundle constraints on existing solver and libmamba records."""

import copy
import json
from pathlib import Path

import pytest
from conda_index.index import _apply_instructions

from main import _patch_repodata


RECORDS = json.loads(
    (Path(__file__).parent / "data/ca_bundle_records.json").read_text()
)
FORMATS = (("packages", ".tar.bz2"), ("packages.conda", ".conda"))


def patched(repodata, subdir):
    instructions = _patch_repodata(copy.deepcopy(repodata), subdir)
    return _apply_instructions(subdir, copy.deepcopy(repodata), instructions)


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("sample", RECORDS, ids=lambda sample: sample["filename"])
def test_published_records_gain_constraints(sample, section, extension):
    record = sample["record"]
    filename = sample["filename"].removesuffix(".tar.bz2").removesuffix(".conda") + extension
    repodata = {section: {filename: record}}
    result = patched(repodata, sample["subdir"])[section][filename]
    assert "ca-certificates >=2026.10.20" in result["constrains"]
    if record["name"] == "conda-libmamba-solver":
        assert "certifi >=2026.10.19" in result["constrains"]
    else:
        assert not any(pin.startswith("certifi") for pin in result["constrains"])
    assert result["depends"] == record["depends"]
    second = patched({section: {filename: result}}, sample["subdir"])[section][filename]
    assert second["constrains"] == result["constrains"]


@pytest.mark.parametrize("sample", RECORDS, ids=lambda sample: sample["filename"])
def test_dual_archive_records_are_mirrored(sample):
    stem = sample["filename"].removesuffix(".tar.bz2").removesuffix(".conda")
    repodata = {
        section: {stem + extension: copy.deepcopy(sample["record"])}
        for section, extension in FORMATS
    }
    result = patched(repodata, sample["subdir"])
    assert (
        result["packages"][stem + ".tar.bz2"]["constrains"]
        == result["packages.conda"][stem + ".conda"]["constrains"]
    )
    assert (
        "ca-certificates >=2026.10.20"
        in result["packages"][stem + ".tar.bz2"]["constrains"]
    )


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize(
    "name,version,build_number,affected",
    [
        ("conda-libmamba-solver", "26.5.0", 4, True),
        ("conda-libmamba-solver", "26.7.0", 0, True),
        ("conda-libmamba-solver", "26.7.0", 1, False),
        ("conda-libmamba-solver", "26.7.0", 2, False),
        ("conda-libmamba-solver", "26.9.0", 0, False),
        ("libmamba", "2.0.0", 6, True),
        ("libmamba", "2.3.2", 5, True),
        ("libmamba", "2.3.2", 6, False),
        ("libmamba", "2.3.2", 7, False),
        ("libmamba", "2.4.0", 0, False),
    ],
)
def test_affected_versions_and_builds(section, extension, name, version, build_number, affected):
    record = {
        "name": name,
        "version": version,
        "build": str(build_number),
        "build_number": build_number,
        "depends": [],
        "constrains": ["unrelated-package <3"],
        "subdir": "linux-64",
    }
    filename = f"{name}-{version}-{build_number}{extension}"
    result = patched({section: {filename: record}}, "linux-64")[section][filename]
    if affected:
        assert "ca-certificates >=2026.10.20" in result["constrains"]
        assert ("certifi >=2026.10.19" in result["constrains"]) == (
            name == "conda-libmamba-solver"
        )
        assert "unrelated-package <3" in result["constrains"]
        assert result["depends"] == []
    else:
        assert result == record


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("name", ["unrelated-package", "libmambapy", "micromamba", "mamba"])
def test_unrelated_records_unchanged(section, extension, name):
    record = {
        "name": name,
        "version": "2.3.2",
        "build": "0",
        "build_number": 0,
        "depends": [],
        "constrains": ["ca-certificates >=2025,<2027"],
        "subdir": "linux-64",
    }
    filename = f"{name}-2.3.2-0{extension}"
    assert (
        patched({section: {filename: record}}, "linux-64")[section][filename] == record
    )


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("constraint", ["certifi >=2026.10.19", "ca-certificates >=2026.10.20"])
def test_partial_hotfix_is_completed(section, extension, constraint):
    record = {
        "name": "conda-libmamba-solver",
        "version": "26.7.0",
        "build": "0",
        "build_number": 0,
        "depends": [],
        "constrains": [constraint],
        "subdir": "noarch",
    }
    filename = f"conda-libmamba-solver-26.7.0-0{extension}"
    result = patched({section: {filename: record}}, "noarch")[section][filename]
    assert sorted(result["constrains"]) == [
        "ca-certificates >=2026.10.20",
        "certifi >=2026.10.19",
    ]
    assert result["depends"] == []
