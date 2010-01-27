## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""application -- XMPP application and plugins"""

from __future__ import absolute_import
import functools, collections, sasl
from . import xml, interfaces, core

__all__ = (
    'Server', 'Client', 'Application', 'ServerAuth', 'ClientAuth',
    'bind', 'stanza', 'Plugin',  'PluginError'
)

def Server(auth, *args, **kwargs):
    return Application(core.ServerCore, *args, auth=auth, **kwargs)

def Client(auth, *args, **kwargs):
    return Application(core.ClientCore, *args, auth=auth, **kwargs)

def Application(Core, plugins=(), **kwargs):
    """Declare an XMPP Application.  An application is an XMLHandler
    that dispatches to stanza handlers.
    """

    plugins = CompiledPlugins(plugins)
    return functools.partial(Core, plugins=plugins, **kwargs)

def ServerAuth(serv_type, host, users):

    def user():
        raise NotImplementedError

    def password():
        raise NotImplementedError

    return sasl.SimpleAuth(
        sasl.DigestMD5Password,
        users,
        user,
        password,
        lambda: serv_type,
        lambda: host
    )

def ClientAuth(serv_type, host, username, password):

    return sasl.SimpleAuth(
        sasl.DigestMD5Password,
        {},
        lambda: username,
        lambda: password,
        lambda: serv_type,
        lambda: host
    )


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
## listeners and stanza handlers.  It merges __nsmap__ declarations
## and adds special EVENTS and STANZAS attributes to each Plugin
## class.  They look like this:

##     EVENTS  = [(EventName, [method-name, ...]), ...]
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
##     A.STANZAS = [('{jabber:client}baz', (None, 'baz'))]
##     B.EVENTS =  [(Foo, ['onFoo']), (Bar, ['gotBar'])]
##     B.STANZAS = [('{jabber:client}baz', (None, 'baz'))]
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
        ns = get_attribute(bases, attr, '__xmlns__', None)
        nsmap = updated_nsmap(bases, attr)
        handlers = scan_attr(attr, ns, nsmap)
        cls = type.__new__(mcls, name, bases, attr)
        return register_handlers(cls, nsmap, *handlers)

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

def updated_nsmap(bases, attr):
    base = merge_dicts(pluckattr(bases, '__nsmap__'))
    return add_dicts(base, attr.get('__nsmap__'))

def register_handlers(cls, nsmap, events, stanzas):
    """Register all special handlers in a plugin."""

    ## Sanity check
    st_handlers = set(m for (_, (_, m)) in stanzas)
    for (_, callbacks) in events:
        dup = st_handlers.intersection(set(callbacks))
        if dup:
            raise PluginError('Stanza handler duplicated as event handler.', dup)

    register(cls, 'EVENTS', merge_events, add_events, events)
    register(cls, 'STANZAS', merge_dicts, add_dicts, stanzas)
    cls.__nsmap__ = nsmap

    return cls

def register(cls, property_name, merge, add, scanned=None):
    """Merge base methods with newly declared methods and record them
    in a special property."""

    base = merge(pluckattr(cls.__bases__, property_name))
    if scanned is None:
        scanned = getattr(cls, property_name, None)
    setattr(cls, property_name, add(base, scanned))
    return cls

def scan_attr(attr, ns, nsmap):
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
            cname = xml.clark(obj.name or name, ns, nsmap)
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

def merge_dicts(groups):
    """Merge a sequence of dicts together into once dict.  The first
    item wins."""

    if not isinstance(groups, list):
        groups = list(groups)
    return dict(x for g in reversed(groups) for x in g.iteritems())

def add_dicts(base, new):
    """Add newly dict items to a base set.  New items replace existing
    ones."""

    if new:
        base.update(new)
    return base

def get_attribute(bases, attr, name, *default):
    """Get the best attribute from a set of bases and newly declared
    attribtues."""

    try:
        return attr[name]
    except KeyError:
        try:
            return next(pluckattr(bases, name))
        except StopIteration:
            if not default:
                raise AttributeError(name)
            return default

def pluckattr(seq, attr):
    """Pluck the value of attr out of a sequence of objects."""

    return (getattr(x, attr) for x in seq if hasattr(x, attr))


