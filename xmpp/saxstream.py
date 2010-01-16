## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""saxstream -- an asynchronous XML stream handler"""

from __future__ import absolute_import
import errno, socket, logging
from xml import sax

__all__ = ('XMLHandler', 'SAXStream')

class XMLHandler(object):
    """Wrap a SAX ContentHandler up in the TCPHandler interface.  Here
    is an example XML Echo server:

        from xml import sax
        import tcpserver

        class Echo(sax.handler.ContentHandler):

            def __init__(self, stream):
                sax.handler.ContentHandler.__init__(self)
                self._stream = stream

            def startDocument(self):
                self._stream.write(u'<?xml version="1.0" encoding="utf-8"?>\n')

            def startElement(self, name, attrs):
                self._stream.write(u'<' + name)
                for (name, value) in attrs.items():
                    self._stream.write(u' %s="%s"' % (name, sax.saxutils.escape(value)))
                self._stream.write(u'>')

            def endElement(self, name):
                self._stream.write(u'</%s>' % name)

            def characters(self, content):
                self._stream.write(sax.saxutils.escape(content))

            def ignorableWhitespace(self, content):
                self._stream.write(content)

        tcpserver.TCPServer(XMLHandler(Echo)).listen('127.0.0.1', 9000)
    """

    def __init__(self, ContentHandler):
        self.ContentHandler = ContentHandler

    def __call__(self, sock, addr, io_loop):
        SAXStream(self.ContentHandler, sock, io_loop)

class SAXStream(object):
    """An XML Stream based on the tornado IOStream class.  As data is
    read from the network socket, it is fed into a SAX parser.  SAX
    events are handled by an instance of the ContentHandler class,
    which should conform to Python's XMLReader interface and accept a
    SAXStream instance as the single argument to __init__()."""

    def __init__(self, ContentHandler, socket, io_loop):
        self.io_loop = io_loop
        self.socket = socket

        self._state = io_loop.ERROR | io_loop.READ
        self._wb = u''

        self._parser = sax.make_parser()
        self._parser.setContentHandler(ContentHandler(self))

        self.io_loop.add_handler(socket.fileno(), self._handle, self._state)

    def close(self):
        if self.socket:
            try:
                self._parser.close()
            except:
                logging.error(
                    'SAXStream: caught exception while closing parser.',
                    exc_info=True
                )
            self.io_loop.remove_handler(self.socket.fileno())
            self.socket.close()
            self.socket = None
        return self

    def write(self, data):
        self._wb += data
        self._add_io_state(self.io_loop.WRITE)
        return self

    def _handle(self, fd, events):
        if events & self.io_loop.READ:
            self._read()
            if not self.socket:
                return

        if events & self.io_loop.WRITE:
            self._write()
            if not self.socket:
                return

        if events & self.io_loop.ERROR:
            self.close()
            return

        state = self.io_loop.ERROR | self.io_loop.READ
        if self._wb:
            state |= self.io_loop.WRITE
        if state != self._state:
            self._new_io_state(state)

    def _read(self):
        try:
            chunk = self.socket.recv(4096)
        except socket.error as exc:
            if exc[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
                return
            else:
                self.close()

        if not chunk:
            self.close()
            return

        self._parser.feed(chunk)

    def _write(self):
        while self._wb:
            try:
                sent = self.socket.send(self._wb)
                self._wb = self._wb[sent:]
            except socket.error as exc:
                if ex[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
                    break
                else:
                    self.close()
                    return

    def _add_io_state(self, state):
        if not self._state & state:
            self._new_io_state(self._state | state)

    def _new_io_state(self, state):
        self._state = state
        self.io_loop.update_handler(self.socket.fileno(), state)
