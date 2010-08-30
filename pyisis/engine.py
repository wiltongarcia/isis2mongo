# -*- coding: utf-8 -*-

"""
Routines used to control and manage ISIS-Cell activity
"""

__updated__ = "2007-12-10"
__created__ = "2007-12-10"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

import sys
from traceback import print_exc
try:
    from cStringIo import StringIO
except:
    from StringIO import StringIO
import codecs
from os import getcwd
from os.path import join
from glob import glob

from logging import getLogger
from traceback import format_exc, extract_tb

import pyisis
import pyisis.session

#ISISAC.TAB
isisac_tab = [
u'\u0041',u'\u0042',u'\u0043',u'\u0044',u'\u0045',u'\u0046',u'\u0047',u'\u0048',
u'\u0049',u'\u004A',u'\u004B',u'\u004C',u'\u004D',u'\u004E',u'\u004F',u'\u0050',
u'\u0051',u'\u0052',u'\u0053',u'\u0054',u'\u0055',u'\u0056',u'\u0057',u'\u0058',
u'\u0059',u'\u005A',u'\u0061',u'\u0062',u'\u0063',u'\u0064',u'\u0065',u'\u0066',
u'\u0067',u'\u0068',u'\u0069',u'\u006A',u'\u006B',u'\u006C',u'\u006D',u'\u006E',
u'\u006F',u'\u0070',u'\u0071',u'\u0072',u'\u0073',u'\u0074',u'\u0075',u'\u0076',
u'\u0077',u'\u0078',u'\u0079',u'\u007A',u'\u0080',u'\u0081',u'\u0082',u'\u0083',
u'\u0084',u'\u0085',u'\u0086',u'\u0087',u'\u0088',u'\u0089',u'\u008A',u'\u008B',
u'\u008C',u'\u008D',u'\u008E',u'\u008F',u'\u0090',u'\u0091',u'\u0092',u'\u0093',
u'\u0094',u'\u0095',u'\u0096',u'\u0097',u'\u0098',u'\u0099',u'\u009A',u'\u00A0',
u'\u00A1',u'\u00A2',u'\u00A3',u'\u00A4',u'\u00A5',u'\u0020']


def loop(sequence, pause=True):
    """Iterate over the elements of a given sequence,
    waiting for user acknolegment after printing each
    element"""
    for e in sequence:
        try:
            print e
            if pause:
                raw_input()
        except KeyboardInterrupt:
            break

class Engine(object):
    """Holds global data-structures used in
    console-only or in gateway mode.
    """
    # Class attribute that holds a dict with collection instances
    collection = {}

    # Global configuration settings
    config = None

    @staticmethod
    def setup(config):
        """Browse config.COLLECTIONS building a dictionary with
        all the collection objects. The key of this dictionary is
        the collection name and the value is a Collection instance.

        Also sets default output encoding.
        """
        # Initialize formatting language
        Engine.config = config
        pyisis.session.initialize(config)
        Engine.collection.clear()
        logger = getLogger('pyisis')

        for typename, name, path in config.COLLECTIONS:
            try:
                CollectionType = getattr(pyisis.files, typename)
                Engine.collection[name]= CollectionType(name, path)
            except IOError, ex:
                logger.warning(_("Failed to create collection %s: %s")%(name, ex))

            except Exception, ex:
                logger.error(_("Unexpected error while processing %s: %s")%(name, ex))
                logger.error(format_exc())

        # Try to identify local collections in current working directory
        local_msts = glob("*.mst")
        if local_msts:
            Engine.collection['current']= pyisis.files.IsisCollection('current', [getcwd()])



#from IPython.ipapi import TryNext, get as ipget
#from IPython.genutils import dir2, Term

def logexcept(self, etype, evalue, etrace):
    """Custom traceback handler that dumps exception traces to log file.
    """
    logger = getLogger('pyisis')
    logger.warning(format_exc())

#def result_display(self, arg):
#    """ Overrides IPython's display hook.
#    Called for displaying the result to the user.
#    """
#    if type(arg) in (type,unicode):
#        # unicode() cannot be called directly on classes (unbounded)
#        print >>Term.cout,  arg
#    else:
#        print >>Term.cout,  unicode(arg).encode(Engine.config.OUTPUT_ENCODING)
#
#    return None

