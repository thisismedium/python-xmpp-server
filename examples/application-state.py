## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""pong -- an example of using ApplicationState directly

This example demonstrates direct use of ApplicationState and
XMPPStream.  Normally the higher-level Application/Plugin abstraction
is used.  The server waits for a <ping> from the client and responds
with a pong.  This is done until the client closes the stream.
"""

import functools, xmpp

class Pong(xmpp.ApplicationState):

    def setup(self):
        self.pings = self.pongs = 0

        self.stanza('{jabber:client}ping', self.onPing)
        self.bind(xmpp.ReceivedStreamOpen, self.receivedOpen)
        self.bind(xmpp.ReceivedStreamClose, self.closeStream)
        self.bind(xmpp.ConnectionClose, self.connectionClosed)

        print 'Waiting for some pings...'

        return self

    def receivedOpen(self):
        self.stream._openStream({ 'from': 'server@example.com' })

    def onPing(self, elem):
        self.pings += 1
        self.write(self.E('pong'))
        self.pongs += 1

    def connectionClosed(self):
        print 'Done: got %d pings and send %d pongs.' % (
            self.pings,
            self.pongs
        )

if __name__ == '__main__':
    pong = functools.partial(xmpp.XMPPStream, Pong)
    handler = xmpp.XMLHandler(pong)
    S = xmpp.TCPServer(handler).listen('127.0.0.1', 9000)
