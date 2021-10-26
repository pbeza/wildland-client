from typing import List, Optional
from wildland.md_pdf.renderer import RendererBase

from wildland.md_pdf.traveller import TravellerBase


class Controller:
    def __init__(self, renderers: Optional[List[RendererBase]]=None) -> None:
        if renderers is not None:
            self.renderers: List[RendererBase] = renderers
        else:
            self.renderers = []

    def run(self):
        for renderer in self.renderers:
            renderer.run()

if __name__ == "__main__":
    ...