## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""xmppstream -- SAX Stream handlers that generate XMPP events"""

from __future__ import absolute_import
import re, collections, functools
from lxml import etree, builder
from . import xmlstream

__all__ = (
    'Application', 'Handler', 'stanza', 'bind',
    'ConnectionOpen', 'ConnectionReset', 'ConnectionClose',
    'StreamStart', 'StreamStop',
    'XMPPError'
)

def Application(handlers):
    """Declare an XMPP Application.  An application is an XMLHandler
    that dispatches to stanza handlers.

        import xmpp

        class Client(xmpp.Handler):

            @xmpp.bind(xmpp.ConnectionReset)
            def on_open(state):
                '''Start by opening a stream.'''
                state.start({ 'from': 'client' })

            @xmpp.bind(xmpp.StreamStart)
            def on_start(state):
                '''The server opened a stream; ping it.'''
                state.write(state.E('ping'))

            @xmpp.stanza('{jabber:client}pong')
            def pong(state, elem):
                '''A pong was received from the server; close the stream.'''
                state.stop()

        class Server(xmpp.Handler):

            @xmpp.bind(xmpp.StreamStart)
            def on_start(state):
                '''A client initiated a stream; open the server stream.'''
                state.start({ 'from': 'server' })

            @xmpp.stanza('{jabber:client}ping')
            def ping(state, elem):
                '''A client sent a ping; reply with a pong.'''
                state.write(state.E('pong'))

            @xmpp.bind(xmpp.StreamStop)
            def on_close(state):
                '''A client closed the stream; close the server stream.'''
                state.stop()

        server = xmpp.Application([Server])
        client = xmpp.Application([Client])

        xmpp.TCPServer(server).listen('127.0.0.1', 9000)
    """

    handler = type('Handlers', tuple(handlers), {})
    target = functools.partial(XMPPHandler, handler.STANZAS, handler.EVENTS)
    return xmlstream.XMLHandler(target)


### Events

class Event(object):
    """Subclass this to declare a new Event.  Use the docstring to
    describe the event and how it should be used."""

class ConnectionOpen(Event):
    """This is triggered once per connection.  Subscribe to this to
    implement connection-level initialization.  Use this for setting
    up connection-level state.  Use ConnectionReset for initializing
    application-level state."""

class ConnectionReset(Event):
    """This is triggered when a stream is reset.  This happens (1)
    immediately after ConnectionOpen, (2) after TLS negotiation, and
    (3) after SASL negotiation.  Application state should almost
    always be initialized on ConnectionReset."""

class ConnectionClose(Event):
    """This is triggered when a connection is closed; use this to tear
    down state."""

class StreamStart(Event):
    """Triggered when a <stream:stream> element is received."""

class StreamStop(Event):
    """Triggered when a </stream:stream> is received."""


### XMPP State

class XMPPState(object):
    """Application state for an XMPP connection is kept here.  This
    state may be reset over the lifetime of an XMPP connection, so
    initialization should be done through a ConnectionReset event
    handler."""

    def __init__(self, handler, E):
        self._handler = handler
        self._events = collections.defaultdict(list)
        self.E = E

    ## ---------- Stream ----------

    def reset(self):
        self._handler._reset()
        ## Resetting the stream destroys the state; using self is no
        ## longer reliable.
        return None

    def write(self, data):
        self._handler._write(data)
        return self

    def start(self, attrs):
        self._handler._begin(attrs)
        return self

    def stop(self):
        self._handler._close()

    ## ---------- Events ----------

    def bind(self, kind, callback):
        self._events[kind].append(callback)
        return self

    def one(self, kind, callback):
        self.bind(kind, Once(callback))
        return self

    def unbind(self, kind, callback):
        if kind in self._events:
            try:
                self._events[kind].remove(callback)
            except ValueError:
                pass
        return self

    def trigger(self, event):
        self._handler._trigger(event)
        return self

    def _trigger(self, event):
        handlers = self._events.get(event, ())
        for (index, handler) in enumerate(handlers):
            handler(self)
            if isinstance(handler, Once):
                del handlers[index]
        return self

