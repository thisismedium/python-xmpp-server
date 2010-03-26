## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""plugin -- framework for extending an XMPP Core"""

from __future__ import absolute_import
from . import xml, interfaces as i
from .prelude import *

__all__ = (
    'bind', 'stanza', 'iq', 'get_children', 'get_child', 'get_text',
    'Plugin', 'Feature', 'PluginError'
)


### Static plugin decorators

def bind(*events):
    """Bind a plugin to an Event or a method to an Event or stanza.

    Binding a method is a shortcut for self.bind(kind, self.method) in
    the plugin initializer.

    Binding a plugin (i.e. using bind as a class decorator), activates
    the plugin at a specific time.  Normally plugins are activated at
    a default time (usually after features are negotiated).
    """

    def decorator(obj):
        ## @bind(EventName) class decorator
        if isinstance(obj, type):
            obj.__activate__ = events
            return obj
        ## @bind(EventName) method decorator
        else:
            return BindMethod(events, obj)
    return decorator

def stanza(obj=None, bind=None, prefix=''):
    """Declare a stanza handler.

    The handler will be installed when the plugin is activated.  If an
    optional EventName is given, wait for this event to install the
    handler.

    The prefix parameter is used internally."""

    ## @stanza(EventName [, 'element-name'])
    if isinstance(obj, type) and issubclass(obj, i.Event):
        return partial(StanzaMethod, obj, bind, prefix)
    ## @stanza('element-name' [, EventName])
    elif isinstance(obj, basestring):
        return partial(StanzaMethod, bind, obj, prefix)
    ## @stanza
    else:
        assert callable(obj), '@stanza must decorate a method.'
        return StanzaMethod(None, None, prefix, obj)

def iq(obj=None, bind=None):
    """Declare an info query handler."""

    return stanza(obj, bind, '{jabber:client}iq/')

def get_children(expr):
    """Declare a method that will return a list of Elements matching
    expr, an XPath expression interpreted according to the Plugin's
    nsmap."""

    return XPathMethod(expr, lambda x: x)

def get_child(expr, default=None):
    """Declare a method that will return on Element that matches expr
    or the default value.  The XPath expression expr is interpreted
    according to the Plugin's nsmap.'"""

    def make(xpath):
        def child(elem):
            found = xpath(elem)
            return found[0] if found else default
        return child

    return XPathMethod(expr, make)

def get_text(expr, default=''):
    """Like get_child(), but return text."""

    return get_child('%s/text()' % expr, default)

BindMethod = namedtuple('BindMethod', 'events method')
StanzaMethod = namedtuple('StanzaMethod', 'event name prefix method')
XPathMethod = namedtuple('XPathMethod', 'expr make')


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
        nsmap = updated_nsmap(ns, bases, attr)
        handlers = scan_attr(attr, ns, nsmap)
        cls = type.__new__(mcls, name, bases, attr)
        cls.E = xml.ElementMaker(namespace=ns, nsmap=nsmap)
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

def updated_nsmap(ns, bases, attr):
    base = merge_dicts(pluckattr(bases, '__nsmap__'))
    result = add_dicts(base, attr.get('__nsmap__'))
    result[None] = ns
    return result

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
    """Find and unbox all of the statically delcared stanza, event,
    and xpath bindings."""

    events = []; stanzas = []
    for (name, obj) in attr.items():
        if isinstance(obj, BindMethod):
            ## event record: (event, method-name)
            for event in obj.events:
                events.append((event, name))
            attr[name] = obj.method
        elif isinstance(obj, StanzaMethod):
            ## stanza record: (name, (activation-event, method-name))
            cname = '%s%s' % (obj.prefix, xml.clark(obj.name or name, ns, nsmap))
            stanzas.append((cname, (obj.event, name)))
            attr[name] = obj.method
        elif isinstance(obj, XPathMethod):
            xpath = xml.xpath(xml.clark_path(obj.expr, nsmap=nsmap))
            attr[name] = staticmethod(obj.make(xpath))
    return (events, stanzas)

def merge_events(groups):
    """Merge a sequence of event groups together into one sequence.
    There can be many event handlers for any particular event."""

    result = ddict(list)
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

