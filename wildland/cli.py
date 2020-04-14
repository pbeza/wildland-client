'''
Wildland command-line interface.
'''

import argparse
import sys
from typing import Optional, Tuple
import os
import tempfile
import subprocess
import shlex
from pathlib import Path

from .manifest_loader import ManifestLoader
from .manifest import Manifest, ManifestError, HEADER_SEPARATOR, split_header
from .exc import WildlandError
from .user import User


PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use

class Command:
    '''Base command'''

    def __init__(self, cmd):
        self.cmd = cmd

    @property
    def help(self):
        '''
        Help text for this command.
        '''
        return self.__class__.__doc__

    def add_arguments(self, parser):
        '''
        Add arguments supported by this command.
        '''

    def handle(self, loader: ManifestLoader, args):
        '''
        Run the command based on parsed arguments.
        '''

        raise NotImplementedError()

    def read_manifest_file(self,
                           loader: ManifestLoader,
                           name: Optional[str],
                           manifest_type: Optional[str]) \
                           -> Tuple[bytes, Optional[Path]]:
        '''
        Read a manifest file specified by name. Recognize None as stdin.

        Returns (data, file_path).
        '''

        if name is None:
            return (sys.stdin.buffer.read(), None)

        path = loader.find_manifest(name, manifest_type)
        if not path:
            if manifest_type:
                raise CliError(
                    f'{manifest_type.title()} manifest not found: {name}')
            raise CliError(f'Manifest not found: {name}')
        print(f'Loading: {path}')
        with open(path, 'rb') as f:
            return (f.read(), path)

    def find_user(self, loader: ManifestLoader, name: Optional[str]) -> User:
        '''
        Find a user specified by name, using default if there is none.
        '''

        if name:
            user = loader.find_user(name)
            if not user:
                raise CliError(f'User not found: {name}')
            print(f'Using user: {user.pubkey}')
            return user
        user = loader.find_default_user()
        if user is None:
            raise CliError(
                'Default user not set, you need to provide --user')
        print(f'Using default user: {user.pubkey}')
        return user


class UserCreateCommand(Command):
    '''Create a new user'''

    def add_arguments(self, parser):
        parser.add_argument(
            'key',
            help='GPG key identifier')
        parser.add_argument(
            '--name',
            help='Name for file')

    def handle(self, loader, args):
        pubkey = loader.sig.find(args.key)
        print(f'Using key: {pubkey}')

        path = loader.create_user(pubkey, args.name)
        print(f'Created: {path}')

        if loader.config.get('default_user') is None:
            print(f'Using {pubkey} as default user')
            loader.config.update_and_save(default_user=pubkey)


class StorageCreateCommand(Command):
    '''Create a new storage'''

    supported_types = [
        'local'
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            required=True,
            choices=self.supported_types,
            help='Storage type')
        parser.add_argument(
            '--user',
            help='User for signing')
        parser.add_argument(
            '--name', required=True,
            help='Name for file')

        parser.add_argument(
            '--path',
            help='Path (for local storage)')

    def handle(self, loader, args):
        if args.type == 'local':
            fields = self.get_fields(args, 'path')
        else:
            assert False, args.type

        loader.load_users()
        user = self.find_user(loader, args.user)

        path = loader.create_storage(user.pubkey, args.type, fields, args.name)
        print('Created: {}'.format(path))

    def get_fields(self, args, *names) -> dict:
        '''
        Create a dict of fields from required arguments.
        '''
        fields = {}
        for name in names:
            if not getattr(args, name):
                raise CliError('Expecting the following fields: {}'.format(
                    ', '.join(names)))
            fields[name] = getattr(args, name)
        return fields


class ContainerCreateCommand(Command):
    '''Create a new container'''

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            help='User for signing')
        parser.add_argument(
            '--name', required=True,
            help='Name for file')
        parser.add_argument(
            '--path', nargs='+', required=True,
            help='Mount path (can be repeated)')
        parser.add_argument(
            '--storage', nargs='+', required=True,
            help='Storage to use (can be repeated)')


    def handle(self, loader, args):
        loader.load_users()
        user = self.find_user(loader, args.user)
        storages = []
        for storage_name in args.storage:
            storage_path = loader.find_manifest(storage_name, 'storage')
            if not storage_path:
                raise CliError(f'Storage manifest not found: {storage_name}')
            print(f'Using storage: {storage_path}')
            storages.append(str(storage_path))
        path = loader.create_container(user.pubkey, args.path, storages,
                                       args.name)
        print(f'Created: {path}')


