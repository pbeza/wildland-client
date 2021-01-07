'''
ImapClient is a module delivering an IMAP mailbox representation
for wildland imap backend. The representation is read-only,
update-sensitive and includes primitive caching support.
'''

import logging
import time
import mimetypes
from dataclasses import dataclass
from threading import Thread, Lock
from typing import Iterable, Dict, List
from email.header import decode_header
from email.parser import BytesParser
from email import policy
from datetime import datetime
from imapclient import IMAPClient
from .TimelineDate import TimelineDate, DatePart

@dataclass(eq=True, frozen=True)
class MessageEnvelopeData:
    '''
    Compact representation of e-mail header, as we use it
    for processing internally.
    '''
    msg_uid: int
    sender: str
    subject: str
    recv_t: datetime
 
@dataclass(eq=True, frozen=True)
class MessagePart:
    '''
    DTO for message attachement / mime part of the message.
    '''
    attachment_name: str # can be None
    mime_type: str
    content: bytes

class ImapClient:
    '''
    IMAP protocol client implementation adding some additional
    level of abstraction over generic IMAPClient to expose
    the features needed by the wildland filesystem.
    '''

    def __init__(self, host: str, login: str, password: str,
                 folder: str, ssl: bool):
        self.logger = logging.getLogger('ImapClient')
        self.logger.debug('creating IMAP client for host: %s', host)
        self.imap = IMAPClient(host, use_uid=True, ssl=ssl)
        self.login = login
        self.password = password
        self.folder = folder
        self._envelope_cache = dict()

        # message id: message contents (only populated, when
        # messge content is requested)
        self._message_cache = dict()

        # all ids retrieved
        self._all_ids = list()

        # lock guarding access to local data structures
        self._local_lock = Lock()

        # monitor thread monitors changes to the inbox and
        # updates the cache accordingly
        self._monitor_thread = None
        self._connected = False

        # lock guarding access to imap client
        self._imap_lock = Lock()


    def connect(self):
        '''
        Connect to IMAP server and start periodic monitoring task.
        '''
        self.logger.debug('connecting to IMAP server')
        self.imap.login(self.login, self.password)
        self.imap.select_folder(self.folder)
        self._envelope_cache = dict()
        self._message_cache = dict()
        self._all_ids = list()

        self._connected = True

        # self._monitor_thread = Thread(target=self._monitor_main)
        # self._monitor_thread.start()

    def disconnect(self):
        '''
        disconnect from IMAP server.
        '''
        self.logger.debug('disconnecting from IMAP server')
        self._connected = False
        self._monitor_thread.join()
        self._monitor_thread = None
        with self._imap_lock:
            self.imap.logout()

    def all_messages_env(self) -> Iterable[MessageEnvelopeData]:
        self._load_messages_if_needed()
        self.logger.debug(f'here is what ecache is: {self._envelope_cache}')

        ## ?
        with self._local_lock: 
            for msgid, envelope in self._envelope_cache.items():
                yield envelope
 

    def get_message(self, msg_id) -> List[MessagePart]:
        '''
        Read and return single message (basic headers and
        main contents) as byte array.
        '''
        self.logger.debug(f'get_message called for: {msg_id}')
        with self._local_lock:
            if msg_id not in self._message_cache:
                self._message_cache[msg_id] = self._load_msg(msg_id)
            rv = self._message_cache[msg_id]

        self.logger.debug(f'now leaving get_message')
        return rv

    def _load_messages_if_needed(self):
        '''
        Load message headers if needed to populate the cache.
        Current implementation doesn't allow for incremental
        cache updates, so every time the cache is being refreshed
        the whole message list is being retrieved. This is
        likely something to be addressed in future.
        '''

        self.logger.debug('entering _load_messages_if_needed')
        with self._local_lock:
            if self._envelope_cache:
                self.logger.debug('fast-leaving _load_messages_if_needed')
                return

        with self._imap_lock, self._local_lock:
            msg_ids = self.imap.search('ALL')
            self._all_ids = msg_ids
            for msgid, data in self.imap.fetch(msg_ids,
                                               ['ENVELOPE']).items():
                env = data[b'ENVELOPE']
                self._register_envelope(msgid, env)
        self.logger.debug('leaving _load_messages_if_needed')

    def _load_msg(self, mid) -> List[MessagePart]:
        '''
        Load a message with given identifier from IMAP server and
        return it as a "pretty string".
        '''
        self.logger.debug('fetching message %d', mid)
        rv = list()
        with self._imap_lock:
            data = self.imap.fetch([mid], 'RFC822')
        parser = BytesParser(policy=policy.default)
        msg = parser.parsebytes(data[mid][b'RFC822'])
        sender = msg['From']
        subj = msg['Subject']
        subj = _decode_subject(subj)

        recv = msg['Date']


        body = msg.get_body(('html', 'plain'))
        content = body.get_payload(decode=True)
        charset = body.get_content_charset()
        if not charset:
            charset = 'utf-8'
        content = content.decode(charset)
        content = bytes(content, charset)
        ctype = body.get_content_type()
        rv.append(MessagePart(subj +
                              mimetypes.guess_extension(ctype),
                              ctype, content))

        for att in msg.iter_attachments():
            content = att.get_payload(decode=True)
            charset = att.get_content_charset()
            if not charset:
                charset = 'utf-8'
            if content is str:
                content = bytes(content, 'utf-8')
            part = MessagePart(att.get_filename(), 
                               att.get_content_type(),
                               content)
            rv.append(part)
        return rv

    def _del_msg(self, msg_id):
        '''
        remove message from local cache
        '''
        hdr = None
        for lst in self._senders.values():
            for an_id, a_hdr in lst:
                if an_id == msg_id:
                    hdr = a_hdr
                    lst.remove((an_id, a_hdr))
                    break
            if hdr is not None:
                break
        if hdr is not None:
            if msg_id in self._message_cache:
                del self._message_cache[msg_id]
            rd = TimelineDate(DatePart.DAY, hdr.recv_t)
            self._timeline[rd.up_to(DatePart.EPOCH)] \
                [rd.up_to(DatePart.YEAR)] \
                [rd.up_to(DatePart.MONTH)] \
                [rd.up_to(DatePart.DAY)].remove((msg_id, hdr))
            self._all_ids.remove(msg_id)

    def _prefetch_msg(self, msg_id):
        '''
        Fetch headers of given message and register them in
        cache.
        '''
        data = self.imap.fetch([msg_id], 'ENVELOPE')
        self.logger.debug('for msg %d received env %s', msg_id, data)
        env = data[msg_id][b'ENVELOPE']
        self._register_envelope(msg_id, env)

    def _register_envelope(self, msgid, env):
        '''
        Create sender and timeline cache entries, based on
        raw envelope of received message.
        '''

        if env.sender:
            saddr = env.sender[0]
        else:
            saddr = env.from_[0]

        sender = f'{saddr.mailbox.decode()}@{saddr.host.decode()}'
        sub = decode_header(env.subject.decode())
        subject = _decode_subject(sub)

        # TODO: MessageEnvelopeData needs refactor, represent all senders
        # and receipients!
        hdr = MessageEnvelopeData(msg_uid=msgid, sender=sender, 
                                  subject=subject, 
                                  recv_t=env.date)
        self._envelope_cache[msgid] = hdr
        self._all_ids.append(msgid)
        self.logger.debug('message %d added to sender %s', msgid, sender)


    def _invalidate_and_reread(self):
        '''
        invalidate local message list. Reread and update index.
        '''
        with self._local_lock:
            srv_msg_ids = self.imap.search('ALL')
            ids_to_remove = set(self._all_ids) - set(srv_msg_ids)
            ids_to_add = set(srv_msg_ids) - set(self._all_ids)
            self.logger.debug('invalidate_and_reread ids_to_remove=%s ids_to_add=%s',
                              ids_to_remove, ids_to_add)
            for mid in ids_to_remove:
                self.logger.debug('removing from cache message %d', mid)
                self._del_msg(mid)

            for mid in ids_to_add:
                self.logger.debug('adding to cache message %d',
                                  mid)
                self._prefetch_msg(mid)

    def _monitor_main(self):
        while self._connected:
            with self._imap_lock:
                reply = self.imap.noop()
                if len(reply) > 1:
                    try:
                        self._invalidate_and_reread()
                    except Exception:
                        self.logger.error("exception in monitor thread",
                                          exc_info=True)
                else:
                    self.logger.warning('unknown response received: %s', reply)
            time.sleep(10)

def _decode_subject(sub) -> str:
    if isinstance(sub, str):
        rv = sub
    else:
        rv = ''
        for (subject, charset) in sub:
            if isinstance(subject, str):
                rv += subject
            else:
                if not charset:
                    charset = 'utf-8'
                rv += subject.decode(charset)
    return rv
