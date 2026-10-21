"""Tests for CA bundle constraints on existing solver and libmamba records."""

import copy
import json
from pathlib import Path

import pytest
from conda_index.index import _apply_instructions

from main import _patch_repodata


CUTOFF = 1789545284140
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
    filename = sample["filename"].removesuffix(".tar.bz2") + extension
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
    stem = sample["filename"].removesuffix(".tar.bz2")
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
@pytest.mark.parametrize("name", ["conda-libmamba-solver", "libmamba", "mamba"])
@pytest.mark.parametrize("timestamp", [None, 0, CUTOFF, CUTOFF + 1])
def test_cutoff_and_missing_timestamps(section, extension, name, timestamp):
    record = {
        "name": name,
        "version": "26.7.0" if name == "conda-libmamba-solver" else "2.3.2",
        "build": "0",
        "build_number": 0,
        "depends": [],
        "subdir": "linux-64",
    }
    if timestamp is not None:
        record["timestamp"] = timestamp
    filename = f"{name}-{record['version']}-0{extension}"
    result = patched({section: {filename: record}}, "linux-64")[section][filename]
    if timestamp == CUTOFF + 1:
        assert "constrains" not in result
    else:
        assert "ca-certificates >=2026.10.20" in result["constrains"]
        assert ("certifi >=2026.10.19" in result["constrains"]) == (
            name == "conda-libmamba-solver"
        )
        assert result["depends"] == []


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("name", ["unrelated-package", "libmambapy", "micromamba"])
def test_unrelated_records_unchanged(section, extension, name):
    record = {
        "name": name,
        "version": "2.3.2",
        "build": "0",
        "build_number": 0,
        "depends": [],
        "constrains": ["ca-certificates >=2025,<2027"],
        "subdir": "linux-64",
        "timestamp": CUTOFF,
    }
    filename = f"{name}-2.3.2-0{extension}"
    assert (
        patched({section: {filename: record}}, "linux-64")[section][filename] == record
    )


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("field", ["depends", "constrains"])
@pytest.mark.parametrize(
    "pin",
    [
        "ca-certificates >=2026.10.21",
        "ca-certificates >=2025,<2027",
        "ca-certificates >=2026.10.20,<2027 build_*",
        "ca-certificates[version='>=2026.10.21,<2027']",
        "ca-certificates >=2026.10.21|==2025.1.1",
    ],
)
def test_prior_restrictions_are_preserved(section, extension, field, pin):
    record = {
        "name": "libmamba",
        "version": "2.3.2",
        "build": "0",
        "build_number": 0,
        "depends": [],
        "constrains": ["unrelated-package <3"],
        "subdir": "linux-64",
        "timestamp": CUTOFF,
    }
    record[field].append(pin)
    filename = f"libmamba-2.3.2-0{extension}"
    result = patched({section: {filename: record}}, "linux-64")[section][filename]
    assert result == record


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("field", ["depends", "constrains"])
def test_solver_adds_only_the_missing_floor(section, extension, field):
    record = {
        "name": "conda-libmamba-solver",
        "version": "26.7.0",
        "build": "0",
        "build_number": 0,
        "depends": [],
        "constrains": [],
        "subdir": "linux-64",
        "timestamp": CUTOFF,
    }
    record[field].append("certifi >=2026.10.21,<2027")
    filename = f"conda-libmamba-solver-26.7.0-0{extension}"
    result = patched({section: {filename: record}}, "linux-64")[section][filename]
    assert "certifi >=2026.10.21,<2027" in result[field]
    assert "ca-certificates >=2026.10.20" in result["constrains"]
    assert "certifi >=2026.10.19" not in result["constrains"]


@pytest.mark.parametrize("section,extension", FORMATS)
@pytest.mark.parametrize("version", ["1.5.8", "2.0"])
def test_historical_mamba_certifi_constraint(section, extension, version):
    record = {
        "name": "mamba",
        "version": version,
        "build": "0",
        "build_number": 0,
        "depends": ["python >=3.8"],
        "subdir": "linux-64",
        "timestamp": CUTOFF,
    }
    filename = f"mamba-{version}-0{extension}"
    result = patched({section: {filename: record}}, "linux-64")[section][filename]
    assert "ca-certificates >=2026.10.20" in result["constrains"]
    assert ("certifi >=2026.10.19" in result["constrains"]) == (version == "1.5.8")
    assert result["depends"] == record["depends"]
