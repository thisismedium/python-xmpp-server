## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""tcp-echo -- an example tcp server and client"""

import xmpp
from tornado.iostream import IOStream

def echo(socket, address, io_loop):
    """A server connection handler that repeats back lines received
    from the client.  The server stops echoing if the client says
    'goodbye'."""

    stream = IOStream(socket, io_loop=io_loop)

    def write(data, *args):
        print 'S: %r' % data
        stream.write(data, *args)

    def handle(data):
        if data == 'goodbye\n':
            write('See you later.\n', stream.close)
        else:
            write('You said: "%s".\n' % data.strip())
            loop()

    def loop():
        stream.read_until("\n", handle)

    loop()

def talk(socket, io_loop):
    """A client connection handler that says hello to the echo server,
    waits for a response, then disconnects."""

    stream = IOStream(socket, io_loop=io_loop)
    messages = [0]

    def write(data, *args):
        print 'C: %r' % data
        stream.write(data, *args)

    def handle(data):
        write('goodbye\n', stream.close)

    stream.read_until("\n", handle)
    write('hello!\n')

if __name__ == '__main__':
    server = xmpp.TCPServer(echo).bind('127.0.0.1', '9000')
    client = xmpp.TCPClient(talk).connect('127.0.0.1', '9000')
    xmpp.start([server, client])

