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
It's example test script, which demonstrated how to use wildland.md_pdf module.
Real use case:
generate mirrored directory tree of gitlab-backend's markdowns as squashed pdfs on every dir level
"""

from pathlib import Path
from wildland.md_pdf.renderer import MarkdownRenderer

if __name__ == "__main__":
    #pylint: disable=line-too-long
    write_start_dir = Path.home()/"wildland/mydirs/ariadne:/forests/pandora:/home/mhaponiuk/cargo_markdowns" # local fs dir

    MarkdownRenderer(Path.home()/"wildland/gitlab/cargo", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/labels", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/milestones", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/projects", write_start_dir).run()
    MarkdownRenderer(Path.home()/"wildland/timeline", write_start_dir).run()
