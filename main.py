# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from collections import defaultdict
import fnmatch
import json
import os
from os.path import join, dirname, isfile, isdir
import re
import sys

import requests

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
    "osx-64",
    "win-32",
    "win-64",
)

REMOVALS = {
    "noarch": (),
    "linux-ppc64le": [],
    "osx-64": [],
    "win-32": ["nomkl-*"],
    "win-64": ["nomkl-*"],
    "any": {
        # early efforts on splitting numpy recipe did not pin numpy-base exactly.
        #     These led to bad builds (built against newest numpy)
        "numpy-*1.11.3-*_6.tar.bz2",
        "numpy-*1.14.3-*_2.tar.bz2",
        # missing blas deps that make solver able to choose wrong things.
        #    numpy-base is pinned exactly, but this effectively defeated the
        #    variant being able to distinguish between openblas and mkl.
        "numpy-1.14.5-py35h28100ab_0.tar.bz2",
        # early vs2017 packages used wrong version numbers
        "vs2017_win-*-15.5.2*",
        "vs2017*h590f102_0*",
        "vs2017*hb4ce483_0*"
    }
}

REVOKED = {
    "linux-64": [
        # build _0 were built against an invalid CuDNN library version
        "tensorflow-base-1.9.0-gpu_py35h9f529ab_0.tar.bz2",
        "tensorflow-base-1.9.0-gpu_py36h9f529ab_0.tar.bz2",
        "tensorflow-base-1.9.0-gpu_py27h9f529ab_0.tar.bz2",
        # compilers with wrong dependencies (missing impl)
        "g*_linux-64-7.2.0-24.tar.bz2",
        ],
    "linux-32": [
        # build _0 were built against an invalid CuDNN library version
        "tensorflow-base-1.9.0-gpu_py35h9f529ab_0.tar.bz2",
        "tensorflow-base-1.9.0-gpu_py36h9f529ab_0.tar.bz2",
        "tensorflow-base-1.9.0-gpu_py27h9f529ab_0.tar.bz2",
        # compilers with wrong dependencies (missing impl)
        "g*_linux-32-7.2.0-24.tar.bz2",
        ],
    "linux-ppc64le": [],
    "osx-64": [],
    "win-32": [
        "spyder-kernels-1.0.1-*_0"
    ],
    "win-64": [
        "spyder-kernels-1.0.1-*_0"
    ],
    "any": []
}

BLAS_USING_PKGS = {"numpy", "numpy-base", "scipy", "numexpr", "scikit-learn", "libmxnet"}

TFLOW_SUBS = {
    # 1.8.0, eigen is the default variant
    '_tflow_180_select ==1.0 gpu': '_tflow_select ==1.1.0 gpu',
    '_tflow_180_select ==2.0 mkl': '_tflow_select ==1.2.0 mkl',
    '_tflow_180_select ==3.0 eigen': '_tflow_select ==1.2.0 eigen',

    # 1.9.0, mkl is the default variant
    '_tflow_190_select ==0.0.1 gpu': '_tflow_select ==2.1.0 gpu',
    '_tflow_190_select ==0.0.2 eigen': '_tflow_select ==2.2.0 eigen',
    '_tflow_190_select ==0.0.3 mkl': '_tflow_select ==2.3.0 mkl',

    # 1.10.0, mkl is the default variant
    '_tflow_1100_select ==0.0.1 gpu': '_tflow_select ==2.1.0 gpu',
    '_tflow_1100_select ==0.0.2 eigen': '_tflow_select ==2.2.0 eigen',
    '_tflow_1100_select ==0.0.3 mkl': '_tflow_select ==2.3.0 mkl',

    # 1.11.0+ needs no fixing
}


