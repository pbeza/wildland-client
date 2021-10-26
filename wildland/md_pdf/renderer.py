from typing import BinaryIO, Iterable, List, Optional
from wildland.md_pdf.traveller import TravellerBase
from pathlib import Path
from markdown import markdown
from io import BytesIO
from weasyprint import HTML


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
        
    def run(self) -> None:
        files = list(self.traveller.run())
        # todo group into 1 pdf

        # fix me files[:2]
        squashed = self.squash_markdowns(files[:2])
        stream: BytesIO = self.engine.render(squashed)

        # todo write_to file
        print(squashed)


if __name__ == "__main__":
    from wildland.md_pdf.traveller import MarkdownEverySubdir
    start_dir: Path = Path.home()/"wildland/gitlab/cargo"
    traveller = MarkdownEverySubdir(start_dir)
    renderer = BasicRenderer(traveller)
    renderer.run()