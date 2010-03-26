## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""core -- xmpp core <http://xmpp.org/rfcs/rfc3920.html>"""

from __future__ import absolute_import
import time
from . import state, xml, xmppstream, features, interfaces as i
from .prelude import *

try:
    import ssl
except ImportError:
    ssl = None

__all__ = (
    'ServerCore', 'ClientCore',
    'ReceivedOpenStream', 'ReceivedCloseStream',
    'SentOpenStream', 'SentCloseStream', 'StreamClosed'
)

class Core(i.CoreInterface):

    def __init__(self, stream, jid, features=None, plugins=None, lang='en'):
        self.stream = stream.read(self._read)
        self.serverJID = jid
        self.lang = lang
        self.state = state.State(self, plugins)

        self.parser = xml.Parser(xmppstream.XMPPTarget(self)).start()
        self.E = xml.ElementMaker(namespace=self.__xmlns__, nsmap=self.nsmap)

        self.install_features(features)
        self._reset()

    def __repr__(self):
        peer = self.stream.socket and self.stream.socket.getpeername()
        return '<%s %r>' % (type(self).__name__, peer)

    __xmlns__ = property(lambda s: s.state.plugins.__xmlns__)
    nsmap = property(lambda s: s.state.plugins.nsmap)

    ### ---------- Stream Interaction ----------

    def initiate(self):
        """Initiate a stream after a reset."""

    def listen(self):
        """Bind important events and stanzas after a reset."""

        (self.state
         .bind_stanza(self.ERROR, self.handle_stream_error)
         .bind_stanza('{jabber:client}iq', self.info_query)
         .one(features.StreamSecured, self.on_stream_secured)
         .one(features.StreamAuthorized, self.on_stream_authorized)
         .one(features.StreamBound, self.on_stream_bound))

        return self

    def activate(self):
        """Default plugin activation is done after basic Features have
        been negotiated."""

        self.parser.stop_tokenizing()
        self.state.activate()
        return self

    def on_stream_secured(self, tls):
        self.secured = True

    def on_stream_authorized(self, auth):
        self.authJID = auth.jid

    def on_stream_bound(self, bindings):
        self.authJID = bindings.jid
        self.resources = bindings.resources

    def add_timeout(self, delay, callback):
        self.stream.io.add_timeout(time.time() + delay, callback)
        return self

    def remove_timeout(self, callback):
        self.stream.io.remove_timeout(callback)
        return self

    ### ---------- Incoming Stream ----------

    ## These are callbacks for the XMPPStream.

    def is_stanza(self, name):
        return self.state.is_stanza(name)

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream, attr)

    def handle_stanza(self, elem):
        self.state.trigger_stanza(elem.tag, elem)

    def handle_close_stream(self):
        self.state.trigger(ReceivedCloseStream)
        self.close()

    ### ---------- Outgoing Stream ----------

    STREAM = '{http://etherx.jabber.org/streams}stream'
    LANG = '{http://www.w3.org/XML/1998/namespace}lang'

    @abc.abstractmethod
    def make_stream(self):
        """Create a <stream:stream> element."""

    def close(self):
        if self.stream:
            if self.root is not None:
                self.close_stream()
            self.state.run(self._close)

    def writer(method):
        """Push writes through the scheduled jobs queue."""

        @wraps(method)
        def queue_write(self, *args, **kwargs):
            self.state.run(method, self, *args, **kwargs)
            return self

        return queue_write

    @writer
    def write(self, data, *args):
        if xml.is_element(data):
            data = xml.stanza_tostring(self.root, data)
        self.stream.write(data, *args)

    @writer
    def open_stream(self, *args):
        if self.root is None:
            self.root = self.make_stream()
            self.stream.write(xml.open_tag(self.root), *args)
            self.state.trigger(SentOpenStream)

    @writer
    def reset(self):
        if self.stream:
            self._reset()

    @writer
    def close_stream(self, *args):
        if self.root is not None:
            self.stream.write(xml.close_tag(self.root), *args)
            self.root = None
            self.state.trigger(SentCloseStream)

    del writer

    ### ---------- Stream Errors ----------

    ERROR = '{http://etherx.jabber.org/streams}error'
    ERROR_NS = 'urn:ietf:params:xml:ns:xmpp-streams'
    TEXT = '{%s}text' % ERROR_NS

    def stream_error(self, name, text=None, exc=None):
        """Send a stream-level error and close the connection.  Errors
        have this basic format:

            <stream:error>
              <{{ name }} xmlns="urn:ietf:params:xml:ns:xmpp-streams" />
              <text xml:lang="en" "urn:ietf:params:xml:ns:xmpp-streams">
                {{ text }}
              </text>
            </stream:error>

        See: <http://xmpp.org/rfcs/rfc3920.html#rfc.section.4.7.3>
        """

        try:
            log.error('Stream Error: %s %r' % (name, text), exc_info=bool(exc))
            with self.state.clear().lock():
                self.open_stream()
                elem = self.E(self.ERROR, self.E(name, xmlns=self.ERROR_NS))
                if text is not None:
                    elem.append(self.E.text(
                        { self.LANG: 'en', 'xmlns': self.ERROR_NS},
                        text
                    ))
                self.write(elem).close()
        except:
            log.exception('Exception while reporting stream error.')

        return self

    def handle_stream_error(self, elem):
        """Handle a stream-level error by logging it and closing the
        stream."""

        log.error('Received Error: %s %r' % (
            xml.tag(xml.child(elem, 0), 'unknown-error'),
            xml.text(xml.child(elem, self.TEXT), 'no description')
        ))

        with self.state.clear().lock():
            self.close()

    def stanza_error(self, elem, kind, condition, text=None):
        """Write a stanza-level error to the stream.

        <stanza-kind to='sender' type='error'>
          [RECOMMENDED to include sender XML here]
          <error type='error-type'>
            <defined-condition xmlns='urn:ietf:params:xml:ns:xmpp-stanzas'/>
            <text xmlns='urn:ietf:params:xml:ns:xmpp-stanzas'
                  xml:lang='langcode'>
              OPTIONAL descriptive text
            </text>
            [OPTIONAL application-specific condition element]
          </error>
        </stanza-kind>
        """
        error = self.E.error(type=kind)
        error.append(self.E(condition, { 'xmlns': self.STANZAS }))
        if text:
            error.append(self.E.text({ 'xmlns': self.STANZAS }, text))

        stanza = self.E(elem.tag, {
            'from': unicode(self.serverJID),
            'type': 'error',
            'id': elem.get('id')
        })
        if len(elem) > 0:
            stanza.append(elem[0])
        stanza.append(error)

        return self.write(stanza)

    ### ---------- Features ----------

    FEATURES = '{http://etherx.jabber.org/streams}features'

    def install_features(self, features=None):
        ## These track the results of core features: TLS, SASL, and
        ## Bind.  They are updated by event listeners; see listen().
        self.secured = False
        self.authJID = None
        self.resources = None

        self.features = features.install(self.state) if features else ()
        return self

    def send_features(self):
        possible = self.features and self.features.include()
        self.write(self.E(self.FEATURES, *filter(xml.is_element, possible)))
        return self.authJID is None

    def wait_for_features(self):
        active = dict(self.features and self.features.active())
        self.state.bind_stanza(self.FEATURES, partial(self.negotiate, active))
        return self.authJID is None

    def negotiate(self, active, elem):
        stop_after_first = self.authJID is None
        for clause in elem:
            feature = active.get(clause.tag)
            if feature and feature.active():
                feature.reply(clause)
                if stop_after_first: break
        return self

    def use_tls(self):
        return bool(ssl and self.stream.socket)

    def starttls(self, callback, **options):
        self.stream.starttls(callback, **options)
        return self

    ### ---------- Core Stanzas ----------

    STANZAS = 'urn:ietf:params:xml:ns:xmpp-stanzas'

    def info_query(self, elem):
        if not self.authJID:
            return self.stream_error('not-authorized')

        kind = elem.get('type')
        if kind == 'error':
            log.exception('Unhandled stanza error %r.', xml.tostring(elem))
            return

        if kind == 'result':
            name = self.iq_ident(elem)
        else:
            child = xml.child(elem)
            if child is None:
                log.exception('No child element: %r.' % xml.tostring(elem))
                return self.stanza_error(
                    elem, 'modify', 'not-acceptable',
                    'GET or SET must have a child element.'
                )
            name = '{jabber:client}iq/%s' % child.tag

        try:
            self.state.trigger_stanza(name, elem)
        except i.StreamError as exc:
            log.debug(
                'Caught StreamError while dispatching %r.', name,
                exc_info=True
            )
            self.stanza_error(elem, 'cancel', 'feature-not-implemented')

    def iq(self, kind, elem_or_callback, *data):
        if xml.is_element(elem_or_callback):
            return self.iq_send(kind, elem_or_callback.get('id'), *data)
        return self.iq_send(kind, self.iq_bind(elem_or_callback), *data)

    def iq_bind(self, callback):
        ident = make_nonce()
        self.state.one_stanza(self.iq_ident(ident), callback, replace=False)
        return ident

    def iq_ident(self, ident):
        if xml.is_element(ident):
            ident = ident.get('id')
        return '{jabber:client}iq[id=%r]' % ident

    def iq_send(self, kind, ident, *data):
        return self.write(self.E.iq(
            { 'id': ident, 'type': kind },
            *data
        ))

    def routes(self, jid):
        if self.resources is None:
            raise state.NoRoute(jid)
        return self.resources.routes(xml.jid(jid))

    ### ---------- Private ----------

    def _read(self, data):
        if not self.stream:
            return

        try:
            self.parser.feed(data)
        except i.StreamError as exc:
            self.stream_error(exc.condition, exc.text, exc)
        except xml.XMLSyntaxError as exc:
            self.stream_error('bad-format', str(exc), exc)
        except Exception as exc:
            self.stream_error('internal-server-error', str(exc), exc)

    def _reset(self):
        self.state.reset()
        self.root = None
        self.listen()
        self.parser.reset()
        self.initiate()
        return self

    def _close(self):
        if self.stream:
            ## This causes a segfault when the stream is closed.
            ## self.parser.close()
            try:
                self.state.trigger(StreamClosed).clear()
                self.stream.shutdown()
            finally:
                self.stream = None


