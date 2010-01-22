====================
 Python XMPP Server
====================

An XMPP Server written in Python.  Examples are available here_.

.. _here: http://github.com/thisismedium/python-xmpp-server/tree/master/examples/

Installation
------------

The XMPP server is using on tornado_ and lxml_.  Before you can
install it, make sure you have these prerequisites installed.

.. _tornado: http://www.tornadoweb.org/
.. _lxml: http://codespeak.net/lxml/

Prerequisites
~~~~~~~~~~~~~

To install the tornado_ and lxml_::

  sudo easy_install setuptools pycurl==7.16.2.1 simplejson lxml
  sudo easy_install -f http://www.tornadoweb.org/ tornado

Since lxml and pycurl have C dependencies, it may be simpler to use a
package management system if it's available for your OS.  Using
MacPorts, for example::

  sudo port install py26-setuptools py26-curl py26-simplejson py26-lxml
  sudo easy_install -f http://www.tornadoweb.org/ tornado

Download and Install
~~~~~~~~~~~~~~~~~~~~

To check out and install python-xmpp-server::

  git clone git://github.com/thisismedium/python-xmpp-server.git
  cd python-xmpp-server
  python setup.py build
  sudo python setup.py install

Test your setup by running an example::

  python examples/ping-pong.py

Hacking
~~~~~~~

If you are going to hack on python-xmpp-server, you can use ``python
setup.py develop`` instead of ``python setup.py install`` to create an
egg-link to the git repository.


