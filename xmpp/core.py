## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""core -- xmpp core <http://xmpp.org/rfcs/rfc3920.html>"""

from __future__ import absolute_import
import abc, logging, functools, sasl, base64
from . import interfaces, state, xml, xmppstream

try:
    import ssl
except ImportError:
    ssl = None

__all__ = (
    'ServerCore', 'ClientCore',
    'ReceivedOpenStream', 'ReceivedCloseStream', 'ReceivedError'
)

class Core(interfaces.CoreInterface):

    def __init__(self, address, stream, auth=None, plugins=None):
        self.peer = address
        self.stream = stream.read(self._read)
        self.auth = auth

        self.parser = xml.Parser(xmppstream.XMPPTarget(self))
        self.E = xml.ElementMaker(
            namespace=plugins.__xmlns__,
            nsmap=plugins.nsmap
        )

        self.state = state.State(self, plugins)
        self.install_features()
        self._reset()

    def _reset(self):
        self.parser.reset()
        self.root = None
        self.state.reset().bind_stanza(self.ERROR, self.handle_error)
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
    def reset(self):
        if self.stream:
            self._reset()

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

    def handle_error(self, elem):
        logging.error('Received Error: %s %r' % (
            xml.tag(xml.child(elem, 0), 'unknown-error'),
            xml.text(xml.child(elem, self.TEXT), 'no description')
        ))

        self.state.trigger(ReceivedError, elem)
        with self.state.clear().lock():
            self.close()

    ### ---------- Features ----------

    FEATURES = ()
    FEATURES_TAG = '{http://etherx.jabber.org/streams}features'

    def install_features(self):
        self.negotiating = True
        self.features = [f(self) for f in self.FEATURES]
        return self

    def send_features(self):
        if self.negotiating:
            include = filter(xml.is_element, (f.include() for f in self.features))
            if include:
                self.write(self.E(self.FEATURES_TAG, *include))
            else:
                self.negotiating = False
        return self.negotiating

    def wait_for_features(self):
        if self.negotiating:
            active = dict((f.TAG, f) for f in self.features if f.active())
            if active:
                self.state.set('features', active)
                self.state.bind_stanza(self.FEATURES_TAG, self.reply_to_features)
            else:
                self.negotiating = False
        return self.negotiating

    def reply_to_features(self, elem):
        features = self.state.get('features')
        done = True
        for clause in elem:
            feature = features.get(clause.tag)
            if feature:
                done = False
                feature.reply(clause)
                break
        self.negotiating = not done
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

class ReceivedError(state.Event):
    pass


### Features

class Feature(object):

    def __init__(self, core):
        self.core = core
        self.E = core.E
        self.install()

    def write(self, data):
        self.core.write(data)
        return self

    def stanza(self, *args):
        self.core.state.bind_stanza(*args)
        return self

    def get(self, name, default=None):
        return self.core.state.get(name, default)

    def set(self, name, value):
        self.core.state.set(name, value)
        return self

class TLS(Feature):
    TLS_NS = 'urn:ietf:params:xml:ns:xmpp-tls'
    TAG = '{%s}starttls' % TLS_NS
    PROCEED = '{%s}proceed' % TLS_NS
    FAILURE = '{%s}failure' % TLS_NS

    def install(self):
        self.core.secured = None

    def active(self):
        return self.core.secured is None and self.use_tls()

    ## ---------- Server ----------

    def include(self):
        if self.active():
            self.stanza(self.TAG, self.initiate_proceed)
            return self.E('starttls', { 'xmlns': self.TLS_NS })

    def initiate_proceed(self, elem):
        self.stanza(self.PROCEED, self.acknowledged, True)
        return self.write(self.E('proceed', { 'xmlns': self.TLS_NS }))

    def acknowledged(self, elem):
        self.starttls()

    ## ---------- Client ----------

    def reply(self, feature):
        if self.active():
            self.stanza(self.PROCEED, self.acknowledge_proceed)
            self.stanza(self.FAILURE, self.failure)
            return self.write(self.E('starttls', { 'xmlns': self.TLS_NS }))

    def acknowledge_proceed(self, elem):
        self.write(self.E('proceed', { 'xmlns': self.TLS_NS }))
        self.starttls()

    ## ---------- Common ----------

    def use_tls(self):
        return ssl and bool(self.core.stream.socket)

    def failure(self, elem):
        self.core.close()

    def starttls(self):
        print 'I would use TLS.'
        self.core.secured = True
        self.core.reset()

