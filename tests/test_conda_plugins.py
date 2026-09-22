import pytest

from main import _patch_repodata


@pytest.mark.parametrize("section,extension", [("packages", ".tar.bz2"), ("packages.conda", ".conda")])
@pytest.mark.parametrize(
    "name,version,telemetry,tos",
    [
        ("conda", "26.7.2", "0.3.0", "0.2.1"),
        ("conda", "26.9.0a0", "0.3.1", "0.3.0"),
        ("conda", "26.9.0rc1", "0.3.1", "0.3.0"),
        ("conda", "26.9.0", "0.3.1", "0.3.0"),
        ("conda", "27.3.0", "0.3.1", "0.3.0"),
        ("conda-build", "26.9.0", "0.3.0", None),
    ],
)
def test_conda_plugin_constraints(section, extension, name, version, telemetry, tos):
    filename = f"{name}-{version}-py314_0{extension}"
    record = {
        "name": name,
        "version": version,
        "build": "py314_0",
        "build_number": 0,
        "depends": ["python >=3.14,<3.15.0a0"],
        "constrains": ["unrelated >=1", "conda-anaconda-telemetry >=0.2.0"],
        "subdir": "linux-64",
    }
    repodata = {"packages": {}, "packages.conda": {}}
    repodata[section][filename] = record

    instructions = _patch_repodata(repodata, "linux-64")

    expected = ["unrelated >=1", f"conda-anaconda-telemetry >={telemetry}"]
    if tos is not None:
        expected.append(f"conda-anaconda-tos >={tos}")
    assert sorted(instructions[section][filename]["constrains"]) == sorted(expected)
    assert "depends" not in instructions[section][filename]
