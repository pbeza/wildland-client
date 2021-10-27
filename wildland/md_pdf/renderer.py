from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional

from anytree import Node, PreOrderIter, RenderTree
from anytree.resolver import ChildResolverError, Resolver
from markdown import markdown
from weasyprint import HTML


class Engine:
    @staticmethod
    def render(text: str) -> BytesIO:
        html = markdown(text, output_format='html')
        stream = BytesIO()
        # HTML(string=html).write_pdf("/home/user/wildland-client/pdf.pdf")
        HTML(string=html).write_pdf(stream)
        return stream

    @staticmethod
    def render_to_file(text: str, path: Path) -> None:
        html = markdown(text, output_format='html')
        HTML(string=html).write_pdf(path)


class MarkdownRenderer:
    def __init__(self, read_start_dir: Path, write_start_dir: Path):
        self.read_start_dir = read_start_dir
        self.write_start_dir = write_start_dir
        self.engine = Engine()

    def find_markdowns(self) -> Iterable[Path]:
        return self.read_start_dir.glob("**/*.md")

    @staticmethod
    def squash_markdowns(paths: Iterable[Path]) -> str:
        markdowns: List[str] = []
        for n, path in enumerate(paths, start=1):
            print(f"squashing {n}th markdown")
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
    def detach_from_parent(node: Node):
        node.parent = None
        assert node.is_root == True

    @staticmethod
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

    def make_tree(self, paths: Iterable[Path]) -> Node:
        root = Node('#')
        for path in paths:
            dirs: List[str] = str(path).split("/")[1:]
            MarkdownRenderer._recursive_make_tree(dirs, parent=root, root=root, markdown_path=path)
        # print(RenderTree(root))

        start_path_tree_str =  "/#" + str(self.read_start_dir)
        start_node = MarkdownRenderer._find_node_by_fullpath(root, start_path_tree_str)
        assert start_node is not None
        self.detach_from_parent(start_node)
        return start_node

    def run(self) -> None:
        paths: Iterable[Path] = self.find_markdowns()
        # paths = list(paths)[:5]
        node = self.make_tree(paths) # internal tree
        print(RenderTree(node))

        for subnode in PreOrderIter(node):
            if subnode.is_leaf:
                continue
            subpaths: List[Path] = [leaf.markdown_path for leaf in subnode.leaves]
            squashed = self.squash_markdowns(subpaths)
            out_dir: Path = self.write_start_dir / self._node_fullpath(subnode).strip("/")      
            out_dir.mkdir(parents=True, exist_ok=True)
            self.engine.render_to_file(squashed, out_dir/'issues.pdf')


if __name__ == "__main__":
    MarkdownRenderer(
        read_start_dir=Path.home()/"wildland/gitlab/cargo", # mounted wildland gitlab backend container
        write_start_dir=Path.home()/"wildland-client/cargo_issues" # local fs dir
    ).run()
    MarkdownRenderer(
        read_start_dir=Path.home()/"wildland/labels/needs/breakdown",
        write_start_dir=Path.home()/"wildland-client/cargo_issues"
    ).run()