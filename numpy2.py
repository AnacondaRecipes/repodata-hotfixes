from os.path import dirname, isdir, isfile, join
from typing import List, Dict, Any, Sequence, Optional
from conda.models.version import VersionOrder
import csv
from collections import defaultdict
import requests
from numpy2_config import numpy2_protect_dict
import logging
import json
import os
import re

proposed_changes = defaultdict(lambda: defaultdict(list))

# Global dictionary to store data for CSV output
csv_data = defaultdict(list)

# Configure the logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('hotfixes.log', mode='w'),
                              logging.StreamHandler()])
# Create a logger object
logger = logging.getLogger(__name__)

CHANNEL_NAME = "main"
CHANNEL_ALIAS = "https://repo.anaconda.com/pkgs"
SUBDIRS = (
    "noarch",
    "linux-32",
    "linux-64",
    "linux-aarch64",
    "linux-armv6l",
    "linux-armv7l",
    "linux-ppc64le",
    "linux-s390x",
    "osx-64",
    "osx-arm64",
    "win-32",
    "win-64",
)

def collect_proposed_change(subdirectory, filename, change_type, original_dependency, updated_dependency, reason):
    """
    Collects a proposed change to a dependency for later processing.
    
    Parameters:
    - subdirectory: The subdirectory where the file is located.
    - filename: The name of the file being modified.
    - change_type: The type of change (e.g., 'version update').
    - original_dependency: The original dependency string.
    - updated_dependency: The updated dependency string.
    - reason: The reason for the change.
    """
    proposed_changes[subdirectory][filename].append({
        "type": change_type,
        "original": original_dependency,
        "updated": updated_dependency,
        "reason": reason
    })

def parse_version(version_str):
    """
    Extracts the version number from a version string.
    
    Parameters:
    - version_str: The version string to parse.
    
    Returns:
    The extracted version number or None if not found.
    """
    match = re.search(r'(\d+(\.\d+)*)', version_str)
    return match.group(1) if match else None

def has_upper_bound(dependency):
    """
    Checks if a dependency string contains an upper bound.
    
    Parameters:
    - dependency: The dependency string to check.
    
    Returns:
    True if an upper bound is found, False otherwise.
    """
    return any(part.strip().startswith('<') for part in dependency.split(','))

def patch_record_with_fixed_deps(dependency, parts):
    """
    Adds an upper bound to a dependency if necessary.
    
    Parameters:
    - dependency: The original dependency string.
    - parts: The parts of the dependency string, split by spaces.
    
    Returns:
    The potentially modified dependency string.
    """
    version_str = parts[1]
    version = parse_version(version_str)
    if version:
        if version_str.startswith('==') or version_str.startswith('<') or version_str[0].isdigit():
            return dependency
        if version_str.startswith('>') or version_str.startswith('>='):
            return f"{dependency},<2.0a0"
        return f"{dependency} <2.0a0"
    return dependency

