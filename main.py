import bisect
import copy
import fnmatch
import json
import os
from os.path import dirname, isdir, isfile, join
import re
import sys
from collections import defaultdict
from pathlib import Path

from conda.models.version import VersionOrder
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
    "linux-s390x",
    "osx-64",
    "osx-arm64",
    "win-32",
    "win-64",
)

REMOVALS = {
    "noarch": (),
    "linux-ppc64le": [
        # This build contains incorrect libffi run depends; removing rather
        # than patching to prevent solver from getting stuck in a bistable
        # solution (since another build has the same set of requirements).
        "cffi-1.14.6-py36h140841e_0.tar.bz2",
        "cffi-1.14.6-py37h140841e_0.tar.bz2",
        "cffi-1.14.6-py38h140841e_0.tar.bz2",
        "cffi-1.14.6-py39h140841e_0.tar.bz2",
    ],
    "osx-64": [
        # qt 5.9.7 accidentially added .conda. to the dylibs names
        "qt-5.9.7-h468cd18_0.tar.bz2",
        # This build contains incorrect libffi run depends; removing rather
        # than patching to prevent solver from getting stuck in a bistable
        # solution (since another build has the same set of requirements).
        "cffi-1.14.6-py36h9ed2024_0.tar.bz2",
        "cffi-1.14.6-py37h9ed2024_0.tar.bz2",
        "cffi-1.14.6-py38h9ed2024_0.tar.bz2",
        "cffi-1.14.6-py39h9ed2024_0.tar.bz2",
        # libcxx-17.0.6*1 is missing run_constrained which breaks clang 14.
        "libcxx-17.0.6-hf547dac_1.tar.bz2",
    ],
    "osx-arm64": [
        # libcxx-17.0.6*1 is missing run_constrained which breaks clang 14.
        "libcxx-17.0.6-he5c5206_1.tar.bz2",
    ],
    "win-32": [
        "nomkl-*",
        # This release/build breaks matplotlib and possibly other things well
        "freetype-2.11.0-h88da6cb_0.tar.bz2",
    ],
    "win-64": [
        "nomkl-*",
        # numba 0.46 didn't actually support py38
        "numba-0.46.0-py38hf9181ef_0.tar.bz2",
        # This release/build breaks matplotlib and possibly other things well
        "freetype-2.11.0-ha860e81_0.tar.bz2",
    ],
    "linux-64": [
        "numba-0.46.0-py38h962f231_0.tar.bz2",
        # This build contains incorrect libffi run depends; removing rather
        # than patching to prevent solver from getting stuck in a bistable
        # solution (since another build has the same set of requirements).
        "cffi-1.14.6-py36h7f8727e_0.tar.bz2",
        "cffi-1.14.6-py37h7f8727e_0.tar.bz2",
        "cffi-1.14.6-py38h7f8727e_0.tar.bz2",
        "cffi-1.14.6-py39h7f8727e_0.tar.bz2",
    ],
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
        "vs2017*hb4ce483_0*",
        # libtiff has incorrect build number and incorrect requirements
        "libtiff-4.0.10-*_1001.tar.bz2",
        # incorrect requirements leading to import failures
        "libarchive-3.3.3-*_0",
        # cph 1.5.0 replaces \r\n in files with \n on windows but does not
        # truncate the file.  This results in corrupt packages.
        "conda-package-handling-1.5.0*",
        # segfaults in 2019.5 that need work to understand.  To be restored soon.
        "mkl*-2019.5*",
        "daal*-2019.5*",
        "intel-openmp*-2019.5*",
        # missing dependencies
        "numpy-devel-1.14.3*",
        # anaconda-client<1.10.0 is incompatible with python 3.10
        "anaconda-client-1.9.0-py310*",
        # navigator-updater=0.5.0 is incompatible with anaconda-navigator
        "navigator-updater-0.5.0-*"
    },
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
    "osx-64": [
        # this build statically links libxml2-with-icu but doesn't statically
        # link icu. xref: https://github.com/AnacondaRecipes/aggregate/issues/10
        "xar-1.6.1-hd3d9906_0.tar.bz2",
        # doesn't specify dependency on openssl, whereas it should
        "libssh2 1.8.0 h1218725_2",
    ],
    "win-32": [
        "spyder-kernels-1.0.1-*_0",
    ],
    "win-64": [
        "spyder-kernels-1.0.1-*_0",
    ],
    "any": [
        # Packages with bad shortcuts that can cause installers
        # and uninstallers to break under certain circumstances.
        "anaconda-navigator-2.6.0-*_1.*",
        "anaconda-navigator-2.6.1-*_1.*",
        "git-2.40.1-*_2.*",
        "git-2.40.1-*_3.*",
        "notebook-7.0.8-*_1.*",
        "spyder-5.5.1-*_1.*",
        "spyder-5.5.1-*_2.*",
        # anaconda-cli-base-0.4.1 build number 0 has missing run_constrained requirements
        "anaconda-cli-base-0.4.1-*_0.*",
    ],
}

# This is a list of numpy-base packages for each subdir which multiple numpy
# packages depend on. Since multiple numpy packages depend on these the
# constrain entry added to them should be to the numpy version not the version
# and build as the later would make some numpy packages un-installable.
NP_BASE_LOOSE_PIN = {
    "linux-64": [
        "numpy-base-1.11.3-py27h2b20989_8.tar.bz2",
        "numpy-base-1.11.3-py27hdbf6ddf_8.tar.bz2",
        "numpy-base-1.11.3-py36h2b20989_8.tar.bz2",
        "numpy-base-1.11.3-py36hdbf6ddf_8.tar.bz2",
        "numpy-base-1.11.3-py37h2b20989_8.tar.bz2",
        "numpy-base-1.11.3-py37hdbf6ddf_8.tar.bz2",
        "numpy-base-1.15.1-py27h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py27h81de0dd_0.tar.bz2",
        "numpy-base-1.15.1-py35h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py35h81de0dd_0.tar.bz2",
        "numpy-base-1.15.1-py36h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py36h81de0dd_0.tar.bz2",
        "numpy-base-1.15.1-py37h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py37h81de0dd_0.tar.bz2",
        "numpy-base-1.9.3-py27h2b20989_7.tar.bz2",
        "numpy-base-1.9.3-py27hdbf6ddf_7.tar.bz2",
        "numpy-base-1.9.3-py35h2b20989_7.tar.bz2",
        "numpy-base-1.9.3-py35hdbf6ddf_7.tar.bz2",
        "numpy-base-1.9.3-py36h2b20989_7.tar.bz2",
        "numpy-base-1.9.3-py36hdbf6ddf_7.tar.bz2",
        "numpy-base-1.9.3-py37h2b20989_7.tar.bz2",
        "numpy-base-1.9.3-py37hdbf6ddf_7.tar.bz2",
    ],
    "osx-64": [
        "numpy-base-1.11.3-py27h9797aa9_8.tar.bz2",
        "numpy-base-1.11.3-py27ha9ae307_8.tar.bz2",
        "numpy-base-1.11.3-py36h9797aa9_8.tar.bz2",
        "numpy-base-1.11.3-py36ha9ae307_8.tar.bz2",
        "numpy-base-1.11.3-py37h9797aa9_8.tar.bz2",
        "numpy-base-1.11.3-py37ha9ae307_8.tar.bz2",
        "numpy-base-1.15.1-py27h42e5f7b_0.tar.bz2",
        "numpy-base-1.15.1-py27h8a80b8c_0.tar.bz2",
        "numpy-base-1.15.1-py35h42e5f7b_0.tar.bz2",
        "numpy-base-1.15.1-py35h8a80b8c_0.tar.bz2",
        "numpy-base-1.15.1-py36h42e5f7b_0.tar.bz2",
        "numpy-base-1.15.1-py36h8a80b8c_0.tar.bz2",
        "numpy-base-1.15.1-py37h42e5f7b_0.tar.bz2",
        "numpy-base-1.15.1-py37h8a80b8c_0.tar.bz2",
        "numpy-base-1.9.3-py27h9797aa9_7.tar.bz2",
        "numpy-base-1.9.3-py27ha9ae307_7.tar.bz2",
        "numpy-base-1.9.3-py35h9797aa9_7.tar.bz2",
        "numpy-base-1.9.3-py35ha9ae307_7.tar.bz2",
        "numpy-base-1.9.3-py36h9797aa9_7.tar.bz2",
        "numpy-base-1.9.3-py36ha9ae307_7.tar.bz2",
        "numpy-base-1.9.3-py37h9797aa9_7.tar.bz2",
        "numpy-base-1.9.3-py37ha9ae307_7.tar.bz2",
    ],
    "win-64": [
        "numpy-base-1.15.1-py27h2753ae9_0.tar.bz2",
        "numpy-base-1.15.1-py35h8128ebf_0.tar.bz2",
        "numpy-base-1.15.1-py36h8128ebf_0.tar.bz2",
        "numpy-base-1.15.1-py37h8128ebf_0.tar.bz2",
    ],
    "win-32": [
        "numpy-base-1.15.1-py27h2753ae9_0.tar.bz2",
        "numpy-base-1.15.1-py35h8128ebf_0.tar.bz2",
        "numpy-base-1.15.1-py36h8128ebf_0.tar.bz2",
        "numpy-base-1.15.1-py37h8128ebf_0.tar.bz2",
    ],
    "linux-ppc64le": [
        "numpy-base-1.11.3-py27h2b20989_8.tar.bz2",
        "numpy-base-1.11.3-py36h2b20989_8.tar.bz2",
        "numpy-base-1.15.1-py27h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py35h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py36h74e8950_0.tar.bz2",
        "numpy-base-1.15.1-py37h74e8950_0.tar.bz2",
    ],
    "noarch": [],
    "linux-32": [],
    "linux-aarch64": [],
    "linux-armv6l": [],
    "linux-armv7l": [],
    "linux-s390x": [],
    "osx-arm64": [],
}

