# -*- coding: utf-8 -*-

"""Tests for restoring jupyterlab 4.5.9 Navigator app metadata (PKG-17295).

PR https://github.com/AnacondaRecipes/jupyterlab-feedstock/pull/59 dropped the
recipe ``app:`` block. 4.5.7 still has the corresponding index fields; 4.5.9
does not. The hotfix should restore them when they are missing.
"""

from __future__ import annotations

__all__ = ()

from main import _patch_repodata, patch_record_in_place

# Recipe:
#   app:
#     entry: jupyter lab
#     icon: icon.png
#     summary: JupyterLab {{ version }}
#     type: desk
# conda-build maps those to index.json as:
JUPYTERLAB_APP_ENTRY = "jupyter lab"
JUPYTERLAB_APP_TYPE = "desk"
JUPYTERLAB_APP_KIND = "app"
# md5 of the feedstock icon.png, as used by 4.5.7 and earlier on main
JUPYTERLAB_ICON = "717340b6962ac8f292a17e7fa60ab5e7.png"


def _jupyterlab_record(version: str, build: str, *, with_app: bool = False) -> dict:
    record = {
        "build": build,
        "build_number": 0,
        "depends": [
            "python >=3.10,<3.11.0a0",
            "jupyter_server >=2.4.0,<3",
        ],
        "license": "BSD-3-Clause",
        "license_family": "BSD",
        "name": "jupyterlab",
        "subdir": "linux-64",
        "version": version,
    }
    if with_app:
        record["app_entry"] = JUPYTERLAB_APP_ENTRY
        record["app_type"] = JUPYTERLAB_APP_TYPE
        record["icon"] = JUPYTERLAB_ICON
        record["summary"] = f"JupyterLab {version}"
        record["type"] = JUPYTERLAB_APP_KIND
    return record


def _expected_app_fields(version: str) -> dict:
    return {
        "app_entry": JUPYTERLAB_APP_ENTRY,
        "app_type": JUPYTERLAB_APP_TYPE,
        "icon": JUPYTERLAB_ICON,
        "summary": f"JupyterLab {version}",
        "type": JUPYTERLAB_APP_KIND,
    }


def test_jupyterlab_459_missing_app_fields_are_restored() -> None:
    """4.5.9 records that lack app metadata get the 4.5.7 Navigator fields back."""
    fn = "jupyterlab-4.5.9-py310h06a4308_0.tar.bz2"
    record = _jupyterlab_record("4.5.9", "py310h06a4308_0")
    patch_record_in_place(fn, record, "linux-64")
    for key, value in _expected_app_fields("4.5.9").items():
        assert record[key] == value


def test_jupyterlab_459_patch_instructions_include_app_keys() -> None:
    """keys_to_check must emit app_entry, app_type, type, summary, and icon."""
    fn = "jupyterlab-4.5.9-py310h06a4308_0.tar.bz2"
    repodata = {
        "packages": {fn: _jupyterlab_record("4.5.9", "py310h06a4308_0")},
        "packages.conda": {},
    }
    instructions = _patch_repodata(repodata, "linux-64")
    patched = instructions["packages"][fn]
    for key, value in _expected_app_fields("4.5.9").items():
        assert patched[key] == value, f"{key} missing or wrong in patch instructions"


def test_jupyterlab_459_conda_only_record_is_patched() -> None:
    """A .conda-only 4.5.9 artifact (no tar.bz2 twin) is patched the same way."""
    fn = "jupyterlab-4.5.9-py310h06a4308_0.conda"
    repodata = {
        "packages": {},
        "packages.conda": {fn: _jupyterlab_record("4.5.9", "py310h06a4308_0")},
    }
    instructions = _patch_repodata(repodata, "linux-64")
    patched = instructions["packages.conda"][fn]
    for key, value in _expected_app_fields("4.5.9").items():
        assert patched[key] == value


def test_jupyterlab_459_idempotent_when_app_already_present() -> None:
    """Do not rewrite app fields that 4.5.9 already has."""
    fn = "jupyterlab-4.5.9-py310h06a4308_0.tar.bz2"
    record = _jupyterlab_record("4.5.9", "py310h06a4308_0", with_app=True)
    original = dict(record)
    patch_record_in_place(fn, record, "linux-64")
    for key in _expected_app_fields("4.5.9"):
        assert record[key] == original[key]


def test_jupyterlab_457_with_app_is_not_rewritten() -> None:
    """Earlier jupyterlab builds that still have app metadata stay as-is."""
    fn = "jupyterlab-4.5.7-py310h06a4308_0.tar.bz2"
    record = _jupyterlab_record("4.5.7", "py310h06a4308_0", with_app=True)
    original = dict(record)
    patch_record_in_place(fn, record, "linux-64")
    for key in _expected_app_fields("4.5.7"):
        assert record[key] == original[key]


def test_jupyterlab_462_missing_app_is_not_patched() -> None:
    """Scope is 4.5.9 only; later versions that also dropped app: are left alone."""
    fn = "jupyterlab-4.6.2-py310h06a4308_0.tar.bz2"
    record = _jupyterlab_record("4.6.2", "py310h06a4308_0")
    patch_record_in_place(fn, record, "linux-64")
    for key in ("app_entry", "app_type", "icon", "summary", "type"):
        assert key not in record
