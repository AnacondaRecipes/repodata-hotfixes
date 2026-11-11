# -*- coding: utf-8 -*-

"""Tests for the GCC toolchain ``_gcc_mutex`` hotfix.

The upcoming manylinux-compliant toolchain will use a different build of
``_gcc_mutex``. Every package that is part of, or depends on, the current GCC
toolchain must gain ``_gcc_mutex * main_*`` so that existing packages cannot
be mixed with the future manylinux ones in a combined-channel environment.
"""

from __future__ import annotations

__all__ = ()

import copy

import pytest
from conda_index.index import _apply_instructions

from main import (
    GCC_MUTEX_DEPENDENCY,
    GCC_MUTEX_PACKAGE,
    _patch_repodata,
    patch_record_in_place,
)


def _make_record(name: str, depends: list[str], build: str = "h1234567_0") -> dict:
    """Build a minimal record dict suitable for ``patch_record_in_place``."""
    build_number_str = build.rsplit("_", 1)[-1]
    try:
        build_number = int(build_number_str)
    except ValueError:
        build_number = 0
    return {
        "name": name,
        "version": "15.2.0",
        "build": build,
        "build_number": build_number,
        "depends": list(depends),
    }


@pytest.mark.parametrize(
    ["name", "subdir", "depends"],
    [
        # Compiler/toolchain packages.
        pytest.param(
            "gcc_linux-64",
            "linux-64",
            ["binutils_linux-64", "gcc_impl_linux-64 15.2.0.*", "sysroot_linux-64"],
            id="gcc_metapackage",
        ),
        pytest.param(
            "gcc_impl_linux-64",
            "linux-64",
            ["binutils_impl_linux-64 >=2.44", "libgcc 15.2.0 h69a1729_8", "sysroot_linux-64"],
            id="gcc_impl",
        ),
        pytest.param(
            "gxx_linux-aarch64",
            "linux-aarch64",
            ["gcc_linux-aarch64", "gxx_impl_linux-aarch64 15.2.0.*"],
            id="gxx_metapackage",
        ),
        pytest.param(
            "gfortran_linux-ppc64le",
            "linux-ppc64le",
            ["gcc_linux-ppc64le", "gfortran_impl_linux-ppc64le 11.2.0.*"],
            id="gfortran_metapackage",
        ),
        pytest.param(
            "binutils_linux-64",
            "linux-64",
            ["binutils_impl_linux-64 2.44 h4b9a079_2"],
            id="binutils_metapackage",
        ),
        pytest.param(
            "clang_impl_linux-64",
            "linux-64",
            ["binutils_impl_linux-64", "libgcc-devel_linux-64", "sysroot_linux-64"],
            id="compiler_depending_on_toolchain",
        ),
        pytest.param(
            "mypyc",
            "linux-64",
            ["gcc_linux-64 11.2.0.*", "mypy 1.10.0", "python >=3.10,<3.11.0a0"],
            id="package_depending_on_gcc",
        ),
        # Runtime / build-only components are part of the same generation.
        pytest.param(
            "libgcc-ng",
            "linux-64",
            ["libgcc 15.2.0 h69a1729_8"],
            id="libgcc_ng_runtime",
        ),
        pytest.param(
            "libgcc",
            "linux-64",
            ["__glibc >=2.28,<3.0.a0", "_openmp_mutex >=4.5"],
            id="libgcc_runtime",
        ),
        pytest.param(
            "libgomp",
            "linux-64",
            ["__glibc >=2.28,<3.0.a0"],
            id="libgomp_runtime",
        ),
        pytest.param(
            "libgfortran5",
            "linux-64",
            ["libgcc 15.2.0 h69a1729_8"],
            id="libgfortran_runtime",
        ),
        pytest.param(
            "libstdcxx-ng",
            "linux-64",
            ["libstdcxx 15.2.0 h39759b7_8"],
            id="libstdcxx_ng_runtime",
        ),
        # Ordinary packages built against the current generation are fenced too.
        pytest.param(
            "numpy",
            "linux-64",
            ["libgcc-ng >=11.2.0", "libstdcxx-ng >=11.2.0", "python"],
            id="legacy_runtime_dependent",
        ),
        pytest.param(
            "numpy",
            "linux-64",
            ["libgcc >=14", "libstdcxx >=14", "python"],
            id="split_runtime_dependent",
        ),
        pytest.param(
            "msgpack-python",
            "linux-64",
            ["libstdcxx-ng >=4.9", "python"],
            id="libstdcxx_only_dependent",
        ),
        pytest.param(
            "python",
            "linux-64",
            ["ld_impl_linux-64 2.44 h153f514_2", "libffi >=3.4", "openssl"],
            id="python_depending_on_ld_impl",
        ),
    ],
)
def test_gcc_toolchain_dependents_gain_mutex(
    name: str, subdir: str, depends: list[str]
) -> None:
    """Toolchain components and their dependents gain the generation marker.

    These records are the current GCC generation. Pinning them to
    ``_gcc_mutex * main_*`` makes them mutually exclusive with the future
    manylinux builds, which will require ``_gcc_mutex * manylinux_*``.
    """
    record = _make_record(name, depends)
    patch_record_in_place(f"{name}-15.2.0-h1234567_0.tar.bz2", record, subdir)
    assert record["depends"].count(GCC_MUTEX_DEPENDENCY) == 1


