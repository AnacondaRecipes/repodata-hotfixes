# -*- coding: utf-8 -*-
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import json
import os
import sys
from collections import defaultdict
from os.path import dirname, isdir, isfile, join

import requests

CHANNEL_NAME = "pro"
CHANNEL_ALIAS = "https://repo.anaconda.com/pkgs"
SUBDIRS = (
    "noarch",
    "linux-32",
    "linux-64",
    "linux-aarch64",
    "linux-armv6l",
    "linux-armv7l",
    "linux-ppc64le",
    "osx-64",
    "win-32",
    "win-64",
)

REMOVALS = {
    "linux-64": (

    ),
    "osx-64": (

    ),
    "win-32": (


    ),
    "win-64": (

    ),
}

EXTERNAL_DEPENDENCIES = {
    "argparse": "python:argparse",
    "bitarray": "python:bitarray",
    "boost": "python:boost",
    "boto": "python:boto",
    "cffi": "python:cffi",
    "jupyter": "python:jupyter",
    "libgfortran": "global:libgfortran",
    "libpostgres": "global:libpostgres",
    "libpq": "global:libpq",
    "libthrift": "global:libthrift",
    "llvmlite": "python:llvmlite",
    "llvmpy": "python:llvmpy",
    "mongo-driver": "global:mongo-driver",
    "nose": "python:nose",
    "numba": "python:numba",
    "numbapro_cudalib": "python:numbapro_cudalib",
    "openssl": "global:openssl",
    "ordereddict": "python:ordereddict",
    "pandas": "python:pandas",
    "pcre": "global:pcre",
    "readline": "global:readline",
    "six": "python:six",
    "snakeviz": "python:snakeviz",
    "sqlite": "global:sqlite",
    "system": "global:system",
    "thrift": "python:thrift",
    "unixodbc": "global:unixodbc",
    "zlib": "global:zlib",
}

NAMESPACE_IN_NAME_SET = {

}


NAMESPACE_OVERRIDES = {
    "mkl": "global",
}


def _patch_repodata(repodata, subdir):
    index = repodata["packages"]
    instructions = {
        "patch_instructions_version": 1,
        "packages": defaultdict(dict),
        "revoke": [],
        "remove": [],
    }

    instructions["remove"].extend(REMOVALS.get(subdir, ()))

    if subdir == "noarch":
        instructions["external_dependencies"] = EXTERNAL_DEPENDENCIES

    def rename_dependency(fn, record, old_name, new_name):
        depends = record["depends"]
        dep_idx = next(
            (q for q, dep in enumerate(depends) if dep.split(' ')[0] == old_name),
            None
        )
        if dep_idx:
            parts = depends[dep_idx].split(" ")
            remainder = (" " + " ".join(parts[1:])) if len(parts) > 1 else ""
            depends[dep_idx] = new_name + remainder
            instructions["packages"][fn]['depends'] = depends

    for fn, record in index.items():
        record_name = record["name"]
        if record_name in NAMESPACE_IN_NAME_SET and not record.get('namespace_in_name'):
            # set the namespace_in_name field
            instructions["packages"][fn]['namespace_in_name'] = True
        if NAMESPACE_OVERRIDES.get(record_name):
            # explicitly set namespace
            instructions["packages"][fn]['namespace'] = NAMESPACE_OVERRIDES[record_name]

    return instructions


def _extract_and_remove_vc_feature(record):
    features = record.get('features', '').split()
    vc_features = tuple(f for f in features if f.startswith('vc'))
    if not vc_features:
        return None
    non_vc_features = tuple(f for f in features if f not in vc_features)
    vc_version = int(vc_features[0][2:])  # throw away all but the first
    if non_vc_features:
        record['features'] = ' '.join(non_vc_features)
    else:
        del record['features']
    return vc_version


def do_hotfixes(base_dir):

    # Step 1. Collect initial repodata for all subdirs.
    repodatas = {}
    for subdir in SUBDIRS:
        repodata_path = join(base_dir, subdir, 'repodata-clone.json')
        if isfile(repodata_path):
            with open(repodata_path) as fh:
                repodatas[subdir] = json.load(fh)
        else:
            repodata_url = "/".join((CHANNEL_ALIAS, CHANNEL_NAME, subdir, "repodata.json"))
            response = requests.get(repodata_url)
            response.raise_for_status()
            repodatas[subdir] = response.json()
            if not isdir(dirname(repodata_path)):
                os.makedirs(dirname(repodata_path))
            with open(repodata_path, 'w') as fh:
                json.dump(repodatas[subdir], fh, indent=2, sort_keys=True, separators=(',', ': '))

    # Step 2. Create all patch instructions.
    patch_instructions = {}
    for subdir in SUBDIRS:
        instructions = _patch_repodata(repodatas[subdir], subdir)
        patch_instructions_path = join(base_dir, subdir, "patch_instructions.json")
        with open(patch_instructions_path, 'w') as fh:
            json.dump(instructions, fh, indent=2, sort_keys=True, separators=(',', ': '))
        patch_instructions[subdir] = instructions


def main():
    base_dir = join(dirname(__file__), CHANNEL_NAME)
    do_hotfixes(base_dir)


if __name__ == "__main__":
    sys.exit(main())
