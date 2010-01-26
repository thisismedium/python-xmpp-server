## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""core -- xmpp core <http://xmpp.org/rfcs/rfc3920.html>"""

from __future__ import absolute_import
import abc, logging, functools
from . import interfaces, state, xml, xmppstream

__all__ = ('ServerCore', 'ClientCore')

class Core(interfaces.CoreInterface):

    def __init__(self, address, stream, plugins=None):
        self.peer = address
        self.stream = stream.read(self._read)

        self.parser = xml.Parser(xmppstream.XMPPTarget(self))
        self.E = xml.ElementMaker(
            namespace=plugins.__xmlns__,
            nsmap=plugins.nsmap
        )

        self.state = state.State(self, plugins)
        self.reset()

    def reset(self):
        self.parser.reset()
        self.root = None
        self.state.reset()
        self.initiate()

    ### ---------- Incoming Stream ----------

    ## These are callbacks for the XMPPStream.

    def is_stanza(self, name):
        return self.state.is_stanza(name)

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream)

    def handle_stanza(self, elem):
        self.state.trigger_stanza(elem)

    def handle_close_stream(self):
        self.state.trigger(ReceivedCloseStream)
        self.close()

    ### ---------- Outgoing Stream ----------

    STREAM = '{http://etherx.jabber.org/streams}stream'
    LANG = '{http://www.w3.org/XML/1998/namespace}lang'

    @abc.abstractmethod
    def make_stream(self):
        """Create a <stream:stream> element."""

    def initiate(self):
        """Initiate a stream after a reset."""
        pass

    def writer(method):
        """Push writes through the scheduled jobs queue."""

        @functools.wraps(method)
        def queue_write(self, *args, **kwargs):
            self.state.run(method, self, *args, **kwargs)
            return self

        return queue_write

    @writer
    def write(self, data):
        if xml.is_element(data):
            data = xml.stanza_tostring(self.root, data)
        self.stream.write(data)

    @writer
    def open_stream(self):
        if self.root is None:
            self.root = self.make_stream()
            self.stream.write(xml.open_tag(self.root))

    @writer
    def close_stream(self):
        if self.root is not None:
            self.stream.write(xml.close_tag(self.root))
            self.root = None

    def close(self):
        if self.stream:
            self.close_stream()
            self.state.run(self._close).flush(True)

    ### ---------- Errors ----------

    ERROR = '{http://etherx.jabber.org/streams}error'
    ERROR_NS = 'urn:ietf:params:xml:ns:xmpp-streams'

    def error(self, name, text=None, exc=None):
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

        if self.stream is None:
            logging.error(
                'Error reported after stream was closed: %s %r' % (name, text),
                exc_info=bool(exc)
            )
            return self
        elif exc:
            logging.error('Stream Error: %s' % exc, exc_info=True)

        try:
            with self.state.clear().lock():
                self.open_stream()
                elem = self.E(self.ERROR, self.E(name, xmlns=self.ERROR_NS))
                if text is not None:
                    elem.append(self.E.text(
                        { self.LANG: 'en', 'xmlns': self.ERROR_NS},
                        text
                    ))
                self.write(elem).close_stream()
            self._close()
        except:
            logging.error('Exception while reporting error.', exc_info=True)

        return self

    ### ---------- Private ----------

    def _close(self):
        if self.stream:
            ## This causes a segfault when the stream is closed.
            ##   self.parser.close()
            self.state.clear()
            self.stream.close()
            self.stream = None

    def _read(self, data):
        if not self.stream:
            return

        try:
            self.parser.feed(data)
        except xmppstream.XMPPError as exc:
            self.error(exc.condition, exc.text, exc)
        except xml.XMLSyntaxError as exc:
            self.error('bad-format', str(exc), exc)
        except Exception as exc:
            self.error('internal-server-error', str(exc), exc)


### Events

class ReceivedOpenStream(state.Event):
    pass

class ReceivedCloseStream(state.Event):
    pass


### Client / Server

class ClientCore(Core):

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream)
        self.wait_for_features()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        return self.E(self.STREAM, {
            'to': 'person@example.net',
            self.LANG: 'en',
            'version': '1.0'
        })

    def initiate(self):
        self.open_stream()

    ### ---------- Features ----------

    def wait_for_features(self):
        self.state.activate()

class ServerCore(Core):

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream)
        self.open_stream()
        self.send_features()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        return self.E(self.STREAM, {
            'from': 'server@example.net',
            'id': make_nonce(),
            self.LANG: 'en',
            'version': '1.0'
        })

    ### ---------- Features ----------

    def send_features(self):
        self.state.activate()

def make_nonce():
    import random, base64, struct

    random.seed()
    value = random.getrandbits(64)
    return base64.b64encode(''.join(struct.pack('L', value)))