def test_existing_libgcc_mutex_does_not_satisfy_gcc_mutex() -> None:
    """_libgcc_mutex is unrelated to toolchain generation and must not skip the marker.

    _libgcc_mutex only arbitrates the legacy libgcc runtime. A package can have
    it and still be part of the current toolchain, so the generation marker must
    be added independently.
    """
    record = _make_record(
        "gcc_impl_linux-64",
        ["_libgcc_mutex 0.1 main", "sysroot_linux-64"],
    )
    patch_record_in_place("gcc_impl_linux-64-15.2.0-h1234567_0.tar.bz2", record, "linux-64")
    assert "_libgcc_mutex 0.1 main" in record["depends"]
    assert record["depends"].count(GCC_MUTEX_DEPENDENCY) == 1


def test_existing_gcc_mutex_is_not_duplicated() -> None:
    """Stamping an already-pinned record must not append a second marker.

    The hotfix is applied to repodata repeatedly; duplicate dependency entries
    would bloat metadata and could confuse downstream tooling.
    """
    record = _make_record(
        "gcc_impl_linux-64",
        ["sysroot_linux-64", GCC_MUTEX_DEPENDENCY],
    )
    patch_record_in_place("gcc_impl_linux-64-15.2.0-h1234567_0.tar.bz2", record, "linux-64")
    assert record["depends"].count(GCC_MUTEX_DEPENDENCY) == 1


def test_mutex_dependency_targets_gcc_mutex() -> None:
    """Guard the marker target: the new generation mutex, not _libgcc_mutex.

    Matching a build glob rather than an exact build keeps the pin valid as
    mutex build strings gain suffixes/numbers over time.
    """
    assert GCC_MUTEX_PACKAGE == "_gcc_mutex"
    assert GCC_MUTEX_DEPENDENCY.startswith("_gcc_mutex ")


def test_existing_manylinux_pin_is_left_alone() -> None:
    """A record already pinned to the manylinux generation must not be re-pinned.

    Rewriting it to ``* main_*`` would make newly built manylinux packages
    unusable in manylinux environments.
    """
    depends = ["libgcc-ng >=15", "_gcc_mutex * manylinux"]
    record = _make_record("numpy", depends)
    patch_record_in_place("numpy-2.3.0-h1234567_0.tar.bz2", record, "linux-64")
    assert record["depends"] == depends


def test_manylinux_pin_in_constrains_is_left_alone() -> None:
    """A generation pin in ``constrains`` is honored too.

    Adding a ``* main_*`` dependency would contradict an existing manylinux
    constrain and make the record unsolvable.
    """
    record = _make_record("numpy", ["libgcc-ng >=15"])
    record["constrains"] = [GCC_MUTEX_PACKAGE + " * manylinux"]
    patch_record_in_place("numpy-2.3.0-h1234567_0.tar.bz2", record, "linux-64")
    assert record["depends"] == ["libgcc-ng >=15"]


@pytest.mark.parametrize(
    ["name", "depends"],
    [
        pytest.param("_libgcc_mutex", [], id="libgcc_mutex"),
        # Older _openmp_mutex builds depend on libgomp, which is itself a
        # toolchain component. The explicit mutex exclusion must take priority.
        pytest.param(
            "_openmp_mutex",
            ["_libgcc_mutex 0.1 main", "libgomp >=7.5.0"],
            id="openmp_mutex_with_libgomp",
        ),
        pytest.param("_gcc_mutex", [], id="gcc_mutex"),
    ],
)
def test_mutex_packages_are_not_stamped(name: str, depends: list[str]) -> None:
    """Mutex packages are shared infrastructure and must never be stamped.

    _libgcc_mutex and _openmp_mutex are reused by both generations, and
    _gcc_mutex is the marker itself. Adding the marker to them would make every
    environment conflict with itself.
    """
    record = _make_record(name, depends)
    patch_record_in_place(f"{name}-0.1-main.tar.bz2", record, "linux-64")
    assert record["depends"] == depends


