# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from collections import defaultdict
import json
import os
from os.path import join, dirname, isfile, isdir
import sys

import requests

CHANNEL_NAME = "free"
CHANNEL_ALIAS = "https://repo.anaconda.com/pkgs"
SUBDIRS = (
    "noarch",
    "linux-32",
    "linux-64",
    "linux-armv6l",
    "linux-armv7l",
    "linux-ppc64le",
    "osx-64",
    "win-32",
    "win-64",
)

def _patch_repodata(repodata, subdir):
    index = repodata["packages"]
    instructions = {
        "patch_instructions_version": 1,
        "packages": defaultdict(dict),
        "revoke": [],
        "remove": [],
    }

    if subdir == "noarch":
        instructions["external_dependencies"] = {
            "msys2-conda-epoch": "global:msys2-conda-epoch",  # ninja, the-silver-searcher
            "libgcc-ng": "global:libgcc-ng",  # astropy 2.0.2
        }

    namespace_in_name_set = {
        "python-crfsuite",
        "python-daemon",
        "python-dateutil",
        "python-editor",
        "python-engineio",
        "python-gflags",
        "python-ldap",
        "python-memcached",
        "python-ntlm",
        "python-rapidjson",
        "python-slugify",
        "python-snappy",
        "python-socketio",
        "python-sybase",
        "python-utils",
    }

    namespace_overrides = {
        "ninja": "global",
        # "numpy-devel": "python",
        "texlive-core": "global",
        # "keras": "python",
        # "keras-gpu": "python",
        "git": "global",
        # "python-javapackages-cos7-ppc64le": "global",
        "anaconda": "python",
        "conda-env": "python",
        "binstar": "python",
        "binstar-build": "python",
        "blz": "python",
        "boost": "python",
        "the-silver-searcher": "global",
        "dynd-python": "python",
        "conda-server": "python",
        "swig": "global",
        "tensorflow": "python",
        "tensorflow-gpu": "python",
        "bazel": "java",
        "thrift": "python",
        "launcher": "global",
        "mathjax": "js",
        "svn": "global",
        "patch": "global",
    }

    if subdir.startswith("win-"):
        python_vc_deps = {
            '2.6': 'vc 9.*',
            '2.7': 'vc 9.*',
            '3.3': 'vc 10.*',
            '3.4': 'vc 10.*',
            '3.5': 'vc 14.*',
            '3.6': 'vc 14.*',
            '3.7': 'vc 14.*',
        }
        vs_runtime_deps = {
            9: 'vs2008_runtime',
            10: 'vs2010_runtime',
            14: 'vs2015_runtime',
        }
        for fn, record in index.items():
            record_name = record['name']
            if record_name == 'python':
                # remove the track_features key
                if 'track_features' in record:
                    instructions["packages"][fn]['track_features'] = None
                # add a vc dependency
                if not any(d.startswith('vc') for d in record['depends']):
                    depends = record['depends']
                    depends.append(python_vc_deps[record['version'][:3]])
                    instructions["packages"][fn]['depends'] = depends
            elif record_name == "vs2015_win-64":
                # remove the track_features key
                if 'track_features' in record:
                    instructions["packages"][fn]['track_features'] = None
            elif record['name'] == "yasm":
                # remove vc from the features key
                vc_version = _extract_and_remove_vc_feature(record)
                if vc_version:
                    instructions["packages"][fn]['features'] = record.get('features', None)
                    # add a vs20XX_runtime dependency
                    if not any(d.startswith('vs2') for d in record['depends']):
                        depends = record['depends']
                        depends.append(vs_runtime_deps[vc_version])
                        instructions["packages"][fn]['depends'] = depends
            elif record_name == "git":
                # remove any vc dependency
                depends = [dep for dep in record['depends'] if not dep.startswith('vc ')]
                if len(depends) != (record['depends']):
                    instructions["packages"][fn]['depends'] = depends
            elif 'vc' in record.get('features', ''):
                # remove vc from the features key
                vc_version = _extract_and_remove_vc_feature(record)
                if vc_version:
                    instructions["packages"][fn]['features'] = record.get('features', None)
                    # add a vc dependency
                    if not any(d.startswith('vc') for d in record['depends']):
                        depends = record['depends']
                        depends.append('vc %d.*' % vc_version)
                        instructions["packages"][fn]['depends'] = depends

    for fn, record in index.items():
        record_name = record["name"]
        if record_name in namespace_in_name_set and not record.get('namespace_in_name'):
            # set the namespace_in_name field
            instructions["packages"][fn]['namespace_in_name'] = True
        if namespace_overrides.get(record_name):
            # explicitly set namespace
            instructions["packages"][fn]['namespace'] = namespace_overrides[record_name]
        if record_name == "gcc" and record['version'].startswith('4.8.'):
            # add upper bound to dependency version constraint
            depends = record['depends']
            upper_bound = ",<4"
            mpfr_idx = next(
                (q for q, dep in enumerate(depends)
                 if dep.startswith('mpfr') and not dep.endswith(upper_bound)),
                None
            )
            if mpfr_idx is not None:
                depends[mpfr_idx] += upper_bound
                instructions["packages"][fn]['depends'] = depends
        if "features" in record:
            if "nomkl" in record["features"]:
                # remove nomkl feature
                instructions["packages"][fn]["features"] = _extract_feature(record, "nomkl")
                if not any(d.startswith("blas ") for d in record["depends"]):
                    depends = record['depends']
                    depends.append("nomkl")
                    instructions["packages"][fn]["depends"] = depends
        if "track_features" in record:
            for feat in record["track_features"].split():
                if feat.startswith(("rb2", "openjdk")):
                    xtractd = record["track_features"] = _extract_track_feature(record, feat)
                    instructions["packages"][fn]["track_features"] = xtractd

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


def _extract_feature(record, feature_name):
    features = record.get('features', '').split()
    features.remove(feature_name)
    return " ".join(features) or None


def _extract_track_feature(record, feature_name):
    features = record.get('track_features', '').split()
    features.remove(feature_name)
    return " ".join(features) or None


def main():

    base_dir = join(dirname(__file__), CHANNEL_NAME)

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


if __name__ == "__main__":
    sys.exit(main())
