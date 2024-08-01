# repodata-hotfixes
## Changes to package metadata to fix behavior

When packages are created, authors do their best to specify constraints that make their package work. Sometimes things change, and their constraints are not accurate for making things work. This results in broken environments. People need to be able to patch the package metadata long after the packages are built, so that we can prevent conda from creating broken environments. This repository holds python scripts that generate JSON files, which are then applied on top of the repodata.json index files that are generated from the original package content.

## Things that may require a metadata hotfix:

* changes to features or track_features (removal, addition, change to different names)
* addition or removal of dependencies
* addition or removal of constraints

## Actions that repodata-hotfixes (main.py, r.py and msys2.py) scripts can do:

### Dependency and Constraint updates

Changing dependencies and constraints is the primary reason hotfixes are applied. Their
may be reasons why you need to change a longstanding package but rebuilding may not be
feasible or perhaps not worth the time. By changing dependencies and constraints,
the data used to solve for dependencies can be modified and leave the larger ecosystem
unharmed.

NOTE: Hotfixes are applied in a overwrite manner. So any changes are implemented
will effect the the entire dependency or constraint list (i.e. If someone
changes one out of the ten dependency for a single package, all ten will still should be in the
"patch-instructions" as patching is an overwriting operation).

### Removal

Adding a package to the removal list will remove the entire entry from the repodata.json. It will no longer be searchable by conda search.

We should put things on the remove list when:
- We need a quick fix to stop consumers from downloading a bad package.

Another approach might be to move the package into broken package directory (see directions in perseverance-skills). This will cause it not to be indexed in the first place.

### Revoked

Adding a package to the revoked list does two things:
1. It inserts the "package_has_been_revoked" into the depends list.
2. It adds the revoked key value pair `revoked: true`

This should cause that the package in question is still available but will not be used by default as "package_has_been_revoked" isn't a valid package.

We should put things on the revoke list when:
- We feel we want a customer to still have access but not the whole consumer population by default
- ?

## Numpy 2.0 Compatibility Checks and Updates

### Running `generate_numpy2_patch.py`

The `generate_numpy2_patch.py` script is used to check and update package dependencies for compatibility with numpy 2.0. To run the script, use the following command:

```
python `generate_numpy2_patch.py`
```

### What numpy2.py does

`generate_numpy2_patch.py` performs the following tasks:
1. Scans through the repodata for packages depending on numpy.
2. Checks if these dependencies need updates to ensure compatibility with numpy 2.0.
3. Proposes changes to add upper bounds to numpy dependencies where necessary.
4. Generates a `numpy2_patch.json` file containing all proposed changes.

### When to use numpy2.py

Use `generate_numpy2_patch.py` when:
- Preparing for a major numpy version update (e.g., transitioning to numpy 2.0).
- You need to audit and update numpy dependencies across many packages.
- You want to ensure compatibility of the ecosystem with upcoming numpy versions.

### Running main.py with proposed_numpy_changes.json

After running `generate_numpy2_patch.py`, you'll have a `numpy2_patch.json` file. To apply these changes:

1. Ensure `numpy2_patch.json` is in the same directory as `main.py`.
2. Run `main.py` as usual:

```
python main.py
```

`main.py` will automatically detect and incorporate the changes from `numpy2_patch.json` into the hotfix process.

## Utility scripts:

### Seeing current hotfixes with `gen-current-hotfix-report.py`:

It can be quite difficult to grok what the hotfix scripts are doing. The script, `gen-current-hotfix-report.py`, attempts to make it easier to see what the current state of the applied hotfixes looks like.

The script downloads the current repodata. It then shows you a diff. Example usage of this script:

```
python gen-current-hotfix-report.py main --subdir linux-64 osx-64 win-64 osx-arm64 linux-ppc64le linux-aarch64 linux-s390x noarch
```

For repeated runs add `--use-cache` to avoid downloading the repodata files.

### Testing hotfixes with `test-hotfix.py`:

The script, `test-hotfix.py`, downloads the current repodata and runs your instructions against it. It then shows you a diff.
This useful for testing out changes before they are committed and deployed. This will show differences in current state of hotfixes
and the ones you are working on.

Example usage of this script:

```
python test-hotfix.py main --subdir linux-64 osx-64 win-64 osx-arm64 linux-ppc64le linux-aarch64 linux-s390x noarch
```

Use the `--color` or `--show-pkgs` options for different outputs.
For repeated runs add `--use-cache` to avoid downloading the repodata files.