def isis_completers(self, event):
    """ This should return a list of strings with possible completions.
    """
    symbol_parts = event.symbol.split('.')
    base = '.'.join(symbol_parts[:-1])
    oinfo = self._ofind(base)
    if not oinfo['found']:
        raise TryNext

    obj = oinfo['obj']
    types = (pyisis.files.IsisCollection, pyisis.files.MasterFile,
             pyisis.records.MasterRecord,
             pyisis.fields.MasterField,
             pyisis.fields.MasterContainerField,
             pyisis.records.XrfRecord)
    if not any((isinstance(obj, i) for i in  types)):
        raise TryNext

    attrs = dir2(obj)
    attrs = [a for a in attrs if not a.startswith('__')]

    # The base of the completion, so we can form the final results list
    bdot = base+'.'
    tcomp = [bdot+a for a in attrs]
    return tcomp


def interactive(collection):
    from IPython.ipapi import TryNext, get as ipget
    from IPython.genutils import dir2, Term

    banner = "\n"+\
_("Welcome to ISIS-NBP Cell %s Interactive Console\n") % pyisis.__version__ +\
"Python %s\n" % sys.version +\
_("Use the console to test and inspect the collections.\n\n")+\
_("Type 'collection' to see a dictionary with all available collections.\n")+\
_("Type '<Ctrl-D>' or 'exit()' followed by '<enter>' to quit.\n")

    print banner.encode(Engine.config.OUTPUT_ENCODING)
    try:
        import readline
        import rlcompleter
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

    # Add these to the global ipshell namespace
    locals().update(collection)
    locals().update({'format':pyisis.session.format,
                     'loop':loop,
                     'MasterFile': pyisis.files.MasterFile,
                     'MasterRecord': pyisis.records.MasterRecord,
                     'MasterField': pyisis.fields.MasterField
                     })

    try:
        __IPYTHON__
    except NameError:
        argv = ['']
        banner = _("The available collections are: %s\n") % (", ".join(collection.keys()))

        exit_msg = _('Closing ISIS-NBP Interactive Python Console\n')

    # First import the embeddable shell class
    from IPython.Shell import IPShellEmbed

    # redefine hooks
    ipshell = IPShellEmbed(argv, banner=banner, exit_msg=exit_msg)
    #ipshell.IP.set_hook('complete_command', isis_completers, re_key = '.*')

    # result _display became obsolete, because encoding conversion
    # is done by __str__ methods and works in the standard Python prompt
    # as well!
    #ipshell.IP.set_hook('result_display', result_display)

    #if Engine.config.SILENT_EXCEPTIONS:
    #    ipshell.IP.set_custom_exc((SyntaxError, NameError, AttributeError, ValueError),
    #                               logexcept)

    # Now create the IPython shell instance.
    ipshell()


def interactive_old(mf):
    """
    THIS FUNCTIONS HAS BEEN REPLACED BY A MODERN IPYTHON CONSOLE.
    You need to install IPython from http://ipython.scipy.org

    This is the interactive prompt of operation
    to test and inspect the master file data and operations.
    The master file is accessible by the global mf variable.
    Use mf[1] to access the first record.

    Type 'q', 'quit' or 'exit' followed by '<enter>' to quit.
    """
    print interactive.__doc__
    try:
        import readline
        import rlcompleter
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

    namespace = {'mf':mf, 'format': pyisis.session.format,
                 #'proc': pyisis.session.proc
                 }
    while 1:
        try:
            cmd = raw_input("pymx> ")
            if cmd.strip() in ('exit','quit','q'):
                raise SystemExit()
            # create file-like string to capture output
            codeOut, codeErr = StringIO(), StringIO()
            try:
                sys.stdout, sys.stderr = codeOut, codeErr
                exec cmd in namespace
            finally:
                sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
                s = codeErr.getvalue()
                if s:
                    print "error:\n%s\n" % s
                s = codeOut.getvalue()
                if s:
                    print "\n%s" % s
                codeOut.close()
                codeErr.close()
        except StandardError,ex:
            print_exc()

