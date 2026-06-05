# -*- coding: utf-8 -*-

"""Tests for adding missing libgomp to Linux libtorch builds."""

from __future__ import annotations

import pytest

from main import patch_record_in_place


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


@pytest.mark.parametrize('subdir', ['linux-64', 'linux-aarch64'])
def test_linux_libtorch_openblas_below_212_gets_libgomp(subdir: str) -> None:
    """OpenBLAS libtorch builds below 2.12 need libgomp for import-time linking."""
    record = _make_record(
        'libtorch',
        '2.10.0',
        'cpu_openblas_h0000000_0',
        ['blas * openblas'],
    )

    patch_record_in_place('libtorch-2.10.0-cpu_openblas_h0000000_0.conda', record, subdir)

    assert 'libgomp' in record['depends']


@pytest.mark.parametrize('subdir', ['linux-64', 'linux-aarch64'])
def test_linux_libtorch_mkl_below_212_gets_libgomp(subdir: str) -> None:
    """MKL libtorch builds below 2.12 also link libgomp via oneDNN."""
    record = _make_record(
        'libtorch',
        '2.10.0',
        'cpu_mkl_h0000000_0',
        ['blas 1.0 mkl', 'intel-openmp >=2025.0.0,<2026.0a0'],
    )

    patch_record_in_place('libtorch-2.10.0-cpu_mkl_h0000000_0.conda', record, subdir)

    assert 'libgomp' in record['depends']


def test_openblas_dependency_also_triggers_libgomp() -> None:
    """Do not rely only on the build string if repodata carries the BLAS variant."""
    record = _make_record(
        'libtorch',
        '2.10.0',
        'h0000000_0',
        ['blas * openblas'],
    )

    patch_record_in_place('libtorch-2.10.0-h0000000_0.conda', record, 'linux-aarch64')

    assert 'libgomp' in record['depends']


@pytest.mark.parametrize(
    ['name', 'version', 'build', 'depends', 'subdir'],
    [
        pytest.param('libtorch', '2.12.0', 'cpu_openblas_h0000000_0',
                     ['blas * openblas'], 'linux-aarch64',
                     id='libtorch_2_12_not_patched'),
        pytest.param('libtorch', '2.10.0', 'cpu_openblas_h0000000_0',
                     ['blas * openblas'], 'osx-arm64',
                     id='non_linux_not_patched'),
        pytest.param('pytorch', '2.10.0', 'cpu_openblas_py313h0000000_0',
                     ['python >=3.13,<3.14.0a0', 'blas * openblas', 'libtorch 2.10.*'],
                     'linux-aarch64', id='pytorch_wrapper_not_patched'),
    ],
)
def test_unaffected_records_do_not_get_libgomp(
        name: str,
        version: str,
        build: str,
        depends: list[str],
        subdir: str,
) -> None:
    """The libtorch libgomp hotfix is limited to Linux libtorch builds below 2.12."""
    record = _make_record(name, version, build, depends)

    patch_record_in_place(f'{name}-{version}-{build}.conda', record, subdir)

    assert 'libgomp' not in record['depends']


def test_libgomp_dependency_is_not_duplicated() -> None:
    """Records already declaring libgomp should be preserved as-is."""
    record = _make_record(
        'libtorch',
        '2.10.0',
        'cpu_openblas_h0000000_0',
        ['blas * openblas', 'libgomp'],
    )

    patch_record_in_place('libtorch-2.10.0-cpu_openblas_h0000000_0.conda', record, 'linux-aarch64')

    assert [dep for dep in record['depends'] if dep.split()[0] == 'libgomp'] == ['libgomp']
