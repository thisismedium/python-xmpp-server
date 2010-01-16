## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""tcpserver -- a simple tcp server"""

from __future__ import absolute_import
import socket, errno, logging, fcntl
from tornado import ioloop

__all__ = ('event_loop', 'TCPServer')

def event_loop():
    return ioloop.IOLoop.instance()

class TCPServer(object):
    """A non-blocking, single-threaded HTTP server implemented using
    the tornado ioloop.  This implementation is heavily based on the
    tornado HTTPServer.  A simple echo server is:

      from tornado.iostream import IOStream
      from xmpp.tcpserver import TCPServer

      def echo(socket, address, io_loop):
          stream = IOStream(socket, io_loop=io_loop)
          stream.read_until("\n", stream.write)

      TCPServer(echo).listen('127.0.0.1', '9000')
    """

    def __init__(self, handler, io_loop=None):
        self.handler = handler
        self.io_loop = io_loop or event_loop()
        self.socket = None

    def listen(self, addr, port):
        try:
            self.bind(addr, int(port)).start().io_loop.start()
        except KeyboardInterrupt:
            logging.info('TCPServer: shutting down')
            self.stop().io_loop.stop()
        except:
            logging.error('TCPServer: uncaught exception', exc_info=True)
            raise

        return self

    def stop(self):
        if self.socket:
            self.io_loop.remove_handler(self.socket.fileno())
            self.socket.close()
            self.socket = None
        return self

    def bind(self, addr, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        flags = fcntl.fcntl(sock.fileno(), fcntl.F_GETFD)
        flags |= fcntl.FD_CLOEXEC
        fcntl.fcntl(sock.fileno(), fcntl.F_SETFD, flags)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(0)
        sock.bind((addr, port))
        sock.listen(128)

        self.socket = sock
        return self

    def start(self):
        ## Note: the tornado HTTPServer forks a subprocesses to match
        ## the number of CPU cores.  It's probably worthwhile to that
        ## here too.
        self.io_loop.add_handler(
            self.socket.fileno(),
            self._accept,
            self.io_loop.READ
        )
        return self

    def _accept(self, fd, events):
        while True:
            try:
                conn, addr = self.socket.accept()
            except socket.error as exc:
                if exc[0] not in (errno.EWOULDBLOCK, errno.EAGAIN):
                    raise
                return
            try:
                conn.setblocking(0)
                self.handler(conn, addr, self.io_loop)
            except:
                logging.error(
                    'TCPServer: conn error (%s)' % (addr,),
                    exc_info=True
                )
                self.io_loop.remove_handler(conn.fileno())
                conn.close()
