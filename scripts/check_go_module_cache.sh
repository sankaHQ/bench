#!/bin/sh
# Image-boundary regression: a cached test library can become a candidate root.
# The baseline's pruned module graph alone does not exercise this case.
set -eu
export GOPROXY=off GOSUMDB=off GOTOOLCHAIN=local GOWORK=off
library=$(cd "${1:?Go lock directory required}" && go list -m -f '{{.Path}}@{{.Version}}' github.com/stretchr/testify)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT HUP INT TERM
cd "$scratch"
go mod init cache-regression
go mod edit -require="$library"
go list -mod=mod -m all
go mod download all
go mod verify
