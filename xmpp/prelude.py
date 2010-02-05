## Copyright (c) 2010, Coptix, Inc.  All rights reserved.
## See the LICENSE file for license terms and warranty disclaimer.

"""prelude -- extra builtins"""

from __future__ import absolute_import
import os, __builtin__ as py, contextlib
import abc, functools as fn, logging, collections as coll, itertools as it

__all__ = (
    'abc', 'log', 'setattrs', 'basename', 'dirname',
    'Sequence', 'deque', 'first', 'chain', 'groupby', 'imap', 'izip', 'ichain',
    'ifilter', 'filter', 'append', 'extend',
    'Mapping', 'ddict', 'namedtuple', 'items', 'keys', 'values', 'chain_items',
    'get', 'setitems', 'update', 'setdefault', 'ipop', 'pop',
    'partial', 'wraps', 'thunk', 'contextmanager'
)


### General

dirname = os.path.dirname
basename = os.path.basename

def setattrs(obj, items=None, **kwargs):
    for (key, val) in chain_items(items, kwargs):
        setattr(obj, key, val)
    return obj


### Logging

log = logging.getLogger(basename(dirname(__file__)))
log.addHandler(logging.StreamHandler())


### Sequences

Sequence = coll.Sequence
deque = coll.deque
chain = it.chain
groupby = it.groupby
imap = it.imap

def first(seq, default=None):
    return next(seq, default)

def filter(pred, seq=None):
    return py.filter(None, pred) if seq is None else py.filter(pred, seq)

def ifilter(pred, seq=None):
    return it.ifilter(bool, pred) if seq is None else it.ifilter(pred, seq)

def izip(*args, **kwargs):
    return (it.izip_longest if kwargs else it.izip)(*args, **kwargs)

def ichain(sequences):
    return (x for s in sequences for x in s)

def append(obj, seq):
    for item in seq:
        obj.append(item)
    return obj

def extend(obj, seq):
    obj.extend(seq)
    return obj


### Mappings

Mapping = coll.Mapping

ddict = coll.defaultdict
namedtuple = coll.namedtuple

def keys(seq):
    if isinstance(seq, Mapping):
        return seq.iterkeys()
    return (k for (k, _) in items(seq))

def values(seq):
    if isinstance(seq, Mapping):
        return seq.itervalues()
    return (v for (_, v) in items(seq))

def items(obj):
    if isinstance(obj, Mapping):
        return obj.iteritems()
    return obj

def chain_items(*obj):
    return ichain(items(o) for o in obj if o is not None)

def setitems(obj, items=None, **kwargs):
    for (key, val) in chain_items(items, kwargs):
        obj[key] = val
    return obj

def get(obj, key, default=None):
    if hasattr(obj, 'get'):
        return obj.get(key, default)
    return next((v for (k, v) in obj if k == key), default)

def update(obj, *args, **kwargs):
    obj.update(*args, **kwargs)
    return obj

def setdefault(obj, items=None, **kwargs):
    for (key, val) in chain_items(items, kwargs):
        obj.setdefault(key, val)
    return obj

def ipop(obj, *keys, **kwargs):
    default = kwargs.get('default')
    return ((k, obj.pop(k, default)) for k in keys)

def pop(obj, *keys, **kwargs):
    default = kwargs.get('default')
    if len(keys) == 1:
        return obj.pop(keys[0], default)
    return (obj.pop(k, default) for k in keys)


### Procedures

partial = fn.partial
wraps = fn.wraps
contextmanager = contextlib.contextmanager

class thunk(object):
    """Like partial, but ignores any new arguments."""

    __slots__ = ('func', 'args', 'keywords')

    def __init__(self, func, *args, **keywords):
        self.func = func
        self.args = args
        self.keywords = keywords

    def __repr__(self):
        return '<%s %r args=%r kwargs=%r>' % (
            type(self).__name__,
            self.func,
            self.args,
            self.keywords
        )

    def __call__(self, *args, **kwargs):
        return self.func(*self.args, **self.keywords)
