# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
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
Set of convenience utils for CLI
"""

from typing import List, Union, TypedDict, Optional

import click

from wildland.storage_backends.base import StorageParam, StorageParamType


class ClickOption(TypedDict):
    """
    Attributes and their types for click options.
    """
    help: Optional[str]
    required: bool
    metavar: Optional[str]
    default: Optional[Union[int, str, bool, List[str]]]
    multiple: bool
    is_flag: Optional[bool]
    prompt: Union[bool, str]
    hide_input: bool


def param_name_to_cli(name: str) -> str:
    """
    Convert param name to cli name i.e. app_key -> --app-key.
    If param is with slash i.e. ssl/no_ssl convert to --ssl/--no-ssl
    """
    if '/' in name:
        name = name.replace('/', '/--')
    if len(name) == 1:
        return f'-{name}'
    return f'--{name.replace("_", "-")}'


def param_name_from_cli(name: str) -> str:
    """
    Convert cli name to param
    """
    return name.replace("-", "_")


def parse_storage_cli_options(storage_options: List[StorageParam]) -> List[click.Option]:
    """
    Make click options from given storage params
    """
    cli_options: List[click.Option] = []
    for option in storage_options:
        name = [param_name_to_cli(option.name)]

        click_option: ClickOption = {
            'multiple': option.param_type == StorageParamType.LIST,
            'is_flag': True if option.param_type == StorageParamType.BOOLEAN else None,
            'prompt': bool(option.private),
            'hide_input': bool(option.private),
            'metavar': option.display_name,
            'default': option.default_value,
            'help': option.description,
            'required': option.required
        }

        cli_options.append(click.Option(name, **click_option))

    return cli_options