BLAS_USING_PKGS = {
    "numpy",
    "numpy-base",
    "scipy",
    "numexpr",
    "scikit-learn",
    "libmxnet",
}

TFLOW_SUBS = {
    # 1.8.0, eigen is the default variant
    "_tflow_180_select ==1.0 gpu": "_tflow_select ==1.1.0 gpu",
    "_tflow_180_select ==2.0 mkl": "_tflow_select ==1.2.0 mkl",
    "_tflow_180_select ==3.0 eigen": "_tflow_select ==1.3.0 eigen",
    # 1.9.0, mkl is the default variant
    "_tflow_190_select ==0.0.1 gpu": "_tflow_select ==2.1.0 gpu",
    "_tflow_190_select ==0.0.2 eigen": "_tflow_select ==2.2.0 eigen",
    "_tflow_190_select ==0.0.3 mkl": "_tflow_select ==2.3.0 mkl",
    # 1.10.0, mkl is the default variant
    "_tflow_1100_select ==0.0.1 gpu": "_tflow_select ==2.1.0 gpu",
    "_tflow_1100_select ==0.0.2 eigen": "_tflow_select ==2.2.0 eigen",
    "_tflow_1100_select ==0.0.3 mkl": "_tflow_select ==2.3.0 mkl",
    # 1.11.0+ needs no fixing
}

CUDATK_SUBS = {
    "cudatoolkit >=9.0,<10.0a0": "cudatoolkit >=9.0,<9.1.0a0",
    "cudatoolkit >=9.2,<10.0a0": "cudatoolkit >=9.2,<9.3.0a0",
    "cudatoolkit >=10.0.130,<11.0a0": "cudatoolkit >=10.0.130,<10.1.0a0",
}
MKL_VERSION_2018_RE = re.compile(r">=2018(.\d){0,2}$")
MKL_VERSION_2018_EXTENDED_RC = re.compile(r">=2018(.\d){0,2}")
LINUX_RUNTIME_RE = re.compile(r"lib(\w+)-ng\s(?:>=)?([\d\.]+\d)(?:$|\.\*)")
LINUX_RUNTIME_DEPS = ("libgcc-ng", "libstdcxx-ng", "libgfortran-ng")

# Packages that do *not* need to have their libffi dependencies patched
LIBFFI_HOTFIX_EXCLUDES = [
    "_anaconda_depends",
]

# Get the directory where the current script is located
script_directory = Path(__file__).parent

# Construct the full path to the JSON file
json_file_path = script_directory / "numpy2_patch.json"

# Read and load the JSON file
NUMPY_2_CHANGES = json.loads(json_file_path.read_text())


def apply_numpy2_changes(record, subdir, filename):
    """
    Applies predefined numpy changes to a record based on its directory and filename.
    Parameters:
    - record: The record to update.
    - subdir: The subdirectory of the record.
    - filename: The filename of the record.
    """
    if subdir not in NUMPY_2_CHANGES:
        return

    change = NUMPY_2_CHANGES[subdir].get(filename)
    if change:
        replace_dep(record[change["type"]], change["original"], change["updated"])


def _replace_vc_features_with_vc_pkg_deps(name, record, depends):
    python_vc_deps = {
        "2.6": "vc 9.*",
        "2.7": "vc 9.*",
        "3.3": "vc 10.*",
        "3.4": "vc 10.*",
        "3.5": "vc 14.*",
        "3.6": "vc 14.*",
        "3.7": "vc 14.*",
    }
    vs_runtime_deps = {
        9: "vs2008_runtime",
        10: "vs2010_runtime",
        14: "vs2015_runtime",
    }
    if name == "python":
        # remove the track_features key
        if "track_features" in record:
            record["track_features"] = ""
        # add a vc dependency
        if not any(d.startswith("vc") for d in depends):
            depends.append(python_vc_deps[record["version"][:3]])
    elif name == "vs2015_win-64":
        # remove the track_features key
        if "track_features" in record:
            record["track_features"] = ""
    elif record["name"] == "yasm":
        # remove vc from the features key
        vc_version = _extract_and_remove_vc_feature(record)
        if vc_version:
            record["features"] = record.get("features") or ""
            # add a vs20XX_runtime dependency
            if not any(d.startswith("vs2") for d in record["depends"]):
                depends.append(vs_runtime_deps[vc_version])
    elif name == "git":
        # remove any vc dependency, as git does not depend on a specific one
        depends[:] = [dep for dep in depends if not dep.startswith("vc ")]
    elif "vc" in record.get("features", ""):
        # remove vc from the features key
        vc_version = _extract_and_remove_vc_feature(record)
        if vc_version:
            record["features"] = record.get("features") or ""
            # add a vc dependency
            if not any(d.startswith("vc") for d in depends):
                depends.append("vc %d.*" % vc_version)


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
    if record_name in namespace_in_name_set and not record.get("namespace_in_name"):
        # set the namespace_in_name field
        instructions["packages"][fn]["namespace_in_name"] = True
    if namespace_overrides.get(record_name):
        # explicitly set namespace
        instructions["packages"][fn]["namespace"] = namespace_overrides[record_name]


def _get_record_depends(fn, record, instructions):
    """Return the depends information for a record, including any patching."""
    record_depends = record.get("depends", [])
    if fn in instructions["packages"]:
        if "depends" in instructions["packages"][fn]:
            # the package depends have already been patched
            record_depends = instructions["packages"][fn]["depends"]
    return record_depends


def _fix_linux_runtime_bounds(depends):
    for i, dep in enumerate(depends):
        if dep.split()[0] not in LINUX_RUNTIME_DEPS:
            continue
        match = LINUX_RUNTIME_RE.match(dep)
        if not match:
            continue
        dep = "lib{}-ng >={}".format(match.group(1), match.group(2))
        if match.group(1) == "gfortran":
            # this is adding an upper bound
            lower_bound = int(match.group(2)[0])
            # ABI break at gfortran 8
            if lower_bound < 8:
                dep += ",<8.0a0"
        depends[i] = dep


def _fix_nomkl_features(record, depends):
    if record["features"] == "nomkl":
        record["features"] = None
        if not any(d.startswith("blas ") for d in depends):
            depends[:] = depends + ["blas * openblas"]
    elif "nomkl" in record["features"]:
        # remove nomkl feature
        record["features"].remove("nomkl")
        if not any(d.startswith("blas ") for d in depends):
            depends[:] = depends + ["blas * openblas"]


def _fix_numpy_base_constrains(record, index, instructions, subdir):
    # numpy-base packages should have run constrains on the corresponding numpy package
    base_pkgs = [d for d in record["depends"] if d.startswith("numpy-base")]
    if not base_pkgs:
        # no base package, no hotfixing needed
        return
    base_pkg = base_pkgs[0]
    try:
        name, ver, build_str = base_pkg.split()
    except ValueError:
        # base package pinning not to version + build, no modification needed
        return
    base_pkg_fn = "%s-%s-%s.tar.bz2" % (name, ver, build_str)
    try:
        if "constrains" in index[base_pkg_fn]:
            return
    except KeyError:
        # package might be revoked
        return
    if base_pkg_fn in NP_BASE_LOOSE_PIN.get(subdir, []):
        # base package is a requirement of multiple numpy packages,
        # constrain to only the version
        req = "%s %s" % (record["name"], record["version"])
    else:
        # base package is a requirement of a single numpy package,
        # constrain to the exact build
        req = "%s %s %s" % (record["name"], record["version"], record["build"])
    instructions["packages"][base_pkg_fn]["constrains"] = [req]


def _fix_cudnn_depends(depends, subdir):
    for dep in depends:
        if dep.startswith("cudnn"):
            original_cudnn_depend = dep
        if dep.startswith("cudatoolkit"):
            cudatoolkit_depend = dep
    is_seven_star = original_cudnn_depend.startswith(
        "cudnn 7*"
    ) or original_cudnn_depend.startswith("cudnn 7.*")
    if subdir.startswith("win-"):
        # all packages prior to 2019-01-24 built with cudnn 7.1.4
        correct_cudnn_depends = "cudnn >=7.1.4,<8.0a0"
    else:
        if original_cudnn_depend.startswith("cudnn 7.0"):
            correct_cudnn_depends = "cudnn >=7.0.0,<=8.0a0"
        elif original_cudnn_depend.startswith("cudnn 7.1.*"):
            correct_cudnn_depends = "cudnn >=7.1.0,<=8.0a0"
        elif original_cudnn_depend.startswith("cudnn 7.2.*"):
            correct_cudnn_depends = "cudnn >=7.2.0,<=8.0a0"
        # these packages express a dependeny of 7* or 7.* which is correct for
        # the cudnn package versions available in defaults but are be rewritten
        # to be more precise.
        # Prior to 2019-01-24 all packages were build against:
        # cudatoolkit 8.0 : cudnn 7.0.5
        # cudatoolkit 9.0 : cudnn 7.1.2
        # cudatoolkit 9.2 : cudnn 7.2.1
        elif is_seven_star and cudatoolkit_depend.startswith("cudatoolkit 8.0"):
            correct_cudnn_depends = "cudnn >=7.0.5,<=8.0a0"
        elif is_seven_star and cudatoolkit_depend.startswith("cudatoolkit 9.0"):
            correct_cudnn_depends = "cudnn >=7.1.2,<=8.0a0"
        elif is_seven_star and cudatoolkit_depend.startswith("cudatoolkit 9.2"):
            correct_cudnn_depends = "cudnn >=7.2.1,<=8.0a0"
        elif original_cudnn_depend == "cudnn 7.3.*":
            correct_cudnn_depends = "cudnn >=7.3.0,<=8.0a0"
        else:
            raise Exception("unknown cudnn depedency")
    idx = depends.index(original_cudnn_depend)
    depends[idx] = correct_cudnn_depends


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
        if is_revoked(fn, subdir):
            instructions["revoke"].append(fn)
        if is_removed(fn, subdir):
            instructions["remove"].append(fn)
        _apply_namespace_overrides(fn, record, instructions)
        patch_record(fn, record, subdir, instructions, index)
    instructions["remove"].sort()
    instructions["revoke"].sort()
    return instructions


