## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""aio -- asynchronous IO"""

from __future__ import absolute_import
import socket, ssl, select, errno, logging, fcntl
from tornado import ioloop

__all__ = (
    'TCPServer', 'TCPClient', 'SocketError', 'would_block', 'in_progress',
    'starttls', 'is_ssl',
    'loop', 'start', 'IOLoop'
)

class TCPServer(object):
    """A non-blocking, single-threaded HTTP server implemented using
    the tornado ioloop.  This implementation is heavily based on the
    tornado HTTPServer.  A simple echo server is:

        import xmpp
        from tornado.iostream import IOStream

        def echo(socket, address, io):
            stream = IOStream(socket, io=io)

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

    def __init__(self, handler, io=None):
        self.handler = handler
        self.io = io or loop()
        self.socket = None

    def stop(self):
        if self.socket:
            self.io.remove_handler(self.socket.fileno())
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
        self.io.add_handler(
            self.socket.fileno(),
            self._accept,
            self.io.READ
        )
        return self

    def _accept(self, fd, events):
        while True:
            try:
                conn, addr = self.socket.accept()
            except SocketError as exc:
                if not would_block(exc):
                    raise
                return
            try:
                conn.setblocking(0)
                self.handler(conn, addr, self.io)
            except:
                logging.error(
                    'TCPServer: conn error (%s)' % (addr,),
                    exc_info=True
                )
                self.io.remove_handler(conn.fileno())
                conn.close()

class TCPClient(object):
    """A non-blocking TCP client implemented with ioloop.  For
    example, here is a client that talks to the echo server in the
    previous example:

        def talk(socket, io):
            stream = IOStream(socket, io=io)
            messages = [0]

            def handle(data):
                stream.write('goodbye\n', stream.close)

            stream.read_until("\n", handle)
            stream.write('hello!\n')

        client = xmpp.TCPClient(talk).connect('127.0.0.1', '9000')
        xmpp.start([client])
    """
    def __init__(self, handler, io=None):
        self.handler = handler
        self.io = io or loop()
        self.socket = None
        self.address = None

    def stop(self):
        if self.socket:
            self.socket.close()
            self.socket = None
        return self

    def connect(self, addr, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        sock.setblocking(0)

        try:
            self.address = (addr, int(port))
            sock.connect(self.address)
        except SocketError as exc:
            if not in_progress(exc):
                raise

        self.socket = sock
        return self

    def start(self):
        self.io.add_handler(self.socket.fileno(), self._ready, self.io.WRITE)
        return self

    def _ready(self, fd, events):
        try:
            self.handler(self.socket, self.address, self.io)
        except:
            logging.error(
                'TCPClient: error while handling WRITE',
                exc_info=True
            )
            self.stop()

SocketError = socket.error

def would_block(exc):
    return exc[0] in (errno.EWOULDBLOCK, errno.EAGAIN)

def in_progress(exc):
    return exc[0] == errno.EINPROGRESS


### TLS

def starttls(socket, handler, events, io=None, success=None, failure=None, **options):
    """Wrap an active socket in an SSL socket."""

    ## Default Options

    options.setdefault('do_handshake_on_connect', False)
    options.setdefault('ssl_version', ssl.PROTOCOL_TLSv1)

    ## Handlers

    def done():
        """Handshake finished successfully."""

        io.set_handler(wrapped.fileno(), handler, events)
        success and success(wrapped)

    def error():
        """The handshake failed."""

        if failure:
            return failure(wrapped)
        ## By default, just close the socket.
        io.remove_handler(wrapped.fileno())
        wrapped.close()

    def handshake(fd, events):
        """Handler for SSL handshake negotiation.  See Python docs for
        ssl.do_handshake()."""

        if events & io.ERROR:
            error()
            return

        try:
            new_state = io.ERROR
            wrapped.do_handshake()
            return done()
        except ssl.SSLError as exc:
            if exc.args[0] == ssl.SSL_ERROR_WANT_READ:
                new_state |= io.READ
            elif exc.args[0] == ssl.SSL_ERROR_WANT_WRITE:
                new_state |= io.WRITE
            else:
                raise

        if new_state != state[0]:
            state[0] = new_state
            io.update_handler(fd, new_state)

    ## set up handshake state; use a list as a mutable cell.
    io = io or ioloop.IOLoop.instance()
    state = [io.ERROR]

    ## Wrap the socket; swap out handlers.
    wrapped = SSLSocket(socket, **options)
    wrapped.setblocking(0)
    if wrapped.fileno() != socket.fileno():
        io.remove_handler(socket.fileno())
    io.set_handler(wrapped.fileno(), handshake, state[0])

    ## Begin the handshake.
    handshake(wrapped.fileno(), 0)
    return wrapped

def is_ssl(socket):
    """True if socket is an active SSLSocket."""

    return bool(getattr(socket, '_sslobj', False))

class SSLSocket(ssl.SSLSocket):
    """Override the send() and recv() methods of SSLSocket to more
    closely emulate normal non-blocking socket behavior.

    The built-in SSLSocket implementation wraps self.read() and
    self.write() in `while True' loops.  This makes the socket
    effectively blocking even if the socket is set to be non-blocking.
    See also: <http://bugs.python.org/issue3890>.

    The read() and write() methods may raise SSLErrors that aren't
    caught by ioloop handlers.  This implementation re-raises
    SSL_ERROR_WANT_READ and SSL_ERROR_WANT_WRITE errors as EAGAIN
    socket.errors.
    """

    def __init__(self, *args, **kwargs):
        super(SSLSocket, self).__init__(*args, **kwargs)

        ## The base socket class overrides these methods; re-override them.
        cls = type(self)
        self.recv = cls.recv.__get__(self, cls)
        self.send = cls.send.__get__(self, cls)

    def send(self, data, flags=0):
        if not self._sslobj:
            return socket.send(self, data, flags)
        elif flags != 0:
            raise ValueError(
                '%s.send(): non-zero flags not allowed' % self.__class__
            )

        try:
            return self.write(data)
        except ssl.SSLError as exc:
            if exc.args[0] in (ssl.SSL_ERROR_WANT_WRITE, ssl.SSL_ERROR_WANT_READ):
                raise SocketError(errno.EAGAIN)
            raise

    def recv(self, buflen=1024, flags=0):
        if not self._sslobj:
            return socket.recv(self, buflen, flags)
        elif flags != 0:
            raise ValueError(
                '%s.recv(): non-zero flags not allowed' % self.__class__
            )

        try:
            return self.read(buflen)
        except ssl.SSLError as exc:
            if exc.args[0] == ssl.SSL_ERROR_WANT_READ:
                raise SocketError(errno.EAGAIN)
            raise


### IO Loop

def loop():
    return IOLoop.instance()

def start(services=(), io=None):
    """Start an event loop.  If services are given, start them before
    starting the loop and stop them before stopping the loop."""

    io = io or loop()
    for svc in services:
        svc.start()

    try:
        normal = True
        io.start()
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
        io.stop()
    else:
        logging.error('Uncaught exception', exc_info=True)
        raise


### Pending bugfix

## Address some issues with IOLoop.add_handler() and ioloop._KQueue.
## This can go away if the patch is accepted for Issue 59
## <http://github.com/facebook/tornado/issues/issue/59>.

class IOLoop(ioloop.IOLoop):
    """Extend the add_handler() method to become set_handler()."""

    def add_handler(self, fd, handler, events):
        return self.set_handler(fd, handler, events)

    def set_handler(self, fd, handler, events):
        """This checks to see whether a handler already exists to
        avoid an OSError from _EPoll and to preserve internal _KQueue
        state."""

        if fd in self._handlers:
            self._handlers[fd] = handler
            self._impl.modify(fd, events | self.ERROR)
        else:
            self._handlers[fd] = handler
            self._impl.register(fd, events | self.ERROR)

class _KQueue(object):
    """A kqueue-based event loop for BSD/Mac systems.

    This implementation tracks activation records for active
    descriptors and which descriptors are waiting for a WRITE event.
    This allows poll() to simulate WRITE events when a descriptor is
    writable, but kqueue.control() has previously signaled a WRITE and
    will not re-signal until something changes about the
    descriptor."""

    class Active(object):
        """A file descriptor activation record."""
        __slots__ = ('filter', 'events')

        def __init__(self, events, filter=0):
            self.events = events  # IOLoop events
            self.filter = filter  # Last filter received from kqueue.control()

        def modify(self, events):
            self.events = events
            return self

    def __init__(self):
        self._kqueue = select.kqueue()
        self._active = {}         # Mapping of <fd, Active> items
        self._writers = set()     # Track fds that want to write

    def register(self, fd, events):
        self._active[fd] = self.control(fd, self.Active(events))

    def modify(self, fd, events):
        self.control(fd, self._active[fd].modify(events))

    def unregister(self, fd):
        self.control(fd, self._active.pop(fd), select.KQ_EV_DELETE)
        self._writers.discard(fd)

    def control(self, fd, active, *flags):
        kevent = select.kevent(fd, self.filter(active.events), *flags)
        self._kqueue.control([kevent], 0)
        if active.events & IOLoop.WRITE:
            self._writers.add(fd)
        else:
            self._writers.discard(fd)
        return active

    def filter(self, events):
        state = 0
        if events & IOLoop.WRITE:
            state |= select.KQ_FILTER_WRITE
        if events & IOLoop.READ or state == 0:
            state |= select.KQ_FILTER_READ
        return state

    def poll(self, timeout):
        kevents = self._kqueue.control(None, 1000, timeout)
        events = {}

        for kevent in kevents:
            fd = kevent.ident
            flags = 0
            if kevent.filter & select.KQ_FILTER_READ:
                flags |= IOLoop.READ
            if kevent.filter & select.KQ_FILTER_WRITE:
                flags |= IOLoop.WRITE
            if kevent.flags & select.KQ_EV_ERROR:
                flags |= IOLoop.ERROR
            try:
                self._active[fd].filter = events[fd] = flags
            except KeyError:
                ## Caught some cruft; remove the filter.
                kevent = select.kevent(fd, kevent.filter, select.KQ_EV_DELETE)
                self._kqueue.control([kevent], 0)

        for fd in self._writers:
            if fd not in events and self._active[fd].events & IOLoop.WRITE:
                events[fd] = IOLoop.WRITE

        return events
