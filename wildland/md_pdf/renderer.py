from typing import BinaryIO, DefaultDict, Iterable, List, Optional
from wildland.md_pdf.traveller import TravellerBase
from pathlib import Path
from markdown import markdown
from io import BytesIO
from weasyprint import HTML
from collections import defaultdict
from anytree import Node, RenderTree, PreOrderIter
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
    def __init__(self, traveller: TravellerBase, engine=Engine()):
        self.engine: Engine = engine
        self.traveller = traveller

    def run(self) -> None:
        ...


class BasicRenderer(RendererBase):
    def __init__(self, traveller: TravellerBase, engine=Engine()):
        super().__init__(traveller, engine)

    def squash_markdowns(self, paths: Iterable[Path]) -> str:
        markdowns: List[str] = []
        for n, path in enumerate(paths, start=1):
            print(f"squashing {n}th markdown")
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
    def _find_by_fullpath(node: Node, fullpath: str) -> Optional[Node]:
        r = Resolver('name')
        try:
            node = r.get(node, fullpath)
            return node
        except ChildResolverError:
            return None

    @staticmethod
    def _start_path_node(root: Node, start_path_tree_str: str) -> Node:
        """
        start_path in traveller term
        """
        node = BasicRenderer._find_by_fullpath(root, start_path_tree_str)
        assert node is not None
        return node

    @staticmethod
    def detach_from_parent(node: Node):
        node.parent = None
        assert node.is_root == True

    @staticmethod
    def _recursive_make_tree(dirs: List[str], parent: Node, root: Node, markdown_path: Path) -> Node:
        name = dirs[0]
        fullname = root.separator.join([BasicRenderer._node_fullpath(parent), name])
        child = BasicRenderer._find_by_fullpath(root, fullname)
        if child is None:
            child = Node(name, parent=parent)
        if len(dirs) == 1:
            child.markdown_path = markdown_path
            return child
        return BasicRenderer._recursive_make_tree(dirs[1:], child, root, markdown_path)

    def make_tree(self, paths: Iterable[Path]) -> Node:
        root = Node('#')
        for path in paths:
            dirs: List[str] = str(path).split("/")[1:]
            BasicRenderer._recursive_make_tree(dirs, parent=root, root=root, markdown_path=path)
        # print(RenderTree(root))

        start_path_tree_str =  "/#" + str(self.traveller.start_path)
        start_node = self._start_path_node(root, start_path_tree_str)
        self.detach_from_parent(start_node)
        return start_node

    def run(self) -> None:
        paths = list(self.traveller.run()) # all markdown paths discovered by traveller
        node = self.make_tree(paths) # internal tree
        print(RenderTree(node))

        for subnode in PreOrderIter(node):
            subpaths: List[Path] = [leaf.markdown_path for leaf in subnode.leaves]
            squashed = self.squash_markdowns(subpaths)

            # TODO create dirs, write squashed markdowns to pdf
            stream: BytesIO = self.engine.render(squashed)
            self.engine.render_to_file(squashed, Path('dupa.pdf'))        

if __name__ == "__main__":
    from wildland.md_pdf.traveller import MarkdownEverySubdir
    start_dir: Path = Path.home()/"wildland/gitlab/cargo"
    traveller = MarkdownEverySubdir(start_dir)
    renderer = BasicRenderer(traveller)
    renderer.run()