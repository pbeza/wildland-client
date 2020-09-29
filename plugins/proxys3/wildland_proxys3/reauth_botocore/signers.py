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
Username and password variant of botocore RequestSigner for use with
re-authorizing proxy.
'''

from botocore.auth import BaseSigner
from botocore.exceptions import (NoRegionError,
                                 UnknownSignatureVersionError)
from botocore.signers import RequestSigner as BotocoreRequestSigner

from .auth import AUTH_TYPE_MAPS


class RequestSigner(BotocoreRequestSigner):

    def get_auth_instance(self,
                          signing_name: str,
                          region_name: str,
                          signature_version: str = None,
                          **kwargs) -> BaseSigner:
        '''
        Get an auth instance which can be used to sign a request using 
        the given signature version.

        Augments to handle the proxy signature version.
        '''
        if signature_version is None:
            signature_version = self._signature_version

        cls = AUTH_TYPE_MAPS.get(signature_version)
        if cls is None:
            raise UnknownSignatureVersionError(
                signature_version=signature_version)

        # If there's no credentials provided (i.e credentials is None),
        # then we'll pass a value of "None" over to the auth classes,
        # which already handle the cases where no credentials have
        # been provided.
        frozen_credentials = None
        if self._credentials is not None:
            frozen_credentials = self._credentials.get_frozen_credentials()
        kwargs['credentials'] = frozen_credentials

        if cls.REQUIRES_REGION:
            if self._region_name is None:
                raise NoRegionError()
            kwargs['region_name'] = region_name
            kwargs['service_name'] = signing_name
        auth = cls(**kwargs)

        return auth
