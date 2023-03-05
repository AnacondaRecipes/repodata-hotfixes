# -*- coding: utf-8 -*-

"""Tests for :func:`~main.replace_dep`."""

from __future__ import annotations

__all__ = ()

import typing

import pytest

from main import replace_dep


def test_fail_append_removing() -> None:
    """Make sure that :func:`~main.replace_dep` raises exception on inappropriate use."""
    with pytest.raises(TypeError):
        replace_dep([], 'any >=1.0.0', None, append=True)


@pytest.mark.parametrize(
    ['old', 'new', 'append', 'expected_outcome', 'expected_dependencies'],
    [
        # delete
        pytest.param(
            'pytest >=7.2.2', None, None,
            '-', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'zstandard >=0.20.0',
            ],
            id='delete_existing',
        ),
        pytest.param(
            'flask >=2.2.3', None, None,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='delete_missing',
        ),
        pytest.param(
            ['django >=4.1.7', 'flask >=2.2.3'], None, None,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='delete_none_of',
        ),
        pytest.param(
            ['anaconda-client >=1.11.1', 'conda >=23.1.0', 'django >=4.1.7', 'zstandard >=0.20.0'], None, None,
            '-', [
                'attrs >=22.2.0', 'pytest >=7.2.2',
            ],
            id='delete_some_of',
        ),

        # insert
        pytest.param(
            [], 'attrs >=22.2.0', True,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='insert_duplicate',
        ),
        pytest.param(
            [], 'django >=4.1.7', True,
            '+', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'django >=4.1.7', 'pytest >=7.2.2',
                'zstandard >=0.20.0',
            ],
            id='insert_unique',
        ),

        # update
        pytest.param(
            'pytest >=7.2.2', 'attrs >=22.2.0', None,
            '-', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'zstandard >=0.20.0',
            ],
            id='update_existing_with_duplicate',
        ),
        pytest.param(
            'pytest >=7.2.2', 'pytest >=7.0.0', None,
            '~', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.0.0', 'zstandard >=0.20.0',
            ],
            id='update_existing_with_unique',
        ),
        pytest.param(
            'django >=4.1.7', 'conda >=23.1.0', None,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='update_missing_with_duplicate',
        ),
        pytest.param(
            'django >=4.1.7', 'django >=4.0.0', None,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='update_missing_with_unique',
        ),
        pytest.param(
            ['django >=4.1.7', 'flask >=2.2.3'], 'zstandard >=0.20.0', None,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='update_none_of_with_duplicate',
        ),
        pytest.param(
            ['django >=4.1.7', 'flask >=2.2.3'], 'mypy >=1.0.0', None,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='update_none_of_with_unique',
        ),
        pytest.param(
            ['attrs >=22.2.0', 'mypy >=1.0.1', 'pytest >=7.2.2'], 'anaconda-client >=1.11.1', None,
            '-', [
                'anaconda-client >=1.11.1', 'conda >=23.1.0', 'zstandard >=0.20.0',
            ],
            id='update_some_of_with_duplicate',
        ),
        pytest.param(
            ['attrs >=22.2.0', 'mypy >=1.0.1', 'pytest >=7.2.2'], 'mypy >=1.0.0', None,
            '~', [
                'anaconda-client >=1.11.1', 'conda >=23.1.0', 'mypy >=1.0.0', 'zstandard >=0.20.0',
            ],
            id='update_some_of_with_unique',
        ),

        # upsert
        pytest.param(
            'pytest >=7.2.2', 'attrs >=22.2.0', True,
            '-', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'zstandard >=0.20.0',
            ],
            id='upsert_existing_with_duplicate',
        ),
        pytest.param(
            'pytest >=7.2.2', 'pytest >=7.0.0', True,
            '~', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.0.0', 'zstandard >=0.20.0',
            ],
            id='upsert_existing_with_unique',
        ),
        pytest.param(
            'django >=4.1.7', 'conda >=23.1.0', True,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='upsert_missing_with_duplicate',
        ),
        pytest.param(
            'django >=4.1.7', 'django >=4.0.0', True,
            '+', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'django >=4.0.0', 'pytest >=7.2.2',
                'zstandard >=0.20.0',
            ],
            id='upsert_missing_with_unique',
        ),
        pytest.param(
            ['django >=4.1.7', 'flask >=2.2.3'], 'zstandard >=0.20.0', True,
            '=', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'pytest >=7.2.2', 'zstandard >=0.20.0',
            ],
            id='upsert_none_of_with_duplicate',
        ),
        pytest.param(
            ['django >=4.1.7', 'flask >=2.2.3'], 'mypy >=1.0.0', True,
            '+', [
                'anaconda-client >=1.11.1', 'attrs >=22.2.0', 'conda >=23.1.0', 'mypy >=1.0.0', 'pytest >=7.2.2',
                'zstandard >=0.20.0',
            ],
            id='upsert_none_of_with_unique',
        ),
        pytest.param(
            ['attrs >=22.2.0', 'mypy >=1.0.1', 'pytest >=7.2.2'], 'anaconda-client >=1.11.1', True,
            '-', [
                'anaconda-client >=1.11.1', 'conda >=23.1.0', 'zstandard >=0.20.0',
            ],
            id='upsert_some_of_with_duplicate',
        ),
        pytest.param(
            ['attrs >=22.2.0', 'mypy >=1.0.1', 'pytest >=7.2.2'], 'mypy >=1.0.0', True,
            '~', [
                'anaconda-client >=1.11.1', 'conda >=23.1.0', 'mypy >=1.0.0', 'zstandard >=0.20.0',
            ],
            id='upsert_some_of_with_unique',
        ),
    ],
)
def test_replace_dep(
        old: str | typing.Iterable[str],
        new: str | None,
        append: bool | None,
        expected_outcome: str,
        expected_dependencies: list[str],
) -> None:
    """Check behavior of the :func:`~main.replace_dep`."""
    depends: list[str] = [
        'anaconda-client >=1.11.1',
        'attrs >=22.2.0',
        'conda >=23.1.0',
        'pytest >=7.2.2',
        'zstandard >=0.20.0',
    ]

    kwargs: dict[str, typing.Any] = {}
    if append is not None:
        kwargs['append'] = append

    assert replace_dep(depends, old, new, **kwargs) == expected_outcome
    assert depends == expected_dependencies
