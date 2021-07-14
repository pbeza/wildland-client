# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                 Maja Kostacinska <maja@wildland.io>
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
Initial implementation of the git backend used to expose git repositories
as wildland containers
"""

#pylint: disable=no-member
import os
import logging
from typing import List, Union, Optional

from git import Repo, Blob, Tree, exc

logging.getLogger('git-client')

class GitClient:
    """
    GitClient reponsible for handling the cloned repository data
    """

    def __init__(self, repo_url: str, location: str,
                 username: Optional[str], password: Optional[str]):
        self.location = location
        self.username = username
        self.password = password
        if self.username and self.password:
            self.url = self.parse_url(repo_url)
        else:
            self.url = repo_url
        self.repo: Optional[Repo] = None

    def connect(self) -> None:
        """
        Clones the chosen repo to /tmp/git_repo/{directory uuid} and
        creates an instance of git.Repo so that all the neccessary
        information about the chosen repository can be accessed from the
        client.

        This method will initially try to clone the repo to the path disclosed in
        self.location. However, if the self.location path is not empty (i.e. a
        repository has already been cloned there), the instance found at
        self.location is utilized instead.
        """
        try:
            os.makedirs(self.location)
        except FileExistsError:
            pass

        try:
            self.repo = Repo.clone_from(url=self.url, to_path=self.location)
        except exc.GitCommandError:
        #fallback in case the repo has already been cloned to self.location
            self.repo = Repo(self.location)

    def parse_url(self, url: str) -> str:
        """
        Parses the initially provided url into one following the
        https://username:token@host.xz[:port]/path/to/repo.git so
        that the default command line authorization can be omitted.
        """
        assert self.username is not None
        assert self.password is not None
        url_parts = url.split('//')
        to_return = url_parts[0] + '//' + self.username + ':' + self.password + '@' + url_parts[1]
        return to_return

    def disconnect(self) -> None:
        """
        Clean up; used when unmounting the container
        """
        assert self.repo is not None
        self.repo = None

    def list_folder(self, path_parts: List[str]) -> List[Union[Blob, Tree]]:
        """
        Lists all git objects under the specified path
        """
        assert self.repo is not None
        assert self.repo.head is not None
        initial_tree = self.repo.head.commit.tree
        to_return = []

        for part in path_parts:
            initial_tree = initial_tree[part]

        for tree in initial_tree.trees:
            to_return.append(tree)

        for blob in initial_tree.blobs:
            to_return.append(blob)

        return to_return

    def get_commit_timestamp(self):
        """
        Returns the timestamp of the repo's HEAD commit
        """
        assert self.repo is not None
        assert self.repo.head is not None
        return self.repo.head.commit.committed_date

    def get_object(self, path_parts: List[str]) -> Union[Blob, Tree]:
        """
        Returns a git object (blob/tree) found under the specified path
        """
        assert self.repo is not None
        assert self.repo.head is not None
        initial_tree = self.repo.head.commit.tree

        for part in path_parts:
            initial_tree = initial_tree[part]

        return initial_tree

    def get_file_content(self, path_parts: List[str]) -> bytes:
        """
        Returns the content of a specified file in bytes
        """
        obj = self.get_object(path_parts)
        return obj.data_stream.read()