def is_revoked(fn, subdir):
    for rev in REVOKED.get(subdir, []):
        if fnmatch.fnmatch(fn, rev):
            return True
    for rev in REVOKED.get("any", []):
        if fnmatch.fnmatch(fn, rev):
            return True
    return False


def is_removed(fn, subdir):
    for rev in REMOVALS.get(subdir, []):
        if fnmatch.fnmatch(fn, rev):
            return True
    for rev in REMOVALS.get("any", []):
        if fnmatch.fnmatch(fn, rev):
            return True
    return False


def patch_record(fn, record, subdir, instructions, index):
    # create a copy of the record, patch in-place and add keys that change
    # to the patch instructions
    original_record = copy.deepcopy(record)
    patch_record_in_place(fn, record, subdir)
    keys_to_check = [
        "app_entry",
        "app_type",
        "constrains",
        "depends",
        "features",
        "namespace",
        "license_family",
        "subdir",
        "track_features",
        "type",
    ]
    for key in keys_to_check:
        if record.get(key) != original_record.get(key):
            instructions["packages"][fn][key] = record.get(key)

    # One-off patches that do not fit in with others
    if record["name"] == "numpy":
        _fix_numpy_base_constrains(record, index, instructions, subdir)

    # set a specific timestamp for numba-0.36.1
    if fn.startswith("numba-0.36.1") and record.get("timestamp") != 1512604800000:
        instructions["packages"][fn]["timestamp"] = 1512604800000

    # set the build_number of the blas-1.0-openblas.tar.bz2 package
    # to 7 to match the package in free
    # https://github.com/conda/conda/issues/8302
    if subdir == "linux-ppc64le" and fn == "blas-1.0-openblas.tar.bz2":
        instructions["packages"][fn]["build_number"] = 7