class Once(collections.namedtuple('once', 'callback')):
    """An event handler that should only be called once."""

    def __call__(self, *args, **kwargs):
        return self.callback(*args, **kwargs)


### Handlers

def bind(event):
    """A decorator that declares an event handler."""

    return functools.partial(BindMethod, event)

def stanza(proc_or_name):
    """A decorator that declars a stanza handler."""

    if callable(proc_or_name):
        return StanzaMethod(proc_or_name.__name__, proc_or_name)
    elif isinstance(proc_or_name, basestring):
        return functools.partial(StanzaMethod, proc_or_name)
    else:
        raise ValueError('Expected procedure or stanza name')

class HandlerType(type):
    """Process stanza and bind declarations in an XMPP Handler."""

    def __new__(mcls, name, bases, attr):
        cls = type.__new__(mcls, name, bases, attr)
        base_events = mcls.merge_events(pluck('EVENTS', bases))
        base_stanzas = mcls.merge_stanzas(pluck('STANZAS', bases))
        (events, stanzas) = mcls.process_attr(attr.get('NAMESPACE'), attr)

        cls.EVENTS = mcls.add_events(base_events, events)
        cls.STANZAS = mcls.add_stanzas(base_stanzas, stanzas)

        return cls

    @classmethod
    def process_attr(mcls, ns, attr):
        events = []; stanzas = []
        for (key, value) in attr.iteritems():
            if isinstance(value, BindMethod):
                events.append((value.event, value.method))
            elif isinstance(value, StanzaMethod):
                stanzas.append((clark_name(value.name, ns), value.method))
        return (events, stanzas)

    @classmethod
    def merge_events(mcls, groups):
        result = collections.defaultdict(list)
        for group in groups:
            for (name, callbacks) in group.iteritems():
                result[name].extend(callbacks)
        return result

    @classmethod
    def add_events(mcls, base, new):
        for (name, callbacks) in new:
            for (name, callback) in new:
                if name in base:
                    del base[name]
                base[name].append(callback)
        return base

    @classmethod
    def merge_stanzas(mcls, groups):
        return dict(x for g in groups for x in g.iteritems())

    @classmethod
    def add_stanzas(mcls, base, new):
        base.update(new)
        return base

def pluck(attr, seq):
    return (getattr(x, attr) for x in seq if hasattr(x, attr))

class BindMethod(staticmethod):

    def __init__(self, name, proc):
        staticmethod.__init__(self, proc)
        self.event = name

    method = property(lambda s: s.__get__(object))

class StanzaMethod(staticmethod):
    def __init__(self, name, proc):
        staticmethod.__init__(self, proc)
        self.name = name

    method = property(lambda s: s.__get__(object))

class Handler(object):
    __metaclass__ = HandlerType


### XML Utilities

CLARK_NAME = re.compile(r'^{[^}]+}.+$')

def clark_name(obj, ns=None):
    """Convert an object to Clark Notation.

    >>> clark_name((u'foo', u'bar'))
    u'{foo}bar'
    >>> clark_name((None, u'bar'), u'foo')
    u'{foo}bar'
    >>> clark_name(u'bar', u'foo')
    u'{foo}bar'
    >>> clark_name(u'{foo}bar')
    return u'{foo}bar'
    """
    if isinstance(obj, basestring):
        probe = CLARK_NAME.match(obj)
        if probe:
            return obj
        obj = (ns, obj)
    return u'{%s}%s' % (obj[0] or ns, obj[1]) if (obj[0] or ns) else obj[1]


### XMPP Streams

class XMPPError(Exception): pass