class SASL(Feature):
    SASL_NS = 'urn:ietf:params:xml:ns:xmpp-sasl'
    TAG = '{%s}mechanisms' % SASL_NS
    MECHANISM = '{%s}mechanism' % SASL_NS
    AUTH = '{%s}auth' % SASL_NS
    CHALLENGE = '{%s}challenge' % SASL_NS
    RESPONSE = '{%s}response' % SASL_NS
    FAILURE = '{%s}failure' % SASL_NS
    ABORT = '{%s}abort' % SASL_NS
    SUCCESS = '{%s}success' % SASL_NS

    MECHANISMS = (sasl.Plain, sasl.DigestMD5)

    def install(self):
        self.core.authenticated = None
        self.auth = self.core.auth

    def active(self):
        return self.core.authenticated is None and self.auth

    ## ---------- Server ----------

    def include(self):
        if self.active():
            self.stanza(self.AUTH, self.send_challenge)
            self.stanza(self.ABORT, self.aborted)
            self.stanza(self.FAILURE, self.failed)
            return self.E(
                'mechanisms', { 'xmlns': self.SASL_NS },
                *[self.E('mechanism', n) for (n, _) in self.mechanisms()]
            )

    def send_challenge(self, elem):
        name = elem.text
        mech = next((m for (n, m) in self.mechanisms() if n == name), None)
        if not mech:
            return self.failure('invalid-mechanism')

        (k, data) = mech(self.auth).challenge()
        self.stanza(self.RESPONSE, functools.partial(self.challenge_loop, k))
        return self.challenge(data)

    def challenge_loop(self, k, elem):
        (k, data) = k(base64.b64decode(elem.text) if elem.text else '')
        if k is False:
            return self.abort()
        elif k is None or k is True:
            self.write(self.E('success', { 'xmlns': self.SASL_NS }))
            return self.success()
        else:
            self.stanza(self.RESPONSE, functools.partial(self.challenge_loop, k), True)
            return self.challenge(data)

    def challenge(self, data):
        self.write(self.E(
            'challenge', { 'xmlns': self.SASL_NS },
            base64.b64encode(data) if data else ''
        ))
        return self

    ## ---------- Client ----------

    def reply(self, feature):
        if self.active():
            mechs = dict(self.mechanisms())
            for offer in feature.iter(self.MECHANISM):
                name = offer.text; mech = mechs.get(name)
                if mech:
                    self.select(name, mech)
                    break

    def select(self, name, mech):
        k = mech(self.auth).respond
        self.stanza(self.SUCCESS, lambda e: self.success())
        self.stanza(self.CHALLENGE, functools.partial(self.reply_loop, k))
        return self.write(self.E('auth', { 'xmlns': self.SASL_NS }, name))

    def reply_loop(self, k, elem):
        (k, data) = k(base64.b64decode(elem.text) if elem.text else '')
        if k is False:
            return self.abort()
        elif k is None:
            return self.response(data)
        elif k is True:
            return self.success()
        else:
            self.stanza(self.CHALLENGE, functools.partial(self.reply_loop, k), True)
            return self.response(data)

    def response(self, data):
        self.write(self.E(
            'response', { 'xmlns': self.SASL_NS },
            base64.b64encode(data) if data else ''
        ))
        return self

    ## ---------- Common ----------

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

    def success(self):
        self.core.authenticated = True
        self.core.reset()
        return self

    def failure(self, name):
        self.write(self.E('failure', { 'xmlns': self.SASL_NS }, self.E(name)))
        self.core.close()
        return self

    def failed(self, elem):
        self.core.close()
        return self

    def abort(self):
        self.write(self.E('abort', { 'xmlns': self.SASL_NS }))
        self.core.close()
        return self

    def aborted(self, elem):
        self.core.close()
        return self


### Client / Server

class ClientCore(Core):

    FEATURES = (TLS, SASL)

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream)
        if not self.wait_for_features():
            self.state.activate()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        return self.E(self.STREAM, {
            'to': 'person@example.net',
            self.LANG: 'en',
            'version': '1.0'
        })

    def initiate(self):
        self.open_stream()

class ServerCore(Core):

    FEATURES = (TLS, SASL)

    ### ---------- Incoming Stream ----------

    def handle_open_stream(self, attr):
        self.state.trigger(ReceivedOpenStream)
        self.open_stream()
        if not self.send_features():
            self.state.activate()

    ### ---------- Outgoing Stream ----------

    def make_stream(self):
        return self.E(self.STREAM, {
            'from': 'server@example.net',
            'id': make_nonce(),
            self.LANG: 'en',
            'version': '1.0'
        })

def make_nonce():
    import random, base64, struct

    random.seed()
    value = random.getrandbits(64)
    return base64.b64encode(''.join(struct.pack('L', value)))