def patch_record_in_place(fn, record, subdir):
    """Patch record in place"""
    name = record["name"]
    version = record["version"]
    build = record["build"]
    build_number = record["build_number"]
    depends = record["depends"]
    constrains = record.get("constrains", [])

    ##########
    # subdir #
    ##########

    if "subdir" not in record:
        record["subdir"] = subdir

    #############
    # namespace #
    #############

    if name == "conda-env" and not any(d.startswith("python") for d in depends):
        record["namespace"] = "python"

    ################
    # CUDA related #
    ################

    # add run constrains on __cuda virtual package to cudatoolkit package
    # see https://github.com/conda/conda/issues/9115
    if name == "cudatoolkit" and "constrains" not in record:
        major, minor = version.split(".")[:2]
        req = f"__cuda >={major}.{minor}"
        record["constrains"] = [req]

    if any(dep.startswith("cudnn 7") for dep in depends):
        _fix_cudnn_depends(depends, subdir)

    # cudatoolkit should be pinning to major.minor not just major
    if name in ("cupy", "nccl"):
        for i, dep in enumerate(depends):
            depends[i] = CUDATK_SUBS[dep] if dep in CUDATK_SUBS else dep

    # depends in package is set as cudatoolkit 9.*, should be 9.0.*
    if fn == "cupti-9.0.176-0.tar.bz2":
        replace_dep(depends, "cudatoolkit 9.*", "cudatoolkit 9.0.*")

    # documentation on cudnn versions before 8.5.0 is now unavailable.
    # cudnn 8.9.2 is max compatible with cudatoolkit 12.1; glibc 2.17 on x86_64; glibc 2.28 on aarch64
    # https://docs.nvidia.com/deeplearning/cudnn/archives/cudnn-892/support-matrix/index.html
    # cudnn 9.1.1 is max compatible with cudatoolkit 12.4; glibc 2.28 on x86_64; glibc 2.28 on aarch64
    # https://docs.nvidia.com/deeplearning/cudnn/backend/v9.1.1/reference/support-matrix.html#linux
    if name == "cudnn" and version == "8.9.2.26":
        if build.startswith("cuda12"):
            replace_dep(depends, "cuda-version 12.*", "cuda-version >=12,<=12.1")
        if subdir == "linux-aarch64":
            depends.append("__glibc >=2.28")
    if name == "cudnn" and version == "9.1.1.17":
        if build.startswith("cuda12"):
            replace_dep(depends, "cuda-version 12.*", "cuda-version >=12,<=12.4")
        if subdir == "linux-64" or subdir == "linux-aarch64":
            depends.append("__glibc >=2.28")

    #######
    # MKL #
    #######

    if name == "numpy-base" and any(_.startswith("mkl >=2018") for _ in depends):
        depends.append("tbb4py")

    for i, dep in enumerate(depends):
        if (
            dep.split()[0] == "mkl"
            and len(dep.split()) > 1
            and MKL_VERSION_2018_RE.match(dep.split()[1])
        ):
            depends[i] = MKL_VERSION_2018_EXTENDED_RC.sub(
                "%s,<2019.0a0" % (dep.split()[1]), dep
            )

    # intel-openmp 2020.* seems to be incompatible with older versions of mkl
    # issues have only been reported on macOS and Windows but
    # add the constrains on all platforms to be safe
    if name == "intel-openmp" and version.startswith("2020"):
        minor_version = version.split(".")[1]
        record["constrains"] = [f"mkl >=2020.{minor_version}"]

    # mkl 2020.x is compatible with 2019.x
    # so mkl >=2019.x,<2020.0a0 becomes mkl >=2019.x,<2021.0a0
    # except on osx-64, older macOS release have problems...
    for i, dep in enumerate(depends):
        if dep.startswith("mkl >=2019") and dep.endswith(",<2020.0a0"):
            if subdir != "osx-64":
                expanded_dep = dep.replace(",<2020.0a0", ",<2021.0a0")
                depends[i] = expanded_dep

    # some of these got hard-coded to overly restrictive values
    if name in ("scikit-learn", "pytorch"):
        for i, dep in enumerate(depends):
            if dep.startswith("mkl 2018") and not any(
                _.startswith("mkl >") for _ in depends
            ):
                depends[i] = "mkl >=2018.0.3,<2019.0a0"
        if "mkl 2018.*" in depends:
            depends.pop(depends.index("mkl 2018.*"))

    ########
    # BLAS #
    ########

    if "features" in record:
        _fix_nomkl_features(record, depends)

    if name in ("mkl_random", "mkl_fft"):
        if not any(re.match(r"blas\s.*\smkl", dep) for dep in record["depends"]):
            depends.append("blas * mkl")

    if name in ("openblas", "openblas-devel"):
        for i, dep in enumerate(depends):
            if dep.split()[0] == "nomkl":
                depends[i] = "nomkl 3.0 0"

    if name == "openblas-devel" and not any(d.startswith("blas ") for d in depends):
        depends.append("blas * openblas")

    if name == "mkl-devel" and not any(d.startswith("blas") for d in depends):
        depends.append("blas * mkl")

    # add in blas mkl metapkg for mutex behavior on packages that have just mkl deps
    if name in BLAS_USING_PKGS and not any(dep.split()[0] == "blas" for dep in depends):
        if any(dep.split()[0] == "mkl" for dep in depends):
            depends.append("blas * mkl")
        elif any(dep.split()[0] in ("openblas", "libopenblas") for dep in depends):
            depends.append("blas * openblas")

    #########
    # numpy #
    #########

    # Correct packages mistakenly built against 1.21.5 on linux-aarch64
    # Replaces the dependency bound with 1.21.2. These packages should
    # actually have been built against an even earlier version of numpy.
    # This is the safest correction we can make for now
    if subdir == "linux-aarch64":
        for i, dep in enumerate(depends):
            if dep.startswith("numpy >=1.21.5,"):
                depends[i] = depends[i].replace(">=1.21.5,", ">=1.21.2,")
                break

    ######################
    # numpy dependencies #
    ######################

    # https://github.com/lmcinnes/pynndescent/releases/tag/release-0.5.13
    # Numpy 2 support added in 0.5.13.
    if name == "pynndescent" and VersionOrder(version) < VersionOrder("0.5.13"):
        replace_dep(depends, "numpy >=1.17", "numpy >=1.17,<2")

    ###########
    # pytorch #
    ###########

    if name == "pytorch":
        # pytorch was built with nccl 1.x
        replace_dep(depends, "nccl", "nccl <2")

        # Impose our BLAS mutex so users don't accidentally mix OpenBLAS and
        # MKL within a single environment.  In theory, having multiple BLAS
        # implementations in an environment isn't a problem; in practice,
        # however, this can lead to all sorts of problems due to other
        # dependencies (like OpenMP implementations) being dragged in.
        if subdir.endswith("-64") and not any(dep.startswith("blas ") for dep in depends):
            if any(dep.startswith("libopenblas") for dep in depends):
                depends.append("blas * openblas")
            if any(dep.startswith("mkl ") for dep in depends):
                depends.append("blas * mkl")

        depends.sort()

    if name == "torchvision" and version == "0.3.0":
        replace_dep(depends, "pytorch >=1.1.0", "pytorch 1.1.*")
        if "pytorch >=1.1.0" in depends:
            # torchvision pytorch depends needs to be fixed to 1.1
            pytorch_dep = depends.index("pytorch >=1.1.0")
            depends[pytorch_dep] = "pytorch 1.1.*"

    if name == "torchvision" and version == "0.4.0":
        if "cuda" in record["build"]:
            depends.append("_pytorch_select 0.2")
        else:
            depends.append("_pytorch_select 0.1")

    if name == "pytorch" and version in ["2.5.1", "2.6.0"] and subdir in ["linux-64", "osx-arm64"]:
        # pytorch 2.5.1 and 2.6.0 are missing a constraint to match libtorch dependency to the same
        # type of build (cpu vs gpu)
        replace_dep(depends, f"libtorch {version}.*", f"libtorch {version}.* *_{build_number}")

    #########
    # scipy #
    #########

    if name == "scipy":
        # Our original build of scipy-1.7.3 (build number 0) did not comply with the
        # upstream's min and max numpy pinnings.
        # See: https://github.com/scipy/scipy/blob/v1.7.3/setup.py#L551-L552
        if version == "1.7.3" and build_number == 0:
            if subdir != 'osx-arm64' and not build.startswith("py310"):
                replace_dep(depends, "numpy >=1.16.6,<2.0a0", "numpy >=1.16.6,<1.23.0")
            if subdir == 'osx-arm64' and not build.startswith("py310"):
                replace_dep(depends, "numpy >=1.19.5,<2.0a0", "numpy >=1.19.5,<1.23.0")
            if build.startswith("py310"):
                replace_dep(depends, "numpy >=1.21.2,<2.0a0", "numpy >=1.21.2,<1.23.0")
        # scipy needs at least nympy 1.19.5
        # https://github.com/scipy/scipy/blob/v1.10.0/pyproject.toml#L78
        elif version == "1.10.0" and build_number == 0:
            if build[:4] in ["py37", "py38", "py39"]:
                replace_dep(depends, "numpy >=1.19,<1.27.0", "numpy >=1.19.5,<1.27.0")
        # scipy needs at least nympy 1.22.4
        # https://github.com/scipy/scipy/blob/v1.12.0/pyproject.toml#L24
        elif version == "1.12.0" and build_number == 0:
            if build[:4] in ["py39", "py310"]:
                replace_dep(depends, "numpy >=1.22.3,<1.29", "numpy >=1.22.4,<1.29")

    ######################
    # scipy dependencies #
    ######################
    # scipy 1.8 and 1.9 introduce breaking API changes impacting these packages
    if name == "theano":
        if version in ["1.0.4", "1.0.5"]:
            replace_dep(depends, "scipy >=0.14", "scipy >=0.14,<1.8")
        elif version in ["0.9.0", "1.0.1", "1.0.2", "1.0.3"]:
            replace_dep(depends, "scipy >=0.14.0", "scipy >=0.14,<1.8")
    if name == "theano-pymc":
        replace_dep(depends, "scipy >=0.14", "scipy >=0.14,<1.8")
    if name == "pyamg" and version in ["3.3.2", "4.0.0", "4.1.0"]:
        replace_dep(depends, "scipy >=0.12.0", "scipy >=0.12.0,<1.8")
    # scipy 1.16 introduces breaking API changes impacting these packages
    if name == "statsmodels" and version in ("0.14.2", "0.14.4"):
        # addressed in https://github.com/statsmodels/statsmodels/releases/tag/v0.14.5
        replace_dep(depends, "scipy >=1.8,!=1.9.2", "scipy >=1.8,!=1.9.2,<1.16")
    if name == "quantecon" and version in ("0.7.0"):
        replace_dep(depends, "scipy >=1.5.0", "scipy >=1.5.0,<1.16")
    if name == "phik" and version in ("0.12.2", "0.12.3", "0.12.4"):
        # addressed in https://github.com/KaveIO/PhiK/releases/tag/v0.12.5
        replace_dep(depends, "scipy >=1.5.2", "scipy >=1.5.2,<1.16")

    ##############
    # tensorflow #
    ##############

    tflow_pkg = name in [
        "tensorflow",
        "tensorflow-gpu",
        "tensorflow-eigen",
        "tensorflow-mkl",
    ]
    if tflow_pkg and version in ["1.8.0", "1.9.0", "1.10.0"]:
        for i, dep in enumerate(depends):
            depends[i] = TFLOW_SUBS[dep] if dep in TFLOW_SUBS else dep

    if name == "keras":
        version_parts = version.split(".")
        if int(version_parts[0]) <= 2 and int(version_parts[1]) < 3:
            for i, dep in enumerate(depends):
                if dep.startswith("tensorflow"):
                    depends[i] = "tensorflow <2.0"

    # tensorboard 2.0.0 build 0 should have a requirement on setuptools >=41.0.0
    # see: https://github.com/AnacondaRecipes/tensorflow_recipes/issues/20
    if name == "tensorboard" and version == "2.0.0" and build_number == 0:
        depends.append("setuptools >=41.0.0")

    if name.startswith("tensorflow-base") and version == "2.4.1":
        replace_dep(depends, "gast", "gast 0.3.3")

    # Relax the scipy pin slightly on linux-64 for tensorflow-base 2.8.2
    # to match linux-aarch64, to facilitate intel/arm version alignment.
    if name.startswith("tensorflow-base") and version == "2.8.2" and subdir == 'linux-64':
        for i, dep in enumerate(depends):
            if dep == "scipy >=1.7.3":
                depends[i] = "scipy >=1.7.1"
                break

    # Tensorflow numpy incompatibilites
    if name.startswith("tensorflow-base"):
        if VersionOrder(version) <= VersionOrder("2.6.0"):
            replace_dep(depends, "numpy >=1.20", "numpy >=1.20,<2.0a0")
        if VersionOrder(version) <= VersionOrder("2.5.0"):
            replace_dep(depends, "numpy >=1.16.6,<2.0a0", "numpy >=1.16.6,<1.24.0a0")

    ##############
    # versioneer #
    ##############

    if name == "versioneer" and record["license_family"].upper() == "NONE":
        record["license_family"] = "PUBLIC-DOMAIN"

    ##############
    # constrains #
    ##############

    # setuptools should not appear in both depends and constrains
    # https://github.com/conda/conda/issues/9337
    if name == "conda" and "setuptools >=31.0.1" in constrains:
        constrains[:] = [req for req in constrains if not req.startswith("setuptools")]

    # basemap is incompatible with proj/proj4 >=6
    # https://github.com/ContinuumIO/anaconda-issues/issues/11590
    # Adding update to constraint to capture data reorg in the project.
    if name == "basemap" and VersionOrder(version) < VersionOrder("1.3.0"):
        record["constrains"] = ["proj4 <6", "proj <6"]

    # 'cryptography' + pyopenssl incompatibility 28 Feb 2023 #
    if name == "cryptography" and VersionOrder(version) >= VersionOrder("39.0.1"):
        # or pyopenssl should have a max cryptography version set
        record["constrains"] = ["pyopenssl >=23.0.0"]

    # intel-openmp requires newer glibc.
    if name == "intel-openmp" and version == "2025.0.0":
        replace_dep(constrains, "__glibc >=2.17", "__glibc >=2.26")

    ############
    # features #
    ############

    if subdir.startswith("win-"):
        _replace_vc_features_with_vc_pkg_deps(name, record, depends)

    ##################
    # track_features #
    ##################

    # reset dependencies for nomkl to the blas metapkg and remove any
    #      track_features (these are attached to the metapkg instead)
    if name == "nomkl" and not subdir.startswith("win-"):
        record["depends"] = ["blas * openblas"]
        if "track_features" in record:
            record["track_features"] = ""

    if record.get("track_features"):
        for feat in record["track_features"].split():
            if feat.startswith(("rb2", "openjdk")):
                xtractd = record["track_features"] = _extract_track_feature(
                    record, feat
                )
                record["track_features"] = xtractd

    #############################################
    # anaconda, conda, conda-build, constructor #
    #############################################

    # Remove new shortcut packages from Navigator panel until they are ready
    if name in [
        "anconda_prompt",
        "anaconda_powershell_prompt",
    ]:
        if "app_entry" in record:
            del record["app_entry"]
        if "app_type" in record:
            del record["app_type"]
        if record.get("type") == "app":
            del record["type"]

    if (
        name == "anaconda"
        and version == "custom"
        and not any(d.startswith("_anaconda_depends") for d in depends)
    ):
        depends.append("_anaconda_depends")

    if name == "anaconda" and version in ["5.3.0", "5.3.1"]:
        mkl_version = [
            i for i in depends if i.split()[0] == "mkl" and "2019" in i.split()[1]
        ]
        if len(mkl_version) == 1:
            depends.remove(mkl_version[0])
            depends.append("mkl 2018.0.3 1")
        elif len(mkl_version) > 1:
            raise Exception("Found multiple mkl entries, expected only 1.")

    if name == "conda-build" and version.startswith("3.18"):
        for i, dep in enumerate(depends):
            parts = dep.split()
            if parts[0] == "conda" and "4.3" in parts[1]:
                depends[i] = "conda >=4.5"
        # CPH 1.5 has a statically linked libarchive and doesn't depend on python-libarchive-c
        #    we were implicitly depending on it, and it goes missing.
        if "python-libarchive-c" not in depends:
            depends.append("python-libarchive-c")

    if name == "conda-build":
        for i, dep in enumerate(depends):
            dep_name, *other = dep.split()
            # Jinja 3.0.0 introduced behavior changes that broke certain
            # conda-build templating functionality.
            if dep_name == "jinja2":
                depends[i] = "jinja2 !=3.0.0"

            # Deprecation removed in conda 4.13 break older conda-builds
            if VersionOrder(version) <= VersionOrder("3.21.8") and dep_name == "conda":
                depends[i] = "{} {}<4.13.0".format(
                    dep_name, other[0] + "," if other else ""
                )

            # Deprecations removed in conda 24.3.0 break conda-build <24.3.0.
            # Note that we don't want to affect conda-build <=3.21.8
            if (
                dep_name == "conda" and
                VersionOrder(version) > VersionOrder("3.21.8") and
                VersionOrder(version) < VersionOrder("24.3.0")
            ):
                depends[i] = "{} {}<24.3.0".format(
                    dep_name, other[0] + "," if other else ""
                )

            # Avoid issue on Windows where an old menuinst 1.x is allowed in the environment
            # and breaks the JSON validation with a failed import
            if dep_name == "menuinst" and VersionOrder(version) <= VersionOrder("3.28.1"):
                depends[i] = "menuinst >=2.0.1"

            # API changes in py-lief 0.15 affect conda-build <25.3.0
            # https://github.com/conda/conda-build/blob/main/CHANGELOG.md#2530-2025-03-17
            if dep_name == "py-lief" and VersionOrder(version) < VersionOrder("25.3.0"):
                depends[i] = "py-lief <0.15"

    if name == "constructor":
        if int(version[0]) < 3:
            replace_dep(depends, "conda", "conda <4.6.0a0")
        if VersionOrder("3.2") <= VersionOrder(version) <= VersionOrder("3.3.1"):
            # Pin nsis on recent versions of constructor
            # https://github.com/conda/constructor/issues/526
            replace_dep(depends, "nsis >=3.01", "nsis 3.01")
        # conda 23.1 broke constructor
        # https://github.com/conda/constructor/pull/627
        if record.get("timestamp", 0) <= 1674637311000:
            replace_dep(depends, "conda >=4.6", "conda >=4.6,<23.1.0a0")

    # libarchive 3.3.2 and 3.3.3 build 0 are missing zstd support.
    # De-prioritize these packages with a track_feature (via _low_priority)
    # so they are not installed unless explicitly requested
    if name == "libarchive" and (
        version == "3.3.2" or (version == "3.3.3" and build_number == 0)
    ):
        depends.append("_low_priority")

    if name == 'anaconda-cloud-auth':
        if re.match(r'0\.1\.[2-3](?!\d)', version):  # = 0.1.2* or = 0.1.3*
            bisect.insort_left(depends, 'jaraco.classes =3')
        if VersionOrder(version) < VersionOrder("0.5.1"):
            record["constrains"] = ["conda >=23.9.0"]

    # In anaconda-cli-base 0.3.0 the plugin structure changed and this package
    # is no longer utilized. Updating pins here to avoid this package being installed
    # alongside the new plugin implementation.
    if name == 'anaconda-cloud-cli':
        if re.match(r'0\.1\.0(?!\d)', version):  # = 0.1.0*
            replace_dep(depends, 'anaconda-cli-base', 'anaconda-cli-base <0.3.0')
            replace_dep(depends, 'anaconda-cloud-auth', 'anaconda-cloud-auth <0.6.0')
        if re.match(r'0\.2\.0(?!\d)', version):  # = 0.2.0*
            replace_dep(depends, 'anaconda-cli-base >=0.2', 'anaconda-cli-base >=0.2,<0.3')
            replace_dep(depends, 'anaconda-cloud-auth >=0.3', 'anaconda-cloud-auth >=0.3,<0.6')
            replace_dep(depends, 'anaconda-client >=1.12.2', 'anaconda-client >=1.12.2,<1.13')

    if name == 'anaconda-client':
        if re.match(r'1\.(?:\d|1[01])\.', version):  # < 1.12.0
            if replace_dep(depends, 'urllib3 >=1.26.4', 'urllib3 >=1.26.4,<2.0.0a') == '=':  # if no changes
                depends.append('urllib3 <2.0.0a')

    if name == 'anaconda-navigator':
        version_order = VersionOrder(version)

        if version_order < VersionOrder('2.3.0'):
            replace_dep(depends, ['pyqt >=5.6,<6.0a0', 'pyqt >=5.6', 'pyqt'], 'pyqt >=5.6,<5.15')

        if version_order < VersionOrder('2.4.0'):
            replace_dep(depends, 'conda', 'conda <22.11.0', append=True)

        if version.startswith('2.4.0'):  # = 2.4.0*
            replace_dep(depends, ['conda', 'conda !=22.11.*'], 'conda <23.5.0,!=22.11.*')

        if re.match(r'2\.4\.[1-3](?!\d)', version):  # = 2.4.1* or = 2.4.2* or = 2.4.3*
            replace_dep(
                depends,
                ['conda', 'conda !=22.11.*', 'conda !=22.11.*,!=23.7.0,!=23.7.1'],
                'conda !=22.11.*,!=23.7.0,!=23.7.1,!=23.7.2,!=23.7.3',
            )

        if version_order <= VersionOrder('2.6.3'):
            replace_dep(depends, 'anaconda-cloud-auth', 'anaconda-cloud-auth <0.7.0')
            replace_dep(depends, 'anaconda-cloud-auth >=0.1.3', 'anaconda-cloud-auth >=0.1.3,<0.7.0')
            replace_dep(depends, 'anaconda-cloud-auth >=0.4.1', 'anaconda-cloud-auth >=0.4.1,<0.7.0')
        elif version_order < VersionOrder('2.6.5'):
            replace_dep(depends, 'anaconda-cloud-auth >=0.7.1', 'anaconda-cloud-auth >=0.7.1,<0.8.0')

    if name in ('aext-assistant-server', 'aext-shared', 'anaconda-toolbox'):
        version_order = VersionOrder(version)
        if version_order <= VersionOrder('4.0.15'):
            replace_dep(depends, 'anaconda-cloud-auth', 'anaconda-cloud-auth <0.7.0')
            replace_dep(depends, 'anaconda-cloud-auth >=0.1.3', 'anaconda-cloud-auth >=0.1.3,<0.7.0')
            replace_dep(depends, 'anaconda-cloud-auth >=0.4.1', 'anaconda-cloud-auth >=0.4.1,<0.7.0')
    if name in ('aext-assistant-server', 'aext-shared', 'anaconda-toolbox',
                'aext-share-notebook-server', 'aext-core', 'aext-panels',
                'aext-panels-server', 'aext-project-filebrowser-server', 'aext-share-notebook'):
        version_order = VersionOrder(version)
        if version_order > VersionOrder('4.0.15') and version_order <= VersionOrder('4.1.0'):
            replace_dep(depends, 'anaconda-cloud-auth >=0.7.1', 'anaconda-cloud-auth >=0.7.1,!=0.8.2')

    if name == "conda-content-trust" and VersionOrder(version) <= VersionOrder("0.1.3"):
        replace_dep(depends, "cryptography", "cryptography <41.0.0a0")

    ########################
    # run_exports mis-pins #
    ########################

    # openssl 1.1.1 uses funnny version numbers, 1.1.1, 1.1.1a, 1.1.1b, etc
    # openssl >=1.1.1,<1.1.2.0a0 -> >=1.1.1a,<1.1.2a
    replace_dep(depends, "openssl >=1.1.1,<1.1.2.0a0", "openssl >=1.1.1a,<1.1.2a")

    # openssl3 preventive measures
    replace_dep(depends, "openssl !=1.1.1e", "openssl !=1.1.1e,<1.1.2a")
    replace_dep(constrains, "openssl !=1.1.1e", "openssl !=1.1.1e,<1.1.2a")
    replace_dep(constrains, "openssl >=1.1.1k", "openssl >=1.1.1k,<1.1.2a")
    if name != "_anaconda_depends":
        replace_dep(depends, "openssl", "openssl <1.1.2a")

    # kealib 1.4.8 changed sonames, add new upper bound to existing packages
    replace_dep(depends, "kealib >=1.4.7,<1.5.0a0", "kealib >=1.4.7,<1.4.8.0a0")
    # Other broad replacements
    for i, dep in enumerate(depends):
        # glib is compatible up to the major version
        if dep.startswith("glib >="):
            depends[i] = dep.split(",")[0] + ",<3.0a0"

        # zstd has been more or less ABI compatible in the 1.4.x releases.
        # `ZSTD_getSequences` is the only symbol reported as being removed
        # between 1.4.0 and 1.5.0, but as far as we can tell, none of our
        # (linux-64) packages actually use it.
        if dep.startswith("zstd >=1.4."):
            depends[i] = dep.split(",")[0] + ",<1.5.0a0"

        # curl >=8.0.0 is not actually a major upgrade
        if dep.startswith("libcurl >=7.") or dep.startswith("curl >=7."):
            depends[i] = dep.split(",")[0] + ",<9.0a0"

    # libffi broke ABI compatibility in 3.3
    if name not in LIBFFI_HOTFIX_EXCLUDES and (
        "libffi >=3.2.1,<4.0a0" in depends or "libffi" in depends
    ):
        if "libffi >=3.2.1,<4.0a0" in depends:
            libffi_idx = depends.index("libffi >=3.2.1,<4.0a0")
        else:
            libffi_idx = depends.index("libffi")
        depends[libffi_idx] = "libffi >=3.2.1,<3.3a0"

    replace_dep(depends, "libnetcdf >=4.6.1,<5.0a0", "libnetcdf >=4.6.1,<4.7.0a0")

    # ZeroMQ DLL includes patch number in DLL name, which limits the upper bound
    if subdir.startswith("win-"):
        replace_dep(depends, "zeromq >=4.3.1,<4.4.0a0", "zeromq >=4.3.1,<4.3.2.0a0")

    # Up to libtiff 4.4.0, the LIBTIFF_CURRENT version was 13, and LIBTIFF_AGE was 8.
    # As of 4.5.0, LIBTIFF_CURRENT was decremented to 6, and LIBTIFF_AGE was reset.
    # This change has major implications for Mach-O dynamic libraries on MacOS.
    # We applied set_configure_script_version.patch in v4.5.0 to fix the issue.
    # In v4.7.0 we removed that patch, so we have to constrain libtiff at runtime to <4.7.0.
    replace_dep(depends, "libtiff >=4.0.8,<5.0a0", "libtiff >=4.0.8,<4.7.0")
    replace_dep(depends, "libtiff >=4.0.9,<5.0a0", "libtiff >=4.0.9,<4.7.0")
    replace_dep(depends, "libtiff >=4.0.10,<5.0a0", "libtiff >=4.0.10,<4.7.0")
    replace_dep(depends, "libtiff >=4.1.0,<5.0a0", "libtiff >=4.1.0,<4.7.0")
    replace_dep(depends, "libtiff >=4.2.0,<5.0a0", "libtiff >=4.2.0,<4.7.0")
    replace_dep(depends, "libtiff >=4.5.0,<5.0a0", "libtiff >=4.5.0,<4.7.0")
    replace_dep(depends, "libtiff >=4.5.1,<5.0a0", "libtiff >=4.5.1,<4.7.0")

    ##########################
    # single package depends #
    ##########################

    # https://github.com/ContinuumIO/anaconda-issues/issues/11315
    if subdir.startswith("win") and name == "jupyterlab" and "pywin32" not in depends:
        depends.append("pywin32")

    # pyqt needs an upper limit of sip, build 2 has this already
    if name == "pyqt" and version == "5.9.2":
        replace_dep(depends, "sip >=4.19.4", "sip >=4.19.4,<=4.19.8")

    # three pyqt packages were built against sip 4.19.13
    # first filename is linux-64, second is win-64 and win-32
    if fn in ["pyqt-5.9.2-py38h05f1152_4.tar.bz2", "pyqt-5.9.2-py38ha925a31_4.tar.bz2"]:
        sip_index = [dep.startswith("sip") for dep in depends].index(True)
        depends[sip_index] = "sip >=4.19.13,<=4.19.14"

    if fn == "dask-2.7.0-py_0.tar.bz2":
        for i, dep in enumerate(depends):
            if dep.startswith("python "):
                depends[i] = "python >=3.6"

    if fn == "dask-core-2.7.0-py_0.tar.bz2":
        depends[:] = ["python >=3.6"]

    if name == "dask-core" and version == "2021.3.1" and build_number == 0:
        depends[:] = [
            "python >=3.7",
            "cloudpickle >=1.1.1",
            "fsspec >=0.6.0",
            "partd >=0.3.10",
            "pyyaml",
            "toolz >=0.8.2",
        ]
    if name == "dask" and version == "2021.3.1" and build_number == 0:
        depends[:] = ["python >=3.7", "numpy >=1.16"] + [
            d
            for d in depends
            if d.split(" ")[0]
            not in ("python", "cloudpickle", "fsspec", "numpy", "partd", "toolz")
        ]
        depends.sort()

    # sparkmagic <=0.12.7 has issues with ipykernel >4.10
    # see: https://github.com/AnacondaRecipes/sparkmagic-feedstock/pull/3
    if name == "sparkmagic" and version in ["0.12.1", "0.12.5", "0.12.6", "0.12.7"]:
        replace_dep(depends, "ipykernel >=4.2.2", "ipykernel >=4.2.2,<4.10.0")

    # sparmagic has issues with pandas >=2
    # see: https://github.com/jupyter-incubator/sparkmagic/pull/812
    if name == "sparkmagic" and VersionOrder(version) < VersionOrder("0.20.5"):
        replace_dep(depends, "pandas >=0.17.1", "pandas >=0.17.1,<2.0.0")

    # notebook <5.7.6 will not work with tornado 6, see:
    # https://github.com/jupyter/notebook/issues/4439
    # notebook <7 will not work with pyzmq>=25 and jupyter_client>=8, see:
    # https://github.com/jupyter/notebook/pull/6749
    if name == "notebook":
        replace_dep(depends, "tornado >=4", "tornado >=4,<6")
        if int(version.split('.', 1)[0]) < 7:
            replace_dep(depends, "pyzmq >=17", "pyzmq >=17,<25")
            replace_dep(depends, "jupyter_client >=5.3.4", "jupyter_client >=5.3.4,<8")
            replace_dep(depends, "jupyter_client >=5.2.0", "jupyter_client >=5.2.0,<8")
            replace_dep(depends, "jupyter_client", "jupyter_client <8")

    # no cross-compatibility possible between Notebook 6 and 7 extensions
    if name == "nb_conda" and VersionOrder(version) <= VersionOrder("2.2.1"):
        replace_dep(depends, "notebook >=4.3.1", "notebook >=4.3.1,<7")
    if name == "nb_conda_kernels" and VersionOrder(version) <= VersionOrder("2.3.1"):
        replace_dep(depends, "notebook >=4.2.0", "notebook >=4.2.0,<7")

    # requests-toolbelt<1.0.0 does not support urllib3>=2.0.0 (which is an indirect dependency)
    # issue: https://github.com/Anaconda-Platform/anaconda-client/issues/654#issuecomment-1655089483
    if (name == 'requests-toolbelt') and version.startswith('0.'):
        depends.append('urllib3 <2.0.0a')

    # spyder 4.0.0 and 4.0.1 should include a lower bound on psutil of 5.2
    # and should pin parso to 0.5.2.
    # https://github.com/conda-forge/spyder-feedstock/pull/73
    # https://github.com/conda-forge/spyder-feedstock/pull/74
    if name == "spyder" and version in ["4.0.0", "4.0.1"]:
        add_parso_dep = True
        for idx, dep in enumerate(depends):
            if dep.startswith("parso"):
                add_parso_dep = False
            if dep.startswith("psutil"):
                depends[idx] = "psutil >=5.2"
            # spyder-kernels needs to be pinned to <=1.9.0, see:
            # https://github.com/conda-forge/spyder-feedstock/pull/76
            if dep.startswith("spyder-kernels"):
                depends[idx] = "spyder-kernels >=1.8.1,<1.9.0"
        if add_parso_dep:
            depends.append("parso 0.5.2.*")

    #  spyder 4.2.4 should have an upper bound on qdarkstyle and requires a newer qtconsole.
    if name == "spyder" and version == "4.2.4":
        replace_dep(depends, "qdarkstyle >=2.8", "qdarkstyle >=2.8,<3.0")
        replace_dep(depends, "qtconsole >=5.0.1", "qtconsole >=5.0.3")

    # spyder 5.0 new dependencies were not properly captured in our recipe
    if name == "spyder-kernels" and version == "2.0.1":
        replace_dep(depends, "ipykernel >=5.1.3", "ipykernel >=5.3.0")
    if name == "spyder" and version == "5.0.0":
        replace_dep(depends, "qdarkstyle >=2.8,<3.0", "qdarkstyle 3.0.2.*")
        replace_dep(
            depends, "spyder-kernels >=1.10.2,<1.11.0", "spyder-kernels >=2.0.1,<2.1.0"
        )
        depends.append("qstylizer >=0.1.10")
        depends.append("cookiecutter >=1.6.0")
        depends.sort()

    # IPython >=7,<7.10 should have an upper bound on prompt_toolkit
    if name == "ipython" and version.startswith("7."):
        replace_dep(depends, "prompt_toolkit >=2.0.0", "prompt_toolkit >=2.0.0,<3")

    # IPython has an upper bound on jedi; see conda-forge/ipython-feedstock#127
    if name == "ipython":
        replace_dep(depends, "jedi >=0.10", "jedi >=0.10,<0.18")

    # jupyter_console 5.2.0 has bounded dependency on prompt_toolkit
    if name == "jupyter_console" and version == "5.2.0":
        replace_dep(depends, "prompt_toolkit", "prompt_toolkit >=1.0.0,<2")

    # jupyter_client 6.0.0 should have lower bound of 3.5 on python
    if name == "jupyter_client" and version == "6.0.0":
        replace_dep(depends, "python", "python >=3.5")

    # numba 0.46.0 and 0.47.0 are missing a dependency on setuptools
    # https://github.com/numba/numba/issues/5134
    if name == "numba" and version in ["0.46.0", "0.47.0"]:
        depends.append("setuptools")

    # numba 0.54.0 0.54.1 0.55.0 have the wrong numpy bounds set
    # see https://github.com/numba/numba/blob/0.54.0/numba/__init__.py#L135
    # see https://github.com/numba/numba/blob/0.54.1/numba/__init__.py#L135
    # see https://github.com/numba/numba/blob/0.55.0/numba/__init__.py#L137
    if name == "numba" and version in ("0.54.0", "0.54.1"):
        record["constrains"] = ["numpy >=1.17,<1.21.0a0"]
    if name == "numba" and version == "0.55.0":
        record["constrains"] = ["numpy >=1.18,<1.22.0a0"]

    # python-language-server should contrains ujson <=1.35
    # see https://github.com/conda-forge/cf-mark-broken/pull/20
    # https://github.com/conda-forge/python-language-server-feedstock/pull/48
    if name == "python-language-server" and version in ["0.31.2", "0.31.7"]:
        replace_dep(depends, "ujson", "ujson <=1.35")

    # pylint 2.5.0 build 0 had incorrect astroid pinning and were missing a
    # dependency on toml >=0.7.1
    if name == "pylint" and version == "2.5.0" and build_number == 0:
        replace_dep(depends, "astroid >=2.3.0,<2.4", "astroid >=2.4.0,<2.5")
        if "toml >=0.7.1" not in depends:
            depends.append("toml >=0.7.1")

    # flask <1.0 should pin werkzeug to <1.0.0
    if name == "flask" and version[0] == "0":
        replace_dep(depends, "werkzeug", "werkzeug <1.0.0")
        replace_dep(depends, "werkzeug >=0.7", "werkzeug >=0.7,<1.0.0")

    # if flask is 1.x is not compatible with the newest versions of
    # some dependencies. Hotfix to pin according to pinnings in v1.1.4:
    # https://github.com/pallets/flask/blob/1.1.4/setup.py#L55-L60
    # Version 1.1.4 will be maintained in a separate branch:
    # https://github.com/AnacondaRecipes/flask-feedstock/tree/main-1.1.x
    if name == "flask" and version[0] == "1" and int(version[-1]) < 4:
        # the two next lines are commented as they break older anaconda distributions (2022.05)
        # replace_dep(depends, "click >=5.1", "click >=5.1,<8.0")
        # replace_dep(depends, "itsdangerous >=0.24", "itsdangerous >=0.24,<2.0")
        replace_dep(depends, "jinja2 >=2.10.1", "jinja2 >=2.10.1,<3.0")
        replace_dep(depends, "jinja2 >=2.10", "jinja2 >=2.10,<3.0")
        replace_dep(depends, "werkzeug >=0.14", "werkzeug >=0.15,<2.0")

    # package found the freetype library in the build enviroment rather than
    # host but used the host run_export: freetype >=2.9.1,<3.0a0
    if subdir == "osx-64" and fn == "harfbuzz-2.4.0-h831d699_0.tar.bz2":
        replace_dep(depends, "freetype >=2.9.1,<3.0a0", "freetype >=2.10.2,<3.0a0")

    # sympy 1.6 and 1.6.1 are missing fastcache and gmpy2 depends
    if name == "sympy" and version in ["1.6", "1.6.1"]:
        depends.append("fastcache")
        depends.append("gmpy2 >=2.0.8")

    if name == "pytest-openfiles" and version == "0.5.0":
        depends[:] = ["psutil", "pytest >=4.6", "python >=3.6"]

    if name == "pytest-doctestplus" and version == "0.7.0":
        depends[:] = ["numpy >=1.10", "pytest >=4.0", "python >=3.6"]

    # astropy 4.2 bumped the minimum version of numpy required; the recipe was
    # updated to reflect this, but older 4.2 build need their metadata patched.
    if name == "astropy" and version == "4.2":
        depends[:] = [d for d in depends if not d.startswith("numpy ")]
        depends.append("numpy >=1.17.0,<2.0a0")
        depends.sort()

    # some builds of gitpyhon 3.1.17 list the wrong dependencies
    if name == "gitpython" and version in ("3.1.17", "3.1.18"):
        depends[:] = ["gitdb >=4.0.1,<5", "python >=3.5", "typing-extensions >=3.7.4.0"]

    # click >=8.0 is actually Python 3.6+
    if name == "click" and int(version.split(".", 1)[0]) >= 8:
        replace_dep(depends, "python", "python >=3.6")

    # click-repl <0.2.0 incompatible with click >=8.0
    # See: https://github.com/click-contrib/click-repl/pull/76
    if name == "click-repl" and version.startswith("0.1."):
        replace_dep(depends, "click", "click <8.0")

    # tifffile 2021.3.31 requires Python >=3.7, imagecodecs >=2021.3.31
    if name == "tifffile" and version == "2021.3.31":
        replace_dep(depends, "python >=3.6", "python >=3.7")
        replace_dep(depends, "imagecodecs", "imagecodecs >=2021.3.31")

    # Panel<0.11.0 requires Bokeh<2.3
    if name == "panel":
        ver_parts = version.split(".")
        if int(ver_parts[0]) == 0 and int(ver_parts[1]) < 11:
            for i, dep in enumerate(depends):
                if dep.startswith("bokeh >=2."):
                    depends[i] = dep.split(",")[0] + ",<2.3"
                if dep.startswith("bokeh >=1."):
                    depends[i] = dep.split(",")[0] + ",<2.0.0a0"

    # Param 2.0 to be released in October 2023 with breaking changes that make
    # incompatible many old versions of the HoloViz packages. Pinning them
    # all to <2.0.0a0.
    # Package name to the last version not pinning Param (either >2 or <2)
    # correctly.
    _holoviz_version_mapping = dict(
        panel='1.2.3',
        holoviews='1.17.1',
        hvplot='0.8.4',
        datashader='0.15.2',
        geoviews='1.10.1',
    )
    if name in _holoviz_version_mapping:
        for _holoviz_pkg, _holoviz_version in _holoviz_version_mapping.items():
            if name != _holoviz_pkg:
                continue
            if VersionOrder(version) > VersionOrder(_holoviz_version):
                continue
            for i, dep in enumerate(depends):
                if not dep.startswith("param"):
                    continue
                if "<2" in dep:
                    continue
                if "," not in dep:
                    if "<=2" in dep or "<=3" in dep:
                        # e.g. param <=2 or param <=3
                        depends[i] = dep.split("<=")[0] + "<2.0.0a0"
                    elif "<" in dep:
                        # e.g. param <3
                        depends[i] = dep.split("<")[0] + "<2.0.0a0"
                    elif ">" not in dep:
                        # e.g. param
                        depends[i] = dep + " <2.0.0a0"
                    elif ">" in dep:
                        # e.g. param >1 or param >=1
                        depends[i] = dep + ",<2.0.0a0"
                else:
                    # e.g. param >1,<3
                    depends[i] = dep.split(",")[0] + ",<2.0.0a0"

    # distributed requires `dask-core`, not `dask`. This requirement also
    # became much stricter with the upstream 2021.5.0 release.
    # see how it was fixed for 2021.5.1:
    #   https://github.com/AnacondaRecipes/distributed-feedstock/blob/master/recipe/meta.yaml
    if name == "distributed":
        if version == "2021.5.0":
            replace_dep(depends, "dask >=2021.04.0", "dask-core 2021.5.0.*")
        if version == "2021.4.1":
            replace_dep(depends, "dask >=2021.3.0", "dask-core >=2021.3.0")

    # aiobotocore 1.2.2 needs botocore >=1.19.52,<1.19.53
    if name == "aiobotocore" and version.startswith("1.2."):
        replace_dep(depends, "botocore", "botocore >=1.19.52,<1.19.53")

    # pyjwt 2.1.0 has incorrect depends/constrains on cryptography
    if name == "pyjwt" and version == "2.1.0":
        depends[:] = list(d for d in depends if not d.startswith("cryptography "))
        record["constrains"] = ["cryptography >=3.3.1,<4.0.0"]

    if name == "pyerfa" and version == "2.0.0":
        replace_dep(depends, "numpy >=1.17", "numpy >=1.20.2,<2.0a0")

    # Possible bug in conda solver, wherein run constrains seem to completely
    # override version requirements in `depends`.  This results in users being
    # able to (e.g.) install the Py3.9 build in Py3.7 or Py3.8 environments.
    if name == "pandas" and version == "1.3.0":
        constrains.clear()
        # Still to set lower bound on compatible Py3.7 interpreters
        if record["build"].startswith("py37"):
            for i, dep in enumerate(depends):
                if dep.startswith("python "):
                    depends[i] = "python >=3.7.1,<3.8.0a0"

    if name == "conda" and version in ("22.11.0", "22.11.1"):
        # exclude all pre-plugin-system libmambapy/conda-libmamba-solver
        constrains[:] = [
            dep
            for dep in constrains
            if not dep.startswith("conda-libmamba-solver")
        ] + ["conda-libmamba-solver >=22.12.0"]
        replace_dep(
            depends, "ruamel.yaml >=0.11.14,<0.17", "ruamel.yaml >=0.11.14,<0.18"
        )

    if name == "conda" and version == "23.9.0":
        constrains[:] = [
            dep
            for dep in constrains
            if not dep.startswith("conda-build ")
        ] + ["conda-build >=3.27"]

    # Add run constraint for conda to fix plugin here:
    # https://github.com/anaconda/conda-anaconda-telemetry/issues/87
    # https://github.com/anaconda/conda-anaconda-telemetry/pull/96
    # https://github.com/anaconda/conda-anaconda-telemetry/issues/127
    if name in ("conda", "conda-build") and VersionOrder(version) >= VersionOrder("24.11.0"):
        constrains[:] = [
            dep
            for dep in constrains
            if not dep.startswith("conda-anaconda-telemetry ")
        ] + ["conda-anaconda-telemetry >=0.2.0"]

    # Add run constraint for conda to require conda-anaconda-tos
    # with the lowest possible version of conda that is compatible with the current version
    # of conda-anaconda-tos
    if name == "conda" and VersionOrder(version) >= VersionOrder("24.11.0"):
        constrains[:] = [
            dep
            for dep in constrains
            if not dep.startswith("conda-anaconda-tos ")
        ] + ["conda-anaconda-tos >=0.2.1"]

    if name == "conda-libmamba-solver":
        # libmambapy 0.23 introduced breaking changes
        replace_dep(depends, "libmambapy >=0.22.1", "libmambapy 0.22.*")
        if version == "22.6.0":
            # conda 4.13 needed for the user agent strings
            replace_dep(depends, "conda >=4.12", "conda >=4.13")
        # conda 22.11 introduces the plugin system
        replace_dep(depends, "conda >=4.13", "conda >=4.13,<22.11.0a")
        # conda 23.1 changed an internal SubdirData API needed for S3/FTP channels
        if VersionOrder(version) < VersionOrder("23.1.0a0"):
            # https://github.com/conda/conda-libmamba-solver/issues/132
            replace_dep(depends, "conda >=22.11.0", "conda >=22.11.0,<23.1.0a")
        # conda 23.3 changed an internal SubdirData API needed with S3/FTP channels
        # conda deprecated Boltons leading to a breakage in the solver api interface
        if VersionOrder(version) < VersionOrder("23.2.0a0"):
            # https://github.com/conda/conda-libmamba-solver/issues/153
            # https://github.com/conda/conda-libmamba-solver/issues/152
            replace_dep(depends, "conda >=22.11.0", "conda >=22.11.0,<23.2.0a")
        if VersionOrder(version) < VersionOrder("24.7.0a0"):
            # https://github.com/conda/conda-libmamba-solver/pull/492
            replace_dep(depends, "libmambapy >=1.5.6", "libmambapy >=1.5.6,<2.0.0a0")
            replace_dep(depends, "libmambapy >=1.5.3", "libmambapy >=1.5.3,<2.0.0a0")
            replace_dep(depends, "libmambapy >=1.5.1", "libmambapy >=1.5.1,<2.0.0a0")
            replace_dep(depends, "libmambapy >=1.4.1", "libmambapy >=1.4.1,<2.0.0a0")
            replace_dep(depends, "libmambapy >=1.0.0", "libmambapy >=1.0.0,<2.0.0a0")
            replace_dep(depends, "libmambapy >=0.23", "libmambapy >=0.23,<2.0.0a0")
            replace_dep(depends, "libmambapy >=0.22.1", "libmambapy >=0.22.1,<2.0.0a0")

    if name == "conda-token" and VersionOrder(version) < VersionOrder("0.5.0"):
        replace_dep(depends, "conda >=4.3", "conda >=4.3,<23.9")

    # snowflake-snowpark-python cloudpickle pins
    if name == "snowflake-snowpark-python" and version == '0.6.0':
        replace_dep(depends, 'cloudpickle >=1.6.0', 'cloudpickle >=1.6.0,<=2.0.0')

    # s3fs downgraded to the last version not requiring botocore.
    # ref dask/dask#10397
    if name == "s3fs" and VersionOrder(version) <= VersionOrder("0.4.2"):
        replace_dep(depends, "python", "python <3.9")
        replace_dep(depends, "python >=3.5", "python >=3.5,<3.9")
        replace_dep(depends, "python >=3.6", "python >=3.6,<3.9")

    # This targets an errant version on the osx-arm64 subdir
    # REMOVE after ffmpeg is updated from 4.2.2.
    if name == "ffmpeg" and version == "4.2.2":
        depends[:] = [d for d in depends if not d.startswith("openssl")]

    # anaconda-ident<0.2 not compatible with anaconda-anon-usage
    # anaconda-anon-usage<0.4 not compatible with anaconda-ident
    # anaconda-ident<0.6 not compatible with anaconda-ident >=0.7.2
    if name == "anaconda-ident":
        if VersionOrder(version) < VersionOrder("0.2"):
            record["constrains"] = ["anaconda-anon-usage <0"]
        replace_dep(depends, "anaconda-anon-usage >=0.4.1,<1", "anaconda-anon-usage >=0.4.1,<0.7.2")
        replace_dep(depends, "anaconda-anon-usage >=0.6.1,<1", "anaconda-anon-usage >=0.6.1,<0.7.2")
    if name == "anaconda-anon-usage":
        if VersionOrder(version) < VersionOrder("0.4"):
            record["constrains"] = ["anaconda-ident <0"]
        if VersionOrder(version) < VersionOrder("0.7.2"):
            record["constrains"] = ["anaconda-ident <0.6.0"]

    # orange3 pandas 2.1 error
    if name == "orange3" and VersionOrder(version) < VersionOrder("3.36.0"):
        replace_dep(depends, "pandas", "pandas >=1.3.0,<2")
        replace_dep(depends, "pandas >=1.3.0", "pandas >=1.3.0,<2")
        replace_dep(depends, "pandas >=1.3.0,!=1.5.0", "pandas >=1.3.0,!=1.5.0,<2")

    # ray-core needs async-timeout
    if name == "ray-core" and VersionOrder(version) < VersionOrder("2.6.4"):
        if not any(_.startswith("async-timeout") for _ in depends):
            depends.append("async-timeout")

    # poppler 24.09.0 incompatibility
    if (name == "graphviz" and VersionOrder(version) < VersionOrder("2.50.0") or
            (version == "2.50.0" and build_number < 2)):
        replace_dep(depends, "poppler", "poppler <=22.12.0")
    if (name in ["libgdal", "libgdal-arrow-parquet"] and VersionOrder(version) < VersionOrder("3.6.2") or
            (version == "3.6.2" and build_number < 7)):
        replace_dep(depends, "poppler", "poppler <=22.12.0")
    if (name == "python-poppler" and VersionOrder(version) < VersionOrder("0.4.1") or
            (version == "0.4.1" and build_number < 1)):
        replace_dep(depends, "poppler", "poppler <=22.12.0")
    if (name == "r-pdftools" and VersionOrder(version) < VersionOrder("3.4.0") or
            (version == "3.4.0" and build_number < 1)):
        replace_dep(depends, "poppler", "poppler <=22.12.0")

    # libarchive 3.7.5 abi breaking change - https://github.com/libarchive/libarchive/pull/1976
    if (name == "libmamba" and VersionOrder(version) >= VersionOrder("1.5.8") and
            VersionOrder(version) <= VersionOrder("1.5.11")):
        replace_dep(depends, "libarchive >=3.7.4,<3.8.0a0", "libarchive >=3.7.4,<3.7.5.0a0")
    if name == "tesseract" and version == "5.2.0":
        replace_dep(depends, "libarchive >=3.7.4,<3.8.0a0", "libarchive >=3.7.4,<3.7.5.0a0")

    # c-blosc2 2.14.4 abi breaking change - https://github.com/Blosc/c-blosc2/issues/581
    if name in ("pytables", "tables"):
        replace_dep(depends, "c-blosc2 >=2.8.0,<3.0a0", "c-blosc2 >=2.8.0,<2.14.4.0a0")
        replace_dep(depends, "c-blosc2 >=2.10.5,<3.0a0", "c-blosc2 >=2.10.5,<2.14.4.0a0")
        replace_dep(depends, "c-blosc2 >=2.12.0,<3.0a0", "c-blosc2 >=2.12.0,<2.14.4.0a0")

    # https://github.com/conda-incubator/conda-project/issues/183
    if name == "conda-project" and VersionOrder(version) <= VersionOrder("0.4.2"):
        replace_dep(depends, "conda-lock >=2.5.6", "conda-lock >=2.5.6,<3.0.0.0a0")

    ###########################
    # compilers and run times #
    ###########################

    if subdir.startswith("linux-"):
        _fix_linux_runtime_bounds(depends)

    if subdir == "osx-64":
        replace_dep(depends, "libgfortran >=3.0.1", "libgfortran >=3.0.1,<4.0.0.a0")

    # loosen binutils_impl dependency on gcc_impl_ packages
    if name.startswith("gcc_impl_"):
        for i, dep in enumerate(depends):
            if dep.startswith("binutils_impl_"):
                dep_parts = dep.split()
                if len(dep_parts) == 3:
                    correct_dep = "{} >={},<3".format(*dep_parts[:2])
                    depends[i] = correct_dep

    # Add mutex package for libgcc-ng
    if name == "libgcc-ng":
        depends.append("_libgcc_mutex * main")

    # Limit breaks as we transition from CentOS 6 to 7
    if (
        subdir == "linux-64"
        and name in ("libgcc-ng", "libstdcxx-ng", "libgfortran-ng")
        and version in ("7.5.0", "8.4.0", "9.3.0", "11.2.0")
    ):
        # This would probably be better as a `constrains`, but conda's solver
        # currently has issues enforcing virtual package constrains. Making
        # `__glibc` a hard `depends` will almost surely break building
        # cross-platform environments (e.g., via setting `$CONDA_SUBDIR`).
        depends.append("__glibc >=2.17")

    if subdir == "osx-64":
        # fix clang_osx-64 and clangcxx_osx-64 packages to include dependencies, see:
        # https://github.com/AnacondaRecipes/aggregate/pull/164
        if name == "clang_osx-64" and version == "4.0.1" and int(build_number) < 17:
            depends[:] = ["cctools", "clang 4.0.1.*", "compiler-rt 4.0.1.*", "ld64"]
        if name == "clangxx_osx-64" and version == "4.0.1" and int(build_number) < 17:
            depends[:] = ["clang_osx-64 >=4.0.1,<4.0.2.0a0", "clangxx", "libcxx"]

    ###########
    # numpy 2 #
    ###########

    # Numpy 2.0.0 Patch

    # Numpy 2.0.0 hotfix will allow a bulk of packages to be locked to below 2.0.0 as the interoperability
    # between numpy 1.x and 2.x is not guaranteed.

    # This will ensure upper bounds on numpy for all packages that are not confirmed to be compatible with numpy 2.0.0
    if NUMPY_2_CHANGES:
        apply_numpy2_changes(record, subdir, fn)


