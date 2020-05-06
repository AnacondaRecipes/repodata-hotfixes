# repodata-hotfixes
## Changes to package metadata to fix behavior

When packages are created, authors do their best to specify constraints that make their package work.  Sometimes things change, and their constraints are not accurate for making things work.  This results in broken environments.  People need to be able to patch the package metadata long after the packages are built, so that we can prevent conda from creating broken environments.  This repository holds python scripts that generate JSON files, which are then applied on top of the repodata.json index files that are generated from the original package content.

## Things that may require a metadata hotfix:

* changes to features or track_features (removal, addition, change to different names)
* addition or removal of dependencies
* addition or removal of constraints

## Testing hotfixes:

There's a script that downloads the current repodata and runs your instructions against it.  It then shows you a diff.  Example usage of this script:

```
python test-hotfix.py main --subdir linux-64 osx-64 win-64 win-32 linux-ppc64le linux-32 noarch
```

Use the --color or --show-pkgs arguments for different outputs.

For repeated runs add --use-cache to avoid downloading the repodata files.

You should run this before merging any PRs so that you understand the effects your change may have (or not have, if you have bugs).
