import tornado.httpserver
import tornado.ioloop
import tornado.web


class BOSHRequestHandler(tornado.web.RequestHandler):
    counter = 0;
    def __init__(self, application, request, transforms='NONE', xmpp_host="host", xmpp_port="port"):
        self._xmpp_host = xmpp_host
        self._xmpp_port = xmpp_port
        super(BOSHRequestHandler,self).__init__(application, request, transforms)
    
    def get(self):
        self.write('Sorry, GET Not Allowed')

    def post(self):
        self.set_header("Content-Type", "text/plain")
        #parse the post
        
        #Lookup the XMPP session wtih this client
        self.write("You wrote " + self.get_argument("message"))


class BOSHServer(object):
    
    def __init__(self, url,port, xmpp_host, xmpp_port):         
        #setup and start the http server
        application = tornado.web.Application([
            (url, BOSHRequestHandler,{"xmpp_host": xmpp_host, "xmpp_port" : xmpp_port }),
        ])
        self.http_server = tornado.httpserver.HTTPServer(application)
        self.http_server.listen(port)
        tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    BOSHServer(r"/",8080,'localhost',9000)