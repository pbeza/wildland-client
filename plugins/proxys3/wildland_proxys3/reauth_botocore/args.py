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
Username and password variant of botocore ClientArgsCreator for use with
re-authorizing proxy.
'''

import copy
from typing import Union

import botocore
from botocore.args import ClientArgsCreator as BotocoreClientArgsCreator
from botocore.client import Config, ClientEndpointBridge
from botocore.endpoint import EndpointCreator
from botocore.model import ServiceModel

from .credentials import Credentials
from .signers import RequestSigner


class ClientArgsCreator(BotocoreClientArgsCreator):

    def get_client_args(self,
                        service_model: ServiceModel,
                        region_name: str,
                        is_secure: bool,
                        endpoint_url: str,
                        verify: Union[bool, str],
                        credentials: Credentials,
                        scoped_config: dict,
                        client_config: Config,
                        endpoint_bridge: ClientEndpointBridge) -> dict:
        final_args = self.compute_client_args(
            service_model, client_config, endpoint_bridge, region_name,
            endpoint_url, is_secure, scoped_config)

        service_name = final_args['service_name']
        parameter_validation = final_args['parameter_validation']
        endpoint_config = final_args['endpoint_config']
        protocol = final_args['protocol']
        config_kwargs = final_args['config_kwargs']
        s3_config = final_args['s3_config']
        partition = endpoint_config['metadata'].get('partition', None)
        socket_options = final_args['socket_options']

        signing_region = endpoint_config['signing_region']
        endpoint_region_name = endpoint_config['region_name']

        event_emitter = copy.copy(self._event_emitter)
        signer = RequestSigner(
            service_model.service_id, signing_region,
            endpoint_config['signing_name'],
            endpoint_config['signature_version'],
            credentials, event_emitter
        )

        config_kwargs['s3'] = s3_config
        new_config = Config(**config_kwargs)
        endpoint_creator = EndpointCreator(event_emitter)

        endpoint = endpoint_creator.create_endpoint(
            service_model, region_name=endpoint_region_name,
            endpoint_url=endpoint_config['endpoint_url'], verify=verify,
            response_parser_factory=self._response_parser_factory,
            max_pool_connections=new_config.max_pool_connections,
            proxies=new_config.proxies,
            timeout=(new_config.connect_timeout, new_config.read_timeout),
            socket_options=socket_options,
            client_cert=new_config.client_cert)

        serializer = botocore.serialize.create_serializer(protocol,
                                                          parameter_validation)
        response_parser = botocore.parsers.create_parser(protocol)

        return {
            'serializer': serializer,
            'endpoint': endpoint,
            'response_parser': response_parser,
            'event_emitter': event_emitter,
            'request_signer': signer,
            'service_model': service_model,
            'loader': self._loader,
            'client_config': new_config,
            'partition': partition,
            'exceptions_factory': self._exceptions_factory
        }