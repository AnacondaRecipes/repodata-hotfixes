# -*- coding: utf-8 -*-

"""Tests for the pybind11-abi hotfix (PKG-13552).

Covers:
- :func:`~main._infer_pybind11_abi` correctness across platforms and build-string shapes.
- :data:`~main.MISSING_PYBIND11_ABI_VERSION_RANGES` structural integrity.
- End-to-end patching via :func:`~main.patch_record_in_place` for representative records.
"""

from __future__ import annotations

__all__ = ()

import typing

import pytest

from conda.models.version import VersionOrder

from main import (
    MISSING_PYBIND11_ABI_VERSION_RANGES,
    _infer_pybind11_abi,
    patch_record_in_place,
)


# ---------------------------------------------------------------------------
# _infer_pybind11_abi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ['subdir', 'build', 'depends', 'expected'],
    [
        # Windows always uses ABI 5 (MSVC branch)
        pytest.param('win-64', 'py310_0', [], '5', id='win-64_py310_msvc'),
        pytest.param('win-64', 'py311_0', [], '5', id='win-64_py311_msvc'),
        pytest.param('win-64', 'h0000000_0', [], '5', id='win-64_no_pybuild_still_msvc'),

        # py3XX in build string, Linux/macOS
        pytest.param('linux-64', 'py313h7010ec8_0', [], '5', id='linux-64_py313'),
        pytest.param('linux-64', 'py312h7010ec8_0', [], '5', id='linux-64_py312'),
        pytest.param('linux-64', 'py311h7010ec8_0', [], '4', id='linux-64_py311'),
        pytest.param('linux-64', 'py310h7010ec8_0', [], '4', id='linux-64_py310'),
        pytest.param('osx-arm64', 'py314h0000000_0', [], '5', id='osx-arm64_py314'),
        pytest.param('osx-arm64', 'py39h0000000_0', [], '4', id='osx-arm64_py39'),

        # CUDA-tagged build strings still have py3XX after the cuda prefix
        pytest.param('linux-64', 'cuda130py312h7010ec8_0', [], '5', id='linux-64_cuda_py312'),
        pytest.param('linux-64', 'cuda129py310h338dc61_0', [], '4', id='linux-64_cuda_py310'),

        # No py3XX in build, but python pin in depends -> fall back to depends
        pytest.param('linux-64', 'h12345_0', ['python 3.12.*'], '5', id='depends_python_3_12'),
        pytest.param('linux-64', 'h12345_0', ['python 3.10.*'], '4', id='depends_python_3_10'),
        pytest.param('osx-arm64', 'h0_0', ['python 3.13.*', 'numpy'], '5',
                     id='depends_python_3_13_amid_others'),

        # No py3XX, no python dep (pure C++ outputs like libtorch) -> None
        pytest.param('linux-64', 'h12345_0', [], None, id='no_python_at_all_linux'),
        pytest.param('osx-arm64', 'h0_0', ['libstdcxx >=14'], None,
                     id='no_python_only_native_deps'),
    ],
)
def test_infer_pybind11_abi(
        subdir: str,
        build: str,
        depends: list[str],
        expected: typing.Optional[str],
) -> None:
    """ABI inference matches pybind11/detail/internals.h PYBIND11_INTERNALS_VERSION."""
    record = {'build': build, 'depends': depends}
    assert _infer_pybind11_abi(record, subdir) == expected


# ---------------------------------------------------------------------------
# MISSING_PYBIND11_ABI_VERSION_RANGES integrity
# ---------------------------------------------------------------------------

def test_version_ranges_well_formed() -> None:
    """Every entry is a (min, max) tuple of strings with min <= max."""
    for name, value in MISSING_PYBIND11_ABI_VERSION_RANGES.items():
        assert isinstance(value, tuple) and len(value) == 2, \
            f"{name}: value must be a (min, max) tuple, got {value!r}"
        lo, hi = value
        assert isinstance(lo, str) and isinstance(hi, str), \
            f"{name}: bounds must be strings, got {value!r}"
        assert VersionOrder(lo) <= VersionOrder(hi), \
            f"{name}: lower bound {lo!r} must be <= upper bound {hi!r}"


def test_pure_cpp_outputs_excluded() -> None:
    """Pure C++ outputs (no python dep) must not be in the patch table.

    These cannot have ABI inferred from build string alone; they need a
    recipe-side fix + rebuild instead. Listed in the patch's docstring.
    """
    pure_cpp_outputs = {'libtorch', 'libctranslate2', 'onnxruntime-cpp', 'onnxruntime-novec-cpp'}
    overlap = pure_cpp_outputs & set(MISSING_PYBIND11_ABI_VERSION_RANGES)
    assert not overlap, \
        f"Pure C++ outputs must not be in the patch table: {overlap}"


def test_triton_range_covers_released_versions() -> None:
    """Regression check: triton 3.7.0 (released 2026-05-19) must be in range.

    The original scan was performed before 3.7.0 shipped; if 3.8.0 ships and
    still lacks pybind11-abi, this test will need updating along with the
    upper bound.
    """
    lo, hi = MISSING_PYBIND11_ABI_VERSION_RANGES['triton']
    assert VersionOrder(lo) <= VersionOrder('3.7.0') <= VersionOrder(hi)


