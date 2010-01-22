## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""application -- XMPP application and plugins"""

from __future__ import absolute_import
import functools, collections
from . import xmlstream, xmppstream

__all__ = ('Application', 'bind', 'stanza', 'Plugin',  'PluginError')

def Application(plugins):
    """Declare an XMPP Application.  An application is an XMLHandler
    that dispatches to stanza handlers.

        import xmpp

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

        server = xmpp.Application([Server, PingPong])
        client = xmpp.Application([Client, PingPong])

        xmpp.TCPServer(server).listen('127.0.0.1', 9000)
    """

    plugins = CompiledPlugins(plugins)
    state = functools.partial(xmppstream.ApplicationState, plugins=plugins)
    target = functools.partial(xmppstream.XMPPStream, state)

    return xmlstream.XMLHandler(target)


### Static plugin decorators

def bind(event):
    """Bind a plugin or method to a certain event.

    Binding a method is a shortcut for self.bind(EventName,
    self.method) in the plugin initializer.

    Binding a plugin (i.e. using bind as a class decorator), activates
    the plugin at a specific time.  Normally plugins are activated at
    a default time (probably right after authorization)."""

    def decorator(obj):
        ## @bind(EventName) class decorator
        if isinstance(obj, type):
            obj.__activate__ = event
            return obj
        ## @bind(EventName) method decorator
        else:
            return BindMethod(event, obj)
    return decorator

def stanza(obj=None, bind=None):
    """Declare a stanza handler.

    The handler will be installed when the plugin is activated.  If an
    optional EventName is given, wait for this event to install the
    handler."""

    ## @stanza(EventName [, 'element-name'])
    if isinstance(obj, type) and issubclass(obj, Event):
        return functools.partial(StanzaMethod, obj, bind)
    ## @stanza('element-name' [, EventName])
    elif isinstance(obj, basestring):
        return functools.partial(StanzaMethod, bind, obj)
    ## @stanza
    else:
        assert callable(obj), '@stanza must decorate a method.'
        return StanzaMethod(None, None, obj)

BindMethod = collections.namedtuple('BindMethod', 'event method')

StanzaMethod = collections.namedtuple('StanzaMethod', 'event name method')


### Plugin Type

## The purpose of this metaclass is to manage declarations of event
## listeners and stanza handlers.  It adds special EVENTS and STANZAS
## attributes to each Plugin class.  They look like this:

##     EVENTS =  [(EventName, [method-name, ...]), ...]
##     STANZAS = [('{ns-uri}stanza', (EventName, method-name)), ...]

## EVENTS is produced by merging together the EVENTS lists in the base
## classes, then adding newly-declared events.  If a Plugin subclasses
## another, its event bindings will override those in the base class
## for the same event name.

## STANZAS is produced in a similar fashion, but there can only be one
## handler for a particular stanza.

##     class A(Plugin):
##
##         @bind(Foo)
##         def gotFoo(self):
##             pass
##
##         @bind(Bar)
##         def gotBar(self):
##             pass
##
##         @stanza
##         def baz(self, elem):
##             pass
##
##     class B(A):
##
##         @bind(Foo)
##         def onFoo(self):
##             pass

## In the example above, the results are:
##
##     A.EVENTS =  [(Foo, ['gotFoo']), (Bar, ['gotBar'])]
##     A.STANZAS = [('{urn:jabber-client}baz', (None, 'baz'))]
##     B.EVENTS =  [(Foo, ['onFoo']), (Bar, ['gotBar'])]
##     B.STANZAS = [('{urn:jabber-client}baz', (None, 'baz'))]
##
## Notice that the A.gotBar() event handler was replaced by B.onBar()
## even though the method names are different.  This is done to keep
## event handling from getting hairy in subclasses.  Defining an event
## handler in a subclass means the new listener needs to call
## base-class event listeners if necessary.

class PluginError(Exception):
    """Raised when a plugin doesn't exist, if a plugin is accessed
    before it's initialized, or if a plugin registers itself as a
    stanza handler and that stanza is already being handled."""

