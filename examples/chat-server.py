import os, copy, xmpp

class ChatServer(xmpp.Plugin):

    @xmpp.stanza('{jabber:client}iq/{vcard-temp}vCard')
    def vcard(self, iq):
        if iq.get('type') == 'get':
            return self.iq('result', iq, self.E.vCard(
                { 'xmlns': 'vcard-temp' },
                self.E('FN', 'No Name')
            ))

    @xmpp.stanza('{jabber:client}iq/{jabber:iq:roster}query')
    def roster(self, iq):
        assert iq.get('type') == 'get'
        return self.iq('result', iq, self.E.query(xmlns='jabber:iq:roster'))

    @xmpp.stanza('{jabber:client}iq/{urn:xmpp:ping}ping')
    def ping(self, iq):
        return self.iq('result', iq)

    @xmpp.stanza('message')
    def message(self, elem):
        for (to, route) in self.routes(elem.get('to')):
            route.write(elem)


    @xmpp.stanza('presence')
    def presense(self, elem):
        pass

if __name__ == '__main__':
    server = xmpp.Server({
        'plugins': [ChatServer],
        'auth': xmpp.ServerAuth('xmpp', 'example.net', { 'weaver': 'secret', 'rob': 'secret' }),
        'resources': xmpp.state.Resources()
        # 'certfile': os.path.join(os.path.dirname(__file__), 'certs/self.crt'),
        # 'keyfile': os.path.join(os.path.dirname(__file__), 'certs/self.key')
    })

    SP = xmpp.TCPServer(server).bind('127.0.0.1', 5222)
    xmpp.start([SP])
