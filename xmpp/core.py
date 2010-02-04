## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""core -- xmpp core <http://xmpp.org/rfcs/rfc3920.html>"""

from __future__ import absolute_import
import sasl, base64, time
from . import state, xml, xmppstream, interfaces as i
from .prelude import *

try:
    import ssl
except ImportError:
    ssl = None

__all__ = (
    'ServerCore', 'ClientCore',
    'ReceivedOpenStream', 'ReceivedCloseStream', 'ReceivedError',
    'SessionStarted'
)

class Core(i.CoreInterface):

    def __init__(self, address, stream, auth=None, resources=None,
                 plugins=None):
        self.peer = address
        self.stream = stream.read(self._read)
        self.auth = auth
        self.resources = resources

        self.state = state.State(self, plugins)
        self.parser = xml.Parser(xmppstream.XMPPTarget(self)).start()
        self.E = xml.ElementMaker(
            namespace=self.state.plugins.__xmlns__,
            nsmap=self.state.plugins.nsmap
        )

        self.install_features()
        self._reset()

    def __repr__(self):
        return '<%s %r>' % (type(self).__name__, self.peer)

    def _reset(self):
        self.state.reset()
        self.root = None
        self.state.bind_stanza(self.ERROR, self.handle_error)
        self.state.bind_stanza('{jabber:client}iq', self.info_query)
        self.parser.reset()
        self.initiate()
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

    def initiate(self):
        """Initiate a stream after a reset."""
        pass

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
    def open_stream(self):
        if self.root is None:
            self.root = self.make_stream()
            self.stream.write(xml.open_tag(self.root))
            self.state.trigger(SentOpenStream)

    @writer
    def reset(self):
        if self.stream:
            self._reset()

    @writer
    def close_stream(self):
        if self.root is not None:
            self.stream.write(xml.close_tag(self.root))
            self.root = None
            self.state.trigger(SentCloseStream)

    def close(self):
        if self.stream:
            if self.root is None:
                self.state.run(self._close)
            else:
                self.close_stream()

    ### ---------- Stream Errors ----------

    ERROR = '{http://etherx.jabber.org/streams}error'
    ERROR_NS = 'urn:ietf:params:xml:ns:xmpp-streams'
    TEXT = '{%s}text' % ERROR_NS

    def error(self, name, text=None, exc=None):
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

        if self.stream is None:
            log.error(
                'Error reported after stream was closed: %s %r' % (name, text),
                exc_info=bool(exc)
            )
            return self
        elif exc:
            log.error('Stream Error: %s' % exc, exc_info=True)

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
            log.error('Exception while reporting error.', exc_info=True)

        return self

    def handle_error(self, elem):
        log.error('Received Error: %s %r' % (
            xml.tag(xml.child(elem, 0), 'unknown-error'),
            xml.text(xml.child(elem, self.TEXT), 'no description')
        ))

        self.state.trigger(ReceivedError, elem)
        with self.state.clear().lock():
            self.close_stream()
        self._close()

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
            'from': self.fromJID,
            'type': 'error',
            'id': elem.get('id')
        })
        if len(elem) > 0:
            stanza.append(elem[0])
        return self.write(append(stanza, error))

    ### ---------- Features ----------

    FEATURES = ()
    FEATURES_TAG = '{http://etherx.jabber.org/streams}features'

    def install_features(self):
        self.secured = None
        self.authJID = None
        self.features = [f(self) for f in self.FEATURES]
        return self

    def send_features(self):
        possible = (f.include() for f in self.features if f.active())
        include = filter(xml.is_element, possible)
        self.write(self.E(self.FEATURES_TAG, *include))
        return self.authJID is None

    def wait_for_features(self):
        active = dict((f.TAG, f) for f in self.features if f.active())
        self.state.set('features', active)
        self.state.bind_stanza(self.FEATURES_TAG, self.reply_to_features)
        return self.authJID is None

    def reply_to_features(self, elem):
        features = self.state.get('features')
        stop_after_first = self.authJID is None
        for clause in elem:
            feature = features.get(clause.tag)
            if feature and feature.active():
                feature.reply(clause)
                if stop_after_first: break
        return self

    ### ---------- Core Stanzas ----------

    STANZAS = 'urn:ietf:params:xml:ns:xmpp-stanzas'

    def info_query(self, elem):
        if not self.authJID:
            return self.error('not-authorized')

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
            log.exception('Caught StreamError while dispatching %r.', name)
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

    def message(self, elem):
        if not self.authJID:
            return self.error('not-authorized')

    def routes(self, jid):
        resources = getattr(self, 'resources', None)
        if not resources:
            raise state.NoRoute(jid)
        return resources.routes(jid)

    def presense(self, elem):
        if not self.authJID:
            return self.error('not-authorized')

    ### ---------- Private ----------

    def _close(self):
        if self.stream:
            ## This causes a segfault when the stream is closed.
            ## self.parser.close()
            try:
                self.state.clear()
                #self.stream.write('', self.stream.close)
                self.stream.shutdown()
            finally:
                self.stream = None

    def _read(self, data):
        if not self.stream:
            return

        try:
            self.parser.feed(data)
        except i.StreamError as exc:
            self.error(exc.condition, exc.text, exc)
        except xml.XMLSyntaxError as exc:
            self.error('bad-format', str(exc), exc)
        except Exception as exc:
            self.error('internal-server-error', str(exc), exc)


