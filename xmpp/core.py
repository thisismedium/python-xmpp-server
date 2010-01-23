## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""core -- xmpp core <http://xmpp.org/rfcs/rfc3920.html>"""

from __future__ import absolute_import
import random, base64, struct, logging
from . import application as app, xmppstream as xs

__all__ = ('Core', )

@app.bind(xs.StreamReset)
class Core(app.Plugin):

    VERSION = '1.0'

    def __init__(self):
        ## Special, connection-level state.
        conn = self.connection
        if not hasattr(conn, 'initiator'):
            conn.__initiator = None
            conn.__secured = False
            conn.__authenticated = False

        ## State
        self.streamSent = False

        ## Stream Attributes
        self.fromJID = None
        self.toJID = None
        self.id = None
        self.lang = None

    def isInitiator(self):
        return self.connection.__initiator is True

    def isSecured(self):
        return self.connection.__secured

    def isAuthenticated(self):
        return self.connection.__authenticated

    ## ---------- Stream Setup ----------

    LANG = '{http://www.w3.org/XML/1998/namespace}lang'

    ## Watch for *StreamOpen events to create the initial stream
    ## state.  Do a little song-and-dance to determine if this
    ## participant is the initiator or not.

    @app.bind(xs.SentStreamOpen)
    def sentStream(self, elem):
        if self.connection.__initiator is None:
            self.connection.__initiator = True

        self.streamSent = True

        if self.connection.__initiator:
            ## Record local stream attributes; wait for features.
            self.streamTo(elem)
        else:
            self.sendFeatures()

    @app.bind(xs.ReceivedStreamOpen)
    def receivedStream(self, elem):
        if self.connection.__initiator is None:
            self.connection.__initiator = False

        if self.connection.__initiator:
            ## Record peer stream attributes; wait for features.
            self.streamFrom(elem)
        else:
            ## Send an opening stream in reply.
            self.streamReply(elem)

    @app.bind(xs.SentStreamClose)
    def sentClose(self):
        self.streamSent = False

    @app.bind(xs.ReceivedStreamClose)
    def receivedClose(self):
        self.closeConnection()

    def streamTo(self, elem):
        """Record local stream attributes.  Something outside this
        plugin as initiated the stream."""

        self.assertVersion(elem.get('version'))
        self.toJID = elem.get('to')
        self.lang = elem.get(self.LANG)
        ## FIXME: move this to post-auth
        self.activatePlugins()

        return self

    def streamFrom(self, elem):
        """Record peer stream attributes.  The peer has responded to
        the locally initiated stream."""

        self.assertVersion(elem.get('version'))
        self.fromJID = elem.get('from')
        self.id = elem.get('id')
        self.lang = self.lang or elem.get(self.LANG)

        return self

    def streamReply(self, elem):
        """The peer has initiated a stream.  Open a stream in reply."""

        self.assertVersion(elem.get('version'))
        self.toJID = elem.get('to')

        ## FIXME! hard-coded values
        fromJID = self.fromJID = 'recipient@example.net'
        sid = self.id = self.makeStreamId()
        lang = self.lang = elem.get(self.LANG, 'en')
        self.openStream({
            'from': fromJID,
            'id': sid,
            'xml:lang': 'en',
            'version': self.VERSION
        })
        ## FIXME: move this to post-auth
        self.activatePlugins()

        return self

    def makeStreamId(self):
        random.seed()
        value = random.getrandbits(64)
        return base64.b64encode(''.join(struct.pack('L', value)))

    ## ---------- Errors ----------

    ERROR_NS = 'urn:ietf:params:xml:ns:xmpp-streams'

    def error(self, name, text=None):
        """Send a stream-level error and close the connection.  Errors
        have this basic format:

            <stream:error>
              <{{ name }} xmlns="urn:ietf:params:xml:ns:xmpp-streams">
              <text xml:lang="en" "urn:ietf:params:xml:ns:xmpp-streams">
                {{ text }}
              </text>
            </stream:error>

        See: <http://xmpp.org/rfcs/rfc3920.html#rfc.section.4.7.3>
        """

        elem = self.E('stream:error', self.E(name, xmlns=self.ERROR_NS))
        if text is not None:
            elem.append(self.E.text(
                { self.LANG: 'en', 'xmlns': self.ERROR_NS},
                text
            ))

        try:
            if not self.streamSent:
                ## FIXME: open the stream somehow
                self.openStream({})
            self.write(elem)
            self.closeConnection()
        except xs.XMPPError:
            self.streamSent = False

            ## This may happen if the connection is closed before the
            ## error stanza or stream-close can be written.
            logging.error(
                'Core.error: caught exception while sending stream error.',
                exc_info=True
            )

        return self

    def assertVersion(self, version):
        if version != self.VERSION:
            self.error(
                'unsupported-version',
                'Supported versions: %r' % self.version
            )
        return self

    ## ---------- Features ----------

    def sendFeatures(self):
        pass
