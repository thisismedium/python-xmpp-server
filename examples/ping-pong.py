## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""ping-pong -- a ping/pong client and server

The example demonstrates how to write a basic Plugin (PingPong) that
can be combined with other plugins (Client or Server) to create an
Application.

There's also an example of a fake "stream" that simply passes data
between Application instances.  This can be used to test Application
interaction without using sockets.
"""

import xmpp


### PingPong "plugin"

class ReceivedPong(xmpp.Event): pass
class ReceivedPing(xmpp.Event): pass

class PingPong(xmpp.Plugin):

    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True
        return self

    @xmpp.stanza
    def ping(self, elem):
        self.trigger(ReceivedPing)
        if self.stopped:
            return self.closeStream()
        return self.sendPong()

    @xmpp.stanza
    def pong(self, elem):
        self.trigger(ReceivedPong)
        if self.stopped:
            return self.closeStream()
        return self.sendPing()

    def sendPing(self):
        return self.write(self.E('ping'))

    def sendPong(self):
        return self.write(self.E('pong'))


### Client / Server Examples

@xmpp.bind(xmpp.StreamReset)
class Client(xmpp.Plugin):

    PONG_LIMIT = 5

    def __init__(self):
        self.pongs = 0
        self.activatePlugins()
        self.openStream({ 'from': 'client@example.net' })

    @xmpp.bind(xmpp.ReceivedStreamOpen)
    def onStart(self):
        self.plugin(PingPong).sendPing()

    @xmpp.bind(ReceivedPong)
    def onPong(self, pingpong):
        self.pongs += 1
        if self.pongs > self.PONG_LIMIT:
            pingpong.stop()

    @xmpp.bind(xmpp.ReceivedStreamClose)
    def onClose(self):
        self.closeConnection()

@xmpp.bind(xmpp.ReceivedStreamOpen)
class Server(xmpp.Plugin):

    def __init__(self):
        self.activatePlugins()
        self.openStream({ 'from': 'server@example.com' })

    @xmpp.bind(xmpp.ReceivedStreamClose)
    def onClose(self):
        self.closeConnection()


### Fake Stream

class Stream(object):
    SCHEDULE = []

    @classmethod
    def loop(cls):
        while cls.SCHEDULE:
            (callback, data) = cls.SCHEDULE[0]
            del cls.SCHEDULE[0]
            callback(data)

    def __init__(self, name, app, dest):
        self.name = name
        self.dest = dest
        print '%s: OPEN' % self.name
        self.target = app.ContentHandler(self)._connectionOpen()
        self.parser = xmpp.XMLParser(self.target)

    def read(self, data):
        self.parser.feed(data)

    def write(self, data):
        print '%s:' % self.name, data
        if self.dest:
            self.SCHEDULE.append((self.dest, data))

    def close(self):
        self.target._connectionClosed()
        print '%s: CLOSED' % self.name

if __name__ == '__main__':
    server = xmpp.Application([Server, PingPong])
    client = xmpp.Application([Client, PingPong])

    SP = Stream('S', server, lambda d: CP.read(d))
    CP = Stream('C', client, lambda d: SP.read(d))

    Stream.loop()