# ---------------------------------------------------------------------------
# End-to-end via patch_record_in_place
# ---------------------------------------------------------------------------

def _make_record(name: str, version: str, build: str, depends: list[str]) -> dict:
    """Build a minimal record dict suitable for patch_record_in_place."""
    build_number_str = build.rsplit('_', 1)[-1]
    try:
        build_number = int(build_number_str)
    except ValueError:
        build_number = 0
    return {
        'name': name,
        'version': version,
        'build': build,
        'build_number': build_number,
        'depends': list(depends),
    }


@pytest.mark.parametrize(
    ['name', 'version', 'build', 'subdir', 'depends', 'expected_abi'],
    [
        # Real records the PR description manually verified
        pytest.param('onnxruntime', '1.24.4', 'py313h0000000_0', 'linux-64',
                     ['python 3.13.*', 'numpy'], '5',
                     id='onnxruntime_py313_linux64'),
        pytest.param('onnxruntime', '1.24.4', 'py311h0000000_0', 'linux-64',
                     ['python 3.11.*', 'numpy'], '4',
                     id='onnxruntime_py311_linux64'),
        pytest.param('onnxruntime', '1.24.4', 'py311h0000000_0', 'win-64',
                     ['python 3.11.*', 'numpy'], '5',
                     id='onnxruntime_py311_win64_msvc'),
        pytest.param('cvxpy-base', '1.8.2', 'py310h0000000_0', 'osx-arm64',
                     ['python 3.10.*'], '4',
                     id='cvxpy_base_py310_osx_arm64'),
        pytest.param('pytorch', '2.11.0', 'cpu_mkl_py313h0000000_0', 'linux-64',
                     ['python 3.13.*'], '5',
                     id='pytorch_2_11_cpu_mkl_py313_linux64'),
        # triton 3.7.0 — explicit regression for the range bump
        pytest.param('triton', '3.7.0', 'cuda130py312h0000000_0', 'linux-64',
                     ['python 3.12.*'], '5',
                     id='triton_3_7_cuda_py312'),
    ],
)
def test_patched_records_gain_pybind11_abi(
        name: str,
        version: str,
        build: str,
        subdir: str,
        depends: list[str],
        expected_abi: str,
) -> None:
    """Records in the patch table without pybind11-abi get the right pin appended."""
    record = _make_record(name, version, build, depends)
    patch_record_in_place(f'{name}-{version}-{build}.conda', record, subdir)
    assert f'pybind11-abi =={expected_abi}' in record['depends']


def test_idempotent_when_pybind11_abi_already_present() -> None:
    """Records that already declare pybind11-abi (e.g. mamba pattern) are untouched."""
    record = _make_record('onnxruntime', '1.24.4', 'py313h0000000_0',
                          ['python 3.13.*', 'numpy', 'pybind11-abi ==5'])
    patch_record_in_place('onnxruntime-1.24.4-py313h0000000_0.conda', record, 'linux-64')
    # exactly one pybind11-abi entry, original preserved
    abi_deps = [d for d in record['depends'] if d.split()[0] == 'pybind11-abi']
    assert abi_deps == ['pybind11-abi ==5']


def test_not_in_patch_table_unchanged() -> None:
    """Packages NOT in MISSING_PYBIND11_ABI_VERSION_RANGES get no pybind11-abi."""
    # mamba is intentionally excluded — it pins pybind11-abi correctly at recipe level
    record = _make_record('mamba', '1.5.0', 'py312h0000000_0', ['python 3.12.*'])
    patch_record_in_place('mamba-1.5.0-py312h0000000_0.conda', record, 'linux-64')
    assert not any(d.split()[0] == 'pybind11-abi' for d in record['depends'])


def test_out_of_range_version_unchanged() -> None:
    """Versions outside the configured range are not patched."""
    # pytorch range is (0.2.0, 2.11.0); 2.12.0 should NOT be touched.
    record = _make_record('pytorch', '2.12.0', 'cpu_mkl_py313h0000000_0',
                          ['python 3.13.*'])
    patch_record_in_place('pytorch-2.12.0-cpu_mkl_py313h0000000_0.conda', record, 'linux-64')
    assert not any(d.split()[0] == 'pybind11-abi' for d in record['depends'])


def test_undetermined_abi_unchanged() -> None:
    """If ABI cannot be inferred (no py3XX, no python dep), no pin is added.

    This covers the pure-C++ output case in spirit, even though those names are
    excluded from the table at the dict level. A defensive double-check.
    """
    # Hypothetical: a record that IS in the table but has no python dep.
    # Should fall through to _infer_pybind11_abi -> None and not be patched.
    record = _make_record('osqp', '1.1.1', 'h0000000_0', ['libstdcxx >=14'])
    patch_record_in_place('osqp-1.1.1-h0000000_0.conda', record, 'linux-64')
    assert not any(d.split()[0] == 'pybind11-abi' for d in record['depends'])