### Events

class SentOpenStream(state.Event):
    pass

class SentCloseStream(state.Event):
    pass

class ReceivedOpenStream(state.Event):
    pass

class ReceivedCloseStream(state.Event):
    pass

class ReceivedError(state.Event):
    pass

class StreamBound(state.Event):
    pass

class SessionStarted(state.Event):
    pass


### Features

class Feature(object):

    def __init__(self, core):
        self.core = core
        self.install()

    def write(self, data, *args):
        self.core.write(data, *args)
        return self

    def one(self, *args, **kwargs):
        self.core.state.one(*args, **kwargs)
        return self

    def trigger(self, *args, **kwargs):
        self.core.state.trigger(*args, **kwargs)
        return self

    def stanza(self, name, *args):
        name = xml.clark(name, self.__xmlns__)
        self.core.state.bind_stanza(name, *args)
        return self

    def stanzas(self, seq=None, **kwargs):
        bind = self.core.state.bind_stanza
        xmlns = self.__xmlns__
        for (name, val) in chain_items(seq, kwargs):
            bind(xml.clark(name, xmlns), val)
        return self

    def get(self, name, default=None):
        return self.core.state.get(name, default)

    def set(self, name, value):
        self.core.state.set(name, value)
        return self

    def iq(self, *args, **kwargs):
        self.core.iq(*args, **kwargs)
        return self

