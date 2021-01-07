'''
Wildland storage backend exposing read only IMAP mailbox
'''
import logging
import mimetypes
from functools import partial
from typing import Iterable, List, Dict
from datetime import timezone

import click
import uuid

from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.generated import \
    GeneratedStorageMixin, FuncFileEntry, FuncDirEntry
from .ImapClient import ImapClient, MessageEnvelopeData, \
    MessagePart
from .name_helpers import FileNameFormatter, TimelineFormatter
from .TimelineDate import TimelineDate, DatePart


logger = logging.getLogger('storage-imap')

class ImapStorageBackend(GeneratedStorageMixin, StorageBackend):
    '''
    Backend responsible for serving imap mailbox content.
    '''

    TYPE = 'imap'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.client = ImapClient(self.params['host'],
                                 self.params['login'],
                                 self.params['password'],
                                 self.params['folder'],
                                 self.params['ssl'])

    def mount(self):
        '''
        mounts the file system
        '''
        self.client.connect()
        logger.debug('backend is mounted')

    def umount(self):
        '''
        unmounts the filesystem
        '''
        self.client.disconnect()

    def _make_msg_container(self, env: MessageEnvelopeData) -> dict:
        '''
        Create a container manifest for a single mail message.
        '''
        logger.info(f'making msg container for msg {env.msg_uid}')
        ns = uuid.UUID(self.backend_id[:32])
        ident = str(env.msg_uid)
        paths = ['/.uuid/{!s}'.format(uuid.uuid3(ns, ident))]
        #        categories = get_message_categories
        return {
            'title': env.subject,
            'paths': paths,
            'backends': {'storage': [{
                'type': 'delegate',
                'reference-container': 'wildland:@default:@parent-container:',
                'subdirectory': '/' + ident
                }]}
        }

    def list_subcontainers(self) -> Iterable[dict]:
        for msg in self.client.all_messages_env():
            yield self._make_msg_container(msg)

    def get_root(self):
        '''
        returns wildland entry to the root directory
        '''
        logger.info(f'get_root() for {self.backend_id}')
        return FuncDirEntry('.', self._root)

    def _root(self):
        logger.info("_root() requested")
        for envelope in self.client.all_messages_env():
            yield FuncDirEntry(str(envelope.msg_uid) + ": " +
                               envelope.subject, 
                               partial(self._msg_contents, 
                                       envelope))

    def _msg_contents(self, e: MessageEnvelopeData):
        # This little method should populate the message directory
        # with message parts decomposed into MIME attachements.
        for part in self.client.get_message(e.msg_uid):
            yield FuncFileEntry(part.attachment_name, 
                                on_read=partial(self._read_part, 
                                                part),
                                timestamp=e.recv_t.replace(tzinfo=timezone.utc).timestamp())

    def _read_part(self, msg_part: MessagePart) -> bytes:
        return msg_part.content

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--host'], metavar='HOST',
                          help='imap server host name',
                          required=True),
            click.Option(['--login'], metavar='LOGIN',
                         help='imap account name / login',
                         required=True),
            click.Option(['--password'], metavar='PASSWORD',
                         help='imap account password',
                         required=True),
            click.Option(['--folder'], metavar='FOLDER',
                         default='INBOX',
                         show_default=True,
                         help='root folder to expose'),
            click.Option(['--ssl/--no-ssl'], metavar='SSL',
                         default=True,
                         show_default=True,
                         help='use encrypted connection')
            ]

    @classmethod
    def cli_create(cls, data):
        return {
            'host': data['host'],
            'login': data['login'],
            'password': data['password'],
            'folder': data['folder'],
            'ssl': data['ssl']
            }


def _filename(hdr) -> str:
    return f'{hdr.sender}-{hdr.subject}'
