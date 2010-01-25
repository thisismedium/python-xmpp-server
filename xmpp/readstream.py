## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""readstream -- unbuffered reads / buffered writes on a non-blocking
socket."""

from __future__ import absolute_import
from tornado import ioloop

__all__ = ('ReadStream', )

class ReadStream(object):
    """A simplified version of Tornado's IOStream class that supports
    unbuffered reads and buffered writes.  This example uses a
    ReadStream to push data into an XML parser:

        import xmpp
        from lxml import etree

        class Target(object):

            def __init__(self, stream):
                self.stream = stream

            def start(self, name, attr):
                self.stream.write('start %r %r\n' % (name, attr.items()))

            def data(self, data):
                self.stream.write('data %r\n' % data)

            def stop(self, name):
                print 'stop', name
                self.stream.write('stop %r\n' % name)

            def close(self):
                self.stream.close()

        def parse(socket, addr, io_loop):
            print '%r connected.' % addr[0]
            stream = xmpp.ReadStream(socket, io_loop)
            parser = etree.XMLParser(target=Target(stream))
            parser.feed('') # Prime the parser.
            stream.read(parser.feed)

        if __name__ == '__main__':
            server = xmpp.TCPServer(parse).bind('127.0.0.1', '9000')
            xmpp.start([server])
    """

    def __init__(self, socket, io_loop=None, read_chunk_size=4096):
        self.socket = socket
        self.io_loop = io_loop or ioloop.IOLoop.instance()

        self._state = io_loop.ERROR
        self._reader = None
        self._read_chunk_size = read_chunk_size
        self._wb = u''

        self.io_loop.add_handler(socket.fileno(), self._handle, self._state)

    def read(self, reader):
        assert not self._reader, "There's already a reader installed."
        self._reader = reader
        self._add_io_state(self.io_loop.READ)
        return self

    def write(self, data):
        self._wb += data
        self._add_io_state(self.io_loop.WRITE)
        return self

    def close(self):
        if self.socket:
            self.io_loop.remove_handler(self.socket.fileno())
            self.socket.close()
            self.socket = None
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

        state = self.io_loop.ERROR
        if self._reader:
            state |= self.io_loop.READ
        if self._wb:
            state |= self.io_loop.WRITE
        if state != self._state:
            self._new_io_state(state)

    def _read(self):
        try:
            chunk = self.socket.recv(self._read_chunk_size)
        except socket.error as exc:
            if exc[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
                return
            else:
                self.close()

        if not chunk:
            self.close()
            return

        self._reader(chunk)

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
