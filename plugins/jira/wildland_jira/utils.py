# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                 Dominik Gonciarz <dominik.gonciarz@besidethepark.com>
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
Common helpers for Jira plugin
"""

import base64
from typing import Union, List, Dict, Literal, Optional
from urllib.parse import quote


def _stringify_param(key: str, value: Union[str, int, List[str]]):
    """
    stringify_query_params helper; encodes key and corresponding value into a string
    """
    value_str = ','.join(value) if isinstance(value, list) else value
    param_str = f'{key}={value_str}'
    return quote(param_str)


def stringify_query_params(params: Dict[str, Union[str, int, List[str]]]) -> str:
    """
    Encodes dictionary of parameters into an url params string
    """
    if len(params) == 0:
        return ''

    return '?' + '&'.join([_stringify_param(key, params[key]) for key in params])


def _stringify_jql_param(key: str, value: Union[str, int, List[str]]):
    """
    encode_dict_to_jql helper; encodes key and corresponding value into a string
    """
    if isinstance(value, list):
        value_str = ' OR '.join([f'{key}="{v}"' for v in value])
        value_str = f'({value_str})'
    else:
        value_str = f'{key}="{value}"'

    return value_str


def encode_dict_to_jql(params: Optional[Dict[str, Union[str, int, List[str]]]],
                       order_by: str,
                       order_dir: Literal["ASC", "DESC"]):
    """
    Produces JQL query from the dict of parameters and sorting
    """
    if params is None:
        params = []
    if order_by is None:
        order_by = 'updatedDate'
    if order_dir is None:
        order_dir = 'DESC'
    encoded_names = [_stringify_jql_param(name, params[name]) for name in params]
    query = " AND ".join(encoded_names) + f' order by {order_by} {order_dir}'
    return quote(query)


def encode_basic_auth(username: str, personal_token: str) -> str:
    """
    Constructs Jira Basic authorization token; which is base64 encoded string of the form:
    'username:personal_token'
    """
    assert username is not None and len(username)
    assert personal_token is not None and len(personal_token)

    basic_token = f'{username}:{personal_token}'
    encoded_basic_token = base64.b64encode(basic_token.encode('utf-8'))

    return str(encoded_basic_token, "utf-8")