class CompiledPlugins(i.PluginManager):
    """A list of plugins used in an Application is "compiled" into
    data structures that facilitate run-time plugin use."""

    def __init__(self, plugins):
        ## Plugins may be delcared as a tuple of (plugin, { kwargs
        ## ... }); start by normalizing the declarations into a list
        ## of plugins and list of procedures to call to activate the
        ## plugin.
        (plugins, activate) = plugin_declarations(plugins)

        ## This nsmap can be used to create an ElementMaker that is
        ## aware of the xmlns attributes of the plugins.
        self.nsmap = merge_nsmaps(plugins) or type(self).nsmap

        ## The taxonomy facilitates Plugin.plugin().
        self.taxonomy = plugin_taxonomy(plugins)

        ## A mapping of (plugin, activation-record) items to faciliate
        ## plugin activation.
        self.stanzas = plugin_stanzas(plugins)

        ## Special plugins are activated when certain events are
        ## triggered.  Default plugins are activated explicitly by
        ## client/server code (probably after the stream is
        ## authenticated).
        (self.special, self.default) = partition_by_activation(plugins, activate)

    def get(self, state, plugin):
        """Look up a plugin instance in the current State."""

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

    def install(self, state):
        """Bind "special" plugins to their activation events."""

        for (event, group) in self.special.iteritems():
            state.one(event, partial(self.activate_group, state, group))
        return self

    def activate(self, state, *args, **kwargs):
        """Activate the default plugins.  This must be done
        explicitly.  See Plugin.activatePlugins()."""

        return self.activate_group(state, self.default, *args, **kwargs)

    def activate_group(self, state, group, *args, **kwargs):
        """Activate a group of plugins simultaneously.  The
        state.lock() ensures that plugin initializers cannot produce
        side-effects that break other plugins."""

        with state.lock() as state:
            for (name, make) in group:
                self.activate_one(state, name, make, args, kwargs)
        return self

    def activate_one(self, state, name, make, args, kwargs):
        """Activate a plugin; see Plugin.plugin()."""

        instance = make(state, *args, **kwargs)
        state.set(name, instance)
        activate_plugin(self.stanzas, state, instance)

        return self

def activate_plugin(stanzas, state, instance):
    """Activate a plugin; see Plugin.plugin()."""

    ## Activate stanza handlers
    for (name, event, method) in stanzas[type(instance)]:
        method = getattr(instance, method)
        if not event:
            state.bind_stanza(name, method)
        else:
            state.bind(event, thunk(state.bind_stanza, name, method))

    ## Activate event listeners
    for (event, listeners) in instance.EVENTS.iteritems():
        for method in listeners:
            state.bind(event, getattr(instance, method))

    return instance

def plugin_declarations(declarations):
    plugins = []; activate = []
    for obj in declarations:
        if isinstance(obj, tuple):
            (plugin, settings) = obj
            plugins.append(plugin)
            activate.append(partial(plugin, **settings))
        else:
            plugins.append(obj)
            activate.append(obj)
    return (plugins, activate)

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
    seen = set(); stanzas = ddict(list)
    for plugin in plugins:
        for (name, (event, method)) in plugin.STANZAS.iteritems():
            if name not in seen:
                seen.add(name)
                stanzas[plugin].append((name, event, method))
    return stanzas

def partition_by_activation(plugins, activate):
    special = ddict(list); default = []
    for (plugin, make) in izip(plugins, activate):
        for event in plugin.__activate__:
            special[event].append((plugin_name(plugin), make))
        else:
            default.append((plugin_name(plugin), make))
    return (special, default)

def merge_nsmaps(plugins):
    """Merge namespace maps for a sequence of plugins together."""

    return merge_dicts(pluckattr(plugins, '__nsmap__'))


### Plugin Base Class

