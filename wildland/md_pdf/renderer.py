# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Michał Haponiuk <mhaponiuk@wildland.io>,
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
Test module to generate mirrored directory tree,
based on gitlab-backend's markdowns, to squashed pdfs on every dir level
example:

source_dir:
    dir1:
        m1.md
    dir2:
        dir21:
            m21.md
result dir:
    source_dir:
        squashed_issues_m1_m21.pdf
        dir1:
            m1.pdf
        dir2:
            m21.pdf
            dir21:
                m21.pdf
"""

from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional, Set

from anytree import Node, PreOrderIter, RenderTree
from anytree.resolver import ChildResolverError, Resolver
from markdown import markdown
from weasyprint import HTML


class Engine:
    """
    used by MarkdownRenderer
    provideds idepedent functions to render pdf from markdown text
    """
    # pylint: disable=missing-docstring
    @staticmethod
    def render(text: str) -> BytesIO:
        html = markdown(text, output_format='html')
        stream = BytesIO()
        HTML(string=html).write_pdf(stream)
        return stream

    # pylint: disable=missing-docstring
    @staticmethod
    def render_to_file(text: str, path: Path) -> None:
        html = markdown(text, output_format='html')
        HTML(string=html).write_pdf(path)


class MarkdownRenderer:
    """"
    Main module class - does all job -> see run() method
    """
    def __init__(self, read_start_dir: Path, write_start_dir: Path):
        self.read_start_dir = read_start_dir
        self.write_start_dir = write_start_dir
        self.engine = Engine()

    def _find_markdowns(self) -> Iterable[Path]:
        return self.read_start_dir.glob("**/*.md")

    @staticmethod
    def squash_markdowns(paths: Iterable[Path]) -> str:
        """
        joins many markdown files into 1 big markdown
        """
        markdowns: List[str] = []
        for n, path in enumerate(paths, start=1):
            print(f"squashing {n}th markdown -- {path.name}")
            title_header = f"# {path.name.strip('.md')}\n"
            markdowns.append(title_header)
            with path.open("rt") as f:
                markdowns.append(f.read())
            markdowns.append('\n')
        squashed = "\n".join(markdowns)
        return squashed

    @staticmethod
    def _node_fullpath(node: Node) -> str:
        """
        example
        args node=Node('/#/home/user/wildland/gitlab/cargo/file.md')
        returns '/#/home/user/wildland/gitlab/cargo/file.md'
        """
        return "/" + node.separator.join([n.name for n in reversed(list(node.iter_path_reverse()))])

    @staticmethod
    def _find_node_by_fullpath(node: Node, fullpath: str) -> Optional[Node]:
        """
        example
        args node=Node('/#'), fullpath='/#/home/user/wildland/gitlab/cargo'
        returns Node('/#/home/user/wildland/gitlab/cargo') or None if does not exist
        """
        r = Resolver('name')
        try:
            node = r.get(node, fullpath)
            return node
        except ChildResolverError:
            return None

    @staticmethod
    def _detach_from_parent(node: Node):
        node.parent = None
        assert node.is_root is True

    @staticmethod
    #pylint: disable=line-too-long
    def _recursive_make_tree(dirs: List[str], parent: Node, root: Node, markdown_path: Path) -> Node:
        name = dirs[0]
        fullname = root.separator.join([MarkdownRenderer._node_fullpath(parent), name])
        child = MarkdownRenderer._find_node_by_fullpath(root, fullname)
        if child is None:
            child = Node(name, parent=parent)
        if len(dirs) == 1:
            child.markdown_path = markdown_path
            return child
        return MarkdownRenderer._recursive_make_tree(dirs[1:], child, root, markdown_path)

    def _make_tree(self, paths: Iterable[Path]) -> Node:
        root = Node('#')
        for path in paths:
            dirs: List[str] = str(path).split("/")[1:]
            MarkdownRenderer._recursive_make_tree(dirs, parent=root, root=root, markdown_path=path)
        # print(RenderTree(root))

        start_path_tree_str =  "/#" + str(self.read_start_dir)
        start_node = MarkdownRenderer._find_node_by_fullpath(root, start_path_tree_str)
        assert start_node is not None
        self._detach_from_parent(start_node)
        return start_node

    @staticmethod
    def _unique_files(paths: List[Path]) -> Set[Path]:
        return set({p.name: p for p in paths}.values())

    def run(self) -> None:
        """
        main method, starts job, creates dirs and renders pdfs
        """
        paths: List[Path] = list(self._find_markdowns())
        node = self._make_tree(paths)
        print(RenderTree(node))

        for subnode in PreOrderIter(node):
            if subnode.is_leaf:
                continue
            subpaths: List[Path] = [leaf.markdown_path for leaf in subnode.leaves]
            unique_subpaths = self._unique_files(subpaths)
            print(f"squshing {len(unique_subpaths)} files")
            squashed = self.squash_markdowns(unique_subpaths)
            out_dir: Path = self.write_start_dir / self._node_fullpath(subnode).strip("/")
            out_dir.mkdir(parents=True, exist_ok=True)
            self.engine.render_to_file(squashed, out_dir/'issues.pdf')


if __name__ == "__main__":
    # example use case, for faster start of development (and debugging)
    source = Path.home()/"wildland/gitlab/cargo" # mounted wildland gitlab backend container
    results = Path.home()/"wildland-client/cargo_issues" # local fs dir
    MarkdownRenderer(read_start_dir=source, write_start_dir=results).run()