def _replace_vc_features_with_vc_pkg_deps(fn, record, instructions):
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
            instructions["packages"][fn]['features'] = record.get('features') or ""
            # add a vs20XX_runtime dependency
            if not any(d.startswith('vs2') for d in record['depends']):
                depends = record['depends']
                depends.append(vs_runtime_deps[vc_version])
                instructions["packages"][fn]['depends'] = depends
    elif record_name == "git":
        # remove any vc dependency, as git does not depend on a specific one
        depends = [dep for dep in record['depends'] if not dep.startswith('vc ')]
        if len(depends) != (record['depends']):
            instructions["packages"][fn]['depends'] = depends
    elif 'vc' in record.get('features', ''):
        # remove vc from the features key
        vc_version = _extract_and_remove_vc_feature(record)
        if vc_version:
            instructions["packages"][fn]['features'] = record.get('features') or ""
            # add a vc dependency
            if not any(d.startswith('vc') for d in record['depends']):
                instructions["packages"][fn]['depends'] = record["depends"] + ['vc %d.*' % vc_version]
    # elif record["name"] == "vc" and "vc" not in record.get("track_features", ""):
    #     tf = record.get("track_features", "") + " vc" + record["version"]
    #     instructions["packages"][fn]["track_features"] = tf.strip()
    # elif record.get("track_features", "").startswith("vc"):
    #     vc_feats = (f for f in record["track_features"].split() if f.startswith("vc"))
    #     for feat in vc_feats:
    #         xtractd = record["track_features"] = _extract_track_feature(record, feat)
    #         instructions["packages"][fn]["track_features"] = xtractd


def _apply_namespace_overrides(fn, record, instructions):
    record_name = record["name"]
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
        "boost": "python",
        "ninja": "global",
        "numpy-devel": "python",
        "texlive-core": "global",
        "keras": "python",
        "keras-gpu": "python",
        "git": "global",
        "python-javapackages-cos7-ppc64le": "global",
        "anaconda": "python",
        "conda-env": "python",
        "tensorflow": "python",
        "tensorflow-gpu": "python",
        "xcb-proto": "global",
        "mxnet": "python",
    }
    if record_name in namespace_in_name_set and not record.get('namespace_in_name'):
        # set the namespace_in_name field
        instructions["packages"][fn]['namespace_in_name'] = True
    if namespace_overrides.get(record_name):
        # explicitly set namespace
        instructions["packages"][fn]['namespace'] = namespace_overrides[record_name]


def _fix_linux_runtime_bounds(fn, record, instructions):
    linux_runtime_re = re.compile(r"lib(\w+)-ng\s(?:>=)?([\d\.]+\d)(?:$|\.\*)")
    if any(dep.split()[0] in ("libgcc-ng", "libstdcxx-ng", "libgfortran-ng")
           for dep in record.get('depends', [])):
        deps = []
        for dep in record['depends']:
            match = linux_runtime_re.match(dep)
            if match:
                dep = "lib{}-ng >={}".format(match.group(1), match.group(2))
                if match.group(1) == "gfortran":
                    # this is adding an upper bound
                    lower_bound = int(match.group(2)[0])
                    # ABI break at gfortran 8
                    if lower_bound < 8:
                        dep += ",<8.0a0"
            deps.append(dep)
        instructions["packages"][fn]["depends"] = deps


