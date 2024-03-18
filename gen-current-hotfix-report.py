"""
gen-current-hotfix-report is a simple script that finds the current effective changes that occur
due to repodata-hotfixes main, r, and mysys2 hotfixes scripts.

There are a few important files that are used to find this information:
- repodata_from_packages.json
  - A clean json file that takes information directly from the packages in a channel
- repodata.json (or also referred to as repodata-patched.json in this script)
  - The result of running the repodata-hotfixes scripts on one of the three operational channels
  - This is what an end-user will search against in the conda cli
- patched_instructions.json
  - The output of a repodata-hotfix channel scripts.
  - This only contains the changes that are going to be patched
  - Patches apply in an overwrite fashion by key
    -(aka if you change on thing in a list of the key the whole list needs to be present)
- repodata-diff.json
  - Json file that only contains the changes that have occurred through the patching process
    - Meaning anything common between values in patch_instructions and repodata_from_packages is thrown out
    - This file isn't found in a regular conda index channel (the 3 above should be)
"""


import copy
import json
import sys
import urllib
from collections import defaultdict
from pathlib import Path

from conda.exports import subdir as conda_subdir
from conda_index.index import _apply_instructions

channel_map = {
    "main": "https://repo.anaconda.com/pkgs/main",
    "r": "https://repo.anaconda.com/pkgs/r",
    "msys2": "https://repo.anaconda.com/pkgs/msys2",
}


current_supported_subdirs = (
    "linux-64",
    "linux-aarch64",
    "linux-ppc64le",
    "linux-s390x",
    "noarch",
    "osx-64",
    "osx-arm64",
    "win-64",
)


def write_readable_json_file(info: dict, filepath: Path):
    """Simple write to from dictionary into pretty json file

    Args:
        info (dict): dictionary containing information
        filepath (Path): path of where json will be written
    """
    with open(filepath, "w") as fobj:
        json.dump(info, fobj, indent=2, sort_keys=True, separators=(",", ": "))
        fobj.write("\n")


def clone_subdir(channel_name: str, channel_base_url: str, subdir_name: str):
    """Download repodata.json and repodata_from_packages.json from channel

    Args:
        channel_base_url (str): Root URL
        subdir (str): subdir of channel (aka platform) to download
    """
    channel_subdir_dir = Path(channel_name) / subdir

    out_file = channel_subdir_dir / "repodata_from_packages.json"
    url = f"{channel_base_url}/{subdir_name}/repodata_from_packages.json"
    print(f"Downloading 'repodata_from_packages.json' from {url}")
    urllib.request.urlretrieve(url, out_file)

    out_file = channel_subdir_dir / "patch_instructions.json"
    url = f"{channel_base_url}/{subdir_name}/patch_instructions.json"
    print(f"Downloading 'patch_instructions' from {url}")
    urllib.request.urlretrieve(url, out_file)


