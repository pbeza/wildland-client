.. program:: wl-forest
.. _wl-forest:

*************************************************
:command:`wl forest` - Forest management commands
*************************************************

Synopsis
========

| :command:`wl forest create [--owner <user>] <storage-template>`
| :command:`wl forest mount []`
| :command:`wl forest unmount []`

Description
===========

These are commands to manage forests. A user's forest is located through their manifests catalog and
consists of all the subcontainers of the containers in their manifests catalog (and, recursively,
all the subcontainers of them etc.).

Commands
========

.. program:: wl-forest-create
.. _wl-forest-create:

:command:`wl forest create [<storage-template>]`
-------------------------------------------------------

Bootstrap a new Forest. If --owner option is not specified, it is created for `@default-owner`.
You must have private key of that user in order to use this command.

Arguments:
| STORAGE_TEMPLATE      storage template used to create Forest containers

Description

This command creates an container in user's manifest catalog for the Forest.
The storage template *must* contain at least one read-write storage.

After the container is created, the following steps take place:

1. A link object to manifests catalog container is generated and appended to USER's manifest.
2. USER manifest and catalog container's manifest are copied to the storage from Forest manifests container

.. option:: --access USER

   Allow an additional user or user path access to containers created using this command. By default,
   those the containers are unencrypted unless at least one USER is passed using this option.

.. option:: --owner USER, --user USER

   Name of the user who owns the Forest. Default: `@default-owner`

.. option:: --manifest-local-dir PATH

   Set manifests storage local directory. Must be an absolute path. Default: `/`


.. program:: wl-forest-mount
.. _wl-forest-mount:

:command:`wl forest mount [--no-refresh-users] [--list-all] [--lazy/--no-lazy] [--save] <forest_name> [<forest_name>...]`
-------------------------------------------------------------------------------------------------------------------------

Mount a forest given by name or path to manifest.
The Wildland system has to be started first, see :ref:`wl start <wl-start>`.

.. option:: --lazy

   Do not mount container backends until first use. This is the default.

.. option:: --no-lazy

   Mount container backends right away. This may take some time.

.. option:: -s, --save

   Add the forest containers to ``default-containers`` in configuration file, so
   that they will be mounted at startup.

.. option:: -c, --with-cache

   Create and use a cache storage for all containers in the forest, using the default cache template
   (see :ref:`wl set-default-cache <wl-set-default-cache>`).
   See :ref:`wl container create-cache <wl-container-create-cache>` for details about caches.

.. option:: --cache-template <template_name>

   Create and use a cache storage for all containers in the forest, using the given template. If used together with `--with-cache` option, explicit `<template_name>` takes precedence.
   See :ref:`wl container create-cache <wl-container-create-cache>`.

.. option:: -l, --list-all

   During mount, list all the forest containers to be mounted and result of mount (changed/not changed).
   Can be very long as a forest could contain lot of containers and numerous subcontainers.

.. option:: -n, --no-refresh-users

    Do not attempt to refresh all local user manifests imported through bridges before mount.
    This can speed up the mount, but can lead to using obsolete user manifests.

.. program:: wl-forest-unmount
.. _wl-forest-unmount:


:command:`wl forest unmount [--path] <forest_name> [<forest_name>...]`
----------------------------------------------------------------------

Unmount a forest given by name or path to manifest.

.. option:: --path <path>

   Mount path to search for.
