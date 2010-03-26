## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""chat-server -- a simple Jabber chat server

This example is a partial implementation of RFC 3921, Instance
Messaging and Presence.  Try logging in as user1 and user2.  Use one
client to add the other as a contact.  Try sending a message or
changing status.
"""

import os, copy, xmpp, logging as log
from collections import namedtuple, defaultdict
from xmpp import xml

class ChatServer(xmpp.Plugin):
    """A basic chat server.  This implementation is very incomplete
    and cuts corners it lots of places."""

    def __init__(self, rosters):
        self.probed = False
        self.rosters = rosters

    @xmpp.iq('{urn:xmpp:ping}ping')
    def ping(self, iq):
        """Clients send pings to keep the connection alive."""

        return self.iq('result', iq)

    @xmpp.stanza('message')
    def message(self, elem):
        """Messages are immediately written to the client."""

        self.recv(elem.get('to'), elem)

    @xmpp.stanza('presence')
    def presence(self, elem):
        """Presence information may be sent out from the client or
        received from another account."""

        if self.authJID.match_bare(elem.get('from')):
            return self.send_presence(elem)
        self.recv_presence(elem)

    def send_presence(self, elem):
        direct = elem.get('to')
        if not direct:
            self.rosters.broadcast(self, elem)
            if not self.probed:
                self.probed = True
                self.rosters.probe(self)
        elif not self.rosters.send(self, direct, elem):
            self.send(direct, elem)

    def recv_presence(self, elem):
        if not self.rosters.recv(self, elem):
            self.write(elem)

    @xmpp.iq('{jabber:iq:roster}query')
    def roster(self, iq):
        """A roster is this account's list of contacts; it may be
        fetched or updated."""

        roster = self.rosters.get(self)
        method = getattr(self, '%s_roster' % iq.get('type'))
        return method and method(iq, roster)

    def get_roster(self, iq, roster):
        query = self.E.query({ 'xmlns': 'jabber:iq:roster' })
        for item in roster.items():
            query.append(item)
        return self.iq('result', iq, query)

    def set_roster(self, iq, roster):
        query = self.E.query(xmlns='jabber:iq:roster')
        for item in iq[0]:
            result = roster.set(item)
            if result is not None:
                query.append(result)
        if len(query) > 0:
            self.push(roster, query)
        return self.iq('result', iq)

    def push(self, roster, query):
        """Push roster changes to all clients that have requested this
        roster."""

        for jid in roster.requests():
            for (to, route) in self.routes(jid):
                route.iq('set', self.ignore, query)

    def ignore(self, iq):
        """An IQ no-op."""

    @xmpp.iq('{vcard-temp}vCard')
    def vcard(self, iq):
        """Fake vCard support: the client requests its vCard after
        establishing a session; send an empty one."""

        if iq.get('type') == 'get':
            return self.iq('result', iq, self.E.vCard(
                { 'xmlns': 'vcard-temp' },
                self.E('FN', 'No Name')
            ))

class Rosters(object):
    """In a real implementation, roster information would be
    persisted.  This class tracks a roster for each bare JID connected
    to the server."""

    def __init__(self):
        self._rosters = {}

    def get(self, conn):
        """Get a connection's roster and remember the request."""

        return self._get(conn).request(conn)

    def _get(self, conn):
        bare = conn.authJID.bare
        roster = self._rosters.get(bare)
        if roster is None:
            ## Automatically create an empty roster.
            roster = self._rosters[bare] = Roster(bare)
        return roster

    def broadcast(self, conn, elem):
        """Send presence information to everyone subscribed to this
        account."""

        roster = self._get(conn)
        for jid in roster.presence(conn.authJID, elem).subscribers():
            conn.send(jid, elem)

    def probe(self, conn):
        """Ask everybody this account is subscribed to for a status
        update.  This is used when a client first connects."""

        roster = self._get(conn)
        elem = conn.E.presence({'from': unicode(conn.authJID), 'type': 'probe'})
        for jid in roster.watching():
            conn.send(jid, elem)

    def send(self, conn, to, elem):
        """Send a subscription request or response."""

        method = getattr(self, 'send_%s' % elem.get('type'), None)
        return method and method(conn, xml.jid(to).bare, elem)

    def send_subscribe(self, conn, contact, pres):
        roster = self.get(conn)
        self.confirm(conn, roster, roster.ask(contact))
        pres.set('to', contact)
        pres.set('from', conn.authJID.bare)
        return conn.send(contact, pres)

    def send_subscribed(self, conn, contact, pres):
        roster = self.get(conn)
        self.confirm(conn, roster, roster.subscribe(contact, 'from'))
        pres.set('to', contact)
        pres.set('from', conn.authJID.bare)
        return self._last(roster, contact, conn.send(contact, pres))

    def _last(self, roster, jid, conn):
        """Send the last presence information for this account to a
        newly subscribed JID."""

        for last in roster.last():
            last = copy.deepcopy(last)
            last.set('to', jid)
            conn.send(jid, last)
        return conn

    def recv(self, conn, elem):
        """Handle subscription requests or responses to this account.
        Reply to probes without involving the client."""

        method = getattr(self, 'recv_%s' % elem.get('type'), None)
        return method and method(conn, elem)

    def recv_subscribe(self, conn, pres):
        return conn.write(pres)

    def recv_subscribed(self, conn, pres):
        roster = self.get(conn)
        contact = xmpp.jid(pres.get('from')).bare
        self.confirm(conn, roster, roster.subscribe(contact, 'to'))
        pres.set('from', contact)
        pres.set('to', conn.authJID.bare)
        return conn.write(pres)

    def recv_probe(self, conn, pres):
        return self._last(self._get(conn), pres.get('from'), conn)

    def confirm(self, conn, roster, item):
        conn.push(roster, conn.E.query({ 'xmlns': 'jabber:iq:roster' }, item))

