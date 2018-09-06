# repodata-hotfixes
## Changes to package metadata to fix behavior

When packages are created, authors do their best to specify constraints that make their package work.  Sometimes things change, and their constraints are not accurate for making things work.  This results in broken environments.  People need to be able to patch the package metadata long after the packages are built, so that we can prevent conda from creating broken environments.  This repository holds python scripts that generate JSON files, which are then applied on top of the repodata.json index files that are generated from the original package content.

## Things that may require a metadata hotfix:

* changes to features or track_features (removal, addition, change to different names)
* addition or removal of dependencies
* addition or removal of constraints
