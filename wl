#!/usr/bin/env python3
# https://gitlab.com/wildland/wildland-client/-/issues/472
#
import os
import pathlib
import sys
sys.path.insert(0, os.fspath(pathlib.Path(__file__).parent))

import progressbar
progressbar.streams.wrap_stdout()
progressbar.streams.wrap_stderr()
# https://github.com/WoLpH/python-progressbar/issues/254
sys.stdout.isatty = progressbar.streams.original_stdout.isatty
sys.stderr.isatty = progressbar.streams.original_stderr.isatty

from wildland.cli.cli_main import main
main()
