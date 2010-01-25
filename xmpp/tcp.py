## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""tcpserver -- a simple tcp server"""

from __future__ import absolute_import
import socket, errno, logging, fcntl
from tornado import ioloop

__all__ = ('TCPServer', 'TCPClient', 'event_loop', 'start')

class TCPServer(object):
    """A non-blocking, single-threaded HTTP server implemented using
    the tornado ioloop.  This implementation is heavily based on the
    tornado HTTPServer.  A simple echo server is:

        import xmpp
        from tornado.iostream import IOStream

        def echo(socket, address, io_loop):
            stream = IOStream(socket, io_loop=io_loop)

            def handle(data):
                if data == 'goodbye\n':
                    stream.write('See you later.\n', stream.close)
                else:
                    stream.write('You said: "%s".\n' % data.strip())
                    loop()

            def loop():
                stream.read_until("\n", handle)

            loop()

        server = xmpp.TCPServer(echo).bind('127.0.0.1', '9000')
        start([server])
    """

    def __init__(self, handler, io_loop=None):
        self.handler = handler
        self.io_loop = io_loop or event_loop()
        self.socket = None

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
        sock.bind((addr, int(port)))
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

class TCPClient(object):
    """A non-blocking TCP client implemented with ioloop.  For
    example, here is a client that talks to the echo server in the
    previous example:

        def talk(socket, io_loop):
            stream = IOStream(socket, io_loop=io_loop)
            messages = [0]

            def handle(data):
                stream.write('goodbye\n', stream.close)

            stream.read_until("\n", handle)
            stream.write('hello!\n')

        client = xmpp.TCPClient(talk).connect('127.0.0.1', '9000')
        xmpp.start([client])
    """
    def __init__(self, handler, io_loop=None):
        self.handler = handler
        self.io_loop = io_loop or event_loop()
        self.socket = None

    def stop(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        return self

    def connect(self, addr, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        sock.setblocking(0)

        try:
            sock.connect((addr, int(port)))
        except socket.error as exc:
            if exc[0] != errno.EINPROGRESS:
                raise

        self.socket = sock
        return self

    def start(self):
        self.io_loop.add_handler(
            self.socket.fileno(),
            self._handle,
            self.io_loop.WRITE
        )
        return self

    def _handle(self, fd, events):
        try:
            self.handler(self.socket, self.io_loop)
        except:
            logging.error(
                'TCPClient: error while handling READ',
                exc_info=True
            )
            self.stop()

def event_loop():
    return ioloop.IOLoop.instance()

def start(services=(), io_loop=None):
    """Start an event loop.  If services are given, start them before
    starting the loop and stop them before stopping the loop."""

    io_loop = io_loop or event_loop()
    for svc in services:
        svc.start()

    try:
        normal = True
        io_loop.start()
    except KeyboardInterrupt:
        logging.info('Received keyboard interrupt.')
    except Exception:
        normal = False

    logging.info('Shutting down services.')
    for svc in services:
        try:
            svc.stop()
        except:
            logging.error(
                'Error while shutting down %r.' % svc,
                exc_info=True
            )

    if normal:
        logging.info('Shutting down event loop.')
        io_loop.stop()
    else:
        logging.error('Uncaught exception', exc_info=True)
        raise



