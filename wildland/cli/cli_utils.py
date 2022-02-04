from typing import List

import click

from wildland.storage_backends.base import StorageParam, StorageParamType


def param_name_to_cli(name: str) -> str:
    if len(name) == 1:
        return f'-{name}'
    return f'--{name.replace("_", "-")}'


def param_name_from_cli(name: str) -> str:
    return name.replace("-", "_")


def parse_storage_cli_options(storage_options: List[StorageParam]) -> List[click.Option]:
    cli_options: List[click.Option] = []
    for option in storage_options:
        names = [param_name_to_cli(name) for name in option.names]

        click_option = {'help': option.description, 'required': option.required}
        if option.display_name:
            click_option['metavar'] = option.display_name
        if option.param_type == StorageParamType.LIST:
            click_option['multiple'] = True
        if option.param_type == StorageParamType.BOOLEAN:
            click_option['is_flag'] = True
        if option.default_value:
            click_option['default'] = option.default_value
        if option.private:
            click_option['prompt'] = True
            click_option['hide_input'] = True

        cli_options.append(click.Option(names, **click_option))

    return cli_options
