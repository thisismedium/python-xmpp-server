## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""xml -- XML utilities"""

from __future__ import absolute_import
import re
from lxml import etree, builder
from . import interfaces as i

__all__ = (
    'Element', 'SubElement', 'tostring', 'XMLSyntaxError', 'ElementMaker', 'E',
    'Parser', 'is_element', 'tag', 'text', 'child', 'xpath', 'clark',
    'jid', 'bare', 'is_full_jid', 'is_bare_jid',
    'open_tag', 'close_tag', 'stanza_tostring'
)

## For convenience

Element = etree.Element
SubElement = etree.SubElement
tostring = etree.tostring
XMLSyntaxError = etree.XMLSyntaxError
ElementMaker = builder.ElementMaker
E = builder.E
xpath = etree.ETXPath


### Parser

class Parser(object):
    """Wrap the lxml XMLParser to require a target and prime the
    incremental parser to avoid hanging on an opening tag.

        class Target(object):
           def start(self, name, attr, nsmap):
               print 'start!', name, attr.items(), nsmap.items()

           def data(self, data):
               print 'data!', repr(data)

           def end(self, name):
               print 'end!', name

        parser = Parser(Target())
        parser.feed('<foo><bar>...</bar></foo>')
        parser.close()

    """

    def __init__(self, target, **kwargs):
        self.target = target
        self.parser = etree.XMLParser(target=target, **kwargs)
        self.rb = ''
        self.feed = self.feed_tokens
        self.stop = False
        self.more = False

    def start(self):
        if self.stop:
            self.close()
            self.target.reset()
            self.stop = False
        self.parser.feed('')
        return self

    def reset(self):
        self.stop = True
        return self

    def stop_tokenizing(self):
        if self.feed == self.feed_tokens:
            self.feed = self.parser.feed
        return self

    def feed_tokens(self, data):
        ## This method buffers data and carefully feeds tokens from
        ## the buffer into the parser.  The parser target may reset
        ## the parser while a particular token is being handled, so if
        ## all the data is fed into the parser immediately, there may
        ## be dangling tags that raise an error the next time the
        ## parser is fed a chunk.

        ## This method is swapped out for self.parser.feed() once the
        ## core has negotiated its features.

        self.rb += data
        self.more = bool(self.rb)
        while self.more:
            for token in self.tokenize():
                self.parser.feed(token)
            if self.more:
                self.start()
        return self

    def tokenize(self):
        ## Tokenize a buffer of XML data.  Tokens are opening tags, data
        ## chunks, and closing tags.
        while self.rb and not self.stop:
            if self.rb.startswith('<'):
                idx = self.rb.find('>')
                if idx == -1:
                    break
                yield self.rb[0:idx + 1]
                self.rb = self.rb[idx + 1:]
            else:
                idx = self.rb.find('<')
                if idx == -1:
                    break
                yield self.rb[0:idx]
                self.rb = self.rb[idx:]

        ## Update the "more" flag to indicate whether more tokens are
        ## available.  The loop may have terminated early if the
        ## parser was reset from inside an event handler.
        self.more = bool(self.rb and self.stop)

    def close(self):
        try:
            self.parser.close()
        except XMLSyntaxError:
            pass
        return self


### Utilities

def is_element(obj):
    """Is obj an etree Element?

    >>> is_element(etree.Element('foo'))
    True
    >>> is_element({})
    False
    """
    return isinstance(obj, etree._Element)

def tag(elem, default=None):
    return elem.tag if is_element(elem) else default

def text(elem, default=None):
    return elem.text if is_element(elem) else default

def child(elem, nth=0, default=None):
    if isinstance(nth, int):
        try:
            return elem[nth]
        except IndexError:
            return default
    elif isinstance(nth, basestring):
        if '/' in nth:
            found = xpath(nth)(elem)
            return found[0] if found else default
        else:
            return next(elem.iter(nth), default)
    else:
        raise ValueError('child: expected nth to be a string or number.')

CLARK_NAME = re.compile(r'^{[^}]+}.+$')
PREFIX_NAME = re.compile(r'^([^:]+):(.+)')

def clark(obj, ns=None, nsmap=None):
    """Convert an object to Clark Notation.

    >>> clark((u'foo', u'bar'))
    u'{foo}bar'
    >>> clark((None, u'bar'), u'foo')
    u'{foo}bar'
    >>> clark(u'bar', u'foo')
    u'{foo}bar'
    >>> clark(u'{foo}bar')
    u'{foo}bar'
    >>> clark(u'stream:features', nsmap={ 'stream': 'urn:STREAM' })
    u'{urn:STREAM}features'
    """

    ## If the default namespace isn't given, try to find one in the
    ## nsmap.
    if ns is None and nsmap:
        ns = nsmap.get(None)

    if isinstance(obj, basestring):
        ## If obj is already in the right format, return it.
        probe = CLARK_NAME.match(obj)
        if probe:
            return obj

        ## Check for prefix notation and resolve in the nsmap.
        probe = PREFIX_NAME.match(obj)
        if probe:
            (prefix, lname) = probe.groups()
            uri = nsmap and nsmap.get(prefix)
            if not uri:
                raise ValueError('Unrecognized prefix %r.' % obj)
            obj = (uri, lname)
        ## This is just an unqualified name, use the default namespace.
        else:
            obj = (ns, obj)

    return u'{%s}%s' % (obj[0] or ns, obj[1]) if (obj[0] or ns) else obj[1]

