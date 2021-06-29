import fnmatch
import json
import os
import re
import sys
from collections import defaultdict
from os.path import dirname, isdir, isfile, join

import requests

CHANNEL_NAME = "r"
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
        "r-nloptr-1.0.4-r3.2.2_1.tar.bz2",  # dependency on nlopt; only in conda-forge, and has problems of its own
    ),
    "osx-64": (),
    "win-32": (),
    "win-64": (),
    "any": {
        "r-3.[12]*",
        "r-base-3.[12]*",
    }
}

REVOKED = {}

EXTERNAL_DEPENDENCIES = {
    "blas": "global:blas",
    "bwidget": "global:bwidget",
    "bzip2": "global:bzip2",
    "cairo": "global:cairo",
    "cudatoolkit": "global:cudatoolkit",
    "curl": "global:curl",
    "cyrus-sasl": "global:cyrus-sasl",
    "expat": "global:expat",
    "fonts-anaconda": "global:fonts-anaconda",
    "fonts-continuum": "global:fonts-continuum",
    "freeglut": "global:freeglut",
    "freetype": "global:freetype",
    "gcc": "global:gcc",
    "gcc_linux-32": "global:gcc_linux-32",
    "gcc_linux-64": "global:gcc_linux-64",
    "geos": "global:geos",
    "gfortran_linux-32": "global:gfortran_linux-32",
    "gfortran_linux-64": "global:gfortran_linux-64",
    "glib": "global:glib",
    "gmp": "global:gmp",
    "gsl": "global:gsl",
    "gxx_linux-32": "global:gxx_linux-32",
    "gxx_linux-64": "global:gxx_linux-64",
    "icu": "global:icu",
    "ipython-notebook": "python:ipython-notebook",
    "jinja2": "python:jinja2",
    "jpeg": "global:jpeg",
    "jupyter": "python:jupyter",
    "krb5": "global:krb5",
    "libcurl": "global:libcurl",
    "libgcc": "global:libgcc",
    "libgcc-ng": "global:libgcc-ng",
    "libgdal": "global:libgdal",
    "libgfortran-ng": "global:libgfortran-ng",
    "libglu": "global:libglu",
    "libopenblas": "global:libopenblas",
    "libpng": "global:libpng",
    "libssh2": "global:libssh2",
    "libstdcxx-ng": "global:libstdcxx-ng",
    "libtiff": "global:libtiff",
    "libuuid": "global:libuuid",
    "libxgboost": "global:libxgboost",
    "libxml2": "global:libxml2",
    "libxslt": "global:libxslt",
    "make": "global:make",
    "mysql": "global:mysql",
    "ncurses": "global:ncurses",
    "notebook": "python:notebook",
    "openssl": "global:openssl",
    "pandoc": "global:pandoc",
    "pango": "global:pango",
    "pcre": "global:pcre",
    "proj4": "global:proj4",
    "python": "global:python",
    "qt": "global:qt",
    "readline": "global:readline",
    "singledispatch": "python:singledispatch",
    "six": "python:six",
    "tk": "global:tk",
    "tktable": "global:tktable",
    "udunits2": "global:udunits2",
    "unixodbc": "global:unixodbc",
    "xz": "global:xz",
    "zeromq": "global:zeromq",
    "zlib": "global:zlib",
}

NAMESPACE_IN_NAME_SET = {

}


NAMESPACE_OVERRIDES = {
    "r": "global",
    "r-tensorflow": "r",
}


def flip_mutex_from_anacondar_to_mro(fn, record, instructions):
    if 'anacondar' in record['build'] and record.get('track_features'):
        instructions['packages'][fn] = {'track_features': None}
    elif 'mro' in record['build'] and not record.get('track_features'):
        instructions['packages'][fn] = {'track_features': 'mro_is_not_default'}


def _get_record_depends(fn, record, instructions):
    """ Return the depends information for a record, including any patching. """
    record_depends = record.get('depends', [])
    if fn in instructions['packages']:
        if 'depends' in instructions['packages'][fn]:
            # the package depends have already been patched
            record_depends = instructions['packages'][fn]['depends']
    return record_depends



