from main import SUBDIRS  # Import SUBDIRS from your main script

import json
import os
import pytest


@pytest.fixture
def json_data():
    """Fixture to load the JSON data from the output file."""
    json_file = 'proposed_numpy_changes.json'
    if not os.path.exists(json_file):
        pytest.skip(f"{json_file} not found. Run the main script first.")
    with open(json_file, 'r') as f:
        return json.load(f)


def test_json_structure(json_data):
    """Test the overall structure of the JSON output."""
    assert isinstance(json_data, dict), "JSON root should be a dictionary"

    # Check if at least one subdir is present
    assert any(subdir in json_data for subdir in SUBDIRS), "At least one subdir should be in the JSON output"

    for subdir in json_data:
        assert subdir in SUBDIRS, f"Unexpected subdir {subdir} in the JSON output"
        assert isinstance(json_data[subdir], dict), f"Subdir {subdir} should contain a dictionary"

    # Log which subdirs are missing
    missing_subdirs = [subdir for subdir in SUBDIRS if subdir not in json_data]
    if missing_subdirs:
        print(f"Note: The following subdirs are not present in the JSON output: {', '.join(missing_subdirs)}")


def test_package_structure(json_data):
    """Test the structure of each package entry."""
    for subdir, packages in json_data.items():
        for package, changes in packages.items():
            assert isinstance(changes, list), f"Changes for {package} in {subdir} should be a list"
            for change in changes:
                assert isinstance(change, dict), f"Each change for {package} in {subdir} should be a dictionary"
                assert set(change.keys()) == {'type', 'original', 'updated', 'reason'}, \
                    f"Change for {package} in {subdir} has incorrect keys"


def test_change_types(json_data):
    """Test that change types are either 'dep' or 'constr'."""
    valid_types = {'dep', 'constr'}
    for subdir, packages in json_data.items():
        for package, changes in packages.items():
            for change in changes:
                assert change['type'] in valid_types, \
                    f"Invalid change type for {package} in {subdir}: {change['type']}"


def test_numpy_changes(json_data):
    """Test that changes are related to numpy or numpy-base."""
    for subdir, packages in json_data.items():
        for package, changes in packages.items():
            for change in changes:
                assert 'numpy' in change['original'].lower() or 'numpy-base' in change['original'].lower(), \
                    f"Change for {package} in {subdir} is not related to numpy: {change['original']}"


def test_version_bounds(json_data):
    """Test that updated dependencies have the correct version bounds."""
    for subdir, packages in json_data.items():
        for package, changes in packages.items():
            for change in changes:
                if change['original'] != change['updated']:
                    assert '<2.0a0' in change['updated'], (
                        f"Updated dependency for {package} in {subdir} "
                        f"doesn't have correct upper bound: {change['updated']}"
                    )


def test_reason_provided(json_data):
    """Test that each change has a non-empty reason."""
    for subdir, packages in json_data.items():
        for package, changes in packages.items():
            for change in changes:
                assert change['reason'], f"Change for {package} in {subdir} has no reason provided"


def test_no_empty_changes(json_data):
    """Test that there are no packages with empty change lists."""
    for subdir, packages in json_data.items():
        for package, changes in packages.items():
            assert changes, f"Package {package} in {subdir} has no changes"


def test_changes_present(json_data):
    """Test that there are actually changes in the output."""
    assert json_data, "JSON output should not be empty"
    assert any(packages for packages in json_data.values()), "At least one subdir should have changes"


if __name__ == '__main__':
    pytest.main([__file__])
