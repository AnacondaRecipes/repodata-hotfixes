from main import SUBDIRS
import json
import os
import pytest


@pytest.fixture
def json_data():
    """Fixture to load the JSON data from the output file."""
    json_file = "numpy2_patch.json"
    if not os.path.exists(json_file):
        pytest.skip(
            f"{json_file} not found in {os.getcwd()}. Run the main script first."
        )
    with open(json_file, "r") as f:
        return json.load(f)


def test_json_structure(json_data):
    """Test the overall structure of the JSON output."""
    assert isinstance(json_data, list), "JSON root should be a list"
    assert len(json_data) > 0, "JSON should not be empty"

    for item in json_data:
        assert isinstance(item, dict), "Each item in the JSON should be a dictionary"
        assert set(item.keys()) == {
            "subdirectory",
            "filename",
            "type",
            "original",
            "updated",
        }, f"Item has incorrect keys: {item.keys()}"
        assert item["subdirectory"] in SUBDIRS, (
            f"Unexpected subdir {item['subdirectory']} in the JSON output"
        )

    # Log which subdirs are missing
    present_subdirs = set(item["subdirectory"] for item in json_data)
    missing_subdirs = set(SUBDIRS) - present_subdirs
    if missing_subdirs:
        print(
            f"Note: The following subdirs are not present in the JSON output: {', '.join(missing_subdirs)}"
        )


def test_change_types(json_data):
    """Test that change types are either 'dep' or 'constr'."""
    valid_types = {"dep", "constr"}
    for item in json_data:
        assert item["type"] in valid_types, (
            f"Invalid change type for {item['filename']} in {item['subdirectory']}: {item['type']}"
        )


def test_numpy_changes(json_data):
    """Test that changes are related to numpy or numpy-base."""
    for item in json_data:
        assert (
            "numpy" in item["original"].lower()
            or "numpy-base" in item["original"].lower()
        ), (
            f"Change for {item['filename']} in {item['subdirectory']} is not related to numpy: {item['original']}"
        )


def test_version_bounds(json_data):
    """Test that updated dependencies have the correct version bounds."""
    for item in json_data:
        if item["original"] != item["updated"]:
            assert "<2.0a0" in item["updated"], (
                f"Updated dependency for {item['filename']} in {item['subdirectory']} "
                f"doesn't have correct upper bound: {item['updated']}"
            )


def test_changes_present(json_data):
    """Test that there are actually changes in the output."""
    assert json_data, "JSON output should not be empty"
    assert len(set(item["subdirectory"] for item in json_data)) > 0, (
        "At least one subdir should have changes"
    )