def _combine_package_types(repodata):
    """
    Given repodata, combines .tar.bz2 entries and .conda entries (that is,
    entries in "packages" and entries in "packages.conda") into one dictionary.
    This updates repodata in place, emptying the "packages.conda" entry into
    the "packages" entry.  They can later be separated again by
    _separate_package_types.

    For this to work, this function performs these checks before combining them
    so that they remain intact and can be separated again:
      - All entries in "packages" DO NOT end in ".conda".
      - All entries "packages.conda" end in ".conda".

    This is messier than using the two dictionary entries correctly in every
    iteration, but the code in this patcher is diverse and a little chaotic,
    and this seems safer for now.
    """
    for artifact in repodata['packages']:
        if artifact.endswith('.conda'):
            raise Exception(
                    'Artifact in "packages" ends with .conda')
    for artifact in repodata['packages.conda']:
        if not artifact.endswith('.conda'):
            raise Exception(
                    'Artifact in "packages.conda" does not end in .conda')


    # # Redundantly (forward-safe), check that the number of packages is not
    # # reduced (which should not be possible if the checks above are written
    # # correctly.
    # all_packages = copy.deepcopy(repodata['packages'])
    # all_packages.update(copy.deepcopy(repodata['packages']))
    # if (   # test for possible intersections
    #         len(all_packages) !=
    #         len(repodata['packages']) + len(repodata['packages.conda'])):
    #     raise Exception(
    #             'Combination of .tar.bz2 and .conda package entries failed; '
    #             'we ended up with the wrong number of entries.')

    repodata['packages'].update(repodata['packages.conda'])
    del repodata['packages.conda']



def _separate_package_types(repodata, instructions=None):
    """
    Given repodata edited by _combine_package_types, separate package types
    again (into the 'packages' and 'packages.conda' entries in repodata, as
    usual).  This updates repodata in place.

    If provided an instructions argument (patch instructions), also separates
    that (in place as well).
    """
    if 'packages.conda' in repodata:
        raise Exception(
                '_separate_package_types likely being used incorrectly: '
                'the given repodata already includes a "packages.conda" dict.')

    repodata['packages.conda'] = {}
    for artifact in list(repodata['packages'].keys()):   # using list(...keys()) so I can change the size of the dict itself during loop iteration.  It's fine.
        if artifact.endswith('.conda'):
            repodata['packages.conda'][artifact] = repodata['packages'][artifact]
            del repodata['packages'][artifact]

    if instructions is None:
        return

    if 'packages.conda' in instructions:
        raise Exception(
                '_separate_package_types likely being used incorrectly: '
                'the given patch instructions already include a '
                '"packages.conda" dict.')

    instructions['packages.conda'] = {}
    for artifact in list(instructions['packages'].keys()):  # using list(...keys()) so I can change the size of the dict itself during loop iteration.  It's fine.
        if artifact.endswith('.conda'):
            instructions['packages.conda'][artifact] = instructions['packages'][artifact]
            del instructions['packages'][artifact]