def write_csv():
    """
    Writes collected data to CSV files, one per issue type.
    """
    for issue_type, data in csv_data.items():
        filename = f"{issue_type}_numpy2_updates.csv"
        with open(filename, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Package', 'Version', 'Build', 'Build Number', 'Original Dependency', 'Updated Dependency', 'Reason'])
            writer.writerows(data)


def log_and_collect(issue_type, package_info, original_dependency, updated_dependency, reason):
    """
    Logs and collects data on dependency modifications for reporting.
    
    Parameters:
    - issue_type: Type of issue prompting modification.
    - package_info: Package name, version, build, and build number.
    - original_dependency: Original dependency specification.
    - updated_dependency: Updated dependency specification.
    - reason: Reason for modification.
    """
    logger.info(f"numpy 2.0.0: {issue_type} for {package_info}. Original: '{original_dependency}' -> New: '{updated_dependency}' ({reason})")
    name, version, build, build_number = package_info.split(' v')[0], package_info.split(' v')[1].split(' (')[0], package_info.split('build: ')[1].split(',')[0], package_info.split('build_number: ')[1][:-1]
    csv_data[issue_type].append([name, version, build, build_number, original_dependency, updated_dependency, reason])


def update_numpy_dependencies(dependencies_list, package_record, dependency_type, package_subdir, filename):
    """
    Adds upper bounds to numpy dependencies as needed.
    
    Iterates through dependencies, modifying those without upper bounds and meeting specific criteria.
    
    Parameters:
    - dependencies_list: Dependencies to check and modify.
    - package_record: Metadata about the current package.
    - dependency_type: Type of dependency ('run', 'build').
    - package_subdir: Package location subdirectory.
    - filename: Package filename.
    """
    for i, dependency in enumerate(dependencies_list):
        parts = dependency.split()
        package_name = parts[0]
        
        # Check for numpy or numpy-base packages and proceed if found
        if package_name in ["numpy", "numpy-base"]:
            # Construct package info string for logging
            package_info = f"{package_record['name']} v{package_record['version']} (build: {package_record['build']}, build_number: {package_record['build_number']})"
            
            # Proceed if no upper bound exists in the dependency
            if not has_upper_bound(dependency):
                # Check if package is in the protection dictionary
                if package_name in numpy2_protect_dict:
                    version_str = parts[1] if len(parts) > 1 else None
                    version = parse_version(version_str) if version_str else None
                    protected_version = parse_version(numpy2_protect_dict[package_name])
                    
                    # Attempt to add an upper bound if version conditions are met
                    if version and protected_version:
                        try:
                            if VersionOrder(version) <= VersionOrder(protected_version):
                                new_dependency = f"{dependency},<2.0a0" if len(parts) > 1 else f"{dependency} <2.0a0"
                                collect_proposed_change(package_subdir, filename, dependency_type, dependency, new_dependency, "Version <= protected_version")
                        except ValueError:
                            new_dependency = f"{dependency},<2.0a0" if len(parts) > 1 else f"{dependency} <2.0a0"
                            collect_proposed_change(package_subdir, filename, dependency_type, dependency, new_dependency, "Version comparison failed")
                    else:
                        collect_proposed_change(package_subdir, filename, dependency_type, dependency, dependency, "Missing version or protected_version")
                elif numpy2_protect_dict.get('add_bound_to_unspecified', False):
                    # Handle dependencies without specified bounds
                    if len(parts) > 1:
                        new_dependency = patch_record_with_fixed_deps(dependency, parts)
                        if new_dependency != dependency:
                            collect_proposed_change(package_subdir, filename, dependency_type, dependency, new_dependency, "Upper bound added")
                        else:
                            collect_proposed_change(package_subdir, filename, dependency_type, dependency, dependency, "No unspecified bound")
                    else:
                        new_dependency = f"{dependency} <2.0a0"
                        collect_proposed_change(package_subdir, filename, dependency_type, dependency, new_dependency, "Upper bound added")
                else:
                    collect_proposed_change(package_subdir, filename, dependency_type, dependency, dependency, "Not in protect_dict, no unspecified bound")
            else:
                # Log if dependency already has an upper bound
                collect_proposed_change(package_subdir, filename, dependency_type, dependency, dependency, "Already has upper bound")


def main():
    base_dir = join(dirname(__file__), CHANNEL_NAME)
    # Step 1. Collect initial repodata for all subdirs.
    repodatas = {}
    for subdir in SUBDIRS:
        repodata_path = join(base_dir, subdir, "repodata_from_packages.json")
        if isfile(repodata_path):
            with open(repodata_path) as fh:
                repodatas[subdir] = json.load(fh)
        else:
            repodata_url = "/".join(
                (CHANNEL_ALIAS, CHANNEL_NAME, subdir, "repodata_from_packages.json")
            )
            response = requests.get(repodata_url)
            response.raise_for_status()
            repodatas[subdir] = response.json()
            if not isdir(dirname(repodata_path)):
                os.makedirs(dirname(repodata_path))
            with open(repodata_path, "w") as fh:
                json.dump(
                    repodatas[subdir],
                    fh,
                    indent=2,
                    sort_keys=True,
                    separators=(",", ": "),
                )
    for subdir in SUBDIRS:
        index = repodatas[subdir]["packages"]
        for fn, record in index.items():
            name = record["name"]
            depends = record["depends"]
            constrains = record.get("constrains", [])

            depends = [dep for dep in depends if dep is not None]
            if "py39" in fn or "py310" in fn or "py311" in fn or "py312" in fn: 
                if name not in ["anaconda", "_anaconda_depends", "__anaconda_core_depends", "_anaconda_core"]:
                    try: 
                        for dep in depends:
                            if dep.split()[0] in ["numpy", "numpy-base"]:
                                update_numpy_dependencies(depends, record, "dep", subdir, fn)
                        for constrain in constrains:
                            if constrain.split()[0] in ["numpy", "numpy-base"]:
                                update_numpy_dependencies(constrains, record, "constr", subdir, fn)
                    except Exception as e:
                        logger.error(f"numpy 2.0.0 error {fn}: {e}")
    
    # Write proposed changes to a JSON file
    with open('proposed_numpy_changes.json', 'w') as f:
        json.dump(proposed_changes, f, indent=2)

    logger.info(f"Proposed changes have been written to proposed_numpy_changes.json")
            
if __name__ == "__main__":
    main()