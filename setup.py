from __future__ import absolute_import
from setuptools import setup, find_packages

setup(
    name = 'python-xmpp-server',
    version = '0.1.1',
    description = 'An XMPP server.',
    author = 'Medium',
    author_email = 'labs@thisismedium.com',
    license = 'BSD',
    keywords = 'server xmpp jabber',

    packages = list(find_packages(exclude=('examples', ))),
    install_requires = ['pycurl==7.19.0', 'simplejson', 'tornado', 'lxml']
)
