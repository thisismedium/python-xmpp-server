## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""xmppstream -- an XMPP stream handler."""

from __future__ import absolute_import
import errno, socket, logging, abc, contextlib, collections, functools
from tornado import ioloop
from . import xml, readstream
from .interfaces import StreamError

__all__ = ('XMPPHandler', 'XMPPTarget')

class XMPPHandler(object):
    """Wrap a Core/XMPPTarget up in the TCPHandler interface.  Here is
    an example of a very simple XMPP server that plays ping/pong:

        import xmpp

        class Pong(xmpp.CoreInterface):

            def __init__(self, addr, stream):
                super(Pong, self).__init__(addr, stream)
                self.pings = 0
                print 'Waiting for some pings from %s.' % (self.address[0])

            def is_stanza(self, name):
                return name == '{jabber:client}ping'

            def handle_open_stream(self, attrs):
                self.stream.write(
                    '<stream:stream xmlns="jabber:client"'
                    ' from="server@example.net" xml:lang="en"'
                    ' xmlns:stream="http://etherx.jabber.org/streams">'
                )

            def handle_stanza(self, name, ping):
                self.pings += 1
                self.stream.write('<pong/>')

            def handle_close_stream(self):
                self.stream.write('</stream:stream>', self.close)

            def close(self):
                print 'Got %d ping(s) from %s.' % (self.pings, self.address[0])
                self.stream.close()

        if __name__ == '__main__':
            pong = xmpp.XMPPHandler(Pong)
            server = xmpp.TCPServer(pong).bind('127.0.0.1', 9000)
            xmpp.start([server])

    """

    def __init__(self, Core, settings={}):
        self.Core = Core
        self.settings = settings

    def __call__(self, socket, addr, io_loop, **kwargs):
        stream = readstream.ReadStream(socket, io_loop, **kwargs)
        self.Core(addr, stream, **self.settings)
        return self

class XMPPTarget(object):
    """An lxml XMLParser Target that processes an XMPP stream."""

    STREAM = '{http://etherx.jabber.org/streams}stream'

    def __init__(self, core):
        self.core = core
        self.stack = [] # Stack of elements received from the peer.

    def reset(self):
        del self.stack[:]

    ### ---------- Parser Target ----------

    def start(self, name, attrs, nsmap):
        """An element has started; push it onto the stack."""

        if self.stack:
            ## A <stream:stream> has already been received.  This is
            ## the beginning of a stanza or part of a stanza.
            if len(self.stack) == 1 and not self.core.is_stanza(name):
                raise StreamError(
                    'unsupported-stanza-type',
                    'Unrecognized stanza %r.' % name
                )
            parent = self.stack[-1]
            self.stack.append(xml.SubElement(parent, name, attrs, nsmap))
        elif name == self.STREAM:
            ## Got a <stream:stream>.
            elem = xml.Element(name, attrs, nsmap)
            self.stack.append(elem)
            self.core.handle_open_stream(attrs)
        else:
            raise StreamError(
                'xml-not-well-formed',
                'Expected %r, not %r.' % (self.STREAM, name)
            )

    def end(self, name):
        """An element has finished; pop if off the stack.  If it is a
        </stream:stream> or the end of a stanza, notify the core."""

        if not self.stack:
            raise StreamError(
                'xml-not-well-formed',
                'Unexpected closing %r.' % name
            )

        elem = self.stack.pop()
        if elem.tag != name:
            raise StreamError(
                'xml-not-well-formed',
                'Expected closing %r, not %r.' % (elem.tag, name)
            )

        if len(self.stack) == 1:
            self.core.handle_stanza(elem)
        elif name == self.STREAM:
            self.core.handle_close_stream()

    def data(self, data):
        """Character data is appended to the current element."""

        if not self.stack:
            raise StreamError(
                'xml-not-well-formed',
                'Unexpected character data: %r' % data
            )

        elem = self.stack[-1]

        if len(elem) != 0:
            ## Append to the tail of the last child if it exists.
            child = elem[-1]
            child.tail = (child.tail or '') + data
        else:
            ## Otherwise, append to the text of this element.
            elem.text = (elem.text or '') + data

    def close(self):
        """The parser has closed successfully."""
        self.reset()
