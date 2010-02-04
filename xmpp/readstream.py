## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""readstream -- non-blocking unbuffered reads / buffered writes"""

from __future__ import absolute_import
import socket, errno
from . import tcp
from .prelude import *

__all__ = ('ReadStream', )

class ReadStream(object):
    """A simplified version of Tornado's IOStream class that supports
    unbuffered reads and buffered writes."""

    def __init__(self, socket, io=None, read_chunk_size=4096):
        self.socket = socket
        self.io = io or tcp.event_loop()

        self._state = io.ERROR
        self._read_chunk_size = read_chunk_size
        self._wb = u''

        self._reader = None
        self._write_callback = None
        self._close_callback = None

        self.io.add_handler(socket.fileno(), self._handle, self._state)

    def read(self, reader):
        assert not self._reader, "There's already a reader installed."
        self._reader = reader
        self._add_io_state(self.io.READ)
        return self

    def write(self, data, callback=None):
        self._wb += data
        self._write_callback = callback
        self._wb and self._write()
        return self

    def shutdown(self, callback=None):
        self._close_callback = callback
        self._reader = None
        if self._wb:
            self._write_callback = self.close
        else:
            self.close()
        return self

    def close(self):
        if self.socket:
            self.io.remove_handler(self.socket.fileno())
            self.socket.close()
            self.socket = None
        return self

    def on_close(self, callback):
        self._close_callback = callback
        return self

    def starttls(self, callback=None, **options):
        ## Delay starttls until the write-buffer is emptied.
        if self._wb:
            self._write_callback = partial(self.starttls, callback, **options)
            return

        def success(socket):
            self.socket = socket
            callback and callback()

        def failure(socket):
            self.socket = socket
            self.close()

        ## Wrap the socket; give startttls() control until the
        ## handshake is finished.
        tcp.starttls(
            self.socket, self._handle, self._state, self.io,
            success=success,
            failure=failure,
            **options
        )

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
        except socket.error as exc:
            if exc[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
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
                self._wb = self._wb[sent:]
            except socket.error as exc:
                if exc[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
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
