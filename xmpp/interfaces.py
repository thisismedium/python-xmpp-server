## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""interfaces -- abstract interfaces"""

from __future__ import absolute_import
import abc, re

__all__ = (
    'Event', 'CoreInterface', 'PluginManager',
    'StreamError', 'StanzaError', 'IQError'
)


### Events

class Event(object):
    """Subclass this to declare a new Event.  Use the docstring to
    describe the event and how it should be used."""


### Core

class CoreInterface(object):
    """XMPP Core interface.  See xmppstream.py and core.py."""
    __metaclass__ = abc.ABCMeta

    def __init__(self, address, stream):
        """The constructor accepts an ReadStream."""

    @abc.abstractmethod
    def is_stanza(self, name):
        """Is name a stanza this XMPP agent can process?"""
        return False

    @abc.abstractmethod
    def handle_open_stream(self, attr):
        """A <stream:stream> opening tag has been received."""

    @abc.abstractmethod
    def handle_stanza(self, elem):
        """A stanza has been received."""

    @abc.abstractmethod
    def handle_close_stream(self):
        """A </stream:stream> closing tag has been received."""

class PluginManager(object):
    """Plugin collection interface.  See core.py and application.py"""

    __xmlns__ = 'jabber:client'

    nsmap = {
        None: __xmlns__,
        'stream': 'http://etherx.jabber.org/streams'
    }

    @abc.abstractmethod
    def install(self, state):
        """Install "special" plugins into the current state."""

    @abc.abstractmethod
    def activate(self, state):
        """Activate normal plugins."""


### Exceptions

class StreamError(Exception):

    def __init__(self, condition, text, *args, **kwargs):
        super(StreamError, self).__init__(condition, text, *args, **kwargs)
        self.condition = condition
        self.text = text

    def __str__(self):
        return ': '.join((self.condition, self.text))

class StanzaError(Exception):

    def __init__(self, type, condition, *args, **kwargs):
        super(StanzaError, self).__init__(type, condition, *args, **kwargs)
        self.type = type
        self.condition = condition

    def __repr__(self):
        return '<%s type=%r %r>' % (
            type(self).__name__,
            self.type,
            self.condition
        )

class IQError(StanzaError):
    pass