class Plugin(object):
    """The Plugin base class.  All Plugins should subclass this."""

    __metaclass__ = PluginType

    ## An event on which this plugin is activated.  Don't set this
    ## directly, use @bind as a class decorator.
    __activate__ = ()

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

        return self

    ## ---------- Stream ----------

    def send(self, where, what):
        return self._transmit('handle', where, what)

    def recv(self, where, what):
        return self._transmit('write', where, what)

    def handle(self, *args):
        self.__core.handle_stanza(*args)
        return self

    def write(self, *args):
        self.__core.write(*args)
        return self

    def iq(self, kind=None, elem=None, *args, **kw):
        """Write an IQ stanza to the stream, bind a callback for
        get/set, or bind iq stanza handlers."""

        ## iq('get/set', callback, iq-body)
        ## iq('result/error', iq-elem)
        if isinstance(kind, basestring) and (args or xml.is_element(elem)):
            ## elem may be an Element or callback
            self.__core.iq(kind, elem, *args)
            return self

        ## iq('kind', handle [, kind=handle, ...])
        ## iq([('kind', handle), ... [, kind=handle, ...]])
        assert not args, 'Unexpected arguments: %r' % args
        if isinstance(kind, basestring):
            kw[kind] = elem
        elif kind:
            kw = chain_items(kind, kw)

        ## 'kind' ==> '{jabber:client}iq/{__xmlns__}kind'
        iq = '{%s}iq/%%s' % self.__core.__xmlns__
        bind = self.__state.bind_stanza
        for (name, handle) in items(kw):
            bind(iq % xml.clark(name, self.__xmlns__), handle)
        return self

    def error(self, *args, **kwargs):
        self.__core.stanza_error(*args, **kwargs)
        return self

    def close(self):
        self.__core.close()
        return None

    def add_timeout(self, *args):
        self.__core.add_timeout(*args)
        return self

    def clear_timeout(self, *args):
        self.__core.remove_timeout(*args)
        return self

    ## ---------- Low-level Stream ----------

    def open_stream(self, *args):
        self.__core.open_stream(*args)
        return self

    def use_tls(self):
        return self.__core.use_tls()

    def starttls(self, *args, **kwargs):
        self.__core.starttls(*args, **kwargs)
        return self

    def reset_stream(self):
        self.__core.reset()
        ## Resetting a stream destroys this plugin.
        return None

    def close_stream(self, *args):
        self.__core.close_stream(*args)
        ## Closing a stream destroys this plugin.
        return None

    def stream_error(self, *args, **kwargs):
        self.__core.stream_error(*args, **kwargs)
        ## Stream-level errors are not recoverable.
        return None

    def _transmit(self, method, where, what):
        from .features import NoRoute # FIXME: ugly circular import.

        try:
            for (jid, route) in self.routes(where):
                getattr(route, method)(what)
        except NoRoute:
            log.warning('transmit(%r, %r, %r)',
                        method,
                        where,
                        xml.tostring(what),
                        exc_info=True)
        return self

    ## ---------- Events ----------

    def bind(self, *args, **kw):
        dispatch(self, self.__state.bind, self.__state.bind_stanza, *args, **kw)
        return self

    def one(self, *args, **kw):
        dispatch(self, self.__state.one, self.__state.one_stanza, *args, **kw)
        return self

    def unbind(self, *args, **kw):
        dispatch(self, self.__state.unbind, self.__state.unbind_stanza, *args, **kw)
        return self

    def trigger(self, event, *args, **kwargs):
        if xml.is_element(event):
            self.__state.trigger_stanza(event, *args, **kwargs)
        else:
            self.__state.trigger(event, self, *args, **kwargs)
        return self

    ## ---------- Features and Plugins ----------

    secured = property(lambda s: s.__core.secured)
    authJID = property(lambda s: s.__core.authJID)

    def plugin(self, cls):
        return self.__plugins.get(self.__state, cls)

    def activate_plugins(self):
        self.__state.activate()
        return self

    def routes(self, jid):
        return self.__core.routes(jid)


def dispatch(plugin, event, stanza, kind=None, callback=None, **kw):
    """Dispatch on one or more event/stanza changes to Plugin state."""

    ## method(kind, callback)
    if isinstance(kind, (basestring, type)):
        return switch(plugin, event, stanza, kind, callback, **kw)
    elif callback:
        raise ValueError('bind(): unexpected second argument')

    ## method([(kind, callback), ...], kind=callback, ...)
    for (name, val) in chain_items(kind, kw):
        switch(plugin, event, stanza, name, val)

def switch(plugin, event, stanza, kind, callback, **kw):
    """Dispatch on one event or stanza change to Plugin state."""

    if isinstance(kind, basestring):
        kind = xml.clark(kind, plugin.__xmlns__)
        stanza(kind, callback, **kw)
    else:
        event(kind, callback, **kw)


### Compiled Features

class CompiledFeatures(i.PluginManager):
    """Features are less complicated than normal Plugins because they
    are activated all at once."""

    def __init__(self, features):
        (features, activate) = plugin_declarations(features)
        self.stanzas = plugin_stanzas(features)
        (special, self.default) = partition_by_activation(features, activate)
        if special:
            raise ValueError('Features may not be bound to events:', special)

    def install(self, state):
        return FeatureList(self, state, (f(state) for (_, f) in self.default))

    def activate(self, state, features):
        for instance in features:
            yield activate_plugin(self.stanzas, state, instance)

class FeatureList(list):
    """The core implementation keeps a list of installed features.
    This list is used to send and respond to the <stream:features>
    stanza."""

    __slots__ = ('state', 'compiled')

    def __init__(self, compiled, state, *args):
        super(FeatureList, self).__init__(*args)
        self.state = state
        self.compiled = compiled

    def include(self):
        return (f.include() for f in self.activated() if f.active())

    def active(self):
        return ((f.TAG, f) for f in self.activated() if f.active())

    def activated(self):
        return self.compiled.activate(self.state, self)


### Feature Base Class

class FeatureType(PluginType):

    def __new__(mcls, name, bases, attr):
        cls = PluginType.__new__(mcls, name, bases, attr)
        if 'TAG' not in attr:
            ## The client uses this to map feature clause names to
            ## Feature instances.  See FeatureList.active().
            cls.TAG = xml.clark(name.lower(), cls.__xmlns__)
        return cls

class Feature(Plugin):
    """A Feature is a special plugin that keeps its state for the
    lifetime of a connection.  Features are negotiated when a stream
    is opened."""

    __metaclass__ = FeatureType

    def active(self):
        """Is this feature currently active?"""

        return False

    def include(self):
        """Include this feature in the list of features sent by a
        server after opening a stream.  The result must be an element
        to include as a child of <stream:mechanisms>."""

        return None

    def reply(self, feature):
        """Reply to a feature clause received from a server."""

        return None
