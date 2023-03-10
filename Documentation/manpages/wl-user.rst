.. program:: wl-user
.. _wl-user:

*************************************
:command:`wl user`: - User management
*************************************

Synopsis
========

| :command:`wl {user|users} list`
| :command:`wl user create <name> --key <key>`
| :command:`wl user {sign|verify} [...] <file>`
| :command:`wl user edit [--editor <editor>] <file>`
| :command:`wl user modify [...] <file>`
| :command:`wl user publish <user> [<user> ...]`
| :command:`wl user unpublish <user> [<user> ...]`

Description
===========

.. todo::

   Write general description about users.

Commands
========

.. program:: wl-user-list
.. _wl-user-list:

:command:`wl {user|users} list [OPTIONS]`
-----------------------------------------

List all known users.

.. option :: --verbose, -v

   When this flag is passed, a more detailed output will be displayed.
   
.. option :: --list-secret-keys, -K

   Only display users for which the private key is available.

.. program:: wl-user-create
.. _wl-user-create:

:command:`wl user create [OPTIONS] NAME`
----------------------------------------

Create a new user manifest and save it.

Unless ``--key`` is provided, the command will generate a new key pair.

.. option:: --key <fingerprint>

   Use an existing key pair to create a user. The key pair must be in the key
   directory (``~/.config/wildland/keys``), as ``<fingerprint>.pub`` and
   ``<fingerprint>.sec`` files.

.. option:: --path <path>

   Specify a path in Wildland namespace (such as ``/users/User``) for the
   user. Can be repeated.

.. option:: --add-pubkey <public_key>

   Add additional public key that can be used to verify manifests owned by this user. The whole
   key must be specified either as a fingerprint or a Wildland user path. In the case where a fingerprint is provided,
   the key will be stored in a ``<fingerprint>.pub`` file in the key directory (``~/.config/wildland/keys``).
   In the case of a user path, all public keys needed to resolve the user path will be added to the same
   directory. Can be repeated.


.. program:: wl-user-delete
.. _wl-user-delete:

:command:`wl user delete [--force] [--cascade] [--delete-keys] NAME [NAME ...]`
-------------------------------------------------------------------------------

Delete a user from local filesystem.

This will consider manifests in the local filesystem (stored in
``~/.config/wildland/``) signed by the user. However, it will not delete
locally stored key pairs (``~/.config/wildland/keys/``).

.. option:: --force, -f

   Delete even if there are manifests (containers/storage) signed by the user.

.. option:: --cascade

   Delete together with manifests (containers/storage) signed by the user.

.. option:: --delete-keys

   Delete together with public/private key pair owned by the user.

.. _wl-user-sign:
.. _wl-user-verify:
.. _wl-user-edit:
.. _wl-user-dump:

:command:`wl user {sign|verify|edit} [OPTIONS] <file>`
------------------------------------------------------

See help for :ref:`wl sign <wl-sign>`, :ref:`wl verify <wl-verify>`, :ref:`wl dump <wl-dump>` and
:ref:`wl edit <wl-edit>`.

.. program:: wl-user-import
.. _wl-user-import:

:command:`wl user import [--path path] [--bridge-owner user] url_or_path`
-------------------------------------------------------------------------

Imports a user. Accepts local paths to manifests, urls to manifests, Wildland urls
to manifests and Wildland urls to Wildland objects.

For users, will import the user and create an appropriate bridge manifest referencing the user.
In the process of bridge creation, the client will attempt to mount the imported user's
manifests catalog containers (if any) and find the imported user's manifest file in `/users/`
directories within those containers. If successful, it will create a link object to that file
and store is in the bridge manifest. Otherwise it will use the url or path that was passed as an
argument to this command.

For Wildland object path, will import all referenced bridges and their reference users.

.. option:: --path

   Overwrite bridge paths with provided paths. Optional. Can be repeated. Works only if a single
   bridge is to imported (to avoid duplicate paths.

.. option:: --bridge-owner

    Override the owner of created bridge manifests with provided owner.

.. program:: wl-user-refresh
.. _wl-user-refresh:

:command:`wl user refresh USER`
----------------------------------------

Iterate over bridges and import all user manifest that those bridges refer to.
Note: This command will override the existing users' manifests.

Unless USER name is provided, the command will iterate over all bridges.

.. program:: wl-user-modify
.. _wl-user-modify:

:command:`wl user modify [--add-path <path>] [--del-path <path>] [--add-pubkey <pubkey>] [--add-pubkey-user <user>] [--del-pubkey <pubkey>] [--add-catalog-entry <path>] [--del-catalog-entry <path>] <file>`
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

Modify a user |~| manifest given by *<file>*.

.. option:: --add-path

   Path to add. Can be repeated.

.. option:: --del-path

   Path to remove. Can be repeated.

.. option:: --add-pubkey

   Public key to add (either in the same format as in the public key file, or provided as a Wildland user path). Can be repeated.

.. option:: --add-pubkey-user

   User whose public key to add. Can be repeated.

.. option:: --del-pubkey

   Public key to remove (either in the same format as in the public key file, or provided as a Wildland user path). Can be repeated.

.. option:: --add-catalog-entry

   Container uri to add. Can be repeated.

.. option:: --del-catalog-entry

   Container uri to remove. Can be repeated.

.. program:: wl-user-publish
.. _wl-user-publish:

:command:`wl user publish <user> [<user> ...]`
----------------------------------------------

Publish user manifests into user's manifests catalog (first container from the catalog
that provides read-write storage will be used).

.. program:: wl-user-unpublish
.. _wl-user-unpublish:

:command:`wl user unpublish <user> [<user> ...]`
------------------------------------------------

Unpublish user manifests from the whole of a user's manifests catalog.