class UserListCommand(Command):
    '''List users'''

    def handle(self, loader, args):
        loader.load_users()
        for user in loader.users:
            print('{} {}'.format(user.pubkey, user.manifest_path))


class StorageListCommand(Command):
    '''List storages'''

    def handle(self, loader, args):
        loader.load_users()
        for path, manifest in loader.load_manifests('storage'):
            print(path)
            storage_type = manifest.fields['type']
            print(f'  type:', storage_type)
            if storage_type == 'local':
                print(f'  path:', manifest.fields['path'])


class ContainerListCommand(Command):
    '''List containers'''

    def handle(self, loader, args):
        loader.load_users()
        for path, manifest in loader.load_manifests('container'):
            print(path)
            for container_path in manifest.fields['paths']:
                print(f'  path:', container_path)


class SignCommand(Command):
    '''Sign a manifest'''

    def __init__(self, cmd, manifest_type=None):
        super().__init__(cmd)
        self.manifest_type = manifest_type

    @property
    def help(self):
        if self.manifest_type:
            return f'Sign a {self.manifest_type} manifest'
        return f'Sign a manifest'

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to sign (default is stdin)')
        parser.add_argument(
            '-o', dest='output_file', metavar='FILE',
            help='Output file (default is stdout)')
        parser.add_argument(
            '-i', dest='in_place', action='store_true',
            help='Modify the file in place')

    def handle(self, loader, args):
        if args.in_place:
            if not args.input_file:
                raise CliError('Cannot -i without a file')
            if args.output_file:
                raise CliError('Cannot use both -i and -o')

        loader.load_users()
        data, path = self.read_manifest_file(loader, args.input_file,
                                             self.manifest_type)

        manifest = Manifest.from_unsigned_bytes(data)
        loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(loader.sig)
        signed_data = manifest.to_bytes()

        if args.in_place:
            print(f'Saving: {path}')
            with open(path, 'wb') as f:
                f.write(signed_data)
        elif args.output_file:
            print(f'Saving: {args.output_file}')
            with open(args.output_file, 'wb') as f:
                f.write(signed_data)
        else:
            sys.stdout.buffer.write(signed_data)


class VerifyCommand(Command):
    '''Verify a manifest'''

    def __init__(self, cmd, manifest_type=None):
        super().__init__(cmd)
        self.manifest_type = manifest_type

    @property
    def help(self):
        if self.manifest_type:
            return f'Verify a {self.manifest_type} manifest'
        return f'Verify a manifest (signature only, no schema)'

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to verify (default is stdin)')

    def handle(self, loader, args):
        loader.load_users()
        data, _path = self.read_manifest_file(loader, args.input_file,
                                              self.manifest_type)
        try:
            manifest = Manifest.from_bytes(data, loader.sig)
            loader.validate_manifest(manifest, self.manifest_type)
        except ManifestError as e:
            raise CliError(f'Error verifying manifest: {e}')
        print('Manifest is valid')