def replace_dep(depends, old, new, *, append=False):
    """
    Replace an old dependency with a new one.

    :param depends: List of dependencies that should be updated.
    :type depends: list[str]

    :param old: Old dependency(s) that should be replaced with a :code:`new` one.
    :type old: str | Iterable[str]

    :param new: New dependency to use instead of the :code:`old` one.

                If set to :code:`None` - instead of replacing function will remove :code:`old` dependency.
    :type new: str | None

    :param append: Append :code:`new` dependency if it is not already added.
    :type append: bool

    :return: Change status. Might be one of the next values:

             - :code:`'+'` - :code:`new` dependency added to the :code:`depends`.
             - :code:`'-'` - :code:`old` dependency removed from the :code:`depends`.
             - :code:`'~'` - :code:`old` dependency is replaced by the :code:`new`.
             - :code:`'='` - no changes made to the :code:`depends`.

             .. note::

                Single character results were chosen to be able to do such kind of checks:

                 .. code-block:: python

                    if replace_dep(...) in '+=':
                        ...

    :rtype: Literal['+', '-', '~', '=']
    """
    if isinstance(old, str):
        old = [old]
    if append and (new is None):
        raise TypeError('Forbidden to append None to dependencies')

    removed = False
    for item in old:
        if item in depends:
            depends.remove(item)
            removed = True

    if (removed or append) and (new is not None) and (new not in depends):
        bisect.insort_left(depends, new)
        if removed:
            return '~'
        return '+'
    if removed:
        return '-'
    return '='


