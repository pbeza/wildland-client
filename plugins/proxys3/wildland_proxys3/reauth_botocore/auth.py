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
This module extends botocore.auth module for use with re-authorizing
proxy.
'''

import functools
import logging
from base64 import b64encode
from hashlib import sha256

from botocore.auth import (AUTH_TYPE_MAPS, EMPTY_SHA256_HASH, PAYLOAD_BUFFER,
                           UNSIGNED_PAYLOAD)
from botocore.auth import BaseSigner
from botocore.awsrequest import AWSRequest
from botocore.exceptions import NoCredentialsError

from .credentials import Credentials


logger = logging.getLogger(__name__)


class SigProxyBasicAuth(BaseSigner):
    '''
    Username and password variant of botocore.auth.S3SigV4Auth for use
    with re-authorizing proxy.
    '''
    def __init__(self, credentials: Credentials) -> None:
        self.credentials = credentials

    # There are also missing docstrings and no ``self`` argument in
    # botocore implementation
    # pylint: disable=missing-function-docstring, no-self-use

    def payload(self, request: AWSRequest) -> str:
        if not self._should_sha256_sign_payload(request):
            # When payload signing is disabled, we use this static
            # string in place of the payload checksum.
            return UNSIGNED_PAYLOAD
        request_body = request.body
        if request_body and hasattr(request_body, 'seek'):
            position = request_body.tell()
            read_chunksize = functools.partial(request_body.read,
                                               PAYLOAD_BUFFER)
            checksum = sha256()
            for chunk in iter(read_chunksize, b''):
                checksum.update(chunk)
            hex_checksum = checksum.hexdigest()
            request_body.seek(position)
            return hex_checksum
        if request_body:
            # The request serialization has ensured that
            # request.body is a bytes() type.
            return sha256(request_body).hexdigest()
        return EMPTY_SHA256_HASH

    def _should_sha256_sign_payload(self, request: AWSRequest) -> bool:
        # S3 allows optional body signing, so to minimize the
        # performance impact, we opt to not SHA256 sign the body on
        # streaming uploads, provided that we're on https.
        client_config = request.context.get('client_config')
        s3_config = getattr(client_config, 's3', None)

        # The config could be None if it isn't set, or if the customer
        # sets it to None.
        if s3_config is None:
            s3_config = {}

        # The explicit configuration takes precedence over any implicit
        # configuration.
        sign_payload = s3_config.get('payload_signing_enabled', None)
        if sign_payload is not None:
            return sign_payload

        # We require that both content-md5 be present and https be
        # enabled to implicitly disable body signing. The combination of
        # TLS and content-md5 is sufficiently secure and durable for us
        # to be confident in the request without body signing.
        if not request.url.startswith('https') or \
                'Content-MD5' not in request.headers:
            return True

        # If the input is streaming we disable body signing by default.
        if request.context.get('has_streaming_input', False):
            return False

        # Certain operations may have payload signing disabled by
        # default. Since we don't have access to the operation model, we
        #  pass in this bit of metadata through the request context.
        return request.context.get('payload_signing_enabled', True)

    def add_auth(self, request: AWSRequest) -> None:
        if self.credentials is None:
            raise NoCredentialsError

        # This could be a retry.  Make sure the previous
        # authorization header is removed first.
        self._modify_request_before_signing(request)

        username = self.credentials.username
        password = self.credentials.password
        signature = b64encode(f'{username}:{password}'.encode()).decode()

        self._inject_signature_to_request(request, signature)

    def _inject_signature_to_request(self,
                                     request: AWSRequest,
                                     signature: str) -> None:
        request.headers['Authorization'] = f'Basic {signature}'

    def _modify_request_before_signing(self, request: AWSRequest) -> None:
        if 'Authorization' in request.headers:
            del request.headers['Authorization']

        if 'X-Amz-Content-SHA256' in request.headers:
            del request.headers['X-Amz-Content-SHA256']

        request.headers['X-Amz-Content-SHA256'] = self.payload(request)


AUTH_TYPE_MAPS['proxy-basic'] = SigProxyBasicAuth
