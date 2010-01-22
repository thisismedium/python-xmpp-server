## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""saxstream -- an asynchronous XML stream handler"""

from __future__ import absolute_import
import errno, socket, logging
from lxml import etree

__all__ = ('XMLHandler', 'XMLParser', 'XMLStream')

class XMLHandler(object):
    """Wrap a SAX ContentHandler up in the TCPHandler interface.  Here
    is an example XML Echo server:

        import sys, xmpp

        class Echo(object):

            def __init__(self, stream):
                self._stream = stream

            def start(self, name, attrs):
                self._stream.write('start %s %r\n' % (name, attrs.items()))

            def endElement(self, name):
                self._stream.write('end %s\n' % name)

            def data(self, data):
                self._stream.write('data: %r\n' % data)

            def close(self):
                self._stream.write('goodbye!')

        if __name__ == '__main__':
            xmpp.TCPServer(xmpp.XMLHandler(Echo)).listen(*sys.argv[1].split(':'))
    """

    def __init__(self, ContentHandler):
        self.ContentHandler = ContentHandler

    def __call__(self, sock, addr, io_loop):
        XMLStream(self.ContentHandler, sock, io_loop)
        return self

class XMLParser(etree.XMLParser):
    """Wrap the lxml XMLParser to require a target and prime the
    incremental parser to avoid hanging on an opening stream tag."""

    def __init__(self, target, **kwargs):
        etree.XMLParser.__init__(self, target=target, **kwargs)

        ## Prime the XMLParser.  Without this, if the first chunk
        ## contains only an opening tag (i.e. <stream:stream ...>),
        ## the ContentHandler events will not be triggered until the
        ## next chunk arrives.
        self.feed('')

    def reset(self):
        self.close()
        self.feed('') # Prime the XMLParser
        return self

    def close(self):
        try:
            etree.XMLParser.close(self)
        except etree.XMLSyntaxError:
            ## This exception can be thrown if the parser is
            ## closed before all open xml elements are closed.
            ## Ignore this since it's common with <stream:stream/>
            pass
        return self

class XMLStream(object):
    """An XML Stream based on the tornado IOStream class.  As data is
    read from the network socket, it is fed into a SAX parser.  SAX
    events are handled by an instance of the ContentHandler class,
    which should conform to Python's XMLReader interface and accept a
    XMLStream instance as the single argument to __init__()."""

    def __init__(self, ContentHandler, socket, io_loop):
        self.io_loop = io_loop
        self.socket = socket

        self._state = io_loop.ERROR | io_loop.READ
        self._wb = u''

        self._handler = ContentHandler(self)
        self._parser = XMLParser(self._handler)
        self._handler._connectionOpen()

        self.io_loop.add_handler(socket.fileno(), self._handle, self._state)

    def close(self):
        if self.socket:
            self._handler._connectionClosed()

            try:
                self._parser.close()
            except:
                logging.error(
                    'XMLStream: caught exception while closing parser.',
                    exc_info=True
                )

            self.io_loop.remove_handler(self.socket.fileno())
            self.socket.close()
            self.socket = None

        return self

    def reset(self):
        self._parser.reset()
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