def _extract_and_remove_vc_feature(record):
    features = record.get("features", "").split()
    vc_features = tuple(f for f in features if f.startswith("vc"))
    if not vc_features:
        return None
    non_vc_features = tuple(f for f in features if f not in vc_features)
    vc_version = int(vc_features[0][2:])  # throw away all but the first
    if non_vc_features:
        record["features"] = " ".join(non_vc_features)
    else:
        del record["features"]
    return vc_version


def _extract_feature(record, feature_name):
    features = record.get("features", "").split()
    features.remove(feature_name)
    return " ".join(features)


def _extract_track_feature(record, feature_name):
    features = record.get("track_features", "").split()
    features.remove(feature_name)
    return " ".join(features)


def do_hotfixes(base_dir):
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

    # Step 2. Create all patch instructions.
    patch_instructions = {}
    for subdir in SUBDIRS:
        instructions = _patch_repodata(repodatas[subdir], subdir)
        patch_instructions_path = join(base_dir, subdir, "patch_instructions.json")
        with open(patch_instructions_path, "w") as fh:
            json.dump(
                instructions, fh, indent=2, sort_keys=True, separators=(",", ": ")
            )
        patch_instructions[subdir] = instructions


def main():
    base_dir = join(dirname(__file__), CHANNEL_NAME)
    do_hotfixes(base_dir)


if __name__ == "__main__":
    sys.exit(main())
