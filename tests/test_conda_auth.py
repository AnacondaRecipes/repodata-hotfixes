"""Compatibility constraints for published conda-auth packages."""

import copy

import pytest
from conda_index.index import _apply_instructions

from main import _patch_repodata


@pytest.mark.parametrize("formats", [("packages",), ("packages.conda",), ("packages", "packages.conda")])
@pytest.mark.parametrize(
    "name,version,timestamp,affected",
    [
        ("conda-auth", "0.2.0", 1700754324876, True),
        ("conda-auth", "0.2.1", 1790232812666, True),
        ("conda-auth", "0.2.1", 1793622915000, False),
        ("conda-auth", "0.2.2", 1790232812666, False),
        ("other-package", "0.2.1", 1790232812666, False),
    ],
)
def test_conda_auth_compatibility(formats, name, version, timestamp, affected):
    record = {
        "name": name,
        "version": version,
        "build": "py311_0",
        "build_number": 0,
        "depends": ["conda >=23.9.0", "python >=3.11,<3.12.0a0", "requests"],
        "subdir": "linux-64",
        "timestamp": timestamp,
    }
    extensions = {"packages": ".tar.bz2", "packages.conda": ".conda"}
    repodata = {
        section: {f"{name}-{version}-py311_0{extensions[section]}": copy.deepcopy(record)}
        for section in formats
    }
    instructions = _patch_repodata(copy.deepcopy(repodata), "linux-64")
    result = _apply_instructions("linux-64", copy.deepcopy(repodata), instructions)
    expected = copy.deepcopy(record)
    if affected:
        expected["depends"][0] = "conda >=23.9.0,<26.9.0a0"
    for section in formats:
        assert next(iter(result[section].values())) == expected

    repeated = _patch_repodata(copy.deepcopy(result), "linux-64")
    assert _apply_instructions("linux-64", copy.deepcopy(result), repeated) == result