class TLS(Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-tls'
    E = xml.ElementMaker(namespace=__xmlns__, nsmap={ None: __xmlns__ })
    TAG = '{%s}starttls' % __xmlns__

    def install(self):
        if not self.active():
            self.core.secured = False

    def active(self):
        return self.core.secured is None and self.core.use_tls()

    ## ---------- Server ----------

    def include(self):
        self.stanza('starttls', self.proceed)
        return self.E.starttls()

    def proceed(self, elem):
        self.write(self.E.proceed(), self.starttls)

    ## ---------- Client ----------

    def reply(self, feature):
        self.stanzas(proceed=self.begin, failure=self.failure)
        return self.write(self.E.starttls())

    def begin(self, elem):
        self.starttls()

    def failure(self, elem):
        self.core.close()

    ## ---------- Common ----------

    def starttls(self):
        self.core.starttls(self.done)

    def done(self):
        self.core.secured = True
        self.core._reset()

class SASL(Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-sasl'
    E = xml.ElementMaker(namespace=__xmlns__, nsmap={ None: __xmlns__ })
    TAG = '{%s}mechanisms' % __xmlns__
    MECHANISM = '{%s}mechanism' % __xmlns__
    MECHANISMS = (sasl.Plain, sasl.DigestMD5)

    def install(self):
        self.auth = self.core.auth

    def active(self):
        return self.core.authJID is None and self.auth

    ## ---------- Server ----------

    def include(self):
        self.stanzas(auth=self.begin, abort=self.aborted, success=self.failed)
        return extend(
            self.E.mechanisms(),
            (self.E('mechanism', n) for n in keys(self.mechanisms()))
        )

    def begin(self, elem):
        name = elem.get('mechanism')
        mech = first(m for (n, m) in self.mechanisms() if n == name)
        if not mech:
            return self.failure('invalid-mechanism')

        state = mech(self.auth).challenge()
        if not state.data and elem.text:
            return self.challenge_loop(state, elem)
        else:
            return self.issue_challenge(state)

    def challenge_loop(self, state, elem):
        state = state(self.decode(elem.text))
        if state.failure():
            return self.abort()
        elif state.success() or state.confirm():
            self.write(self.E.success())
            return self.success(state)
        else:
            return self.issue_challenge(state)

    def issue_challenge(self, state):
        self.stanza('response', partial(self.challenge_loop, state))
        self.write(self.E.challenge(self.encode(state.data)))
        return self

    ## ---------- Client ----------

    def reply(self, feature):
        mechs = dict(self.mechanisms())
        for offer in feature.iter(self.MECHANISM):
            name = offer.text; mech = mechs.get(name)
            if mech:
                self.select(name, mech)
                break

    def select(self, name, mech):
        state = mech(self.auth).respond
        self.stanza('challenge', partial(self.reply_loop, state))
        return self.write(self.E.auth(mechanism=name))

    def reply_loop(self, state, elem):
        state = state(self.decode(elem.text))
        if state.failure():
            return self.abort()
        elif state.success():
            return self.success(state)

        self.stanza('success', thunk(self.success, state))
        if state.confirm():
            return self.response(state.data)
        else:
            self.stanza('challenge', partial(self.reply_loop, state))
            return self.response(state.data)

    def response(self, data):
        self.write(self.E.response(self.encode(data)))
        return self

    ## ---------- Common ----------

    def decode(self, data):
        return base64.b64decode(data) if data else ''

    def encode(self, data):
        return base64.b64encode(data) if data else ''

    def mechanisms(self):
        result = self.get('mechanisms')
        if result is None:
            result = []
            secured = self.core.secured
            for Mech in self.MECHANISMS:
                if secured or Mech.SECURE:
                    result.append((Mech.__mechanism__, Mech))
            self.set('mechanisms', result)
        return result

    def success(self, state):
        self.core.authJID = xml.jid(state.entity, host=self.auth.host())
        self.core._reset()
        return self

    def failure(self, name):
        self.write(self.E.failure(self.E(name)))
        self.core.close()
        return self

    def failed(self, elem):
        self.core.close()
        return self

    def abort(self):
        self.write(self.E.abort())
        self.core.close()
        return self

    def aborted(self, elem):
        self.core.close()
        return self

class Bind(Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-bind'
    E = xml.ElementMaker(namespace=__xmlns__, nsmap={ None: __xmlns__ })
    TAG = '{%s}bind' % __xmlns__
    IQ_BIND = '{jabber:client}iq/{%s}bind' % __xmlns__
    RESOURCE = '{%s}bind/{%s}resource' % (__xmlns__, __xmlns__)
    JID = '{%s}bind/jid' % __xmlns__

    def install(self):
        self.resources = self.core.resources

    def active(self):
        return bool(self.core.authJID and self.core.resources)

    ### ---------- Server ----------

    def include(self):
        self.stanza(self.IQ_BIND, self.bind)
        return self.E.bind()

    def bind(self, iq):
        assert iq.get('type') == 'set'
        jid = self.resources.bind(xml.text(xml.child(iq, self.RESOURCE)), self.core)
        self.core.authJID = jid
        return self.iq('result', iq, self.E.bind(self.E.jid(jid)))

    ### ---------- Client ----------

    def reply(self, feature):
        return self.iq('set', self.bound, self.E.bind())

    def bound(self, iq):
        assert iq.get('type') == 'result'
        jid = self.resources.bound(xml.child(self.JID), self.core)
        self.authJID = jid
        self.trigger(StreamBound)
        return self

class Session(Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-session'
    E = xml.ElementMaker(namespace=__xmlns__, nsmap={ None: __xmlns__ })
    TAG = '{%s}session' % __xmlns__
    IQ_SESSION = '{jabber:client}iq/{%s}session' % __xmlns__

    def install(self):
        pass

    def active(self):
        return bool(self.core.authJID and self.core.resources)

    ### ---------- Server ----------

    def include(self):
        self.stanza(self.IQ_SESSION, self.start)
        return self.E.session()

    def start(self, iq):
        return self.iq('result', iq)

    ### ---------- Client ----------

    def reply(self, feature):
        self.one(StreamBound, self.establish)

    def establish(self):
        return self.iq('set', self.started, self.E.session())

    def started(self, iq):
        assert iq.get('type') == 'result'
        self.trigger(SessionStarted)


### Client / Server

class ClientCore(Core):

    FEATURES = (TLS, SASL, Bind, Session)

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.fromJID = attr.get('from')
        self.id = attr.get('id')

        self.state.trigger(ReceivedOpenStream)
        self.state.run(self._after)

    def _after(self):
        if not self.wait_for_features():
            self.state.activate()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        self.toJID = 'server@example.net'
        self.lang = 'en'

        return self.E(self.STREAM, {
            'to': self.toJID,
            self.LANG: self.lang,
            'version': '1.0'
        })

    def initiate(self):
        self.open_stream()

    def use_tls(self):
        return bool(ssl and self.stream.socket)

    def starttls(self, callback):
        self.stream.starttls(callback)
        return self

class ServerCore(Core):

    FEATURES = (TLS, SASL, Bind, Session)

    def __init__(self, address, stream, auth=None, plugins=None, resources=None,
                 certfile=None, keyfile=None):
        self.certfile = certfile
        self.keyfile = keyfile
        Core.__init__(self, address, stream, auth, resources, plugins)

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.toJID = attr.get('to')
        self.state.trigger(ReceivedOpenStream)
        self.state.run(self._after)

    def _after(self):
        self.open_stream()
        if not self.send_features():
            self.state.activate()

    def handle_stanza(self, elem):
        if self.authJID:
            fromJID = elem.get('from')
            assert fromJID is None or fromJID == self.authJID
            if fromJID is None:
                elem.set('from', self.authJID)
        self.state.trigger_stanza(elem.tag, elem)

    def handle_close_stream(self):
        self.state.trigger(ReceivedCloseStream)
        self.stream.on_close(self._close)
        if self.root is not None:
            self.close_stream()
            self.stream.io.add_timeout(time.time() + 5, self.stream.shutdown)
        else:
            self.close()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        self.fromJID = 'server@example.net'
        self.id = make_nonce()
        self.lang = 'en'

        return self.E(self.STREAM, {
            'from': self.fromJID,
            'id': self.id,
            self.LANG: self.lang,
            'version': '1.0'
        })

    def use_tls(self):
        return bool(
            ssl
            and self.certfile
            and self.keyfile
            and self.stream.socket
        )

    def starttls(self, callback):
        if not self.certfile and self.keyfile:
            raise i.StreamError(
                'internal-server-error',
                'Cannot STARTTLS without a certfile and keyfile.'
            )
        self.stream.starttls(
            callback,
            server_side=True,
            certfile=self.certfile,
            keyfile=self.keyfile
        )
        return self

def make_nonce():
    import random, base64, struct

    random.seed()
    value = random.getrandbits(64)
    return base64.b64encode(''.join(struct.pack('L', value)))