### Events

class SentOpenStream(i.Event):
    """A <stream:stream> tag has been sent."""

class SentCloseStream(i.Event):
    """A </stream:stream> tag has been sent."""

class ReceivedOpenStream(i.Event):
    """A <stream:stream> tag has been received."""

class ReceivedCloseStream(i.Event):
    """A </stream:stream> tag has been received."""

class StreamClosed(i.Event):
    """Triggered just before a stream is shutdown."""


### Client

class ClientCore(Core):

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.id = attr.get('id')
        self.state.trigger(ReceivedOpenStream).run(self._opened)

    def _opened(self):
        self.state.one(features.SessionStarted, thunk(self.activate))
        self.wait_for_features()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        return self.E(self.STREAM, {
            'to': unicode(self.serverJID),
            self.LANG: self.lang,
            'version': '1.0'
        })

    def initiate(self):
        self.open_stream()


### Server

class ServerCore(Core):

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream).run(self._opened)

    def _opened(self):
        self.open_stream()
        if not self.send_features():
            self.state.one(features.SessionStarted, thunk(self.activate))
            pass

    def handle_stanza(self, elem):
        if self.authJID:
            if not elem.get('from'):
                elem.set('from', unicode(self.authJID))
        self.state.trigger_stanza(elem.tag, elem)

    def handle_close_stream(self):
        self.state.trigger(ReceivedCloseStream)
        self.close()

    def close(self):
        if self.stream:
            if self.root is not None:
                self.close_stream(self._close)
            else:
                self.state.run(self._close)

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        self.id = make_nonce()

        return self.E(self.STREAM, {
            'from': unicode(self.serverJID),
            'id': self.id,
            self.LANG: self.lang,
            'version': '1.0'
        })

def make_nonce():
    import random, hashlib

    random.seed()
    return hashlib.md5(str(random.getrandbits(64))).hexdigest()
