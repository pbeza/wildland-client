'''
Wildland command-line interface.
'''

import argparse
import sys

from .manifest_loader import ManifestLoader
from .manifest import Manifest, ManifestError

# pylint: disable=no-self-use

class Command:
    '''Base command'''

    cmd: str = ''

    def __init__(self, subparsers):
        self.parser = subparsers.add_parser(self.cmd,
                                            help=self.__class__.__doc__)
        self.add_arguments(self.parser)

    def add_arguments(self, parser):
        '''
        Add arguments supported by this command.
        '''

    def handle(self, loader: ManifestLoader, args):
        '''
        Run the command based on parsed arguments.
        '''

        raise NotImplementedError()


class UserCreateCommand(Command):
    '''Create a new user'''

    cmd = 'user-create'

    def add_arguments(self, parser):
        parser.add_argument(
            'key',
            help='GPG key identifier')
        parser.add_argument(
            '--name',
            help='Name for file')

    def handle(self, loader, args):
        pubkey = loader.sig.find(args.key)
        print('Using key: {}'.format(pubkey))

        path = loader.create_user(pubkey, args.name)
        print('Created: {}'.format(path))


class UserListCommand(Command):
    '''List users'''

    cmd = 'user-list'

    def handle(self, loader, args):
        loader.load_users()
        for user in loader.users:
            print('{} {}'.format(user.pubkey, user.manifest_path))


class SignCommand(Command):
    '''Sign a manifest'''
    cmd = 'sign'

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
                print('Cannot -i without a file')
                sys.exit(1)
            if args.output_file:
                print('Cannot use both -i and -o')
                sys.exit(1)
            args.output_file = args.input_file

        loader.load_users()
        data = self.load(args)
        manifest = Manifest.from_unsigned_bytes(data, loader.sig)
        signed_data = manifest.to_bytes()
        self.save(args, signed_data)

    def load(self, args) -> bytes:
        '''
        Load from file or stdin.
        '''
        if args.input_file:
            with open(args.input_file, 'rb') as f:
                return f.read()
        return sys.stdin.buffer.read()

    def save(self, args, data: bytes):
        '''
        Save to file or stdout.
        '''

        if args.output_file:
            with open(args.output_file, 'wb') as f:
                f.write(data)
        else:
            sys.stdout.buffer.write(data)


class VerifyCommand(Command):
    '''Verify a manifest'''
    cmd = 'verify'

    def add_arguments(self, parser):
        parser.add_argument(
            'input_file', metavar='FILE', nargs='?',
            help='File to verify (default is stdin)')

    def handle(self, loader, args):
        loader.load_users()
        data = self.load(args)
        try:
            Manifest.from_bytes(data, loader.sig)
        except ManifestError as e:
            print(e)
            sys.exit(1)
        print('Signature is OK')

    def load(self, args) -> bytes:
        '''
        Load from file or stdin.
        '''

        if args.input_file:
            with open(args.input_file, 'rb') as f:
                return f.read()
        return sys.stdin.buffer.read()


class MainCommand:
    '''
    Main Wildland CLI command that defers to sub-commands.
    '''

    command_classes = [
        UserCreateCommand,
        UserListCommand,
        SignCommand,
        VerifyCommand,
    ]

    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.add_arguments(self.parser)
        subparsers = self.parser.add_subparsers(dest='cmd')
        self.commands = []
        for command_cls in self.command_classes:
            command = command_cls(subparsers)
            self.commands.append(command)

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

    MainCommand().run(cmdline)


if __name__ == '__main__':
    main()
