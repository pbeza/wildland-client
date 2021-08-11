#!/bin/bash -e
. /home/user/env/bin/activate

export EDITOR=vim
export PATH=/home/user/wildland-client:/home/user/wildland-client/docker:$PATH
export __fish_prompt_hostname="$HOSTNAME"
export LC_ALL=C.UTF-8
export XDG_RUNTIME_DIR=/tmp/docker-user-runtime
export DEBIAN_FRONTEND="noninteractive"

# workaround for https://github.com/docker/distribution/issues/2853
sudo chmod 666 /dev/fuse

MOUNT_DIR="$HOME/wildland"
mkdir "$MOUNT_DIR"

if [ "${EXPERIMENTAL_API,,}" = "true" ] || [ "${EXPERIMENTAL_API}" = "1" ]; then
    # Run Unicorn (REST API)
    mkdir /home/user/gunicorn

    cd /home/user/wildland-client/wildland/api
    gunicorn -c /home/user/wildland-client/gunicorn.py --daemon
    cd /home/user/wildland-client/

    sudo a2ensite wl-rest
fi

sudo service apache2 start

mkdir -p /home/user/.config/wildland
if ! grep -q '^mount-dir:' /home/user/.config/wildland/config.yaml 2>/dev/null; then
    # fresh start?
    echo "mount-dir: $MOUNT_DIR" >> /home/user/.config/wildland/config.yaml
fi
