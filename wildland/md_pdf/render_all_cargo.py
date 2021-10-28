from pathlib import Path
from wildland.md_pdf.renderer import MarkdownRenderer

if __name__ == "__main__":
    write_start_dir = Path.home()/"wildland/mydirs/ariadne:/forests/pandora:/home/mhaponiuk/cargo_markdowns" # local fs dir

    MarkdownRenderer(Path.home()/"wildland/gitlab/cargo", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/labels", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/milestones", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/projects", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/timeline", write_start_dir).run()