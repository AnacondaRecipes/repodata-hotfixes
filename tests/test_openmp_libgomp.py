# -*- coding: utf-8 -*-

"""Tests for audited Linux packages missing libgomp run dependencies."""

from __future__ import annotations

import pytest

from main import patch_record_in_place


def _make_record(name: str, version: str, build: str, depends: list[str]) -> dict:
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
    ['name', 'version', 'build', 'depends', 'subdir'],
    [
        pytest.param(
            'opencv', '4.13.0', 'headless_py310h0000000_6',
            ['_openmp_mutex >=5.1', 'libgcc >=14'],
            'linux-64',
            id='opencv_linux64',
        ),
        pytest.param(
            'libfaiss', '1.14.1', 'hcf21eff_0_cpu',
            ['_openmp_mutex >=5.1', 'mkl >=2025.0.0,<2026.0a0'],
            'linux-64',
            id='libfaiss_linux64',
        ),
        pytest.param(
            'lightgbm', '4.6.0', 'cpu_py310h0000000_1',
            ['_openmp_mutex', 'libgcc >=14'],
            'linux-aarch64',
            id='lightgbm_linux_aarch64',
        ),
    ],
)
def test_audited_packages_get_libgomp(
        name: str,
        version: str,
        build: str,
        depends: list[str],
        subdir: str,
) -> None:
    record = _make_record(name, version, build, depends)

    patch_record_in_place(f'{name}-{version}-{build}.conda', record, subdir)

    assert 'libgomp' in record['depends']


@pytest.mark.parametrize(
    ['name', 'version', 'build', 'depends', 'subdir'],
    [
        pytest.param(
            'opencv', '4.11.0', 'headless_py310h0000000_0',
            ['_openmp_mutex >=5.1'],
            'linux-64',
            id='wrong_version',
        ),
        pytest.param(
            'opencv', '4.13.0', 'headless_py310h0000000_6',
            ['_openmp_mutex >=5.1', 'libgomp'],
            'linux-64',
            id='already_has_libgomp',
        ),
        pytest.param(
            'opencv', '4.13.0', 'headless_py310h0000000_6',
            ['_openmp_mutex >=5.1'],
            'win-64',
            id='non_linux',
        ),
        pytest.param(
            'sleef', '3.5.1', 'h7c1795a_3',
            ['_openmp_mutex >=5.1'],
            'linux-64',
            id='sleef_fixed_build',
        ),
        pytest.param(
            'ceres-solver', '2.1.0', 'h3c60e43_1',
            ['_openmp_mutex', 'libgcc-ng >=11.2.0'],
            'linux-64',
            id='ceres_solver_no_gnu_link',
        ),
        pytest.param(
            'libgcc-ng', '11.2.0', 'h1234567_1',
            ['_libgcc_mutex 0.1 main', '_openmp_mutex'],
            'linux-aarch64',
            id='libgcc_ng_structural',
        ),
    ],
)
def test_audited_rule_does_not_apply(
        name: str,
        version: str,
        build: str,
        depends: list[str],
        subdir: str,
        request: pytest.FixtureRequest,
) -> None:
    record = _make_record(name, version, build, depends)

    patch_record_in_place(f'{name}-{version}-{build}.conda', record, subdir)

    libgomp_deps = [dep for dep in record['depends'] if dep.split()[0] == 'libgomp']
    if request.node.callspec.id == 'already_has_libgomp':
        assert libgomp_deps == ['libgomp']
    else:
        assert libgomp_deps == []


def test_legacy_linux64_gets_openmp_mutex() -> None:
    record = _make_record(
        'fasttsne',
        '0.2.13',
        'py36hdd07704_1',
        ['libgcc-ng >=7.3.0', 'numpy >=1.11.3,<2.0a0'],
    )

    patch_record_in_place('fasttsne-0.2.13-py36hdd07704_1.conda', record, 'linux-64')

    assert 'libgomp' in record['depends']
    assert '_openmp_mutex >=5.1' in record['depends']


def test_legacy_mutex_not_added_on_linux_aarch64() -> None:
    record = _make_record(
        'fasttsne',
        '0.2.13',
        'py36hdd07704_1',
        ['libgcc-ng >=7.3.0'],
    )

    patch_record_in_place('fasttsne-0.2.13-py36hdd07704_1.conda', record, 'linux-aarch64')

    assert 'libgomp' in record['depends']
    assert '_openmp_mutex >=5.1' not in record['depends']


def test_sleef_build_2_gets_libgomp() -> None:
    record = _make_record(
        'sleef',
        '3.5.1',
        'h5eee18b_2',
        ['_openmp_mutex >=5.1', 'libgcc-ng >=11.2.0'],
    )

    patch_record_in_place('sleef-3.5.1-h5eee18b_2.conda', record, 'linux-64')

    assert 'libgomp' in record['depends']