@pytest.mark.parametrize(
    ["name", "subdir", "depends"],
    [
        # Already carries the marker.
        pytest.param(
            "gcc_linux-64",
            "linux-64",
            ["gcc_impl_linux-64 15.2.0.*", GCC_MUTEX_DEPENDENCY],
            id="already_has_mutex",
        ),
        # Unrelated packages are untouched.
        pytest.param(
            "six",
            "linux-64",
            ["python >=3.10,<3.11.0a0"],
            id="pure_python_no_toolchain",
        ),
        # Non-Linux subdirs do not use the GCC toolchain.
        pytest.param(
            "gfortran_osx-64",
            "osx-64",
            ["gfortran_impl_osx-64", "clang_osx-64"],
            id="osx_toolchain",
        ),
        pytest.param(
            "vs2017_win-64",
            "win-64",
            ["vs2017_runtime"],
            id="windows",
        ),
    ],
)
def test_records_without_gcc_toolchain_dependency_unchanged(
    name: str, subdir: str, depends: list[str]
) -> None:
    """Out-of-scope and already-marked records must keep their metadata as-is.

    Pure Python packages stay generation-neutral (so they remain installable
    with either a main or a manylinux python), non-Linux subdirs do not use
    this toolchain, and already-marked records must not be modified again.
    """
    record = _make_record(name, depends)
    patch_record_in_place(f"{name}-15.2.0-h1234567_0.tar.bz2", record, subdir)
    assert record["depends"] == depends


def test_libgcc_ng_gets_both_mutexes() -> None:
    """libgcc-ng keeps its legacy runtime mutex and gains the generation marker.

    The existing libgcc-ng hotfix and the new generation fence address
    different concerns and must coexist without replacing each other.
    """
    record = _make_record("libgcc-ng", ["libgcc 15.2.0 h69a1729_8"])
    patch_record_in_place("libgcc-ng-15.2.0-h166f726_8.tar.bz2", record, "linux-64")
    assert record["depends"].count("_libgcc_mutex * main") == 1
    assert record["depends"].count(GCC_MUTEX_DEPENDENCY) == 1


def test_libgcc_ng_legacy_mutex_dependency_preserved() -> None:
    """Legacy libgcc-ng builds keep their pre-existing mutex deps and gain the marker.

    The original ``_libgcc_mutex 0.1 main`` dependency and the historical
    ``* main`` pin added by the libgcc-ng hotfix must not regress when the
    generation marker is appended.
    """
    record = _make_record(
        "libgcc-ng", ["_libgcc_mutex 0.1 main", "_openmp_mutex >=4.5"]
    )
    patch_record_in_place("libgcc-ng-11.2.0-h1234567_0.tar.bz2", record, "linux-64")
    assert "_libgcc_mutex 0.1 main" in record["depends"]
    assert record["depends"].count("_libgcc_mutex * main") == 1
    assert record["depends"].count(GCC_MUTEX_DEPENDENCY) == 1


@pytest.mark.parametrize(
    "formats", [("packages",), ("packages.conda",), ("packages", "packages.conda")]
)
def test_gcc_mutex_hotfix_is_idempotent(formats) -> None:
    """Applying the hotfix to patched repodata must not change it again.

    Patch instructions can be re-applied on top of repodata that already
    contains the marker. The second pass must produce no further modifications
    (and no duplicate dependencies) for either archive format.
    """
    record = _make_record(
        "gcc_linux-64",
        ["binutils_linux-64", "gcc_impl_linux-64 15.2.0.*", "sysroot_linux-64"],
    )
    extensions = {"packages": ".tar.bz2", "packages.conda": ".conda"}
    repodata = {
        section: {
            f"gcc_linux-64-15.2.0-h1234567_0{extensions[section]}": copy.deepcopy(record)
        }
        for section in formats
    }

    instructions = _patch_repodata(copy.deepcopy(repodata), "linux-64")
    result = _apply_instructions("linux-64", copy.deepcopy(repodata), instructions)

    for section in formats:
        patched = next(iter(result[section].values()))
        assert patched["depends"].count(GCC_MUTEX_DEPENDENCY) == 1

    repeated = _patch_repodata(copy.deepcopy(result), "linux-64")
    assert _apply_instructions("linux-64", copy.deepcopy(result), repeated) == result
