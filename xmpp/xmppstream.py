## Copyright (c) 2009, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""xmppstream -- SAX Stream handlers that generate XMPP events"""

from __future__ import absolute_import
import abc, re, collections
from lxml import etree, builder

__all__ = (
    'Event', 'XMPPError', 'ApplicationState', 'XMPPStream',
    'ConnectionOpen', 'StreamReset', 'ConnectionClose',
    'SentStreamOpen', 'SentStreamClose',
    'ReceivedStreamOpen', 'ReceivedStreamClose'
)


### Application State

class ApplicationState(object):
    """Application state for an XMPP connection is managed here.  This
    state may be reset over the lifetime of an XMPP connection.

    Here is an example of a ping/pong server that does not use the
    higher-level state abstractions available in application.py:

        import functools, xmpp

        class Pong(xmpp.ApplicationState):

            def setup(self):
                self.pings = self.pongs = 0

                self.stanza('{urn:jabber-client}ping', self.onPing)
                self.bind(xmpp.ReceivedStreamOpen, self.receivedOpen)
                self.bind(xmpp.ReceivedStreamClose, self.closeStream)
                self.bind(xmpp.ConnectionClose, self.connectionClosed)

                return self

            def receivedOpen(self):
                self.stream._openStream({ 'from': 'server@example.com' })

            def onPing(self, elem):
                self.pings += 1
                self.write(self.E('pong'))
                self.pongs += 1

            def connectionClosed(self):
                print 'Done: got %d pings and send %d pongs.' % (
                    self.pings,
                    self.pongs
                )

        pong = functools.partial(xmpp.XMPPStream, Pong)
        handler = xmpp.XMLHandler(pong)
        S = xmpp.TCPServer(handler).listen('127.0.0.1', 9000)
    """

    def __init__(self, stream, plugins=None):
        self.stream = stream
        self.events = collections.defaultdict(list)
        self.stanzas = {}

        self.E = stream._E
        self.activated = False
        self.plugins = plugins or NoPlugins()

        self.setup()

    def setup(self):
        self.plugins.install(self)
        return self

    def activate(self):
        if self.activated:
            raise PluginError('Plugins are already activated.')
        self.activated = True
        self.plugins.activateDefault(self)
        return self

    def hasStanza(self, name):
        return name in self.stanzas

    def handleStanza(self, name, elem):
        handler = self.stanzas.get(name)
        if not handler:
            raise XMPPError('Unrecognized stanza %r.' % name)
        return handler(elem)

    ## ---------- Stream ----------

    def write(self, data):
        self.stream._write(data)
        return self

    def openStream(self, attrs):
        self.stream._openStream(attrs)
        return self

    def resetStream(self, open_attrs=None):
        self.stream._resetStream(open_attrs)
        return self

    def closeStream(self):
        self.stream._closeStream()
        return self

    def closeConnection(self):
        self.stream._close()
        return self

    ## ---------- Events ----------

    def stanza(self, name, callback):
        exists = self.stanzas.get(name)
        if exists:
            raise PluginError('The %r stanza is handled by %r.' % (
                name,
                exists
            ))
        self.stanzas[name] = callback
        return self

    def bind(self, kind, callback):
        self.events[kind].append(callback)
        return self

    def one(self, kind, callback):
        self.bind(kind, Once(callback))
        return self

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
                handler(*args, **kwargs)
                if isinstance(handler, Once):
                    del handlers[index]
        return self

