## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""state -- xmpp connection state and event management"""

from __future__ import absolute_import
from . import interfaces as i
from .prelude import *

__all__ = ('State', )


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
        self.plugins.activate(self)
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
            idx = 0; lim = len(handlers)
            while idx < lim:
                handler = handlers[idx]
                self.run(handler, *args, **kwargs)
                if isinstance(handler, Once):
                    del handlers[idx]
                    lim -= 1
                else:
                    idx += 1
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

    def unbind_stanza(name, callback=None):
        try:
            if not callback or self.stanzas[name] is callback:
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

