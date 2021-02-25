# Wildland project
#
# Copyright (C) 2020 Golem Foundation,
#                    Piotr K. Isajew <piotr@wildland.io>
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

'''
A simple configuration for Python logging system to divert all messages to 
Apple's Unified Logging.
'''

import logging
from PBRLogBridge import log_message

class apple_log(logging.StreamHandler):

    def __init__(self):
        logging.StreamHandler.__init__(self)

    def emit(self, record):
        text = self.format(record)
        log_message(text)

    @staticmethod
    def configure():
#        cfg = {
#            'version': 1,
#            'handlers': {
#                'ios_log': {} # here the class
#            },
#            'root': {
#                'handlers': ['ios_log'],
#                'level': 'DEBUG',
#            }
#        }
        ioshandler = apple_log()
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger().addHandler(ioshandler)
