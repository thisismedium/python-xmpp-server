## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""readstream -- a simple example of xmpp.ReadStream

This example uses a ReadStream to push chunks of data into an XML
parser.  The parser targets a SAX-style content handler that reports
the tokenized XML back to the client.

For example:
   python examples/readstream.py &
   echo some-file.xml | nc 127.0.0.1 9000
"""

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
