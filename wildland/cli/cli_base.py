# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Wildland command-line interface - base module.
"""

import collections
import sys
import traceback
import types
from pathlib import Path
from typing import List, Tuple, Callable
import click

from ..utils import format_options_required_first, format_multi_command_options, \
    format_command_options
from ..core.wildland_core import WildlandCore


# pylint: disable=no-self-use


class ContextObj:
    """Helper object for keeping state in :attr:`click.Context.obj`"""

    def __init__(self, client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session
        self.wlcore = WildlandCore(self.client)


class AliasedGroup(click.Group):
    """A very simple alias engine for :class:`click.Group`"""

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.aliases = {}
        self.debug = False

    def __call__(self, *args, **kwargs):
        try:
            return self.main(*args, **kwargs)
        except Exception as exc:
            click.secho(f'Error: {exc}', fg="red")
            if self.debug is True:
                traceback.print_exception(*sys.exc_info())

            if isinstance(exc, click.ClickException):
                # pylint: disable=no-member
                sys.exit(exc.exit_code)
            else:
                sys.exit(1)

    def command(self, *args, **kwargs):
        show_default_settings = {'show_default': True}

        if 'alias' not in kwargs:
            return super().command(*args, context_settings=show_default_settings, **kwargs)

        aliases = kwargs.pop('alias')
        super_decorator = super().command(*args, context_settings=show_default_settings, **kwargs)

        def decorator(f):
            cmd = super_decorator(f)
            self.add_alias(**{alias: cmd.name for alias in aliases})
            return cmd

        return decorator

    def group(self, *args, **kwargs):
        if 'alias' not in kwargs:
            return super().group(*args, **kwargs)

        aliases = kwargs.pop('alias')
        super_decorator = super().group(*args, **kwargs)

        def decorator(f):
            cmd = super_decorator(f)
            self.add_alias(**{alias: cmd.name for alias in aliases})
            return cmd

        return decorator

    def add_alias(self, **kwds):
        """Add aliases to a command

        >>> cmd.add_alias(alias='original-command')
        """
        assert all(
            alias not in (*self.aliases, *self.commands) for alias in kwds)
        self.aliases.update(kwds)

    def get_command(self, ctx, cmd_name):
        if self.name == 'wl' and 'debug' in ctx.params:
            self.debug = ctx.params['debug']

        # 1) try exact command
        rv = super().get_command(ctx, cmd_name)
        if rv is not None:
            return rv

        # 2) try exact alias
        if cmd_name in self.aliases:
            return super().get_command(ctx, self.aliases[cmd_name])

        # 3) try unambiguous prefix in both commands and aliases
        matches: List[Tuple[str, bool]] = []
        matches.extend((cn, False)
            for cn in self.list_commands(ctx) if cn.startswith(cmd_name))
        matches.extend((an, True)
            for an in self.aliases if an.startswith(cmd_name))

        if len(matches) == 0:
            return None

        if len(matches) > 1:
            desc = ', '.join(
                f'{name} ({"alias" if is_alias else "command"})'
                for (name, is_alias) in matches)
            ctx.fail(f'too many matches: {desc}')

        name, is_alias = matches[0]
        if is_alias:
            name = self.aliases[name]

        click.secho(f'Understood {cmd_name!r} as {name!r}', fg="yellow")
        return super().get_command(ctx, name)

    def format_commands(self, ctx, formatter):
        super().format_commands(ctx, formatter)
        if not self.aliases:
            return

        aliases_reversed = collections.defaultdict(set)
        for alias, cmd_name in self.aliases.items():
            aliases_reversed[cmd_name].add(alias)

        with formatter.section('Aliases'):
            formatter.write_dl((cmd_name, ', '.join(sorted(aliases_reversed[cmd_name])))
                for cmd_name in sorted(aliases_reversed))

    # pylint: disable=unidiomatic-typecheck
    def add_command(self, cmd, name=None):
        if type(cmd) is click.Group:
            setattr(cmd, "format_options", types.MethodType(format_multi_command_options, cmd))
        elif type(cmd) is click.Command:
            setattr(cmd, "format_options", types.MethodType(format_command_options, cmd))

        return super().add_command(cmd, name)

    def format_options(self, ctx, formatter):
        format_options_required_first(self, ctx, formatter)
        self.format_commands(ctx, formatter)


def aliased_group(name=None, **kwargs) -> Callable[[Callable], AliasedGroup]:
    """
    A decorator that creates an AliasedGroup and typechecks properly.
    """

    def decorator(f):
        return click.group(name, cls=AliasedGroup, **kwargs)(f)

    return decorator