def clark_path(expr, ns=None, nsmap=None):
    """Expand an XPath expression into an ETXPath expression.

    >>> clark_path('foo/bar', 'baz')
    u'{baz}foo/{baz}bar'
    >>> clark_path('/n:frob/{a}mumble/quux/text()', 'urn:D', { 'n': 'urn:N' })
    u'/{urn:N}frob/{a}mumble/{urn:D}quux/text()'
    """

    if ns is None and nsmap:
        ns = nsmap.get(None)

    ## FIXME: This is very brute-force.  Replace with a proper
    ## tokenizer.  It does not handle attribute names or expressions.
    return '/'.join(
        ## The isalpha() check prevents expansion of:
        ##    {foo}bar
        ##    [...]
        ##    ''
        ##    text()
        clark(t, ns, nsmap) if (t and t[0].isalpha() and t[-1].isalpha()) else t
        for t in expr.split('/')
    )

class jid(object):

    __slots__ = ('name', 'host', 'resource', '_unicode')

    PARSE = re.compile('([^@/]+)(?:@([^/]+))?(?:/(.+))?$')

    def __new__(cls, obj, host=None, resource=None):
        if obj is None:
            return None
        elif isinstance(obj, jid) and host is None and resource is None:
            return obj
        return object.__new__(cls)

    def __init__(self, obj, host=None, resource=None):
        if isinstance(obj, jid):
            self.name = obj.name
            self.host = host or obj.host
            self.resource = resource or obj.resource
        else:
            (self.name, self.host, self.resource) = \
                self._parse(obj, host, resource)
        self._unicode = self._make_unicode()

    def __repr__(self):
        return '%s(%r, %r, %r)' % (
            type(self).__name__, self.name, self.host, self.resource
        )

    def __unicode__(self):
        return self._unicode

    def __hash__(self):
        return hash(self._unicode)

    def __eq__(self, other):
        if isinstance(other, jid):
            other = other._unicode
        if isinstance(other, basestring):
            return self._unicode == other
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, (jid, basestring)):
            return not self == other
        return NotImplemented

    @property
    def bare(self):
        if not self.host:
            raise ValueError('No host: %r.' % self)
        return u'%s@%s' % (self.name, self.host)

    @property
    def full(self):
        if not self.resource:
            raise ValueError('No resource: %r.' % self)
        return u'%s@%s/%s' % (self.name, self.host, self.resource)

    def match_bare(self, other):
        return self.bare == type(self)(other).bare

    @classmethod
    def _parse(cls, name, host=None, resource=None):
        if not isinstance(name, basestring):
            raise TypeError('Expected string, not %r.' % type(name))
        probe = cls.PARSE.match(name)
        if not probe:
            raise i.StreamError('internal-server-error', 'Bad JID: %r' % name)

        return (
            probe.group(1),
            probe.group(2) if host is None else host,
            probe.group(3) if resource is None else resource
        )

    def _make_unicode(self):
        if self.host and self.resource:
            return self.full
        elif self.host:
            return self.bare
        else:
            ## FIXME: Is this allowed?
            return u'%s/%s' % (self.name, resource)

def bare(obj):
    return jid(obj).bare

def is_full_jid(obj):
    if isinstance(obj, basestring):
        return '/' in obj
    elif isinstance(obj, jid):
        return bool(obj.host and obj.resource)
    raise TypeError('Expected string or jid, not %r.' % type(obj))

def is_bare_jid(obj):
    if isinstance(obj, basestring):
        return '@' in obj and '/' not in obj
    elif isinstance(obj, jid):
        return jid.host and not jid.resource
    raise TypeError('Expected string or jid, not %r.' % type(obj))


### Hacks

def open_tag(elem, encoding='utf-8'):
    """Render just an opening tag for elem."""

    ## lxml serializes whole nodes at a time.  This will just return
    ## the opening tag.  For this hack to work, elem needs to be
    ## empty.

    ## <stream:stream ... /> ==> <stream:stream ...>
    return etree.tostring(elem, encoding=encoding).replace('/>', '>')

def close_tag(elem, encoding='utf-8'):
    """Render just a closing tag for elem."""

    ## Complement of open_tag_hack().
    elem.text = ' '
    data = etree.tostring(elem, encoding=encoding)
    elem.clear()

    ## <stream:stream ...> </stream:stream> ==> </stream:stream>
    return data[data.rindex('<'):]

def stanza_tostring(root, stanza, encoding='utf-8'):
    """Serialize a stanza in the context of a root element, but don't
    include the root element in the result."""

    ## This hack is here because lxml serializes whole nodes at a
    ## time.  When it does this, the root node has lots of xmlns
    ## declarations (all normal so far).  Whole-node serialization is
    ## great because it ensures the serialized XML is well-formed, but
    ## XMPP stanzas are in the context of a <stream:stream> element
    ## that's never closed.

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

    ## <stream ...><foo/></stream> ==> <foo/>
    return stream[stream.index('<', 1):stream.rindex('<')]