def find_diffs(patch_instructions: dict, ref_data: dict, patched_data: dict) -> dict:
    """Find differences between packages patch patch_instructions and reference data

        This function only keeps the differences between the reference data and the patched_data.
        In other words it removes anything common between values in patch_instructions and
        repodata_from_packages.
    Args:
        patch_instructions (dict): patch_instructions dictionary from patch_instructions
        ref_data (dict): reference information aka from repodata_from_packages.json
        patched_data (dict): repodata information coming from repodata.json

    Returns:
        dict: Dictionary contain only the differences between two libraries
    """
    pi_packages = patch_instructions["packages"]
    pi_remove_packages = patch_instructions["remove"]
    rd_packages = ref_data["packages"]
    patched_packages = patched_data["packages"]

    sd = {
        "packages": {},
        "patched_but_on_remove_list": [],
        "patch_instruction_on_nonexistent_package": [],
    }

    sd["removed"] = [
        prp for prp in pi_remove_packages if prp not in patched_packages.keys()
    ]
    sd["not_removed"] = [
        prp for prp in pi_remove_packages if prp in patched_packages.keys()
    ]
    for package_name, pck in pi_packages.items():
        try:
            if package_name in pi_remove_packages:
                sd["patched_but_on_remove_list"].append(package_name)
            ref_pck = rd_packages[package_name]
            pck_keys = set(pck.keys())
            ref_pck_keys = set(ref_pck.keys())
            common_keys = pck_keys & ref_pck_keys
            new_keys = pck_keys - ref_pck_keys
            changes = {}
            # # This is new to original repo, so I can add the information straight across
            new_and_common_keys = new_keys | common_keys
            # There seems to be a few different mappings
            # str->str, int->int, list->list and str->None
            # We will map all single changes as a formatted strings <Ref Value> -> <New Value>
            # For list to list we will only keep the differences
            for k in sorted(new_and_common_keys):
                ref_val = ref_pck[k] if k in ref_pck else ""
                patch_val = pck[k]
                if isinstance(patch_val, list):
                    item_changes = {}
                    if k in new_keys:
                        # It's new so nothing exists here
                        ref_items = set()
                    else:
                        ref_items = set(ref_val)
                    patch_items = set(patch_val)
                    new_or_modded_items = patch_items - ref_items
                    removed_or_modded_items = ref_items - patch_items
                    item_changes["src"] = list(removed_or_modded_items)
                    item_changes["patch"] = list(new_or_modded_items)
                    changes[k] = item_changes
                else:
                    changes[k] = f"{ref_val}->{patch_val}"
            sd["packages"][package_name] = changes

        except KeyError:
            # This should never occur but his here to assure that things are accounted for
            sd["patch_instruction_on_nonexistent_package"].append(package_name)
    return sd


def _has_change(pkg_diff_dict: dict) -> bool:
    """Helper function to see if there are any meaningful changes to a package

    Args:
        pkg_diff_dict (dict): Diff dictionary under test

    Returns:
        bool: True if there is a change, False if there is none
    """
    bool_vals = []
    for val in pkg_diff_dict.values():
        if isinstance(val, dict):
            bool_val = _has_change(val)
        else:
            bool_val = bool(val)
        bool_vals.append(bool_val)
    has_change = any(bool_vals)
    return has_change