def _fix_nomkl_features(fn, record, instructions):
    if "nomkl" == record["features"]:
        del record['features']
        if not any(d.startswith("blas ") for d in record["depends"]):
            instructions["packages"][fn]["depends"] = record['depends'] + ["blas * openblas"]
    elif "nomkl" in record["features"]:
        # remove nomkl feature
        record['features'].remove('nomkl')
        if not any(d.startswith("blas ") for d in record["depends"]):
            instructions["packages"][fn]["depends"] = record['depends'] + ["blas * openblas"]
            instructions["packages"][fn]["features"] = record['features']


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
            "util-linux": "global:util-linux",  # libdap4, pynio
            "meld3": "python:meld3",  # supervisor
            "msys2-conda-epoch": "global:msys2-conda-epoch",  # anaconda
        }

    for fn, record in index.items():
        if (any(fnmatch.fnmatch(fn, rev) for rev in REVOKED.get(subdir, [])) or
                 any(fnmatch.fnmatch(fn, rev) for rev in REVOKED.get("any", []))):
            instructions['revoke'].append(fn)
        if (any(fnmatch.fnmatch(fn, rev) for rev in REMOVALS.get(subdir, [])) or
                 any(fnmatch.fnmatch(fn, rev) for rev in REMOVALS.get("any", []))):
            instructions['remove'].append(fn)
        _apply_namespace_overrides(fn, record, instructions)
        if fn.startswith("numba-0.36.1") and record.get('timestamp') != 1512604800000:
            # set a specific timestamp
            instructions["packages"][fn]['timestamp'] = 1512604800000

        # strip out pyobjc stuff from twisted  (maybe Kale understands this one?)
        #
        # 2018/09/10: we're not sure why this one was necessary.  Commenting until we understand the need for it.
        #
        # if record["name"] == "twisted" and any(dep.startswith("pyobjc-") for dep in record.get("constrains", ())):
        #         instructions["packages"][fn]['constrains'] = [dep for dep in record["constrains"]
        #                                                       if not dep.startswith("pyobjc-")]

        if "features" in record:
            _fix_nomkl_features(fn, record, instructions)

        # this was a not-very-successful approach at fixing features
        blas_req_feature = record.get('requires_features', {}).get("blas")
        if blas_req_feature:
            if not any(dep.startswith("blas ") for dep in record['depends']):
                record['depends'].append("blas * %s" % blas_req_feature)
                instructions["packages"][fn]["depends"] = record['depends']
            # del record["requires_features"]["blas"]
            # instructions["packages"][fn]["requires_features"] = record["requires_features"]

        if record.get("track_features"):
            for feat in record["track_features"].split():
                if feat.startswith(("rb2", "openjdk")):
                    xtractd = record["track_features"] = _extract_track_feature(record, feat)
                    instructions["packages"][fn]["track_features"] = xtractd

        # reset dependencies for nomkl to the blas metapkg and remove any
        #      track_features (these are attached to the metapkg instead)
        if record['name'] == 'nomkl' and not subdir.startswith("win-"):
            record['depends'] = ["blas * openblas"]
            if 'track_features' in record:
                instructions["packages"][fn]["track_features"] = None

        if record['name'] == 'conda-env':
            if not any(d.startswith('python') for d in record['depends']):
                instructions["packages"][fn]["namespace"] = "python"

        if record['name'] == 'openblas-devel' and not any(d.startswith('blas ') for d in record['depends']):
            record["depends"].append("blas * openblas")
            instructions["packages"][fn]["depends"] = record["depends"]

        if record['name'] == 'mkl-devel' and not any(d.startswith('blas') for d in record['depends']):
            record["depends"].append("blas * mkl")
            instructions["packages"][fn]["depends"] = record["depends"]

        if record['name'] == 'pyqt'and record['version'] == '5.9.2':
            # pyqt needs an upper limit of sip, build 2 has this already
            if 'sip >=4.19.4' in record['depends']:
                sip_index = record['depends'].index('sip >=4.19.4')
                record['depends'][sip_index]= 'sip >=4.19.4,<=4.19.8'
                instructions["packages"][fn]["depends"] = record["depends"]

        if record['name'] in ['tensorflow', 'tensorflow-gpu', 'tensorflow-eigen', 'tensorflow-mkl']:
            if record['version'] not in ['1.8.0', '1.9.0', '1.10.0']:
                continue
            # use _tflow_select as the mutex/selector not _tflow_180_select, etc
            depends = [TFLOW_SUBS[d] if d in TFLOW_SUBS else d for d in record['depends']]
            instructions["packages"][fn]["depends"] = depends

        if fn == 'cupti-9.0.176-0.tar.bz2':
            # depends in package is set as cudatoolkit 9.*, should be 9.0.*
            instructions["packages"][fn]["depends"] = ['cudatoolkit 9.0.*']

        # add in blas mkl metapkg for mutex behavior on packages that have just mkl deps
        if (record['name'] in BLAS_USING_PKGS and not
                   any(dep.split()[0] == "blas" for dep in record['depends'])):
            if any(dep.split()[0] == 'mkl' for dep in record['depends']):
                record["depends"].append("blas * mkl")
            elif any(dep.split()[0] in ('openblas', "libopenblas") for dep in record['depends']):
                record["depends"].append("blas * openblas")
            instructions["packages"][fn]["depends"] = record["depends"]

        # some of these got hard-coded to overly restrictive values
        if record['name'] in ('scikit-learn', 'pytorch'):
            new_deps = []
            for dep in record['depends']:
                if dep.startswith('mkl 2018'):
                    if not any(_.startswith('mkl >') for _ in record['depends']):
                        new_deps.append("mkl >=2018.0.3")
                elif dep == 'nccl':
                    # pytorch was built with nccl 1.x
                    new_deps.append('nccl <2')
                else:
                    new_deps.append(dep)
            record["depends"] = new_deps
            instructions["packages"][fn]["depends"] = record["depends"]


        if subdir.startswith("win-"):
            _replace_vc_features_with_vc_pkg_deps(fn, record, instructions)

        elif subdir.startswith("linux-"):
            _fix_linux_runtime_bounds(fn, record, instructions)

    instructions['remove'].sort()
    instructions['revoke'].sort()
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
    return " ".join(features)


def _extract_track_feature(record, feature_name):
    features = record.get('track_features', '').split()
    features.remove(feature_name)
    return " ".join(features)


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