def _patch_repodata(repodata, subdir):
    instructions = {
        "patch_instructions_version": 1,
        "packages": defaultdict(dict),
        "revoke": [],
        "remove": [],
    }
    if 'packages' not in repodata:
        return instructions

    # Move all "packages.conda" contents to "packages", checking to ensure that
    # they can be separated later.
    _combine_package_types(repodata)
    index = repodata["packages"]
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
        # ensure that all r/r-base/mro-base packages have the mutex
        if record_name == "r-base":
            if not any(dep.split()[0] == "_r_mutex" for dep in record['depends']):
                if "_r-mutex 1.* anacondar_1" not in record['depends']:
                    record['depends'].append("_r-mutex 1.* anacondar_1")
                instructions["packages"][fn]["depends"] = record['depends']
        elif record_name == "mro-base":
            if not any(dep.split()[0] == "_r_mutex" for dep in record['depends']):
                if "_r-mutex 1.* mro_2" not in record['depends']:
                    record['depends'].append("_r-mutex 1.* mro_2")
                instructions["packages"][fn]["depends"] = record['depends']
        elif record_name == "_r-mutex":
            flip_mutex_from_anacondar_to_mro(fn, record, instructions)
        # None of the 3.1.2 builds used r-base, and none of them have the mutex
        elif record_name == "r" and record['version'] == "3.1.2":
            # less than build 3 was an actual package; no r-base connection.  These need the mutex.
            if int(record["build_number"]) < 3:
                if "_r-mutex 1.* anacondar_1" not in record['depends']:
                    record['depends'].append("_r-mutex 1.* anacondar_1")
                instructions["packages"][fn]["depends"] = record['depends']
            else:
                # this dep was underspecified
                try:
                    record['depends'].remove('r-base')
                except ValueError:
                    pass
                record['depends'].append('r-base 3.1.2')
                instructions["packages"][fn]["depends"] = record['depends']

        # Every artifact's metadata requires 'subdir'.
        if "subdir" not in record:
            record["subdir"] = subdir
            instructions["packages"][fn]["subdir"] = subdir

        # cyclical dep here.  Everything should depend on r-base instead of r, as r brings in r-essentials
        new_deps = []
        for dep in record['depends']:
            parts = dep.split()
            if len(parts) > 1 and parts[0] == 'r':
                new_deps.append("r-base %s" % parts[1])
            else:
                new_deps.append(dep)
        record['depends'] = new_deps
        instructions["packages"][fn]["depends"] = record['depends']

        # try to attach mutex metapackages more directly
        if not any(dep.split()[0] == "_r-mutex" for dep in record['depends']):
            if any(dep.split()[0] == "r-base" for dep in record['depends']):
                record['depends'].append("_r-mutex 1.* anacondar_1")
            elif any(dep.split()[0] == "mro-base" for dep in record['depends']):
                record['depends'].append("_r-mutex 1.* mro_2")
            instructions["packages"][fn]["depends"] = record['depends']

        if (any(fnmatch.fnmatch(fn, rev) for rev in REVOKED.get(subdir, [])) or
                any(fnmatch.fnmatch(fn, rev) for rev in REVOKED.get("any", []))):
            instructions['revoke'].append(fn)
        if (any(fnmatch.fnmatch(fn, rev) for rev in REMOVALS.get(subdir, [])) or
                any(fnmatch.fnmatch(fn, rev) for rev in REMOVALS.get("any", []))):
            instructions['remove'].append(fn)

        if any(dep == 'mro-base' for dep in record.get('depends', [])):
            deps = record['depends']
            deps.remove('mro-base')
            version = re.search(r".*\-.*mro(\d{3})", fn).group(1)
            lb = '.'.join((_ for _ in version))
            ub = '.'.join((_ for _ in str(int(version) + 10)))
            ub = '.'.join(ub.split('.')[:2] + ['0'])
            deps.append("mro-base >={},<{}a0".format(lb, ub))
            instructions["packages"][fn]["depends"] = deps

        if any(dep == 'r-base' for dep in record.get('depends', [])):
            deps = record['depends']
            deps.remove('r-base')
            version = re.search(r".*\-.*r(\d{3})", fn).group(1)
            lb = '.'.join((_ for _ in version))
            ub = '.'.join((_ for _ in str(int(version) + 10)))
            ub = '.'.join(ub.split('.')[:2] + ['0'])
            deps.append("r-base >={},<{}a0".format(lb, ub))
            instructions["packages"][fn]["depends"] = deps

        if any(dep.startswith('glib >=') for dep in record['depends']):
            if record['name'] == 'anaconda':
                continue

            def fix_glib_dep(dep):
                if dep.startswith('glib >='):
                    return dep.split(',')[0] + ',<3.0a0'
                else:
                    return dep
            record_depends = _get_record_depends(fn, record, instructions)
            depends = [fix_glib_dep(dep) for dep in record_depends]
            if depends != record_depends:
                instructions["packages"][fn]["depends"] = depends

    # Split the "packages" entries back into "packages" and "packages.conda" in
    # both the repodata and instructions, undoing what we did earlier in this
    # function to combine them.
    _separate_package_types(repodata, instructions)

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
