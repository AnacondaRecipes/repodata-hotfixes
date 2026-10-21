from main import SUBDIRS
import json
from pathlib import Path
import pytest


@pytest.fixture
def json_data():
    """Fixture to load the JSON data from the output file."""
    json_file = Path(__file__).parents[1] / 'numpy2_patch.json'
    with json_file.open() as f:
        return json.load(f)


def test_json_structure(json_data):
    """Test the overall structure of the JSON output."""
    assert isinstance(json_data, dict)
    assert len(json_data) > 0, "JSON should not be empty"

    for subdir, changes in json_data.items():
        assert subdir in SUBDIRS, f"Unexpected subdir {subdir} in the JSON output"
        assert isinstance(changes, dict)
        for filename, item in changes.items():
            assert filename.endswith(('.tar.bz2', '.conda'))
            assert isinstance(item, dict)
            assert set(item) == {'type', 'original', 'updated'}, f"Item has incorrect keys: {item.keys()}"

    # Log which subdirs are missing
    present_subdirs = set(json_data)
    missing_subdirs = set(SUBDIRS) - present_subdirs
    if missing_subdirs:
        print(f"Note: The following subdirs are not present in the JSON output: {', '.join(missing_subdirs)}")


def test_change_types(json_data):
    """Test that change types name repodata dependency fields."""
    valid_types = {'depends', 'constrains'}
    for subdir, changes in json_data.items():
        for filename, item in changes.items():
            assert item['type'] in valid_types, f"Invalid change type for {filename} in {subdir}: {item['type']}"


def test_numpy_changes(json_data):
    """Test that changes are related to numpy or numpy-base."""
    for subdir, changes in json_data.items():
        for filename, item in changes.items():
            assert item['original'].split()[0] in {'numpy', 'numpy-base'}, \
                f"Change for {filename} in {subdir} is not related to numpy: {item['original']}"


def test_version_bounds(json_data):
    """Test that updated dependencies have the correct version bounds."""
    for subdir, changes in json_data.items():
        for filename, item in changes.items():
            if item['original'] != item['updated']:
                assert '<2.0a0' in item['updated'], (
                    f"Updated dependency for {filename} in {subdir} "
                    f"doesn't have correct upper bound: {item['updated']}"
                )


def test_changes_present(json_data):
    """Test that there are actually changes in the output."""
    assert json_data, "JSON output should not be empty"
    assert any(json_data.values()), "At least one subdir should have changes"