class EditCommand(Command):
    '''Edit and sign a manifest'''

    def __init__(self, cmd, manifest_type=None):
        super().__init__(cmd)
        self.manifest_type = manifest_type

    @property
    def help(self):
        if self.manifest_type:
            return f'Edit, validate and sign a {self.manifest_type} manifest'
        return f'Edit and sign a manifest'

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE',
            help='File to edit')

        parser.add_argument(
            '--editor', metavar='EDITOR',
            help='Editor to use')

    def handle(self, loader, args):
        if args.editor is None:
            args.editor = os.getenv('EDITOR')
            if args.editor is None:
                raise CliError('No editor specified and EDITOR not set')

        data, path = self.read_manifest_file(loader, args.input_file,
                                             self.manifest_type)

        if HEADER_SEPARATOR in data:
            _, data = split_header(data)

        # Do not use NamedTemporaryFile, because the editor might create a new
        # file instead modifying the existing one.
        with tempfile.TemporaryDirectory(prefix='wledit.') as temp_dir:
            temp_path = Path(temp_dir) / path.name
            with open(temp_path, 'wb') as f:
                f.write(data)

            command = '{} {}'.format(
                args.editor, shlex.quote(f.name))
            print(f'Running editor: {command}')
            try:
                subprocess.run(command, shell=True, check=True)
            except subprocess.CalledProcessError:
                raise CliError('Running editor failed')

            with open(temp_path, 'rb') as f:
                data = f.read()

        loader.load_users()
        manifest = Manifest.from_unsigned_bytes(data)
        loader.validate_manifest(manifest, self.manifest_type)
        manifest.sign(loader.sig)
        signed_data = manifest.to_bytes()
        with open(path, 'wb') as f:
            f.write(signed_data)
        print(f'Saved: {path}')


class MountCommand(Command):
    '''Mount the Wildland filesystem'''

    def handle(self, loader, args):
        mount_dir = loader.config.get('mount_dir')
        if not os.path.exists(mount_dir):
            print(f'Creating: {mount_dir}')
            os.makedirs(mount_dir)
        print(f'Mounting: {mount_dir}')

        options = ['base_dir=' + str(loader.config.base_dir)]
        if loader.config.get('dummy'):
            options.append('dummy_sig')
        cmd = [str(FUSE_ENTRY_POINT), str(mount_dir), '-o', ','.join(options)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise CliError(f'Failed to mount: {e}')


class UnmountCommand(Command):
    '''Unmount the Wildland filesystem'''

    def handle(self, loader, args):
        mount_dir = loader.config.get('mount_dir')
        cmd = ['umount', str(mount_dir)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise CliError(f'Failed to unmount: {e}')


class MainCommand:
    '''
    Main Wildland CLI command that defers to sub-commands.
    '''

    commands = [
        UserCreateCommand('user-create'),
        UserListCommand('user-list'),
        SignCommand('user-sign', 'user'),
        VerifyCommand('user-verify', 'user'),
        EditCommand('user-edit', 'user'),

        StorageCreateCommand('storage-create'),
        StorageListCommand('storage-list'),
        SignCommand('storage-sign', 'storage'),
        VerifyCommand('storage-verify', 'storage'),
        EditCommand('storage-edit', 'storage'),

        ContainerCreateCommand('container-create'),
        ContainerListCommand('container-list'),
        SignCommand('container-sign', 'container'),
        VerifyCommand('container-verify', 'container'),
        EditCommand('container-edit', 'container'),

        SignCommand('sign'),
        VerifyCommand('verify'),
        EditCommand('edit'),

        MountCommand('mount'),
        UnmountCommand('unmount'),
    ]

    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.add_arguments(self.parser)
        subparsers = self.parser.add_subparsers(dest='cmd')
        for command in self.commands:
            command_parser = subparsers.add_parser(command.cmd,
                                                   help=command.help)
            command.add_arguments(command_parser)

    def add_arguments(self, parser):
        '''
        Add common arguments.
        '''

        parser.add_argument(
            '--base-dir',
            help='Base directory for configuration')
        parser.add_argument(
            '--dummy', action='store_true',
            help='Use dummy signatures')
        parser.add_argument(
            '--gpg-home',
            help='Use a different GPG home directory')

    def run(self, cmdline):
        '''
        Entry point.
        '''
        args = self.parser.parse_args(cmdline)

        loader = ManifestLoader(
            dummy=args.dummy, base_dir=args.base_dir, gpg_home=args.gpg_home)

        for command in self.commands:
            if args.cmd == command.cmd:
                command.handle(loader, args)
                return
        self.parser.print_help()


def main(cmdline=None):
    '''
    Wildland CLI entry point.
    '''

    if cmdline is None:
        cmdline = sys.argv[1:]

    try:
        MainCommand().run(cmdline)
    except CliError as e:
        print(f'error: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
