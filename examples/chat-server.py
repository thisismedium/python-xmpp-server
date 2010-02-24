import os, copy, xmpp

class ChatServer(xmpp.Plugin):

    @xmpp.iq('{vcard-temp}vCard')
    def vcard(self, iq):
        if iq.get('type') == 'get':
            return self.iq('result', iq, self.E.vCard(
                { 'xmlns': 'vcard-temp' },
                self.E('FN', 'No Name')
            ))

    @xmpp.iq('{jabber:iq:roster}query')
    def roster(self, iq):
        assert iq.get('type') == 'get'
        return self.iq('result', iq, self.E.query(xmlns='jabber:iq:roster'))

    @xmpp.iq('{urn:xmpp:ping}ping')
    def ping(self, iq):
        return self.iq('result', iq)

    @xmpp.stanza('message')
    def message(self, elem):
        for (to, route) in self.routes(elem.get('to')):
            route.write(elem)

    @xmpp.stanza('presence')
    def presence(self, elem):
        pass

if __name__ == '__main__':

    ## Create a server application with 2 users: user1@example.net and
    ## user2@example.net.
    server = xmpp.Server({
        'plugins': [ChatServer],
        'host': 'example.net',
        'users': { 'user1': 'password1', 'user2': 'password2' },
        'certfile': os.path.join(os.path.dirname(__file__), 'certs/self.crt'),
        'keyfile': os.path.join(os.path.dirname(__file__), 'certs/self.key')
    })

    SP = xmpp.TCPServer(server).bind('127.0.0.1', 5222)
    xmpp.start([SP])
