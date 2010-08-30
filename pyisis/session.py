# -*- coding: utf-8 -*-

"""
Encapsulate global variables in session object, allowing parallel
execution of the formating language.
"""

__updated__ = "2009-07-30"
__created__ = "2008-08-13"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

import sys
import re
import pyisis.ast
import pyisis.lexer
import pyisis.parser
from os.path import exists, join, split
from pyisis.fields import MasterField, MasterContainerField
# Global pattern of include pre-processing directive
include_pat = re.compile(r"@[\w\d\.\/]+")

# Maps expressions to formatting functions
_cache = {}

class Session(object):
    def __init__(self, config):
        self.lexer = pyisis.lexer.PftLexer()
        self.parser = pyisis.parser.PftParser(lexer=self.lexer,
                                              debug=config.YACC_DEBUG,
                                              outputdir=config.PARSER_AUXFILES_DIR)
        self.compiler = pyisis.ast.PftCompiler()
        self.config = config

# create a default session
session = None
def initialize(config):
    """Create default session object to be used by the single-threaded
    interactive console or the test suite.
    """
    global session
    session = Session(config)

def format(expr, record, session=None, mst=None, debug=False):
    """ Apply the formatting function resulting from the compilation
    of expression over the pair (mst,record).
    Every formatting function is saved in a cache to avoid recompilation
    in the future.
    """
    # clear heading and trailing spaces
    # they are meaningless, but if present could break the grammar
    expr = expr.strip()

    if session is None:
        session = pyisis.session.session

    if mst is None:
        if record.mst is not None:
            # Check if record has mst field set
            mst = record.mst
        else:
            # If no mst given, create a dummy with default configuration
            class DummyMst(object):
                def __init__(self):
                    self.config = session.config
            mst = DummyMst()

    # expand include (@) expressions
    # These should be expanded  before checking the cache,
    # in order to the expanded version of the expression to
    # be the one cached. In this way, if the content of the file
    # changes the cache will behave as expected.
    #------Preprocessing
    while 1:
        # loop needed to handle include inside include
        includes = include_pat.findall(expr)
        if not includes:
            # no include was found
            break
        for include in includes:
            filenamepath = include[1:]
            if exists(filenamepath):
                includefile = filenamepath
            else:
                includefile = join(split(mst.filepath)[0], filenamepath)
            if exists(includefile):
                try:
                    expanded_include = open(includefile).read().strip()
                    #expanded_include = expanded_include.replace('\n','').replace('\r','')
                    expr = include_pat.sub(expanded_include, expr)

                except:
                    raise Exception (_('Include file error'))
            else:
                raise Exception (_('File %s not found' % includefile))
        #DEBUG
        #try:
        #    del _cache[expr]
        #except KeyError:
        #    pass
    
    try:
        # look up function in the cache of pre-compiled expressions
        formatter = _cache[expr]
    except KeyError:
        # generate another formatting function
        if debug:
            print "TOK:\n"
            session.lexer.input(expr)
            for i in session.lexer:
                print "\t",i
        ast = session.parser.parse(expr, debug=mst.config.YACC_DEBUG)
        if debug:
            print "AST:\n", ast

        chain = pyisis.ast.flatten(ast)
        if debug:
            print "CHAIN:\n", chain

        formatter = session.compiler.compile_code(chain)

        # add newly created function to the cache
        if not debug:
            _cache[expr] = formatter

    lw = mst.config.MAX_LINE_WIDTH
    result = formatter(rec=record, mst=mst, debug=debug)
    sys.stdout.flush()
    mst.config.MAX_LINE_WIDTH = lw
    return result.encode(mst.config.OUTPUT_ENCODING)

# create alias for function
pft=format
