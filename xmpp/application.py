## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""application -- XMPP application constructors

These are shortcuts for creating XMPP applications.  All that's really
necessary to create an XMPP server is:

    xmppstream.XMPPHandler(core.ServerCore, {
        'jid': 'example.net',
        'plugins': plugin.CompiledPlugins([...]),
        'features': plugin.CompiledFeatures([...])
    })

These shortcuts process settings into the form above.
"""

from __future__ import absolute_import
import sasl, socket
from . import core, xmppstream, plugin, state, features
from .prelude import *

__all__ = ('Server', 'Client', 'Application', 'ServerAuth', 'ClientAuth')


### Applications

def Server(settings):
    return Application(core.ServerCore, server_settings(settings))

def Client(settings):
    return Application(core.ClientCore, client_settings(settings))

def Application(Core, settings):
    """Declare an XMPP Application.  An application is an XMLHandler
    that dispatches to stanza handlers.
    """

    settings['features'] = plugin.CompiledFeatures(settings.pop('features', ()))
    settings['plugins'] = plugin.CompiledPlugins(settings.pop('plugins', ()))

    return xmppstream.XMPPHandler(Core, settings)

def default_settings(settings, defaults):
    """Create missing settings by making default values."""

    for (name, default) in defaults:
        if name not in settings:
            settings[name] = default(settings)
    return settings


### Server

def server_settings(settings):
    return default_settings(settings, (
        ('jid', server_jid),
        ('features', server_features)
    ))

def server_jid(settings):
    return settings.get('host') or socket.gethostname()

def server_features(settings):
    auth = server_auth(settings)
    resources = default_resources(settings)
    return (
        (features.StartTLS, dict(
            ipop(settings, 'certfile', 'keyfile'),
            server_side=True)),
        (features.Mechanisms, dict(ipop(settings, 'mechanisms'), auth=auth)),
        (features.Bind, dict(resources=resources)),
        features.Session
    )

def server_auth(settings):
    auth = pop(settings, 'auth')
    if not auth:
        users = pop(settings, 'users')
        if not (users and isinstance(users, Mapping)):
            raise ValueError(
                'To make a server, add a "users" setting.  It should be '
                'a dictionary of (username, password) items.'
             )
        auth = ServerAuth(
            settings.pop('service', 'xmpp'),
            pop(settings, 'host') or socket.gethostname(),
            users
        )
    return auth

def default_resources(settings):
    return pop(settings, 'resources') or features.Resources()

def ServerAuth(serv_type, host, users):

    def user():
        raise NotImplementedError

    def password():
        raise NotImplementedError

    def get_host():
        return host

    return sasl.SimpleAuth(
        sasl.DigestMD5Password,
        users,
        user,
        password,
        lambda: serv_type,
        get_host,
        realm=get_host
    )


### Client

def client_settings(settings):
    return default_settings(settings, (
        ('jid', client_jid),
        ('features', client_features)
    ))

def client_jid(settings):
    jid = settings.get('host')
    if not jid:
        raise ValueError('Missing required "host" setting.')
    return jid

def client_features(settings):
    auth = client_auth(settings)
    resources = default_resources(settings)
    return (
        features.StartTLS,
        (features.Mechanisms, dict(ipop(settings, 'mechanisms'), auth=auth)),
        (features.Bind, dict(resources=resources)),
        features.Session
    )

def client_auth(settings):
    auth = pop(settings, 'auth')
    if not auth:
        (username, password) = pop(settings, 'username', 'password')
        if username is None or password is None:
            raise ValueError('Missing "username" or "password".')

        host = pop(settings, 'host')
        if not host:
            raise ValueError('Missing required "host" setting.')

        auth = ClientAuth(
            settings.pop('service', 'xmpp'),
            host,
            username,
            password
        )
    return auth

def ClientAuth(serv_type, host, username, password):

    return sasl.SimpleAuth(
        sasl.DigestMD5Password,
        {},
        lambda: username,
        lambda: password,
        lambda: serv_type,
        lambda: host
    )