class PluginManager(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def install(self, state):
        """Install "special" plugins into the current state."""

    @abc.abstractmethod
    def activateDefault(self, state):
        """Activate normal plugins."""

class NoPlugins(PluginManager):

    def install(self, state):
        pass

    def activateDefault(self, state):
        pass

class Once(collections.namedtuple('once', 'callback')):
    """An event handler that should only be called once."""

    def __call__(self, *args, **kwargs):
        return self.callback(*args, **kwargs)


### Events

class Event(object):
    """Subclass this to declare a new Event.  Use the docstring to
    describe the event and how it should be used."""

class ConnectionOpen(Event):
    """This is triggered once per connection.  Subscribe to this to
    implement connection-level initialization.  Use this for setting
    up connection-level state.  Use StreamReset for initializing
    application-level state."""

class ConnectionClose(Event):
    """This is triggered when a connection is closed; use this to tear
    down state."""

class StreamReset(Event):
    """This is triggered when a stream is reset.  This happens (1)
    immediately after ConnectionOpen, (2) after TLS negotiation, and
    (3) after SASL negotiation.  Application state should almost
    always be initialized on StreamReset."""

class SentStreamOpen(Event):
    """Triggered when a <stream:stream> element is sent."""

class SentStreamClose(Event):
    """Triggered when a </stream:stream> is sent."""

class ReceivedStreamOpen(Event):
    """Triggered when a <stream:stream> element is received."""

class ReceivedStreamClose(Event):
    """Triggered when a </stream:stream> is received."""


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

class XMPPStream(object):
    """An lxml XMLParser Target that processes an XMPP stream.  It's
    best to interact with an XMPPStream through a Plugin.

    Implementation note: most of the methods and attributes declared
    here begin with an underscore not to flag them as private, but to
    avoid collision with lxml XMLParser target method names.
    """

    __xmlns__ = 'urn:jabber-client'

    VERSION = 1.0

    NSMAP = {
        None: __xmlns__,
        'stream': 'http://etherx.jabber.org/streams'
    }

    STREAM = clark_name((NSMAP['stream'], 'stream'))

    def __init__(self, state, stream):
        self._new_state = state
        self._stream = stream

        self._E = builder.ElementMaker(
            namespace=self.__xmlns__,
            nsmap=self.NSMAP
        )

        self._closed = None

    def _setup(self):
        self._state = self._new_state(self)
        self._peer = []   # Stack of elements received from the peer.
        self._root = None # Stream element sent to peer.

    def _write(self, data):
        if self._closed:
            raise XMPPError('Cannot write to closed stream.')

        if isinstance(data, etree._Element):
            data = tostring_hack(self._root, data)
        self._stream.write(data)

    def _trigger(self, *args, **kwargs):
        self._state.trigger(*args, **kwargs)

    def _stanza(self, *args, **kwargs):
        self._state.handleStanza(*args, **kwargs)

    def _openStream(self, attrs):
        if self._root:
            raise XMPPError('Stream already open.')

        attrs['version'] = unicode(self.VERSION)
        self._root = self._E(self.STREAM, attrs)

        ## FIXME: hack; replace with an lxml api call to
        ## generate an opening tag if there is one.
        ##   <stream:stream ... /> ==> <stream:stream ...>
        self._write(etree.tostring(self._root).replace('/>', '>'))
        return self._trigger(SentStreamOpen)

    def _resetStream(self, attrs=None):
        """Reset the stream.  This will destroy the current state and
        may be called any time."""

        self._stream.reset()
        self._setup()
        self._trigger(StreamReset)
        if attrs is not None:
            self._openStream(attrs)

    def _closeStream(self):
        if self._root is not None:
            self._root = None
            ## FIXME: hack; replace this with an lxml api call to
            ## generate a closing tag if there is one.
            self._write('</stream:stream>')
            self._trigger(SentStreamClose)
        return self

    def _close(self):
        """Close the connection.  This can only be called once."""

        if not self._closed:
            ## This will callback to _connectionClosed()
            self._stream.close()
        return self

    ### ---------- Private XMLStream Interface ----------

    def _connectionOpen(self):
        """This is a private method called by XMLStream.  Don't call
        this directly."""

        if self._closed:
            raise XMPPError('This stream has been closed.')
        elif self._closed is not None:
            raise XMPPError('This stream is already open.')

        self._closed = False
        self._setup()
        self._trigger(ConnectionOpen)
        self._trigger(StreamReset)
        return self

    def _connectionClosed(self):
        """This is a private method called by XMLStream.  Don't call
        this directly; use _close()."""

        ## FIXME? What happens if the peer has already closed the
        ## connection?
        self._closeStream()

        self._closed = True
        self._trigger(ConnectionClose)

        return self

    ### ---------- Parser Target ----------

    def start(self, name, attrs, nsmap):
        """An element has started; push it onto the stack."""

        if self._peer:
            if len(self._peer) == 1 and not self._state.hasStanza(name):
                raise XMPPError('Unrecognized stanza', name)
            parent = self._peer[-1]
            self._peer.append(etree.SubElement(parent, name, attrs, nsmap))
        elif name == self.STREAM:
            self._peer.append(etree.Element(name, attrs, nsmap))
            self._trigger(ReceivedStreamOpen)
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
            self._trigger(ReceivedStreamClose)

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

def tostring_hack(root, stanza, encoding='utf-8'):

    ## This hack is here because lxml serializes whole nodes at a
    ## time.  When it does this, the root node has lots of xmlns
    ## declarations (all normal so far).  Whole-node serialization is
    ## great because it ensures, but XMPP stanzas are in the context
    ## of a <stream:stream> element that's never closed.

    ## Since individual stanzas are technically SubElements of the
    ## stream, they should not need the namespace declarations that
    ## have been declared on the stream element.  But, stanzas are
    ## serialized as self-contained trees since the <stream:stream>
    ## element is perpetually open.  The lxml tostring() method adds
    ## the stream-level namespace declarations to each stanza.  While
    ## this causes no harm, it is alot of repeated noise and wasted
    ## space.

    ## Workaround by temporarily adding stanza to root before
    ## serializing it.  There's no need to hack the parser since it's
    ## always in the context of a stream.

    root.append(stanza)
    stream = etree.tostring(root, encoding=encoding)
    root.clear()

    ## Yikes!
    return stream[stream.index('<', 1):stream.rindex('<')]