def generate_summary(summary_stats: dict, simplified_diffs: dict):
    print("Summary:")
    print()
    hdr_str = "|   platform  | changes | removals | revokes |"
    print(hdr_str)
    print("-" * len(hdr_str))
    for subdir in subdirs:
        npc, nrm, nrv = (
            summary_stats[subdir]["package_changes"],
            summary_stats[subdir]["package_removals"],
            summary_stats[subdir]["package_revokes"],
        )
        print(f"{subdir:15}{npc:8}{nrm:9}{nrv:10}")
    print()
    print("Removal Summary:")
    print("----------------")
    print("Removals that also have patches applied")
    for subdir in subdirs:
        if simplified_diffs[subdir]["patched_but_on_remove_list"]:
            print(f"For {subdir}:")
            for pkg in simplified_diffs[subdir]["patched_but_on_remove_list"]:
                print("   ", pkg)
            print()
    print()
    print("Packages that failed to be removed:")
    for subdir in subdirs:
        if simplified_diffs[subdir]["not_removed"]:
            print(f"For {subdir}:")
            for pkg in simplified_diffs[subdir]["not_removed"]:
                print("   ", pkg)
            print()

    print()
    print(
        "Unnecessarily Patched (aka no changes though patches were applied) Packages Summary:"
    )
    print("----------------")
    for subdir in subdirs:
        subdir_unnecessary_patches = [
            pkg
            for pkg, pkg_info in simplified_diffs[subdir]["packages"].items()
            if not _has_change(pkg_info)
        ]
        if subdir_unnecessary_patches:
            print(f"For {subdir}:")
            for pkg in subdir_unnecessary_patches:
                print("   ", pkg)
            print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate what current repodata-hotfixes is doing."
    )
    parser.add_argument(
        "channel",
        help="channel name or url to download repodata from",
        choices=channel_map.keys(),
    )
    parser.add_argument(
        "--subdirs",
        nargs="*",
        help=f"subdir(s) to download/diff. 'all' can also be used => {current_supported_subdirs} ",
        default=(conda_subdir,),
    )
    parser.add_argument("--use-cache", action="store_true", help="use cached repodata")
    parser.add_argument(
        "--show-pkgs", action="store_true", help="Show packages that differ"
    )
    args = parser.parse_args()

    channel = args.channel
    if "all" in args.subdirs:
        subdirs = current_supported_subdirs
    else:
        subdirs = args.subdirs

    ##############################
    # Making directory structure #
    ##############################

    # NOTE: Only main, r and msys2 are available
    base_path = Path(channel)
    if not base_path.is_dir():
        print(
            f"Creating channel directory structure for channel '{channel}' and platforms {subdirs}..."
        )
        if base_path.exists():
            sys.exit(
                f"{base_path} exists but it is not a directory. Won't overwrite so exiting."
            )

        base_path.mkdir()

    for subdir in subdirs:
        subdir_dir = base_path / subdir
        if not subdir_dir.is_dir():
            subdir_dir.mkdir()

    ##############################
    # Downloading data           #
    ##############################
    channel_base_url = channel_map[channel]

    if args.use_cache:
        print(f"Using cache for {' '.join(subdirs)}.")
    if not args.use_cache:
        print(f"Cloning subdirs {' '.join(subdirs)}...")
        for subdir in subdirs:
            clone_subdir(channel, channel_base_url, subdir)

    ###############################
    # Analyze data                #
    ###############################
    print("Analyzing results...")
    summary_stats = dict()
    simplified_diffs = dict()
    for subdir in subdirs:
        repodata_filepath = base_path / subdir / "repodata_from_packages.json"
        patch_instructions_filepath = base_path / subdir / "patch_instructions.json"
        if not (repodata_filepath.exists() or patch_instructions_filepath.exists()):
            print("Missing files.  Attempting to reclone.")
            clone_subdir(channel, channel_base_url, subdir)

        with open(repodata_filepath) as f:
            repodata = json.load(f)

        with open(patch_instructions_filepath) as f:
            patch_instructions = json.load(f)

        summary_stats[subdir] = {
            "package_changes": len(patch_instructions["packages"]),
            "package_removals": len(patch_instructions["remove"]),
            "package_revokes": len(patch_instructions["revoke"]),
        }

        # Making a clean copy as _apply_instructions mutates original
        repodata_clean = copy.deepcopy(repodata)
        patched_repodata = _apply_instructions(subdir, repodata, patch_instructions)
        patched_repodata_filepath = base_path / subdir / "repodata-patched.json"
        print(
            f"Writing out new repodata as {patched_repodata_filepath} for '{subdir}' platform."
        )
        write_readable_json_file(patched_repodata, patched_repodata_filepath)

        simplified_diff_filepath = base_path / subdir / "repodata-diff.json"
        subdir_simple_diff = find_diffs(patch_instructions, repodata_clean, patched_repodata)
        simplified_diffs[subdir] = subdir_simple_diff
        print(
            f"Writing out simple diff as {simplified_diff_filepath} for '{subdir}' platform."
        )
        write_readable_json_file(subdir_simple_diff, simplified_diff_filepath)

    # Summary
    generate_summary(summary_stats, simplified_diffs)

    ##############################
    # Process data               #
    ##############################
    # Let's look at this is in a different way.  Let's look at it by what changes are being pushed on

    changes_dict = defaultdict(set)
    for subdir in subdirs:
        for pkg, chg_dict in simplified_diffs[subdir]["packages"].items():
            for change_key, changes in chg_dict.items():
                if isinstance(changes, dict):
                    for change_item in changes["patch"]:
                        changes_dict[(change_key, f"->{change_item}")].add(pkg)
                else:
                    changes_dict[(change_key, changes)].add(pkg)

    with open(f"{channel}_changes.tsv", "w") as f:
        f.write("change_key\tchange\tpackage\n")
        for change_key_n_change, v in sorted(changes_dict.items()):
            change_key, change = change_key_n_change
            for pkg in sorted(list(v)):
                f.write(f"{change_key}\t{change}\t{pkg}\n")
