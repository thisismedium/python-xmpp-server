## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""readstream -- non-blocking unbuffered reads / buffered writes"""

from __future__ import absolute_import
from . import aio
from .prelude import *

__all__ = ('ReadStream', )

class ReadStream(object):
    """A simplified version of Tornado's IOStream class that supports
    unbuffered reads and buffered writes."""

    def __init__(self, socket, io=None, read_chunk_size=4096):
        self.socket = socket
        self.io = io or aio.loop()

        self._state = io.ERROR
        self._read_chunk_size = read_chunk_size
        self._wb = u''

        self._reader = None
        self._write_callback = None
        self._close_callback = None

        self.io.add_handler(socket.fileno(), self._handle, self._state)

    def read(self, reader):
        """Add a reader to this stream.  There can only be one reader
        at a time; it is called with each chunk received from the
        socket."""

        assert not self._reader, "There's already a reader installed."
        self._reader = reader
        self._add_io_state(self.io.READ)
        return self

    def write(self, data, callback=None):
        """Write data to the stream.  The data is sent immediately;
        any data that cannot be sent is buffered.  Once the write
        buffer is emptied, the optional callback is called."""

        self._wb += data
        self._write_callback = callback
        self._wb and self._write()
        return self

    def shutdown(self, callback=None):
        """Close this stream once the write buffer is emptied and
        optionally run callback."""

        if self.socket:
            self._reader = None
            if callback:
                self._close_callback = callback
            if self._wb:
                self._write_callback = self.close
            else:
                self.close()
        return self

    def close(self):
        """Immediately close the stream."""

        if self.socket:
            self.io.remove_handler(self.socket.fileno())
            self.socket.close()
            self.socket = None
            self._close_callback and self._close_callback()
        return self

    def on_close(self, callback):
        """Register a callback that is run after the stream is closed."""

        self._close_callback = callback
        return self

    def starttls(self, callback=None, **options):
        """Begin TLS negotiation; options are passed through to
        do_handshake().  If callback is given, it is called after a
        successful negotiation."""

        ## Delay starttls until the write-buffer is emptied.
        if self._wb:
            self._write_callback = partial(self.starttls, callback, **options)
            return

        def success(socket):
            self.socket = socket
            self.io.add_handler(socket.fileno(), self._handle, self._state)
            callback and callback()

        def failure(socket):
            self.socket = socket
            self.close()

        ## Wrap the socket; give startttls() control until the
        ## handshake is finished.
        aio.starttls(self.socket, success, failure, self.io, **options)

        ## Temporarily set this to None so _handle() doesn't
        ## self.io.update_handler()
        self.socket = None

    def _handle(self, fd, events):
        if events & self.io.READ:
            self._read()
            if not self.socket:
                return

        if events & self.io.WRITE:
            self._write()
            if not self.socket:
                return

        if events & self.io.ERROR:
            self.close()
            return

        state = self.io.ERROR
        if self._reader:
            state |= self.io.READ
        if self._wb:
            state |= self.io.WRITE
        if state != self._state:
            self._new_io_state(state)

    def _read(self):
        try:
            chunk = self.socket.recv(self._read_chunk_size)
        except aio.SocketError as exc:
            if aio.would_block(exc):
                return
            else:
                self.close()
                return

        if not chunk:
            self.close()
            return

        self._reader(chunk)

    def _write(self):
        while self._wb:
            try:
                sent = self.socket.send(self._wb)
                ## print 'wrote!', self._wb[:sent]
                self._wb = self._wb[sent:]
            except aio.SocketError as exc:
                if aio.would_block(exc):
                    break
                else:
                    self.close()
                    return False
        if not self._wb and self._write_callback:
            callback = self._write_callback
            self._write_callback = None
            callback()
        return bool(self._wb)

    def _add_io_state(self, state):
        if not self._state & state:
            self._new_io_state(self._state | state)

    def _new_io_state(self, state):
        self._state = state
        self.io.update_handler(self.socket.fileno(), state)
