# Copyright 2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
'''
This module extends botocore.credentials module for use with
re-authorizing proxy.
'''

from collections import namedtuple

from botocore.compat import ensure_unicode


ReadOnlyCredentials = namedtuple('ReadOnlyCredentials',
                                 ['username', 'password'])


class Credentials:
    '''
    Username and password variant of botocore.credentials.Credentials
    for use with re-authorizing proxy.
    '''
    def __init__(self,
                 username: str,
                 password: str,
                 method: str = None) -> None:
        self.username = username
        self.password = password

        if not method:
            method = 'explicit'
        self.method = method

        self._normalize()

    # There are also missing docstrings in botocore implementation.
    # pylint: disable=missing-function-docstring

    def _normalize(self) -> None:
        # Keys would sometimes (accidentally) contain non-ascii
        # characters. It would cause a confusing UnicodeDecodeError in
        # Python 2. We explicitly convert them into unicode to avoid such error.
        #
        # Eventually the service will decide whether to accept the
        # credential. This also complies with the behavior in Python 3.
        self.username = ensure_unicode(self.username)
        self.password = ensure_unicode(self.password)

    def get_frozen_credentials(self) -> ReadOnlyCredentials:
        return ReadOnlyCredentials(self.username, self.password)
