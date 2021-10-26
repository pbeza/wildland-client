from typing import BinaryIO, DefaultDict, Iterable, List, Optional
from wildland.md_pdf.traveller import TravellerBase
from pathlib import Path
from markdown import markdown
from io import BytesIO
from weasyprint import HTML
from collections import defaultdict
from anytree import Node, RenderTree
from anytree.search import findall
from anytree.resolver import Resolver, ChildResolverError


class Engine:
    @staticmethod
    def render(text: str) -> BytesIO:
        html = markdown(text, output_format='html4')
        stream = BytesIO()
        # HTML(string=html).write_pdf("/home/user/wildland-client/pdf.pdf")
        HTML(string=html).write_pdf(stream)
        return stream

    @staticmethod
    def render_to_file(text: str, path: Path) -> None:
        html = markdown(text, output_format='html4')
        HTML(string=html).write_pdf(path)


class RendererBase:
    def __init__(self, traveller: TravellerBase, engine=Engine):
        self.engine = engine
        self.traveller = traveller

    def run(self) -> None:
        ...


class BasicRenderer(RendererBase):
    def __init__(self, traveller: TravellerBase, engine=Engine):
        super().__init__(traveller, engine)

    def squash_markdowns(self, paths: Iterable[Path]) -> str:
        markdowns: List[str] = []
        for path in paths:
            title_header = f"# {path.name.strip('.md')}\n"
            with path.open("rt") as f:
                markdowns.append(title_header)
                markdowns.append(f.read())
                markdowns.append('\n')
        squashed = "\n".join(markdowns)
        return squashed

    @staticmethod
    def _node_fullpath(node: Node) -> str:
        """
        from Node('/root/home/user/wildland/gitlab/cargo/file.md')
        to
        '/root/home/user/wildland/gitlab/cargo/file.md'
        """
        return "/" + node.separator.join([n.name for n in reversed(list(node.iter_path_reverse()))])

    @staticmethod
    def _find_by_fullpath(root: Node, fullpath: str) -> Optional[Node]:
        r = Resolver('name')
        try:
            node = r.get(root, fullpath)
            return node
        except ChildResolverError:
            return None

    def _start_path_node(self, root: Node) -> Node:
        """
        start_path in traveller term
        """
        node = BasicRenderer._find_by_fullpath(root, traveller.start_path)
        assert node is not None
        return node

    @staticmethod
    def _recursive_make_tree(dirs: List[str], parent: Node, root: Node) -> Node:
        name = dirs[0]
        fullname = root.separator.join([BasicRenderer._node_fullpath(parent), name])
        child = BasicRenderer._find_by_fullpath(root, fullname)
        if child == None:
            child = Node(name, parent=parent)
        if len(dirs) == 1:
            return child
        return BasicRenderer._recursive_make_tree(dirs[1:], child, root)

    def make_tree(self, paths: Iterable[Path]) -> Node:
        root = Node('#')
        for path in paths:
            dirs: List[str] = str(path).split("/")[1:]
            BasicRenderer._recursive_make_tree(dirs, parent=root, root=root)
        # print(RenderTree(root))

        # trim from root to start_path dir
        r = Resolver('name')
        node = r.get(root, "/#" + str(self.traveller.start_path))
        node.parent = None
        return node

    def run(self) -> None:
        paths = list(self.traveller.run())
        node = self.make_tree(paths)
        print(RenderTree(node))
        
        # fix me files[:2]
        squashed = self.squash_markdowns(paths[:2])
        stream: BytesIO = self.engine.render(squashed)
        # todo write_to file
        # print(squashed)


if __name__ == "__main__":
    from wildland.md_pdf.traveller import MarkdownEverySubdir
    start_dir: Path = Path.home()/"wildland/gitlab/cargo"
    traveller = MarkdownEverySubdir(start_dir)
    renderer = BasicRenderer(traveller)
    renderer.run()