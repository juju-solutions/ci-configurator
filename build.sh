#!/bin/bash -e

if [[ -z "$CONFIG_BZR_REPO" ]] ; then
  echo "ERROR: Cannot build charm. Must set BZR_CONFIG_REPO in environment."
  exit 1
fi

make sourcedeps
make configrepo
