## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""xml -- XML utilities"""

from __future__ import absolute_import
import re
from lxml import etree, builder

__all__ = (
    'Element', 'SubElement', 'tostring', 'XMLSyntaxError', 'ElementMaker',
    'Parser', 'is_element', 'tag', 'text', 'child', 'clark',
    'open_tag', 'close_tag', 'stanza_tostring'
)

## For convenience

Element = etree.Element
SubElement = etree.SubElement
tostring = etree.tostring
XMLSyntaxError = etree.XMLSyntaxError
ElementMaker = builder.ElementMaker


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
        self.settings = kwargs
        self.target = target
        self.reset()

    def reset(self):
        self.target.reset()
        ## Trying to re-use the same parser by clearing it with
        ## parser.stop() results in segfaults.
        self.parser = etree.XMLParser(target=self.target, **self.settings)
        return self.feed('') # Prime the XMLParser

    def feed(self, data):
        self.parser.feed(data)
        return self

    def close(self):
        self._destroy()
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

def child(elem, nth, default=None):
    if isinstance(nth, int):
        try:
            return elem[nth]
        except IndexError:
            return default
    elif isinstance(nth, basestring):
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