Item = namedtuple('Item', 'attr groups')

class Roster(object):
    """A roster stores contact information for an account, tracks the
    last presence broadcast by each client, and which clients have
    requested the roster."""

    def __init__(self, jid):
        self.jid = jid
        self._items = {}
        self._requests = set()
        self._last = {}

    def request(self, conn):
        """Remember that a client requested roster information.  The
        remembered set is used to push roster updates."""

        if conn.authJID not in self._requests:
            jid = conn.authJID
            self._requests.add(jid)
            conn.one(xmpp.StreamClosed, lambda: self.forget(jid))
        return self

    def requests(self):
        """The set of clients that requested this roster."""

        return self._requests

    def precence(self, jid, presense):
        """Update the last presence sent from a client."""

        self._last[jid] = presense
        return self

    def last(self):
        """Iterate over the last presence sent from each client."""

        return self._last.itervalues()

    def forget(self, jid):
        """A client has disconnected."""

        self._requests.discard(jid)
        self._last.pop(jid, None)
        return self

    def items(self):
        """Iterate over all roster items."""

        return (self._to_xml(i) for i in self._items.itervalues())

    def subscribers(self):
        """Iterate over accounts subscribed to this account."""

        return self._match_subscription('both', 'from')

    def watching(self):
        """Iterate over accounts this account is subscribed to."""

        return self._match_subscription('both', 'to')

    def _match_subscription(self, *subs):
        return (
            j for (j, s) in self._items.iteritems()
            if s.attr.get('subscription') in subs
        )

    def set(self, item):
        """Handle a roster update sent from a client."""

        jid = item.get('jid')
        if item.get('subscription') == 'remove':
            self._items.pop(jid, None)
            return None
        else:
            state = self._items[jid] = self._merge(jid, self._from_xml(item))
            return self._to_xml(state)

    def update(self, jid, **attr):
        """Update roster state."""

        return self._updated(self._get(jid), **attr)

    def ask(self, contact):
        """Update roster state to reflect a new subscription request."""

        return self.subscribe(contact, 'none', ask='subscribe')

    def subscribe(self, jid, new, ask=None):
        """Update roster state to reflect changes in the state of a
        subscription request."""

        state = self._get(jid)
        old = state.attr.get('subscription')
        if old is None:
            pass
        elif new == 'none':
            new = old
        elif ((new == 'to' and old == 'from')
              or (new == 'from' and old == 'to')):
            new = 'both'
        return self._updated(state, ask=ask, subscription=new)

    def _get(self, jid):
        state = self._items.get(jid)
        if state is None:
            state = self._items[jid] = self._create(jid)
        return state

    def _updated(self, state, **attr):
        state.attr.update(attr)
        return self._to_xml(state)

    def _create(self, jid):
        return Item({ 'jid': jid, 'name': '', 'subscription': 'none' }, [])

    def _merge(self, jid, new):
        old = self._items.get(jid)
        if old is not None:
            for key in old.attr:
                if new.attr.get(key) is None:
                    new.attr[key] = old.attr[key]
        return new

    def _from_xml(self, item):
        return Item({
            'jid': item.get('jid'),
            'name': item.get('name'),
            'subscription': item.get('subscription'),
            'ask': item.get('ask')
        }, [g.text for g in item])

    def _to_xml(self, state):
        (attr, groups) = state
        return xml.E.item(
            dict(i for i in attr.iteritems() if i[1] is not None),
            *[xml.E.group(g) for g in groups]
        )

if __name__ == '__main__':

    ## Create a server application with 2 users: user1@example.net and
    ## user2@example.net.
    server = xmpp.Server({
        'plugins': [(ChatServer, { 'rosters': Rosters() })],
        'host': 'localhost',
        'users': { 'user1': 'password1', 'user2': 'password2' }
        ## 'certfile': os.path.join(os.path.dirname(__file__), 'certs/self.crt'),
        ## 'keyfile': os.path.join(os.path.dirname(__file__), 'certs/self.key')
    })

    SP = xmpp.TCPServer(server).bind('127.0.0.1', 5222)
    xmpp.start([SP])
