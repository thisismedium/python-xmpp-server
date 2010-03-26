"""_bosh.tac -- run the punjab BOSH server for a REPL

To run this example, use the `bosh-service' script.
"""

from twisted.web import server, resource, static
from twisted.application import service, internet
from twisted.scripts.twistd import run
from punjab.httpb  import Httpb, HttpbService

root = static.File("_bosh") # a static html directory

b = resource.IResource(HttpbService(1))
root.putChild('bosh', b) # url for BOSH

site  = server.Site(root)

application = service.Application("punjab")
internet.TCPServer(5280, site).setServiceParent(application)
