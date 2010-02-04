## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""state -- xmpp connection state and event management"""

from __future__ import absolute_import
import weakref, random, hashlib
from . import interfaces as i, xmppstream, xml
from .prelude import *

__all__ = ('Event', 'State', 'Resources', 'NoRoute')


### Events

class Event(object):
    """Subclass this to declare a new Event.  Use the docstring to
    describe the event and how it should be used."""


### State

class State(object):
    """Manage events, synchronize plugins, keep plugin state."""

    def __init__(self, core, plugins=None):
        self.core = core
        self.plugins = plugins or NoPlugins()

        self.locked = False
        self.schedule = deque()
        self.events = ddict(list)
        self.stanzas = {}
        self.state = {}

    def reset(self):
        return self.flush(True).clear().install()

    def install(self):
        self.plugins.install(self)
        return self

    def activate(self):
        self.plugins.activate_default(self)
        return self

    def clear(self):
        self.locked = False
        self.schedule.clear()
        self.events.clear()
        self.stanzas.clear()
        self.state.clear()
        return self

    ## ---------- Plugin State ----------

    def get(self, name, default=None):
        return self.state.get(name, default)

    def set(self, name, value):
        self.state[name] = value
        return self

    ## ---------- Events ----------

    def bind(self, kind, callback):
        self.events[kind].append(callback)
        return self

    def one(self, kind, callback):
        return self.bind(kind, Once(callback))

    def unbind(self, kind, callback):
        if kind in self.events:
            try:
                self.events[kind].remove(callback)
            except ValueError:
                pass
        return self

    def trigger(self, event, *args, **kwargs):
        handlers = self.events.get(event)
        if handlers:
            for (index, handler) in enumerate(handlers):
                if isinstance(handler, Once):
                    del handlers[index]
                self.run(handler, *args, **kwargs)
        return self

    ## ---------- Stanzas ----------

    def is_stanza(self, name):
        return name in self.stanzas

    def bind_stanza(self, name, callback, replace=True):
        exists = self.stanzas.get(name)
        if exists and not replace:
            raise ValueError('The %r stanza is handled by %r.' % (
                name,
                exists
            ))
        self.stanzas[name] = callback
        return self

    def one_stanza(self, name, callback, *args, **kwargs):
        return self.bind_stanza(name, Once(callback), *args, **kwargs)

    def unbind_stanza(name):
        try:
            del self.stanzas[name]
        except KeyError:
            pass
        return self

    def trigger_stanza(self, name, *args, **kwargs):
        handler = self.stanzas.get(name)
        if not handler:
            raise i.StreamError(
                'unsupported-stanza-type',
                'Unrecognized stanza %r.' % name
            )
        elif isinstance(handler, Once):
            del self.stanzas[name]
        return self.run(handler, *args, **kwargs)

    ## ---------- Synchronization ----------

    @contextmanager
    def lock(self):
        """A re-entrant lock that guards events and writes to the
        stream.  This is useful for coordinating activity across many
        plugins.  When the lock is released, pending jobs are run."""

        orig = self.locked
        try:
            self.locked = True
            yield self
        finally:
            self.locked = orig
            if not orig:
                self.schedule and self.flush()

    def run(self, method, *args, **kwargs):
        """Run or schedule a job; if delayed, it will be run later
        through flush()."""

        if self.locked:
            self.schedule.append(partial(method, *args, **kwargs))
            return self

        with self.lock():
            method(*args, **kwargs)
        return self

    def flush(self, force=False):
        """Try to flush any scheduled jobs."""

        if not self.schedule or (self.locked and not force):
            return self

        try:
            self.locked = True
            while self.schedule:
                self.schedule.popleft()()
            return self
        finally:
            self.locked = False

class Once(namedtuple('once', 'callback')):
    """An event handler that should only be called once."""

    def __call__(self, *args, **kwargs):
        return self.callback(*args, **kwargs)

class NoPlugins(i.PluginManager):

    def install(self, state):
        pass

    def activate_default(self, state):
        pass


### Resources

class NoRoute(Exception):
    """Routes are used to deliver messages.  This exception is raised
    when no routes can be found for a particular jid."""

class Resources(object):
    """Track resource bindings for a node.

    See also: core.Bind
    """

    def __init__(self):

        ## This technique is derived from weakref.WeakValueDictionary
        def remove(wr, selfref=weakref.ref(self)):
            self = selfref()
            if self is not None:
                self.unbind(wr.key)
        self._remove = remove

        self._bound = {}
        self._routes = ddict(set)

    def bind(self, name, core):
        """Create a fresh binding."""

        resource = '%s-%d' % (name or 'Resource', random.getrandbits(32))
        jid = xml.jid(core.authJID, resource=md5(resource))
        return self._bind(core, core.authJID, jid)

    def bound(self, jid, core):
        """Register a binding created for this core."""

        return self._bind(core, xml.jid(jid, resource=False), jid)

    def _bind(self, core, bare, jid):
        ## Bindings are made with weak references to keep the
        ## book-keeping overhead in the core to a minimum.
        wr = weakref.KeyedRef(core, self._remove, jid)
        if self._bound.setdefault(jid, wr)() is not core:
            raise i.IQError('cancel', 'conflict')
        self._routes[bare].add(jid)
        return jid

    def unbind(self, jid):
        """Destroy a registered binding."""

        del self._bound[jid]
        bare = xml.jid(jid, resource=False)
        routes = self._routes.get(bare)
        if routes:
           if len(routes) > 1:
               routes.remove(jid)
           else:
               del self._routes[bare]
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
        routes = self._routes.get(jid)
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