class PluginType(type):

    def __new__(mcls, name, bases, attr):
        try:
            ns = attr['__xmlns__']
        except KeyError:
            ns = next(pluck('__xmlns__', bases), None)

        handlers = scan_attr(ns, attr)
        cls = type.__new__(mcls, name, bases, attr)
        return register_handlers(cls, *handlers)

    def __call__(cls, state, *args, **kwargs):
        """Tweak the construction protocol to pass a magic
        ApplicationState object to __new__(), but not to __init__().
        This is done so that the state can be added to the instance,
        but Plugin implementations are free to make an __init__()
        without worrying about what the state parameter means or
        calling a superclass constructor."""

        obj = cls.__new__(cls, state, *args, **kwargs)
        if obj:
            obj.__init__(*args, **kwargs)

        return obj

def register_handlers(cls, events, stanzas):
    """Register all special handlers in a plugin."""

    ## Sanity check
    st_handlers = set(m for (_, (_, m)) in stanzas)
    for (_, callbacks) in events:
        dup = st_handlers.intersection(set(callbacks))
        if dup:
            raise PluginError('Stanza handler duplicated as event handler.', dup)

    register(cls, 'EVENTS', events, merge_events, add_events)
    register(cls, 'STANZAS', stanzas, merge_stanzas, add_stanzas)

    return cls

def register(cls, property_name, scanned, merge, add):
    """Merge base methods with newly declared methods and record them
    in a special property."""

    base = merge(pluck(property_name, cls.__bases__))
    setattr(cls, property_name, add(base, scanned))
    return cls

def pluck(attr, seq):
    """Pluck the value of attr out of a sequence of objects."""

    return (getattr(x, attr) for x in seq if hasattr(x, attr))

def scan_attr(ns, attr):
    """Find and unbox all of the statically delcared stanza and event
    bindings."""

    events = []; stanzas = []
    for (name, obj) in attr.items():
        if isinstance(obj, BindMethod):
            ## event record: (event, method-name)
            events.append((obj.event, name))
            attr[name] = obj.method
        elif isinstance(obj, StanzaMethod):
            ## stanza record: (name, (activation-event, method-name))
            cname = xmppstream.clark_name(obj.name or name, ns)
            stanzas.append((cname, (obj.event, name)))
            attr[name] = obj.method
    return (events, stanzas)

def merge_events(groups):
    """Merge a sequence of event groups together into one sequence.
    There can be many event handlers for any particular event."""

    result = collections.defaultdict(list)
    seen = set()
    for group in groups:
        for (event, callbacks) in group.iteritems():
            for method in callbacks:
                if method not in seen:
                    seen.add(method)
                    result[event].append(callbacks)
    return result

def add_events(base, new):
    """Add newly declared events to a base set of events.  New
    declarations replace old ones."""

    for (event, callback) in new:
        if event in base:
            del base[event]
            base[event] = [callback]
        else:
            callbacks = base[event]
            if callback not in callbacks:
                callbacks.append(callback)
    return base

def merge_stanzas(groups):
    """Merge a sequence of stanza groups together into once sequence.
    There can only be one stanza handler for each stanza.  The first
    handler wins."""

    if not isinstance(groups, list):
        groups = list(groups)
    return dict(x for g in reversed(groups) for x in g.iteritems())

def add_stanzas(base, new):
    """Add newly declared stanza handlers to a base set.  New handlers
    replace existing ones."""

    base.update(new)
    return base


### Compiled Plugins

