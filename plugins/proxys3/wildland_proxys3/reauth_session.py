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
This module extends boto3.session module for use with re-authorizing
proxy.
'''

import copy
from typing import Union

from boto3.session import Session as BotoSession
from boto3.exceptions import ResourceNotExistsError, UnknownAPIVersionError
from boto3.resources.base import ServiceResource
from boto3.utils import LazyLoadedWaiterModel, ServiceContext
from botocore.exceptions import DataNotFoundError, UnknownServiceError
from botocore.client import BaseClient, Config

from .reauth_botocore.session import Session as BotocoreSession, get_session
from .reauth_resources.factory import ResourceFactory


class ReauthSession(BotoSession):
    '''
    Augments boto3 Session object to use the username and password based
    authentication.
    '''

    def __init__(self,
                 username: str,
                 password: str,
                 region_name: str = None,
                 botocore_session: BotocoreSession = None) -> None:
        if not botocore_session:
            # Create a new default session
            botocore_session = get_session()

        botocore_session.set_credentials(username, password)

        super().__init__(region_name=region_name,
                         botocore_session=botocore_session)

        self.resource_factory = ResourceFactory(
            self._session.get_component('event_emitter'))

    # It is used to override boto3.session.Session to use the username
    # and password based authentication
    # pylint: disable=arguments-differ

    def client(self,
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

        return self._session.create_client(
            service_name, region_name=region_name, api_version=api_version,
            use_ssl=use_ssl, verify=verify, endpoint_url=endpoint_url,
            username=username, password=password, config=config)

    def resource(self,
                 service_name: str,
                 region_name: str = None,
                 api_version: str = None,
                 use_ssl: bool = True,
                 verify: Union[bool, str] = None,
                 endpoint_url: str = None,
                 username: str = None,
                 password: str = None,
                 config: Config = None) -> ServiceResource:
        '''
        Create a resource service client by name
        '''

        try:
            resource_model = self._loader.load_service_model(
                service_name, 'resources-1', api_version)
        except UnknownServiceError:
            available = self.get_available_resources()
            has_low_level_client = (
                    service_name in self.get_available_services())
            raise ResourceNotExistsError(service_name, available,
                                         has_low_level_client)
        except DataNotFoundError:
            # This is because we've provided an invalid API version.
            available_api_versions = self._loader.list_api_versions(
                service_name, 'resources-1')
            raise UnknownAPIVersionError(
                service_name, api_version, ', '.join(available_api_versions))

        if api_version is None:
            # Even though botocore's load_service_model() can handle
            # using the latest api_version if not provided, we need
            # to track this api_version in boto3 in order to ensure
            # we're pairing a resource model with a client model
            # of the same API version.  It's possible for the latest
            # API version of a resource model in boto3 to not be
            # the same API version as a service model in botocore.
            # So we need to look up the api_version if one is not
            # provided to ensure we load the same API version of the
            # client.
            #
            # Note: This is relying on the fact that
            #   loader.load_service_model(..., api_version=None)
            # and loader.determine_latest_version(..., 'resources-1')
            # both load the same api version of the file.
            api_version = self._loader.determine_latest_version(
                service_name, 'resources-1')

        # Creating a new resource instance requires the low-level client
        # and service model, the resource version and resource JSON data.
        # We pass these to the factory and get back a class, which is
        # instantiated on top of the low-level client.
        if config is not None:
            if config.user_agent_extra is None:
                config = copy.deepcopy(config)
                config.user_agent_extra = 'Resource'
        else:
            config = Config(user_agent_extra='Resource')

        client = self.client(
            service_name, region_name=region_name, api_version=api_version,
            use_ssl=use_ssl, verify=verify, endpoint_url=endpoint_url,
            username=username, password=password, config=config)
        service_model = client.meta.service_model

        # Create a ServiceContext object to serve as a reference to
        # important read-only information about the general service.
        service_context = ServiceContext(
            service_name=service_name, service_model=service_model,
            resource_json_definitions=resource_model['resources'],
            service_waiter_model=LazyLoadedWaiterModel(
                self._session, service_name, api_version))

        # Create the service resource class.
        cls = self.resource_factory.load_from_definition(
            resource_name=service_name,
            single_resource_json_definition=resource_model['service'],
            service_context=service_context)

        return cls(client=client)