class XMPPHandler(object):
    """A SAX ContentHandler that processes an XMPP stream.  Stanza and
    Event handlers may be registered to act on this stream.  It's best
    to act through the XMPPState."""

    VERSION = 1.0

    NAMESPACE = 'jabber:client'

    NSMAP = {
        None: NAMESPACE,
        'stream': 'http://etherx.jabber.org/streams'
    }

    STREAM = clark_name((NSMAP['stream'], 'stream'))

    StateType = XMPPState

    def __init__(self, stanzas, events, stream, state=None):
        self._stream = stream
        self._stanzas = stanzas
        self._events = events
        self._StateType = state or self.StateType
        self._E = builder.ElementMaker(namespace=self.NAMESPACE, nsmap=self.NSMAP)
        self._open()

    def _open(self):
        """Open the connection.  This should only be called once."""

        self._setup()
        self._trigger(ConnectionOpen)
        self._trigger(ConnectionReset)

    def _reset(self):
        """Reset the stream.  This will destroy the current state and
        may be called any time."""

        self._stream.reset()
        self._setup()
        self._trigger(ConnectionReset)

    def _setup(self):
        self._state = self.StateType(self, self._E)
        self._ns_new = {}
        self._peer = []
        self._root = None

    def _write(self, data):
        if isinstance(data, etree._Element):
            data = etree.tostring(data, encoding='utf-8')
        self._stream.write(data)

    def _begin(self, attrs):
        if self._root:
            raise XMPPError('Stream already open.')

        attrs['version'] = unicode(self.VERSION)
        self._root = self._E(self.STREAM, attrs)

        ## FIXME: hack; replace with an lxml api call to
        ## generate an opening tag if there is one.
        ##   <stream:stream ... /> ==> <stream:stream ...>
        return self._write(etree.tostring(self._root).replace('/>', '>'))

    def _end(self):
        if self._root is None:
            raise XMPPError('Stream already closed.')

        self._root = None
        ## FIXME: hack; replace this with an lxml api call to
        ## generate a closing tag if there is one.
        return self._write('</stream:stream>')

    def _close(self):
        self._end()
        self._trigger(ConnectionClose)
        self._stream.close()

    ## ---------- Events ----------

    def _trigger(self, event):
        state = self._state._trigger(event)

        for handler in self._events.get(event, ()):
            handler(state)

        return self

    def _stanza(self, name, elem):
        handler = self._stanzas.get(name)
        if not handler:
            raise XMPPError('Unrecognized stanza: %r.' % name)
        handler(self._state, elem)
        if self._peer:
            ## Destroy this stanza by clearing out the root element.
            self._peer[0].clear()

    def _streamStart(self):
        self._trigger(StreamStart)

    def _streamStop(self):
        self._trigger(StreamStop)

    ### ---------- Parser Target ----------

    def start(self, name, attrs):
        """An element has started; push it onto the stack.  If it is
        the root, set up the stream.  If it is a child of the root,
        make sure a stanza handler exists and collect any nested
        elements into a ElementTree."""

        if self._peer:
            if len(self._peer) == 1 and name not in self._stanzas:
                raise XMPPError('Unrecognized stanza', name)
            self._peer.append(etree.SubElement(self._peer[-1], name, attrs))
        elif name == self.STREAM:
            self._peer.append(etree.Element(name, attrs))
            self._streamStart()
        else:
            raise XMPPError('Expected %r, not %r.' % (self.STREAM, name))

    def end(self, name):
        """When the end of an element is signaled, it is popped off
        the stack.  If it is the root, tear down the stream.  If it is
        a child of the root, a stanza handler is notified."""

        if not self._peer:
            raise XMPPError('Unexpected closing %r.' % name)

        elem = self._peer.pop()
        if elem.tag != name:
            raise XMPPError('Expected closing %r, not %r.' % (elem.tag, name))

        if len(self._peer) == 1:
            self._stanza(name, elem)
        elif name == self.STREAM:
            self._streamStop()

    def data(self, data):
        """Character data is appended to the current element."""

        if not self._peer:
            raise XMPPError('Unexpected character data: %r' % data)

        elem = self._peer[-1]

        if len(elem) != 0:
            ## Append to the tail of the last child if it exists.
            child = elem[-1]
            child.tail = (child.tail or '') + data
        else:
            ## Otherwise, append to the text of this element.
            elem.text = (elem.text or '') + data

    def close(self):
        """The parser has closed successfully."""
