## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""interfaces -- abstract interfaces"""

from __future__ import absolute_import
import abc

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
    def reset(self, core):
        """Install "special" plugins into the current state."""

    @abc.abstractmethod
    def activate_default(self, state):
        """Activate normal plugins."""

