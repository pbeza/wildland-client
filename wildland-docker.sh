#!/bin/sh -e
# a very simple wrapper script for starting up-to-date docker with wildland

localdir="$(readlink -f "$(dirname "$0")")"
cd "$localdir"

docker-compose pull wildland-client
docker-compose run --service-ports wildland-client "$@"
