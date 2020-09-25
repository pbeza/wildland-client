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
Username and password variant of boto3 ResourceFactory for use with 
re-authorizing proxy.
'''

from boto3.docs import docstring
from boto3.resources.action import ServiceAction
from boto3.resources.factory import ResourceFactory as BotoResourceFactory


class ResourceFactory(BotoResourceFactory):
    def _create_action(factory_self, action_model, resource_name,
                       service_context, is_load: bool = False):
        """
        Creates a new method which makes a request to the underlying
        AWS service.
        """
        # Create the action in in this closure but before the ``do_action``
        # method below is invoked, which allows instances of the resource
        # to share the ServiceAction instance.

        action = ServiceAction(
            action_model, factory=factory_self,
            service_context=service_context
        )

        # A resource's ``load`` method is special because it sets
        # values on the resource instead of returning the response.
        if is_load:
            # We need a new method here because we want access to the
            # instance via ``self``.
            def do_action(self, *args, **kwargs):
                response = action(self, *args, **kwargs)
                self.meta.data = response

            # Create the docstring for the load/reload methods.
            lazy_docstring = docstring.LoadReloadDocstring(
                action_name=action_model.name,
                resource_name=resource_name,
                event_emitter=factory_self._emitter,
                load_model=action_model,
                service_model=service_context.service_model,
                include_signature=False
            )
        else:
            # We need a new method here because we want access to the
            # instance via ``self``.
            def do_action(self, *args, **kwargs):
                response = action(self, *args, **kwargs)

                if hasattr(self, 'load'):
                    # Clear cached data. It will be reloaded the next
                    # time that an attribute is accessed.
                    # TODO: Make this configurable in the future?
                    self.meta.data = None

                return response

            lazy_docstring = docstring.ActionDocstring(
                resource_name=resource_name,
                event_emitter=factory_self._emitter,
                action_model=action_model,
                service_model=service_context.service_model,
                include_signature=False
            )

        do_action.__name__ = str(action_model.name)
        do_action.__doc__ = lazy_docstring

        return do_action
