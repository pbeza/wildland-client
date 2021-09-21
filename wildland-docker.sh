#!/bin/sh -e
# a very simple wrapper script for starting up-to-date docker with wildland

while [ $# -gt 0 ] ; do
  case $1 in
    -e | --experimental-api) p_out=true ;;
    *) echo "Invalid option $1";;
  esac
  shift
done

localdir="$(readlink -f "$(dirname "$0")")"
cd "$localdir"

# run wildland-client service
docker-compose pull wildland-client
docker-compose run --service-ports wildland-client "$@"
