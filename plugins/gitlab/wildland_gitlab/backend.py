# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                       Maja Kostacinska <maja@wildland.io>
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
Wildland storage backend exposing GitLab issues
"""

# pylint: disable=no-member
import stat
from typing import List, Tuple, Dict, Any
from functools import partial
from pathlib import PurePosixPath
from datetime import datetime

import uuid
import click

from wildland.container import ContainerStub
from wildland.storage_backends.base import StorageBackend, Attr, File, StorageParam
from wildland.manifest.schema import Schema
from wildland.storage_backends.generated import GeneratedStorageMixin, FuncDirEntry, \
    FileEntry, StaticFile
from wildland.log import get_logger
from .gitlab_client import GitlabClient, CompactIssue

logger = get_logger('GitlabBackend')


class GitlabFileEntry(FileEntry):
    """
    A slightly modified version of the StaticFileEntry class in the .generated module.
    Provides an option to create a file entry based on the file's size; thus, the
    actual content of the file is not necessary up until the file is to be opened.
    """

    def __init__(self,
                 issue: CompactIssue,
                 client: GitlabClient,
                 ):
        super().__init__(f'{issue.title}.md')
        self.issue = issue
        self.client = client

        self.attr = Attr(
            size=issue.issue_size,
            timestamp=int(datetime.timestamp(issue.updated_at)),
            mode=stat.S_IFREG | 0o444
        )

    def getattr(self) -> Attr:
        return self.attr

    def open(self, flags: int) -> File:
        description = self.client.get_issue_description(self.issue)
        return StaticFile((str(description)).encode('utf-8'), self.attr)


class GitlabStorageBackend(GeneratedStorageMixin, StorageBackend):
    """
    Storage backend for GitLab issues
    """

    TYPE = 'gitlab'
    SCHEMA = Schema({
        "title": "Storage manifest (GitLab)",
        "type": "object",
        "required": ["server_url", "personal_token"],
        "properties": {
            "server_url": {
                "type": "string",
                "description": "GitLab url; default: https://gitlab.com/"
            },
            "personal_token": {
                "type": "string",
                "description": "personal access token generated by GitLab"
            },
            "projectid": {
                "type": "string",
                "description": "(optional) GitLab project ID."
            }
        }
    })

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.read_only = True
        project_id = self.params.get('projectid')
        self.client = GitlabClient(url=self.params['server_url'],
                                   personal_token=self.params['personal_token'],
                                   project_id=project_id)
        self.all_compact_issues: List[CompactIssue] = []

    def mount(self):
        """
        Forms a connection to the GitLab server
        """
        self.client.connect()
        logger.debug('fetching a list of issues now:')
        self.all_compact_issues = self.client.get_compact_issues()

    def unmount(self):
        """
        Severs the previously formed connection with the server
        """
        self.client.disconnect()

    def _issue_content(self, issue: CompactIssue):
        """
        Creates a StaticFileEntry from a single issue description
        """
        yield GitlabFileEntry(issue, self.client)

    def get_root(self):
        return FuncDirEntry('.', self._root)

    def _root(self):
        for issue in self.all_compact_issues:
            yield FuncDirEntry(self._id_issue(issue),
                               partial(self._issue_content, issue))

    @property
    def can_have_children(self) -> bool:
        return True

    def get_children(self, client=None, query_path: PurePosixPath = PurePosixPath('*')):
        """
        Creates a separate container for each of the issues fetched from the server
        """
        logger.debug('creating subcontainers for the issues')
        assert self.all_compact_issues is not None
        for issue in self.all_compact_issues:
            yield self._make_issue_container(issue)
        logger.debug('subcontainers succesfully created')

    @classmethod
    def _get_issue_categories(cls, issue: CompactIssue) -> List[str]:
        """
        Provides a list of categories the issue will appear under.
        As of right now, the main category patterns are:
        - /timeline/YYYY/MM/DD
        - /labels/ISSUE_NAME (separate category for each of the issue's labels)
        - /projects/PROJECT_NAME
        - /milestones/MILESTONE_TITLE
        """
        paths = []
        to_return = []

        # date
        date = issue.updated_at
        paths.append(PurePosixPath('/timeline') /
                     PurePosixPath('%04d' % date.year) /
                     PurePosixPath('%02d' % date.month) /
                     PurePosixPath('%02d' % date.day))

        # labels
        if issue.labels:
            for label in issue.labels:
                to_append = PurePosixPath('/labels')
                l = label.split('::')
                for part in l:
                    to_append = to_append / PurePosixPath(part)
                paths.append(to_append)

        # project_name
        paths.append(PurePosixPath('/projects') /
                     PurePosixPath(f'{issue.project_name}'))

        # milestones
        if issue.milestone_title:
            paths.append(PurePosixPath('/milestones') /
                         PurePosixPath(issue.milestone_title))

        for path in paths:
            to_return.append(str(path))

        return to_return

    def _id_issue(self, issue: CompactIssue) -> str:
        """
        Generates an uuid necessary in order to create the path for the subcontainers
        """
        return str(uuid.uuid3(uuid.UUID(self.backend_id), str(issue.ident)))

    def _make_issue_container(self, issue: CompactIssue) -> Tuple[PurePosixPath, ContainerStub]:
        """
        Creates a separate subcontainer for each of the issues fetched from the server
        """
        issue_uuid = self._id_issue(issue)
        paths = [f'/.uuid/{issue_uuid}']
        categories = self._get_issue_categories(issue)
        subcontainer_path = '/' + issue_uuid
        return PurePosixPath(subcontainer_path), ContainerStub({
            'paths': paths,
            'title': issue.title,
            'categories': categories,
            'backends': {'storage': [{
                'type': 'delegate',
                'reference-container': 'wildland:@default:@parent-container:',
                'subdirectory': subcontainer_path
            }]}
        })

    @classmethod
    def storage_options(cls) -> List[StorageParam]:
        return [
            StorageParam('server_url',
                         display_name='URL',
                         default_value='https://gitlab.com/',
                         description='GitLab server url'
                         ),
            StorageParam('personal_token',
                         required=True,
                         description='personal access token generated by GitLab; '
                                     'used for authorization purposes'
                         ),
            StorageParam('projectid',
                         description='(optional) GitLab project ID. Can be copied from the '
                                     'Project ID field upon entering the desired project.'
                         )
        ]

    @classmethod
    def validate_and_parse_params(cls, params) -> Dict[str, Any]:
        data = {
            'server_url': params['server_url'],
            'personal_token': params['personal_token'],
            'projectid': params['projectid']
        }
        data = cls.remove_non_required_params(data)

        cls.SCHEMA.validate(data)
        return data

    @classmethod
    def cli_options(cls):
        return [
            click.Option(
                ['--server-url'], metavar='URL',
                default='https://gitlab.com/',
                show_default=True,
                help='GitLab server url'),
            click.Option(
                ['--personal-token'], required=True,
                help='personal access token generated by GitLab; used for authorization purposes'),
            click.Option(
                ['--projectid'], required=False,
                help='(optional) GitLab project ID. Can be copied from the Project ID field upon'
                     ' entering the desired project.')
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'server_url': data['server_url'],
            'personal_token': data['personal_token'],
            'projectid': data['projectid']
        }