class CompiledPlugins(xmppstream.PluginManager):
    """A list of plugins used in an Application is "compiled" into
    data structures that facilitate run-time plugin use."""

    def __init__(self, plugins):
        self.plugins = plugins

        ## The taxonomy facilitates Plugin.plugin().
        self.taxonomy = plugin_taxonomy(plugins)

        ## A mapping of (plugin, activation-record) items to faciliate
        ## plugin activation.
        self.stanzas = plugin_stanzas(plugins)

        ## Special plugins are activated when certain events are
        ## triggered.  Default plugins are activated explicitly by
        ## client/server code (probably after the stream is
        ## authenticated).
        (self.special, self.default) = partition_by_activation(plugins)

    def get(self, state, plugin):
        """Look up a plugin instance in the current
        ApplicationState."""

        name = self.taxonomy.get(plugin)
        if name is None:
            raise PluginError('Plugin %r is not registered.' % plugin)

        value = getattr(state, name, None)
        if value is None:
            active = plugin.__activate__ or 'default-activation'
            raise PluginError('Plugin %r will not be active until %r.' % (
                plugin,
                active
            ))

        return value

    def activate(self, state, name, plugin):
        """Activate a plugin; see Plugin.plugin()."""

        ## Create plugin instance; add it to the state
        instance = plugin(state)
        setattr(state, name, instance)

        ## Activate stanza handlers
        for (name, event, method) in self.stanzas[plugin]:
            method = getattr(instance, method)
            if not event:
                state.stanza(name, method)
            else:
                state.bind(event, thunk(state.stanza, name, method))

        ## Activate event listeners
        for (event, listeners) in plugin.EVENTS.iteritems():
            for method in listeners:
                state.bind(event, getattr(instance, method))

        return self

    def install(self, state):
        """Bind "special" plugins to their activation events."""

        for (event, name, plugin) in self.special:
            state.one(event, thunk(self.activate, state, name, plugin))
        return self

    def activateDefault(self, state):
        """Activate the default plugins.  This must be done
        explicitly.  See Plugin.activatePlugins()."""

        for (name, plugin) in self.default:
            self.activate(state, name, plugin)
        return self

def plugin_taxonomy(plugins):
    taxonomy = {}
    for plugin in plugins:
        name = plugin_name(plugin)
        for cls in plugin_mro(plugin):
            taxonomy.setdefault(cls, name)
    return taxonomy

def plugin_name(plugin):
    return '%s.%s' % (plugin.__module__, plugin.__name__)

def plugin_mro(plugin):
    return (
        c for c in plugin.mro()
        if issubclass(c, Plugin) and c is not Plugin
    )

def plugin_stanzas(plugins):
    seen = set(); stanzas = collections.defaultdict(list)
    for plugin in plugins:
        for (name, (event, method)) in plugin.STANZAS.iteritems():
            if name not in seen:
                seen.add(name)
                stanzas[plugin].append((name, event, method))
    return stanzas

def partition_by_activation(plugins):
    special = []; default = []
    for plugin in plugins:
        event = plugin.__activate__
        if event:
            special.append((event, plugin_name(plugin), plugin))
        else:
            default.append((plugin_name(plugin), plugin))
    return (special, default)

def thunk(proc, *args, **kwargs):
    """Make a thunk that closes over some arguments and ignores
    subsequent ones when it's called."""

    return lambda *a, **k: proc(*args, **kwargs)

class Plugin(object):
    """The Plugin base class.  All Plugins should subclass this."""

    __metaclass__ = PluginType

    ## An event on which this plugin is activated.  Don't set this
    ## directly, use @bind as a class decorator.
    __activate__ = None

    ## The default xmlns for stanza handlers.
    __xmlns__ = 'urn:jabber-client'

    def __new__(cls, state, *args, **kwargs):
        """Record a special state attribute that's used internally in
        the Plugin base class."""

        self = object.__new__(cls)
        self.__state = state
        self.__stream = state.stream
        self.__plugins = state.plugins
        self.E = state.E

        return self

    ## ---------- Plugins ----------

    def plugin(self, cls):
        return self.__plugins.get(self.__state, cls)

    def activatePlugins(self):
        return self.__state.activate()

    ## ---------- Stream ----------

    def write(self, data):
        self.__stream._write(data)
        return self

    def openStream(self, attrs):
        self.__stream._openStream(attrs)
        return self

    def resetStream(self):
        self.__stream._resetStream()
        ## Resetting a stream destroys this plugin.
        return None

    def closeStream(self):
        self.__stream._closeStream()
        ## Closing a stream destroys this plugin.
        return None

    def closeConnection(self):
        self.__stream._close()
        return None

    ## ---------- Events ----------

    def stanza(self, *args, **kwargs):
        self.__state.stanza(*args, **kwargs)
        return self

    def bind(self, *args, **kwargs):
        self.__state.bind(*args, **kwargs)
        return self

    def one(self, *args, **kwargs):
        self.__state.one(*args, **kwargs)
        return self

    def unbind(self, *args, **kwargs):
        self.__state.unbind(*args, **kwargs)
        return self

    def trigger(self, event, *args, **kwargs):
        self.__state.trigger(event, self, *args, **kwargs)
        return self
