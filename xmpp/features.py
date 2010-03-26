## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""features -- XMPP stream features"""

from __future__ import absolute_import
import sasl, weakref, random, hashlib, base64
from . import plugin, xml, interfaces as i
from .prelude import *

__all__ = (
    'StartTLS', 'StreamSecured',
    'Mechanisms', 'StreamAuthorized',
    'Bind', 'StreamBound', 'Resources', 'NoRoute',
    'Session', 'SessionStarted'
)


### Events

class StreamSecured(i.Event):
    """TLS negotiated was successful."""

class StreamAuthorized(i.Event):
    """SASL authorization was successful."""

class StreamBound(i.Event):
    """Resource binding is finished."""

class SessionStarted(i.Event):
    """A Session has begun."""


### TLS

class StartTLS(plugin.Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-tls'

    def __init__(self, **options):
        self.options = options
        self._active = (
            not options.get('server_side')
            or (options.get('keyfile') and options.get('certfile'))
        )

    def active(self):
        return self._active and self.use_tls()

    @plugin.bind(StreamAuthorized)
    def on_authorized(self, auth):
        self._active = False

    ## ---------- Server ----------

    def include(self):
        self.bind('starttls', self.proceed)
        return self.E.starttls()

    def proceed(self, elem):
        self.write(self.E.proceed(), self.negotiate)

    ## ---------- Client ----------

    def reply(self, feature):
        self.bind(proceed=thunk(self.negotiate), failure=thunk(self.close))
        return self.write(self.E.starttls())

    ## ---------- Common ----------

    def negotiate(self):
        self.starttls(self.done, **self.options)

    def done(self):
        self._active = False
        self.trigger(StreamSecured).reset_stream()


### SASL

class Mechanisms(plugin.Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-sasl'

    DEFAULT_MECHANISMS = (sasl.Plain, sasl.DigestMD5)

    def __init__(self, auth, mechanisms=None):
        self.auth = auth
        self.mechanisms = mechanisms or self.DEFAULT_MECHANISMS
        self.jid = None

    def active(self):
        return not self.jid

    ## ---------- Server ----------

    def include(self):
        self.bind(
            auth=self.begin,
            abort=self.terminate,
            success=self.terminate,
            failure=self.terminate
        )
        return extend(
            self.E.mechanisms(),
            imap(self.E.mechanism, keys(self.allowed()))
        )

    def begin(self, elem):
        Mech = get(self.allowed(), elem.get('mechanism'))
        if not Mech:
            return self.failure('invalid-mechanism')
        log.debug('Begin mechanism: %r.', Mech)
        state = Mech(self.auth).challenge()
        if not state.data and elem.text:
            return self.challenge_loop(state, elem)
        else:
            return self.issue_challenge(state)

    def challenge_loop(self, state, elem):
        log.debug('SASL challenge-loop: %r %r', state, elem.text)
        state = state(self.decode(elem.text))
        if state.failure():
            return self.abort()
        elif state.success() or state.confirm():
            return self.write(self.E.success(), partial(self.success, state))
        else:
            return self.issue_challenge(state)

    def issue_challenge(self, state):
        self.bind('response', partial(self.challenge_loop, state))
        self.write(self.E.challenge(self.encode(state.data)))
        return self

    ## ---------- Client ----------

    get_mechanisms = plugin.get_children('mechanism')

    def reply(self, feature):
        mechs = dict(self.allowed())
        for offer in self.get_mechanisms(feature):
            name = offer.text; mech = mechs.get(name)
            if mech:
                self.select(name, mech)
                break

    def select(self, name, mech):
        state = mech(self.auth).respond
        self.bind('challenge', partial(self.reply_loop, state))
        return self.write(self.E.auth(mechanism=name))

    def reply_loop(self, state, elem):
        state = state(self.decode(elem.text))
        if state.failure():
            return self.abort()
        elif state.success():
            return self.success(state)

        ## Not done yet; continue challenge loop until SUCCESS.
        self.bind('success', thunk(self.success, state))
        if state.confirm():
            return self.response(state.data)
        else:
            self.bind('challenge', partial(self.reply_loop, state))
            return self.response(state.data)

    def response(self, data):
        self.write(self.E.response(self.encode(data)))
        return self

    ## ---------- Common ----------

    def decode(self, data):
        return base64.b64decode(data) if data else ''

    def encode(self, data):
        return base64.b64encode(data) if data else ''

    def allowed(self):
        for Mech in self.mechanisms:
            if self.secured or Mech.SECURE:
                yield (Mech.__mechanism__, Mech)

    def success(self, state):
        self.jid = xml.jid(state.entity, host=self.auth.host())
        return self.trigger(StreamAuthorized).reset_stream()

    def failure(self, name):
        self.write(self.E.failure(self.E(name)))
        return self.close()

    def abort(self):
        self.write(self.E.abort())
        return self.close()

    def terminate(self, elem):
        log.error('Terminating SASL negotiation: %r.', xml.tostring(elem))
        return self.close()


### Resource Binding

class Bind(plugin.Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-bind'

    def __init__(self, resources):
        self.resources = resources
        self.jid = None

    def active(self):
        return bool(self.authJID)

    ### ---------- Server ----------

    get_resource = plugin.get_text('bind/resource')

    def include(self):
        self.iq('bind', self.new_binding)
        return self.E.bind()

    def new_binding(self, iq):
        assert iq.get('type') == 'set'
        self.jid = self.resources.bind(self.get_resource(iq), self)
        self.iq('result', iq, self.E.bind(self.E.jid(unicode(self.jid))))
        return self.trigger(StreamBound)

    ### ---------- Client ----------

    _get_jid = plugin.get_text('bind/jid')

    def get_jid(self, obj):
        return xml.jid(self._get_jid(obj))

    def reply(self, feature):
        return self.iq('set', self.bound, self.E.bind())

    def bound(self, iq):
        assert iq.get('type') == 'result'
        self.jid = self.resources.bound(self.get_jid(iq), self)
        return self.trigger(StreamBound)

class NoRoute(Exception):
    """Routes are used to deliver messages.  This exception is raised
    when no routes can be found for a particular jid."""

class Resources(object):
    """Track resource bindings for a node."""

    def __init__(self):
        ## This technique is derived from weakref.WeakValueDictionary
        def remove(wr, selfref=weakref.ref(self)):
            self = selfref()
            if self is not None:
                self.unbind(wr.key)
        self._remove = remove

        self._bound = {}
        self._routes = ddict(set)

    def bind(self, name, feature):
        """Create a fresh binding."""

        resource = '%s-%d' % (name or 'Resource', random.getrandbits(32))
        jid = xml.jid(feature.authJID, resource=md5(resource))
        return self._bind(feature, jid)

    def bound(self, jid, feature):
        """Register a binding created for this feature."""

        return self._bind(feature, jid)

    def _bind(self, feature, jid):
        ## Bindings are made with weak references to keep the
        ## book-keeping overhead in the core and plugins to a minimum.
        wr = weakref.KeyedRef(feature, self._remove, jid)
        if self._bound.setdefault(jid, wr)() is not feature:
            raise i.IQError('cancel', 'conflict')
        self._routes[jid.bare].add(jid)
        return jid

    def unbind(self, jid):
        """Destroy a registered binding."""

        del self._bound[jid]
        routes = self._routes.get(jid.bare)
        if routes:
           if len(routes) > 1:
               routes.remove(jid)
           else:
               del self._routes[jid.bare]
        return self

    def routes(self, jid):
        """Produce a sequence of routes to the given jid.

        Routes are used to deliver messaged.  A full jid has only one
        route; a bare jid may have multiple routes.  If there are no
        routes found, a NoRoutes exception is raised."""

        bound = self._bound

        ## Only one route for a full JID
        if xml.is_full_jid(jid):
            wr = bound.get(jid)
            if wr is None:
                raise NoRoute(jid)
            return ((jid, wr()),)

        ## A bare JID may map to multiple full JIDs.
        routes = self._routes.get(jid.bare)
        if routes:
            routes = tuple(
                (w.key, w())
                for w in ifilter(bound.get(j) for j in routes)
            )
        if not routes:
            raise NoRoute(jid)
        return routes

def md5(data):
    return hashlib.md5(data).hexdigest()


### Sessions

class Session(plugin.Feature):
    __xmlns__ = 'urn:ietf:params:xml:ns:xmpp-session'

    def active(self):
        return bool(self.authJID)

    ### ---------- Server ----------

    def include(self):
        self.iq('session', self.start)
        return self.E.session()

    def start(self, iq):
        self.trigger(SessionStarted)
        return self.iq('result', iq)

    ### ---------- Client ----------

    def reply(self, feature):
        self.one(StreamBound, self.establish)

    def establish(self, bindings):
        return self.iq('set', self.started, self.E.session())

    def started(self, iq):
        assert iq.get('type') == 'result'
        self.trigger(SessionStarted)
