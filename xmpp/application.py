## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""application -- XMPP application constructors"""

from __future__ import absolute_import
import sasl
from . import core, xmppstream, plugin

__all__ = ('Server', 'Client', 'Application', 'ServerAuth', 'ClientAuth')

def Server(settings):
    return Application(core.ServerCore, settings)

def Client(settings):
    return Application(core.ClientCore, settings)

def Application(Core, settings):
    """Declare an XMPP Application.  An application is an XMLHandler
    that dispatches to stanza handlers.
    """

    settings['plugins'] = plugin.CompiledPlugins(settings.pop('plugins', ()))
    return xmppstream.XMPPHandler(Core, settings)

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
