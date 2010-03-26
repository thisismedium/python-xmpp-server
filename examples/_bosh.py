## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""_bosh.py -- demonstrate how to use XMPP instead of a web service.

To run this example, use the `bosh-service' script.
"""

import os, sys, json, xmpp, base64, sqlite3, contextlib as ctx
from md import collections as coll
from xmpp import xml

class Directory(xmpp.Plugin):
    """A simple directory of people."""

    def __init__(self, db):
        self.db = db

    @xmpp.stanza('presence')
    def presence(self, elem):
        """No-op on presence so strophe doesn't fail."""

    @xmpp.iq('{urn:D}people')
    def people(self, iq):
        """List people or update a person."""

        method = getattr(self, '%s_people' % iq.get('type'))
        return method and method(iq)

    def get_people(self, iq):
        with ctx.closing(self.db.cursor()) as cursor:
            cursor.execute(
                'SELECT rowid, name, email, address '
                'FROM people ORDER BY rowid'
            )
            result = [dict(zip(r.keys(), r)) for r in cursor]
            print '\n\n****GET****', result, '\n\n'
            return self._dumps(iq, result)

    def set_people(self, iq):
        result = []
        with ctx.closing(self.db.cursor()) as cursor:
            for person in self._loads(iq[0].text):
                if person.get('rowid'):
                    result.append(self.update_person(cursor, person))
                else:
                    result.append(self.insert_person(cursor, person))
            self.db.commit()
            return self._dumps(iq, result)

    def insert_person(self, cursor, person):
        cursor.execute(
            'INSERT INTO people VALUES (:name, :email, :address);',
            person)
        person['rowid'] = cursor.lastrowid
        return person

    def update_person(self, cursor, person):
        cursor.execute(
            ('UPDATE people SET name=:name, email=:email, address=:address '
             'WHERE rowid = :rowid'),
            person)
        return person

    def _dumps(self, iq, value):
        """Dump a value to JSON and return it in a _response()."""

        return self._result(iq, json.dumps(value))

    def _loads(self, data):
        return json.loads(base64.b64decode(data))

    def _result(self, iq, data, **attr):
        """Create a result for _dispatch."""

        attr.setdefault('xmlns', 'urn:D')
        return self.iq('result', iq, self.E(
            iq[0].tag,
            attr,
            base64.b64encode(data)
        ))

def main():
    server = xmpp.Server({
        'plugins': [(Directory, { 'db': setup_db() })],
        'users': { 'user': 'secret' },
        'host': 'localhost'
    })
    print 'Waiting for clients...'
    xmpp.start([xmpp.TCPServer(server).bind('127.0.0.1', 5222)])

def setup_db():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    with ctx.closing(db.cursor()) as cursor:
        cursor.execute('''CREATE TABLE people (
            name TEXT,
            email TEXT,
            address TEXT
        )''')
        db.commit()
    return db

if __name__ == '__main__':
    main()