### Compiled Plugins

class CompiledPlugins(interfaces.PluginManager):
    """A list of plugins used in an Application is "compiled" into
    data structures that facilitate run-time plugin use."""

    def __init__(self, plugins):
        self.plugins = plugins

        ## This nsmap can be used to create an ElementMaker that is
        ## aware of the xmlns attributes of the plugins.
        self.nsmap = merge_nsmaps(plugins)

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

        value = state.get(name)
        if value is None:
            active = plugin.__activate__ or 'default-activation'
            raise PluginError('Plugin %r will not be active until %r.' % (
                plugin,
                active
            ))

        return value

    def install(self, core):
        """Bind "special" plugins to their activation events."""

        for (event, group) in self.special.iteritems():
            state.one(event, thunk(self.activate_group, state, group))
        return self

    def activate_default(self, state):
        """Activate the default plugins.  This must be done
        explicitly.  See Plugin.activatePlugins()."""

        return self.activate_group(state, self.default)

    def activate_group(self, state, group):
        """Activate a group of plugins simultaneously.  The
        state.lock() ensures that plugin initializers cannot produce
        side-effects that break other plugins."""

        with state.lock() as state:
            for (name, plugin) in group:
                self.activate(state, name, plugin)
        return self

    def activate(self, state, name, plugin):
        """Activate a plugin; see Plugin.plugin()."""

        ## Create plugin instance; add it to the state
        instance = plugin(state)
        state.set(name, instance)

        ## Activate stanza handlers
        for (name, event, method) in self.stanzas[plugin]:
            method = getattr(instance, method)
            if not event:
                state.bind_stanza(name, method)
            else:
                state.bind(event, thunk(state.bind_stanza, name, method))

        ## Activate event listeners
        for (event, listeners) in plugin.EVENTS.iteritems():
            for method in listeners:
                state.bind(event, getattr(instance, method))

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
    special = collections.defaultdict(list); default = []
    for plugin in plugins:
        event = plugin.__activate__
        if event:
            special[event].append((plugin_name(plugin), plugin))
        else:
            default.append((plugin_name(plugin), plugin))
    return (special, default)

def thunk(proc, *args, **kwargs):
    """Make a thunk that closes over some arguments and ignores
    subsequent ones when it's called."""

    return lambda *a, **k: proc(*args, **kwargs)

def merge_nsmaps(plugins):
    """Merge namespace maps for a sequence of plugins together."""

    return merge_dicts(pluckattr(plugins, '__nsmap__'))


### Plugin Base Class

class Plugin(object):
    """The Plugin base class.  All Plugins should subclass this."""

    __metaclass__ = PluginType

    ## An event on which this plugin is activated.  Don't set this
    ## directly, use @bind as a class decorator.
    __activate__ = None

    ## The default xmlns for stanza handlers.
    __xmlns__ = 'jabber:client'

    ## Add entries to the namespace map
    __nsmap__ = {
        None: __xmlns__,
        'stream': 'http://etherx.jabber.org/streams'
    }

    def __new__(cls, state, *args, **kwargs):
        """Record a special state attribute that's used internally in
        the Plugin base class."""

        self = object.__new__(cls)
        self.__state = state
        self.__core = state.core
        self.__plugins = state.plugins

        self.E = self.__core.E

        return self

    ## ---------- Plugins ----------

    def plugin(self, cls):
        return self.__plugins.get(self.__state, cls)

    def activate_plugins(self):
        self.__state.activate()
        return self

    ## ---------- Stream ----------

    def write(self, data):
        self.__core.write(data)
        return self

    def open_stream(self):
        self.__core.open_stream()
        return self

    def reset_stream(self):
        self.__core.reset()
        ## Resetting a stream destroys this plugin.
        return None

    def close_stream(self):
        self.__core.close_stream()
        ## Closing a stream destroys this plugin.
        return None

    def close(self):
        self.__core.close()
        return None

    def error(self, *args, **kwargs):
        self.__core.error(*args, **kwargs)
        return None

    ## ---------- Events ----------

    def stanza(self, *args, **kwargs):
        self.__state.bind_stanza(*args, **kwargs)
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
