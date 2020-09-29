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
Username and password variant of botocore Session for use with re-authorizing 
proxy.
'''

from typing import Union

from botocore import UNSIGNED
from botocore import retryhandler, translate
from botocore.client import BaseClient, Config
from botocore.exceptions import PartialCredentialsError
from botocore.session import Session as BotocoreSession

from .client import ClientCreator
from .credentials import Credentials


class Session(BotocoreSession):
    '''
    Augments botocore Session object to use the username and password based
    authentication.
    '''

    def set_credentials(self, username: str, password: str) -> None:
        '''
        Ignores aws_access_key_id, aws_secret_access_key, 
        aws_session_token and use username and password instead.
        '''

        self._credentials = Credentials(username, password)

    def get_credentials(self) -> Credentials:
        '''
        Return the credentials associated with this session.
        '''

        return self._credentials

    def create_client(self,
                      service_name: str,
                      region_name: str = None,
                      api_version: str = None,
                      use_ssl: bool = True,
                      verify: Union[bool, str] = None,
                      endpoint_url: str = None,
                      username: str = None,
                      password: str = None,
                      config: Config = None) -> BaseClient:
        '''
        Create a low-level service client by name.
        '''

        default_client_config = self.get_default_client_config()
        # If a config is provided and a default config is set, then
        # use the config resulting from merging the two.
        if config and default_client_config:
            config = default_client_config.merge(config)
        # If a config was not provided then use the default
        # client config from the session
        elif default_client_config:
            config = default_client_config

        region_name = self._resolve_region_name(region_name, config)

        # Figure out the verify value base on the various
        # configuration options.
        if not verify:
            verify = self.get_config_variable('ca_bundle')

        if not api_version:
            api_version = self.get_config_variable('api_versions').get(
                service_name, None)

        loader = self.get_component('data_loader')
        event_emitter = self.get_component('event_emitter')
        response_parser_factory = self.get_component('response_parser_factory')

        if config and config.signature_version is UNSIGNED:
            credentials = None
        elif username and password:
            credentials = Credentials(username, password)
        elif self._missing_cred_vars(username, password):
            raise PartialCredentialsError(
                provider='explicit',
                cred_var=self._missing_cred_vars(username, password))
        else:
            credentials = self.get_credentials()

        endpoint_resolver = self._get_internal_component('endpoint_resolver')
        exceptions_factory = self._get_internal_component('exceptions_factory')
        config_store = self.get_component('config_store')

        client_creator = ClientCreator(
            loader, endpoint_resolver, self.user_agent(), event_emitter,
            retryhandler, translate, response_parser_factory,
            exceptions_factory, config_store)

        client = client_creator.create_client(
            service_name=service_name, region_name=region_name,
            is_secure=use_ssl, endpoint_url=endpoint_url, verify=verify,
            credentials=credentials, scoped_config=self.get_scoped_config(),
            client_config=config, api_version=api_version)

        monitor = self._get_internal_component('monitor')

        if monitor is not None:
            monitor.register(client.meta.events)

        return client

    def _missing_cred_vars(self,
                           username: str,
                           password: str) -> Union[None, str]:
        if username and not password:
            return 'password'
        if password and not username:
            return 'username'
        return None


def get_session(env_vars: dict = None) -> Session:
    '''
    Return a new session object.
    '''

    return Session(env_vars)