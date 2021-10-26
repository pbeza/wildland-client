from typing import Iterable, List
import glob
import os
from pathlib import Path


class TravellerBase:
    def __init__(self, start_path: Path = Path.home()/"wildland") -> None:
        self.start_path = start_path

    def run(self) -> Iterable[Path]:
        raise NotImplementedError


class MarkdownEverySubdir(TravellerBase):
    def run(self) -> Iterable[Path]:
        return self.markdowns()

    def markdowns(self) -> Iterable[Path]:
        return self.start_path.glob("**/*.md")

    
if __name__=="__main__":
    traveller = MarkdownEverySubdir(start_path=Path.home()/"wildland/gitlab/cargo")
    print(list(traveller.run()))