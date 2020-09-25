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
Username and password variant of botocore ClientCreator for use with
re-authorizing proxy.
'''

from typing import Union

from botocore.client import ClientCreator as BotocoreClientCreator
from botocore.client import ClientEndpointBridge, Config
from botocore.model import ServiceModel

from .args import ClientArgsCreator
from .credentials import Credentials


class ClientCreator(BotocoreClientCreator):

    def _get_client_args(self,
                         service_model: ServiceModel,
                         region_name: str,
                         is_secure: bool,
                         endpoint_url: str,
                         verify: Union[bool, str],
                         credentials: Credentials,
                         scoped_config: dict,
                         client_config: Config,
                         endpoint_bridge: ClientEndpointBridge) -> dict:
        args_creator = ClientArgsCreator(
            self._event_emitter, self._user_agent,
            self._response_parser_factory, self._loader,
            self._exceptions_factory, config_store=self._config_store)
        return args_creator.get_client_args(
            service_model, region_name, is_secure, endpoint_url,
            verify, credentials, scoped_config, client_config, endpoint_bridge)
