# -*- coding: utf-8 -*-

"""
Handling of formatting language. Abstract Syntax Tree.
"""

__updated__ = "2009-07-30"
__created__ = "2007-05-20"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

import re
import sys
import operator
from string import Template
from itertools import count
from tempfile import gettempdir
from time import strftime, localtime, mktime
from os.path import exists, join, split
from copy import copy

from pyisis.fields import MasterField, MasterContainerField
import engine
import pyisis.config


# Mode flags and vars
filing_pat = re.compile(r"\<(.+?)\=.+?\>", re.U)
remove_pat = re.compile(r"\<(.+?)\>", re.U)
#Proc filters
proc_filter_delete = re.compile(r'[dD]{1}(\d+\/\d+)|[Dd]{1}(\d+)|([Dd]{1}\*)')
proc_filter_add    = re.compile(u'[Aa](\d+).([\`\$\+\'\;\!\*\#\@\%\(\)\-\?\&\|\<\>\=\"\/\[\]a-zA-Z0-9\:\n\w\s\.\,\xa1-\xff]*).')
proc_filter_hadd   = re.compile(r'[hH]\s*(\d+)\s+(\d+)\s+(.*)')
proc_filter_gizmo  = re.compile(r'[gG]([a-zA-Z0-9\.\/\-/_]+)((\,+\d+)+)')
proc_filter_gsplit = re.compile(r'[gG]split(\/clean)*\=(\d*)\=(.){1}')

NEXTLINESPACES  = 0
FIRSTLINESPACES = 1
EMPTYSPACES     = 2
TWOSPACES       = " " * 2
SINGLESPACE     = " "

#cache to ref function
_ref_record_cache = {}

class BreakException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class ContinueException(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)


def get_last_line(workarea, remove=True):
    """ Given the workarea, return the last line, consisting in
    text starting from the last linefeed to the end of the workarea.
    """
    if (not workarea):
        return ''
    
    try:
        if workarea[-1][-1] == LeafNode.linesep:
            return ''
    except:
        pass 

    result = ''.join(workarea)
    position = result.rfind(LeafNode.linesep) + 1
    last_line = result[position:]
    return last_line


def strip_func_params(func_name, param_nodes, expected_param_count):
    """It validates the expected param count with the input nodes,
    raising an exception if the count mismatches.

    This function returns the stripped seqeunce of param nodes.
    """
    try:
        param_count = len(param_nodes)
    except TypeError:
        # if param_nodes is not iterable -> single node
        param_count = 1
        param_nodes = [param_nodes]

    if param_count not in expected_param_count:
        raise Exception(_("Wrong number of parameters given to %s()."%func_name +\
                          "Expected %r, but got %d "% (expected_param_count,
                                                       param_count)
                          ))
    return param_nodes


def format_mode(result):
    linesep = ''
    if result[-1] == LeafNode.linesep:
        linesep = LeafNode.linesep
        result = result[:-1]        
    if len(result) >= 3 and result.strip()[-1] != '.':
        result = '%s.  %s' %(result, linesep)
    else:
        result = "%s  " % result    
    return result


class Sequence(list):
    """Non-leaf node to aggregate leaf nodes.
    """
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        if len(self)==0:
            return ''
        else:
            result = []
            for node in self:
                try:
                    if isinstance(node,RepeatableLiteral):
                        continue
                    
                    elif isinstance(node,Mfn):
                        temp_result = node.format(record, mst, result, chain, pos, occ, debug)
                    
                    elif isinstance(node, Field):
                        #Field puts data direct to workarea
                        temp_result = node.format(record, mst, workarea+result, chain, pos, occ, debug)                        
                        if temp_result:
                            result += temp_result[len(workarea+result):]
                        continue                    
                    
                    elif isinstance(node, ConditionalLiteral):
                        
                        temp_result = node.eval(record, mst, workarea+result, chain, pos, occ, debug)                     
                        #Fix break line in workarea to field from external database
                        if LeafNode.fix_conditional_literal:
                            if result:
                                temp_workarea = result
                            else:
                                temp_workarea = workarea
                            last_field = temp_workarea.pop()
                            lastline = get_last_line(workarea+result)
                            new_pieces = break_line(lastline+last_field+temp_result,mst.config.MAX_LINE_WIDTH)
                            szlastline = len(lastline)
                            for piece in new_pieces:
                                temp_workarea.append(piece[szlastline:])
                                temp_workarea.append(LeafNode.linesep)
                                szlastline = 0
                            temp_workarea.pop()# Clear last newline
                            LeafNode.fix_conditional_literal = False
                            continue
                
                    else:
                        temp_result = node.eval(record, mst, workarea+result, chain, pos, occ, debug)                     
                        #clear right spaces brefore inconditional literal
                        if isinstance(node, InconditionalLiteral) and node.reset_last_spaces:
                            try:
                                data = result[-1]
                                for idx in range(len(data)-1,-1,-1):
                                    if data[idx] != SINGLESPACE:
                                        result[-1] = data[:idx]
                                        break
                            except:
                                pass
                            node.reset_last_spaces = False          
                        
                    if temp_result and type(temp_result) != int:
                        if chain.case == "U":
                            temp_result = temp_result.upper()
                        
                        result.append(temp_result)

                except BreakException:
                    raise BreakException(''.join(result))
                except ContinueException:
                    raise ContinueException(''.join(result))
                    
            result = ''.join(result)
            try:
                dont_apply_format = chain.dont_apply_format
            except:
                dont_apply_format = False 
            
            if chain.mode == 'D' and result != LeafNode.linesep and not dont_apply_format:
                result = format_mode(result)

            return result


    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        # Sequence nodes are eliminated before the node chain is assembled
        return self.eval(record, mst, workarea, chain, pos, occ, debug)

    def max_repeat(self, record):
        if self:
            return max([i.max_repeat(record) for i in self])
        else:
            return 1

    def merge(self, node):
        """Merge this node with another node
        and return a Sequence Node. If node param
        is already a sequence its children is merged into
        this instance, if it is a leaf node then it is adopted.
        """
        if type(node)==Sequence:
            self.extend(node)
        elif isinstance(node, LeafNode):
            self.append(node)
        return self


    def find_node(self, nodetype, from_pos):
        """Loop through the sequence of nodes and return the first
        occurence of node with the given _nodetype_ whose index is
        equal or bigger than _from_pos_.

        This function returns the pair (node_pos, node_obj).
        """
        for pos, node in enumerate(self[from_pos:]):
            if nodetype==type(node):
                return pos+from_pos, node # found
            
        return -1, None # not found

    def __repr__(self):
        inner = LeafNode.linesep.join(repr(i) for i in self)
        return "%s:%s"%(self.__class__.__name__, inner)


class Node(object):
    def __repr__(self):
        return u"%s"%self.__class__.__name__


class LeafNode(Node):

    linesep            = '\n'
    last_field_value   = ''
    proc_chain         = False
    ref_chain          = False
    fix_conditional_literal = False
    
    
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        try:
            value = self.value
        except AttributeError:
            value = ''
        return "%s:%s"%(self.__class__.__name__, value)

    def merge(self, node):
        """Merge this node with another node
        and return a Sequence Node. If node param
        is already a sequence then that node is returned instead
        after the merger. Otherwise, if node param is also a LeafNode
        then a SeqeunceNode is created and returned.
        """
        if type(node)==Sequence:
            node.insert(0, self)
            return node
        elif isinstance(node, LeafNode):
            seq  = Sequence([self, node])
            return seq

    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Default behavior: a node evals itself and the resulting
        string is added to the end of the workarea. Prior to append
        the text produced by the node, ensure it does not exceed
        the MAX_LINE_WIDTH.
        """
        lastline = get_last_line(workarea)
        try:
            value = unicode(self.eval(record, mst, workarea, chain, pos, occ, debug))        
        except (BreakException,ContinueException):
            return ''
        
        if isinstance(self, ConditionalLiteral) and LeafNode.ref_chain:
            workarea.append(value)
            return
        
        current = lastline + value
        max_width = mst.config.MAX_LINE_WIDTH-1
        
        newline = False
        if current.find(LeafNode.linesep) >= 0:
            if current[-1] == LeafNode.linesep:
                current = current[:-1]
                newline = True
                
            pieces = current.split(LeafNode.linesep)

            for idx,piece in enumerate(pieces):

                szlastline = len(lastline)
                if len(piece) <= max_width+1:
                    if idx:
                        szlastline = 0
                    workarea.append(piece[szlastline:])
                    if idx < len(pieces)-1:
                        workarea.append(LeafNode.linesep)
                else:
                    new_pieces = break_line(piece, max_width)
                    for nidx,word in enumerate(new_pieces):
                        workarea.append(word[szlastline:])
                        szlastline = 0
                        if nidx < len(new_pieces)-1:
                            workarea.append(LeafNode.linesep)
                        
            if newline:
                workarea.append(LeafNode.linesep)        
        else:
            if len(current) > max_width:
                new_pieces = break_line(current, max_width)
                szlastline = len(lastline)
                for idx,word in enumerate(new_pieces):
                    workarea.append(word[szlastline:])
                    szlastline = 0
                    if idx < len(new_pieces)-1:
                        workarea.append(LeafNode.linesep)
            else:
                workarea.append(value)

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        return self.value

    def max_repeat(self, record):
       return self.value.max_repeat(record)


class Mid(LeafNode):
    """Extracts the inner part of a string."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas = strip_func_params('mid', self.value, [3])
        expr = non_commas[0]
        start = non_commas[1]
        length = non_commas[2]

        expr = unicode(expr.eval(record, mst, workarea, chain, pos, occ, debug))
        start = int(start.eval(record, mst, workarea, chain, pos, occ, debug))
        length = int(length.eval(record, mst, workarea, chain, pos, occ, debug))
        # Indexing in PFT begins with 1, in Python begins with 0.
        if start<=0:
            start = 1
        return expr[start-1:start-1+length]


class Left(LeafNode):
    """Extracts the n left part of a string."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('left', self.value, [2])
        self.expr = non_commas[0]
        self.length = non_commas[1]

        expr = unicode(self.expr.eval(record, mst, workarea, chain, pos, occ, debug))
        length = int(self.length.eval(record, mst, workarea, chain, pos, occ, debug))
        if length < 0:
            length = 0
        return expr[:length]


class Right(LeafNode):
    """Extracts the n right part of a string."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('right', self.value, [2])
        self.expr = non_commas[0]
        self.length = non_commas[1]
        expr = unicode(self.expr.eval(record, mst, workarea, chain, pos, occ, debug))
        length = int(self.length.eval(record, mst, workarea, chain, pos, occ, debug))
        size = len(expr)
        if length < 0:
            length = 0
        if length > size:
            length = size
        return expr[size-length:size]


class Replace(LeafNode):
    """Returns string expr1 with substring expr2 replaced by expr3."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('replace', self.value, [3])
        self.expr1 = non_commas[0]
        self.expr2 = non_commas[1]
        self.expr3 = non_commas[2]
        expr1 = unicode(self.expr1.eval(record, mst, workarea, chain, pos, occ, debug))
        #Exception do not apply mdu to replace
        local_case = chain.case
        chain.case = 'l'
        expr2 = unicode(self.expr2.eval(record, mst, workarea, chain, pos, occ, debug))
        expr3 = unicode(self.expr3.eval(record, mst, workarea, chain, pos, occ, debug))
        chain.case = local_case

        if not expr2:
            expr3 = ''

        return expr1.replace(expr2,expr3)


class Date(LeafNode):
    """Returns system date."""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        expr = self.value
        if expr == 'DATETIME':
            dt = strftime('%d/%m/%y %H:%M:%S')
        elif expr == 'DATEONLY':
            dt = strftime('%d/%m/%y')
        else:
            dt = strftime('%Y%m%d %H%M%S %w %j')
        return dt

    def max_repeat(self, record):
       return 1


class Datex(LeafNode):
    """Returns system date."""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):

        non_commas =  strip_func_params('datex', self.value, [1])
        self.expr1 = non_commas[0]
        seconds = int(self.expr1.eval(record, mst, workarea, chain, pos, occ, debug))
        dt = strftime('%Y%m%d %H%M%S %w %j',localtime(seconds))
        return dt

    def max_repeat(self, record):
       return 1


class Cat(LeafNode):
    """Returns file content."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('cat', self.value, [1])
        expr = non_commas[0]
        fname = expr.eval(record, mst, workarea, chain, pos, occ, debug)
        filename = join(split(mst.filepath)[0], fname)
        try:
            result = open(filename).read()
        except:
            result = ''

        return result


class Type(LeafNode):
    """Returns content type."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('type', self.value, [1])
        self.expr1 = non_commas[0]
        value = unicode(self.expr1.eval(record, mst, workarea, chain, pos, occ, debug))
        try:
            number = int(value)
            return 'N'
        except:
            pass

        for char in value:
            if char not in engine.isisac_tab:
                return 'X'
        return 'A'


class Search(LeafNode):
    """Returns the mfn of the first posting."""
    
    def __init__(self, record_key, filename=None):
        LeafNode.__init__(self, record_key)
        self.record_key = record_key
        self.filename = filename
        
        
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        chain.dont_apply_format = True
        expr_key = unicode(self.record_key.eval(record, mst, workarea, chain, pos, occ, debug)).encode(mst.config.OUTPUT_ENCODING)
        chain.dont_apply_format = False
        
        fname = mst.name
        if self.filename:
            if not isinstance(self.filename, str):
                chain_case = chain.case
                chain.case = 'l'            
                try:
                    fname = unicode(self.filename.eval(record, mst, workarea, chain, pos, occ, debug)).strip()
                except:
                    raise Exception (_("Data base does not exist"))
                chain.case = chain_case
            else:
                fname = self.filename              
            
        filename = search_path(mst, fname, 'idx')
        
        if not filename:
            raise Exception (_("Data base does not exist"))
        
        try:
            result = mst.get_mfn_post(expr_key, mst, filename=filename)
        except:
            result = 0
        return result


class Npost(LeafNode):
    """Returns the total postings for a key in an inverted file."""

    def __init__(self, record_key, filename=None):
        LeafNode.__init__(self, record_key)
        self.record_key = record_key
        self.filename = filename
        
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        
        chain.dont_apply_format = True
        expr_key = unicode(self.record_key.eval(record, mst, workarea, chain, pos, occ, debug)).upper()
        if self.filename:
            self.filename = unicode(self.filename.eval(record, mst, workarea, chain, pos, occ, debug))
        chain.dont_apply_format = False
        try:
            result = mst.search_index(expr_key,filename=self.filename).__length_hint__()
        except:
            result = 0

        return result



class Newline(LeafNode):
    """Sets and/or resets default CR/LF pair with character(s)."""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('newline', self.value, [1])
        expr = non_commas[0]
        value = unicode(expr.eval(record, mst, workarea, chain, pos, occ, debug))
        LeafNode.linesep = value
        return ''



class Nocc(LeafNode):
    """Returns the number of occurrences of a data field/subfield"""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('nocc', self.value, [1])
        field = self.value.value
        try:
            result = len(record[field['tag']])
        except:
            result = 0

        if 'subfield' in field.keys():
            try:
                getattr(record[field['tag']],field['subfield'])
                result = 1
            except (KeyError, AttributeError):
                result = 0

        return result


class Iocc(LeafNode):
    """Returns order number"""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        return int(occ)

    def max_repeat(self, record):
       return 1


class LineWidth(LeafNode):
    """Sets the output line width to n characters"""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        non_commas =  strip_func_params('lw', self.value, [1])
        self.expr1 = non_commas[0]

        try:
            mst.config.MAX_LINE_WIDTH = int(self.expr1.eval(record, mst, workarea, chain, pos, occ, debug))
        except:
            raise Exception (_("Invalid parameter"))
        
        return ''


class GetMSTName(LeafNode):
    """Returns the current master filename"""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        if chain.case == 'U':
            return mst.name.upper()
        else:
            return mst.name

    def max_repeat(self, record):
       return 1


class Variable(LeafNode):
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        try:
            result = chain.variables[self.value.upper()]
            if self.value[0].upper() == 'E':
                result = int(result)
            else:
                #Variable is string
                if chain.case.upper() == 'U':
                    result = result.upper()
            return result
        except KeyError:
            # FIXME: variable referenced before assigment
            return ''


class Attr(LeafNode):
    def __init__(self, varname,value):
        self.varname = varname.upper()
        self.value = value

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        value = self.value.eval(record, mst, workarea, chain, pos, debug)
        chain.variables[self.varname] = value
        return value

    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        # force update of chain.variables dictionary
        self.eval(record, mst, workarea, chain, pos, debug)
        return ""


class RepeatableGroup(LeafNode):
    """Encapsulates a sequence of nodes where repeatable fields
    are handled separetely instead as a single concatenated string.
    """
    def __init__(self, value):
        LeafNode.__init__(self, value)
        self.occ = 0 # repeatable occurence counter

    def __repr__(self):
        return "%s(%r)"%(self.__class__.__name__, self.value)

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        results = []
        occs = 0
        lineseppos = 0

        #gets continue command in chain
        try:
            idx_continue, nodetype = self.value.find_node(Continue,0)
        except:
            idx_continue, nodetype = (-1, None)
        
        #find number of repetitions        
        try:
            for pos, node in enumerate(self.value):
                if isinstance(node, RepeatableLiteral):
                    node.eval(record, mst, workarea, chain, pos, occ, debug)
                    
                occs = max(occs, node.max_repeat(record))
                #Get spacer position 
                try:
                    if node.value in ('/','#'):
                        lineseppos = pos
                except:
                    pass
            sequence = self.value
        except TypeError:
            occs = self.value.max_repeat(record)
            sequence = [self.value]
            
        #occ+2 permits print len(index)+1 at the end (like mx) 
        if idx_continue > 0:
            limit = occs+2
        else:
            limit = occs+1
        for occ in range(1, limit):
      
            try:
                # prepare new chain == self.value
                self.value.mode = chain.mode
                self.value.case = chain.case
                self.value.occ = occ
                # Loop through the new chain
                # collecting output for each occurence
                for position, node in enumerate(sequence):
      
                    if isinstance(node, RepeatableLiteral):
                        continue
                    #Some nodes dont have value attr. ex. Branch
                    try:
                        if node.value == '/' and results[-1] == LeafNode.linesep:
                            continue
                    except:
                        pass
                    
                    if isinstance(node,Field):                        
                        sweepRepeatableLiteral(record, mst, workarea+results, self.value, occ, debug)
                        temp_result = node.format(record, mst, workarea+results, self.value, pos, occ, debug)                        
                        if temp_result:
                            results += temp_result[len(workarea+results):]
                        continue
    
                    else:
                        evaluated = node.eval(record, mst, workarea + results, self.value,
                                              position, occ=occ, debug=debug)

                    if evaluated:
                        results.append(''.join(evaluated))

            except ContinueException, lastvalue:
                if lastvalue.value:
                    results.append(str(lastvalue.value))
                if lineseppos > position:
                    # don't put "." to last empty index/InconditinalLiteral
                    if chain.mode == 'D' and occ <= occs:
                        if results[-1].strip()[-1] != '.':
                            results.append('.  ')
                    results.append(LeafNode.linesep)
                continue
            
            except BreakException, lastvalue:
                if lastvalue.value:
                    results.append(str(lastvalue.value))
                if lineseppos > position:
                    results.append(LeafNode.linesep)
                break
            
        return ''.join(results)


    def max_repeat(self, record):
       raise Exception (_('Invalid nested repeatable groups'))


class Ref(LeafNode):
    def __init__(self, record_key, pft, dbase=None):
        LeafNode.__init__(self, record_key)
        self.pft = pft
        self.dbase = dbase

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        try:
            new_record = None
            record_mfn =  self.value.eval(record, mst, workarea, chain, pos, debug)
            if self.dbase is not None:
                if not isinstance(self.dbase, str):
                    dbase = self.dbase.eval(record, mst, workarea, chain, pos, occ, debug).strip()
                else:
                    dbase = self.dbase
                # cross-database reference, fetch foreign record
                if '.' in dbase:
                    # given collection.database
                    collection_name, db_name = dbase.split('.')
                else:
                    # given just database
                    db_name = dbase
                    collection_name = mst.collection_name

                #try cache first    
                try:
                    fcache = _ref_record_cache[dbase]
                except KeyError:
                    fcache = _ref_record_cache[dbase] = {}
                try:
                    new_record = fcache[record_mfn]
                except KeyError:                    
                    try:
                        #Current database
                        target_mst = engine.Engine.collection[collection_name][db_name]
                        new_record = target_mst[record_mfn]
                        _ref_record_cache[dbase][record_mfn] = new_record
                    except:
                        #Open mst file
                        fname = search_path(mst, dbase, 'mst')
                        if not fname:
                            raise Exception (_("Data base does not exist"))
                    
                        config = pyisis.config.config
                        fconfname = fname.replace('.mst','.ini')
                        if exists(fconfname):
                            config.load(fconfname)
                        target_mst = pyisis.files.MasterFile(fname,config=config)
                        new_record = target_mst[record_mfn]
                        _ref_record_cache[dbase][record_mfn] = new_record
            else:
                # use same database present in the given record
                new_record = mst[record_mfn]
        except BreakException:
            return ''

        if isinstance(self.pft, Break):
            raise BreakException(value='')
        temp_wa = copy(workarea)
        LeafNode.ref_chain = True
        temp_result = format_chain(new_record, mst, flatten(self.pft) , debug, temp_wa)
        LeafNode.ref_chain = False
        result = temp_result[len(''.join(workarea)):] 
        return result


class Select(LeafNode):
    def __init__(self, expr, optlist, elsecase=None):
        self.expr       = expr
        self.elsecase   = elsecase
        self.caseoptlist= optlist

    def __repr__(self):
        return "Select expression:[%r] options:[%r] elsecase:[%r]"%(self.expr, str(self.caseoptlist),self.elsecase)

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        result = ''; formatlist = {}
        for case_opt,case_fmt in self.caseoptlist:
            optionval = case_opt.eval(record, mst, workarea, chain, pos, occ, debug)
            if type(optionval) is not str:
                optionval = unicode(optionval.value)
            formatlist[optionval] = case_fmt

        select_value = unicode(self.expr.eval(record, mst, workarea, chain, pos, occ, debug))

        try:
            result = formatlist[select_value].eval(record, mst, workarea, chain, pos, occ, debug)
        except KeyError:
            if self.elsecase:
                result = self.elsecase.eval(record, mst, workarea, chain, pos, occ, debug)
        return result

    def max_repeat(self, record):
       return self.expr.max_repeat(record)

    
def procgizmo(filename, record, reclist):  
    """Applies a gizmo to the record, to a list of specific fields (tags).
    """  
    try:
        tags = [int(rec) for rec in reclist.split(',') if rec]
        gizmo = {}
        config = pyisis.config.config
        try:
            config.load('%s.ini' % filename)
        except:
            pass
        gsplit_mst = pyisis.files.MasterFile('%s.mst' % filename, config=config)

        for grecord in gsplit_mst:
            gizmo[grecord[1].data] = grecord[2].data
        
        for tag in tags:
            data = record[tag].data
            for key, streplace in gizmo.items():
                data = data.replace(key,streplace)
            record[tag].data = data
    
    except Exception, e:
        print str(e)
    return record


class Proc(LeafNode):
    """Append, Delete or replace data fields in the current record"""

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        
        def add_field(record, field, value):
            mf = MasterField(field,value)
            if record.has_key(field):
                if type(record[field]) is MasterContainerField:
                    record[field].append(mf)
                else:
                    oldmf = record[field]
                    record[field] = MasterContainerField(field,[oldmf,mf])
            else:
                record[field] = mf    
            return record[field]    
            
        result = ''
        LeafNode.proc_chain = True
        for node in self.value:
            try:
                result += node.eval(record, mst, workarea, chain, pos, occ, debug)
            except:
                pass
        LeafNode.proc_chain = False

        #Applies gizmo
        gizmo_cmds = proc_filter_gizmo.findall(result)
        for fname, tags, tag in gizmo_cmds:
            record = procgizmo(fname, record, tags)

        #Applies gsplit char
        gsplit_cmds = proc_filter_gsplit.findall(result)
        for clean_cmd, tag, char in gsplit_cmds:
            data = record[int(tag)].data.split(char)
            result = ''
            for word in data:
                if clean_cmd:
                    result += word.strip()
                else:
                    result += word
            record[int(tag)].data = result
        
        #Applies field delete command
        deletecmds = proc_filter_delete.findall(result)
        for fieldocc, field, allfields in deletecmds:
            try:
                if allfields:
                    record.clear()
                    break

                elif field:
                    del record[int(field)]

                elif fieldocc:
                    field, occ = fieldocc.split('/')
                    del record[int(field)][int(occ)-1]

            except KeyError:
                pass
        
        #Applies field add command
        add_tags = proc_filter_add.findall(result)
        for field,value in add_tags:
            field = int(field)
            record[field] = add_field(record, field, value)

        #Applies field add command
        h_add_tags = proc_filter_hadd.findall(result)
        for field, size, data in h_add_tags:
            field = int(field)
            fmt = '%%-%ds' % int(size)
            value = fmt % data            
            record[field] = add_field(record, field, value)

        #record.save(mst)
        return ''


class Number(LeafNode):
    def max_repeat(self, record):
       return 1

class Minus(Number):
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        return -self.value.eval(record, mst, workarea, chain, pos, occ, debug)

class NumFuncVal(Number):

    @staticmethod
    def get_values(strvalue, getall=False):
        """Extract list (first or all numeric) values from
        the given strvalue. Default behaviour is to extract
        only the first value.
        """
        results = []
        # if given a number convert it to string
        # if it is already a string, it remains a string

        strvalue = unicode(strvalue)
        for pat in NUMERIC_PATTERNS:
            matches = pat.findall(strvalue)
            # matches = pat.findall("rodrigo 1.5 senra 123.21")
            # matches == [('1.5', ''), ('123.21', '')]
            if matches:
                if getall:
                    results.extend([eval(i[0]) for i in matches])
                else:
                    results.append(eval(matches[0][0]))
        if not results:
            # list should contain at least one value
            results.append(0)
        return results

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Returns the numerical value of the expression parameter <P>.
        If <P> produces only alphanumeric values, then VAL return 0.
        If there is at least one numeric value in <P>, then return
        the first value found from left to right.
        """
        try:
            evaluated = self.value.eval(record, mst, workarea, chain, pos, occ, debug)
        except:
            raise Exception (_("Invalid parameter"))
        
        return NumFuncVal.get_values(evaluated)[0]

class Size(Number):
    """Returns size of format"""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        sz = 0
        if not isinstance(self.value,(Sequence,list)):
            self.value = [self.value]
        for node in self.value:
            if isinstance(node, list):
                node = node[0]
            result = unicode(node.eval(record, mst, workarea, chain, pos, occ, debug))
            sz += len(result)
        return sz

class Seconds(Number):
    """Returns seconds since January 1st 1970."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):

        non_commas = strip_func_params('seconds', self.value, [1])
        expr = non_commas[0]
        expr = unicode(expr.eval(record, mst, workarea, chain, pos, occ, debug))

        year  = int(expr[0:4])
        month = int(expr[4:6])
        day   = int(expr[6:8])

        try:
            hour = int(expr[9:11])
        except:
            hour = 0
        try:
            minute = int(expr[11:13])
        except:
            minute = 0
        try:
            secs = int(expr[13:15])
        except:
            secs = 0
        return mktime((year, month, day, hour, minute, secs, 0, 0, 0 ))


class FFunc(Number):
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Converts numerical value (or expression) into string.
        """
        non_commas =  strip_func_params('f', self.value, [1,2,3])
        param_count = len(non_commas)
        value = non_commas[0]
        try:
            self.width = non_commas[1]
        except IndexError:
            self.width = 16
        try:
            self.decimals = non_commas[2]
        except IndexError:
           self.decimals = None

        width = self.width.eval(record, mst, workarea, chain, pos, occ, debug)
        try:
            decimals = self.decimals.eval(record, mst, workarea, chain, pos, occ, debug)
        except AttributeError:
            decimals = None
        if decimals is None:
            template = "%s%d%s" % ("%", width, "E")
        elif decimals==0:
            template = "%s%dd" % ("%", width)
        else:
            template = "%s%d.%df" % ("%", width, decimals)
        return template % value.eval(record, mst, workarea, chain, pos, occ, debug)



class NumFuncSeq(Number):
    def __init__(self, value, func):
        Number.__init__(self, value)
        self.func = func

    def get_sequence(self, node, record, mst, workarea, chain, pos, occ, debug=False):
        """Recursivley iterate through the Expression Tree given
        by node, computing a sequence (list) of the respective numeric
        values present in such tree. Returns an empty list or a non-empty
        list of numeric values.
        """
        values = []
        if isinstance(node, Number):
            values.append(node.eval(record, mst, workarea, chain, pos, occ, debug))
        elif type(node) in (BoolFunc, Spacer, XSpacer, CSpacer):
            pass
        elif type(node)==Sequence:
            for subnode in node:
                values.extend(self.get_sequence(subnode, record, mst, workarea, chain, pos, debug))
        else:
            # Apply equivalen VAL() to string expression
            strvalue = node.eval(record, mst, workarea, chain, pos, occ, debug)
            values.extend(NumFuncVal.get_values(strvalue, getall=True))
        return values

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Applies the aggregator function (self.func) to all
        values generated by the expression tree given as parameter.
        """
        values = self.get_sequence(self.value, record, mst, workarea, chain, pos, debug)
        # clean-up the sequence removing strings
        values = [i for i in values if not isinstance(i,str)]
        if not values:
            return ''

        if self.func=='RSUM':
            return sum(values)
        elif self.func=='RMAX':
            return max(values)
        elif self.func=='RMIN':
            return min(values)
        elif self.func=='RAVR':
            return sum(values)/len(values)
        else:
            raise Exception(_("Aggregation function %s not implemented yet")%self.func)


class Instr(Number):
    
    def __init__(self, format1, format2):
        self.format1 = format1
        self.format2 = format2
        #Used by Field/RepeatableLiteral
        self.value = [format1,format2]
                
    """Returns the numerical value of first occurrence of the expr2 in the expr1."""
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        chain_case = chain.case
        chain.case = 'l'
        
        chain.summary = self.format1
        expr1 = unicode(self.format1.eval(record, mst, workarea, chain, pos, occ, debug))    
        expr2 = unicode(self.format2.eval(record, mst, workarea, chain, pos, occ, debug))
        
        chain.case = chain_case
        if not expr1 or not expr2:
            return 0
        #Returns 0 to not found and starts from index 1
        result = expr1.find(expr2) + 1
        return result


class Not(Number):
    "Logic inversion unary operation"
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        return not self.value.eval(record, mst, workarea, chain, pos, occ, debug)

class BoolFunc(LeafNode):
    "Boolean Functions: A() or P()"
    def __init__(self, func, field):
        self.func = func.lower()
        self.field = field

    def __repr__(self):
        return "%s(%r)"%(self.func, self.field)

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        # Paranoic checking !
        if type(self.field)!=Field:
            raise Exception(_('Invalid parameter for boolean function.'))
        if self.func not in ('a','p'):
            raise Exception(_('Invalid boolean function named %s') % self.func)

        field_value = self.field.eval(record, mst, workarea, chain, pos, occ, debug)
        if self.func=='p':
            return bool(field_value)
        elif self.func=='a':
            return not bool(field_value)

    def max_repeat(self, record):
       return self.field.max_repeat(record)

class BinOp(Number):
    """Numeric or Relational binary operation"""
    safe_operations = {'+': operator.add,
                       '-': operator.sub,
                       '*': operator.mul,
                       '/': operator.truediv,
                       '%': operator.mod,
                       '=': operator.eq,
                       '<>': operator.ne,
                       '<': operator.lt,
                       '>': operator.gt,
                       '<=': operator.le,
                       '>=': operator.ge,
                       ':': operator.sequenceIncludes,
                       'and': operator.and_,
                       'or': operator.or_,
                       'xor': operator.xor,
     }

    def __init__(self, operation, left, right):
        self.operation = operation
        self.left = left
        self.right = right

    def __repr__(self):
        return "BinOp %s (%r, %r)"%(self.operation, self.left, self.right)

    def set_InconditionalLitaralformat(self,state):
        """Disable format value to IoncditionalLiteral
        """
        for both in ('left','right'):
            try:
                getattr(self,both).apply_format = state
            except:
                pass

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        
        self.set_InconditionalLitaralformat(False)
        left = self.left.eval(record, mst, workarea, chain, pos, occ, debug)
        right = self.right.eval(record, mst, workarea, chain, pos, occ, debug)
        self.set_InconditionalLitaralformat(True)

        if chain.case == 'U':
            try:
                left = left.upper()
            except:
                pass
            try:
                right = right.upper()
            except:
                pass
        try:
            # eval is not safe to use!
            # return eval("left %s right"%self.operation, {}, locals())
            operation = self.operation.lower()
            return BinOp.safe_operations[operation](left, right)
        except KeyError:
            raise Exception(_("Unsupported operation %s")%(self.operation))


    def max_repeat(self, record):
       return max([self.left.max_repeat(record), self.right.max_repeat(record)])


class Branch(LeafNode):
    def __init__(self, condition, dotrue, dofalse):
        self.condition = condition
        self.dotrue = flatten(dotrue)
        self.dofalse = flatten(dofalse)

    def __repr__(self):
        return "Branch Condition:[%r] True:[%r] False:[%r])"%(self.condition, self.dotrue, self.dofalse)

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        chain.branch = True
        if self.condition.eval(record, mst, workarea, chain, pos, occ, debug):
            chain.summary = self.dotrue
            sweepRepeatableLiteral(record, mst, workarea, chain.summary, occ=0, debug=debug)
            return self.dotrue.format(record, mst, workarea, chain, pos, occ, debug)
        else:
            if self.dofalse is not None:
                chain.summary = self.dofalse
                sweepRepeatableLiteral(record, mst, workarea, chain.summary, occ=0, debug=debug)
                return self.dofalse.format(record, mst, workarea, chain, pos, occ, debug)
            else:
                return ''

    def max_repeat(self, record):
       return max([self.condition.max_repeat(record),self.dotrue.max_repeat(record),self.dofalse.max_repeat(record)])



class WhileLoop(LeafNode):
    def __init__(self, condition, fmt):
        self.condition = condition
        self.dowhile = flatten(fmt)

    def __repr__(self):
        return "Loop Condition:[%r] True:[%r]"%(self.condition, self.dowhile)

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        result = ''
        while self.condition.eval(record, mst, workarea, chain, pos, occ, debug):
            try:
                sweepRepeatableLiteral(record, mst, workarea, self.dowhile, occ, debug)        
                result += self.dowhile.eval(record, mst, workarea, chain, pos, occ, debug)
            except BreakException:
                break
            except ContinueException:
                continue
        return result

    def max_repeat(self, record):
       return self.condition.max_repeat(record)


class Spacer(LeafNode):

    def unconditional_newline(self, record, mst, workarea, chain, pos, debug=False, result=False):
        workarea.append(LeafNode.linesep)

    def conditional_newline(self, record, mst, workarea, chain, pos, debug=False, result=False):
        last_line = "".join(workarea)
        if not last_line.endswith(LeafNode.linesep):
            workarea.append(LeafNode.linesep)

    def delete_previous_newlines(self, record, mst, workarea, chain, pos, debug=False):
        temp_workarea = []
        flag = 0
        for line in workarea:
            if line == LeafNode.linesep:
                flag += 1
            else:
                flag = 0
            if flag <= 1:
                temp_workarea.append(line)
        for line in range(0,len(workarea)): workarea.pop()
        for line in temp_workarea:
            workarea.append(line)


    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """A Spacer node must inspect the workarea prior to rendering itself.
        It will have a different behavior depending on its value:
          # - unconditional new line
          / - conditional (prev non-blank) new line
          % - delete previous blank lines
          Xn - insert n spaces
          Cn - tabulate to column
        """
        handler = {'#':self.unconditional_newline,
                   '/':self.conditional_newline,
                   '%':self.delete_previous_newlines}

        #Apply only if field exists
        try:
            previous_node = chain[pos-1]
        except:
            previous_node = None      
        if previous_node and isinstance(previous_node,Field):
            if not previous_node.field_exists:
                return ''
            
        handler[self.value](record, mst, workarea, chain, pos, debug)


    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Eval only needs to be implemented when the format defined in
        the LeafNode base class is not overriden. Since the Spacer class
        overrides format(), the eval() auxiliary function is not necessary.
        """
        if self.value != "#" and workarea and workarea[-1][-1] == LeafNode.linesep:
            return ''
        elif self.value in ('#','/'):
            return LeafNode.linesep
        else:
            return ''

    def max_repeat(self, record):
       return 1


class XSpacer(LeafNode):

    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        last_line = get_last_line(workarea)
        if len(last_line) + self.value <= mst.config.MAX_LINE_WIDTH:
            workarea.append(SINGLESPACE * self.value)
        else:
            # Xn when spills into the next line, starts from left margin
            workarea.append(LeafNode.linesep)       # skip to new line
            
            
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Eval only needs to be implemented when the format defined in
        the LeafNode base class is not overriden. Since the Spacer class
        overrides format(), the eval() auxiliary function is not necessary.
        """
        return SINGLESPACE * self.value

    def max_repeat(self, record):
       return 1


class CSpacer(LeafNode):
    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """A CSpacer node must inspect the workarea prior to rendering itself.
          Corresponds to -> Cn - tabulate n spaces or move into the next line
          and tabulate there. If n>MAX_LINE_WIDTH then ignore.
        """
        n = self.value
        if n>mst.config.MAX_LINE_WIDTH:
            # tabulation is bigger than max line width - just ignore it
            return

        last_line = get_last_line(workarea)
        if len(last_line) >= n:
            workarea.append(LeafNode.linesep)
            workarea.append(SINGLESPACE * (n-1))
        else:
            difference = n-len(last_line)
            workarea.append(SINGLESPACE * (difference-1))


    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Eval only needs to be implemented when the format defined in
        the LeafNode base class is not overriden. Since the Spacer class
        overrides format(), the eval() auxiliary function is not necessary.
        """
        self.format(record, mst, workarea, chain, pos, occ, debug)

    def max_repeat(self, record):
       return 1


class Field(LeafNode):
    
    def __init__(self, value):
        self.value = value
        #controls repeatable literal formatting (before)
        #field tag exists
        self.masterfield = False 
        self.field_exists = True
        self.l_repeatableLiteral = None
        self.r_repeatableLiteral = None
        self.conditionalsuffix = ''

    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Check if this is a VField(v) or Dummy Field(n,d) using the type attribute.
        Dummy fields should not be rendered in the workarea.
        """
        if self.value['type']=='v':
            field_text = self.eval(record, mst, workarea, chain, pos, occ, debug)
            # Begin mode changes
            subfdelimiter = mst.config.SUBFIELD_DELIMITER
            if chain.case=='U':
                field_text = field_text.upper()
            if chain.mode in ('H','D'):
                try:
                    word = filing_pat.findall(field_text)[0]
                except IndexError:
                    pass # no need to remove filing patterns
                else:
                    field_text = remove_pat.sub(word, field_text)
                # replace subfield delimiters for punctuation marks
                field_text = field_text.replace("><","; ")
                # first subfield is ignored
                subfield_pat0 = re.compile(r"^(\%s\w)"%subfdelimiter, re.U)
                field_text = subfield_pat0.sub("", field_text)
                # ^a -> :
                subfield_pat1 = re.compile(r"(\%s[aA])"%subfdelimiter, re.U)
                if self.l_repeatableLiteral:
                    delimiter = self.l_repeatableLiteral.value
                else:
                    delimiter = ": "
                field_text = subfield_pat1.sub(delimiter, field_text)
                # ^b through ^i -> ,
                subfield_pat1 = re.compile(r"(\%s[bcdefghiBCDEFGHI])"%subfdelimiter, re.U)
                field_text = subfield_pat1.sub(", ", field_text)
                # all others -> .
                subfield_pat2 = re.compile(r"(\%s\w)"%subfdelimiter, re.U)
                field_text = subfield_pat2.sub(". ", field_text)
                # remove descriptor delimiters
                field_text = field_text.replace("<","").replace(">","")

            if chain.mode=='D':
                if field_text:
                    if not (field_text[-1] in (".",",",";")):
                        # add punctuation mark
                        field_text += "."
                    # add spaces
                    field_text += "  "

            #checks previous n field type
            previous_node = None 
            try:
                if pos > 0:
                    previous_node = chain[pos-1]
            except:
                pass

            previous_nfield = (previous_node and isinstance(previous_node,Field) and \
                               previous_node.value['type'] == 'n' and \
                               not previous_node.value['tag'] in record.keys())
            
            #Previous Conditional literal clear spaces  
            previous_is_condliteral = isinstance(previous_node,ConditionalLiteral)
            
            #flag to newline rule
            self.field_exists = previous_nfield or field_text
            
            #Don't apply formatting to empty field
            if not field_text:
                return 
            
            #Dont apply format if proc
            if LeafNode.proc_chain:
                workarea.append(field_text)
                return workarea
            
            lastline = get_last_line(workarea)
            #gets only last piece of the line
            if len(lastline) > mst.config.MAX_LINE_WIDTH:
                lastline = break_line(lastline, mst.config.MAX_LINE_WIDTH)[-1]

            # handle alignment
            spaces = ''
            max_width = mst.config.MAX_LINE_WIDTH - 1
            if previous_nfield or previous_is_condliteral:
                f,c = (0,0)
                max_width = mst.config.MAX_LINE_WIDTH
            else:
                try:
                    f, c =  self.value['alignment']

                    # segmentation fault in mx                     
                    if c >= max_width and max_width != 0:
                        return ''
                        #raise Exception(_('Indent value error'))
                    
                    if c > 0:
                        spaces = SINGLESPACE * c 
                        
                except KeyError:
                    f, c = (0,0)
                    
            szlastline = len(lastline)
            #Add field to workarea
            if self.r_repeatableLiteral or self.l_repeatableLiteral:
                if szlastline:
                    fspaces = ''
                else:
                    fspaces = SINGLESPACE * f                 
                field_text = '%s%s' % (fspaces,field_text)
                
                words = field_text.split(LeafNode.linesep)
                for idx, word in enumerate(words):
                    if not word:
                        spaces = SINGLESPACE * f
                    if self.masterfield or not idx:
                        workarea.append(word)
                    else:
                        workarea.append(spaces+word)
                        spaces = SINGLESPACE * c
                    if idx < len(words)-1 and len(words) != 1:
                        workarea.append(LeafNode.linesep)
            else:         
      
                if not szlastline:
                    fspaces = SINGLESPACE * f
                else:
                    fspaces = ''
                
                if szlastline >= max_width:
                    workarea.append(LeafNode.linesep)
                    lastline = ''
                    szlastline = 0
                    fspaces = SINGLESPACE * f
                
                #two spaces break line special case
                two_spaces_fields = field_text.split(TWOSPACES)
                if len(two_spaces_fields) > 1 and two_spaces_fields[0].find(SINGLESPACE)==-1 and\
                   len(two_spaces_fields[0]) + 2 + szlastline > max_width:
                    words= None
                    force_break_line = True
                else:
                    words = break_line(lastline + fspaces + field_text, max_width, spaces)
                    force_break_line = False
                
                #force break line if lastline > max_width or it terminates with 2 spaces
                if words and len(words[0]) < szlastline or force_break_line:
                    words = break_line(fspaces + field_text, max_width, spaces)
                    workarea.append(LeafNode.linesep)
                    lastline = ''
                    szlastline = 0
                    fspaces = SINGLESPACE * f

                szlastline = len(lastline)
                for idx,word in enumerate(words):
                    workarea.append(word[szlastline:])
                    szlastline = 0
                    if idx < len(words)-1 and len(words) != 1:
                        workarea.append(LeafNode.linesep)
                        
            LeafNode.last_field_value = field_text
            return workarea


    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False, obj2str=True):
        """The obj2str parameter says that if the end result
        should be converted into string or not. Default behavior is
        to do the conversion to string.
        """
        
        def do_break_line(apply_spaces,format_spaces, result, lastline, max_width, nspaces=''):

            new_pieces = break_line(lastline+result, max_width, nspaces)
            if lastline.find(new_pieces[0]) >=0 and len(new_pieces) == 2:
                return '%s%s' % (LeafNode.linesep,result)
            fresult = ''
            szlastline = len(lastline)
            for idx,word in enumerate(new_pieces):
                if not idx:
                    word = word[szlastline+len(format_spaces[apply_spaces]):]    
                else:
                    word = word[len(nspaces):]
                if word:
                    fresult += word
                if idx < len(new_pieces)-1:
                    fresult += LeafNode.linesep
            return fresult
        
        def do_slicer(params, data):
            begin, end = params['slicer']
            if end:
                # end = number of chars to show
                # last index (not included) -> begin+end
                return data[begin: begin+end]
            else:
                return data[begin:]

        #MasterContainerField size
        mcfSize = 1
        params = self.value
        
        # The occ flag is used from a RepeatableGroup node to
        # serialize repeatable field evaluation. If occ==0 then all
        # repetitions are treated as a single piece of text (except
        # RepeatableLiterals that are handle accordingly).
        tag = params['tag']

        # shortcut variables to avoid multiple hash access
        has_subfield = params.has_key('subfield')
        has_occurence = params.has_key('occurence')
        has_slicer = params.has_key('slicer')
    
        # prepare tag
        try:
            result = record[tag]
        except (KeyError,TypeError):            
            return ''
            
        mcfSize = len(result)
        # prepare occurence
        if has_occurence:
            begin, end = params['occurence']
            if type(begin) is not int and begin != 'LAST':
                try:
                    begin = chain.variables[begin.upper()]
                except KeyError:
                    raise Exception (_('Invalid variable'))
            if end and type(end) is not int and end != 'LAST':
                try:
                    end = chain.variables[end.upper()]
                except KeyError:
                    raise Exception (_('Invalid variable'))

            if isinstance(result,MasterContainerField):
                if end:
                    if end == 'LAST':
                        end = len(result)
                    result = MasterContainerField(tag, sequence=result[begin:end])
                else:
                    try:
                        if begin == 'LAST':
                            begin = len(result)
                        result = result[begin]
                    except IndexError:
                        return ''
            else:
                # occurence 1 of non-repeatable field
                if begin!=1:
                    return ''
                # result remains == record[tag]

        if occ!=0 and not has_occurence:
            # inside RepeatableGroup
            if isinstance(result,MasterContainerField):
                try:
                    result = result[occ]
                except IndexError:
                    return ''
            else:
                if occ != 1:
                    return ''

        # prepare subfield
        if has_subfield:
            try:
                subfield = params['subfield']
                if len(result) == 1:
                    result = MasterField(0,result[subfield])
                else:
                    if not occ:
                        occ = 1
                    result = MasterField(0,result[occ][subfield])
            except KeyError:
                # invalid subfield access
                return ''
        
        #empty sub_field
        if result.data in ('',LeafNode.linesep):
            return ''
        
        if obj2str:
            # dereference MasterField
            try:
                prefix = self.r_repeatableLiteral.value
            except:
                prefix = ''
            try:
                suffix = self.l_repeatableLiteral.value
            except:
                suffix = ''

            #Set parameters to field data
            lastline = get_last_line(workarea)
            szlastline = len(lastline)
            max_width = mst.config.MAX_LINE_WIDTH-1
            try:
                initial_space, next_line_space =  params['alignment']
            except:
                initial_space, next_line_space = 0, 0
            fspaces = SINGLESPACE * initial_space
            nspaces = SINGLESPACE * next_line_space 
            format_spaces = {NEXTLINESPACES: nspaces, FIRSTLINESPACES: fspaces, \
                             EMPTYSPACES: ''}
            apply_spaces  = NEXTLINESPACES

            
            if isinstance(result, MasterField):
                self.masterfield = False
                result = result.data

                #do slice before suffix and prefix
                if has_slicer:
                    result = do_slicer(params, result)
                    
                #set repeatable literal and calculate break line
                if self.r_repeatableLiteral or self.l_repeatableLiteral:

                    if prefix and self.r_repeatableLiteral.plus:
                        prefix = ''
                        
                    if suffix and self.l_repeatableLiteral.plus:
                        #repeatable group
                        if occ == mcfSize or not occ:
                            suffix = ''

                    fresult = ''
                    #appends additional field format data
                    if occ == mcfSize or not occ:
                        conditionalsuffix = self.conditionalsuffix
                    else:
                        conditionalsuffix = ''
                    result = prefix + result + suffix + conditionalsuffix
                    
                    if LeafNode.proc_chain:
                        return result
      
                    if not lastline:
                        result = '%s%s' % (fspaces, result)
                        apply_spaces = FIRSTLINESPACES
                    #check if prefix + lastline + result cause line overflow    
                    if prefix and szlastline + len(result) > max_width:
                        
                        #spaces in prefix cause line overflow 
                        if szlastline + len(prefix) > max_width+1:
                            fresult += LeafNode.linesep
                            lastline = ''
                            #field data and prefix to next line
                            if len(result)+len(fspaces) > max_width:
                                apply_spaces = FIRSTLINESPACES
                                result = '%s%s' % (fspaces,result)
                            else:
                                apply_spaces = EMPTYSPACES
                        
                        #prefix starts with space
                        elif prefix[0] == SINGLESPACE:
                            
                            #adds only prefix in last line before break 
                            if szlastline + len(prefix) in (max_width+1, max_width):
                                lastline = ''
                                result = nspaces + result[len(prefix):]
                                fresult += '%s\n'%(prefix)

                            else:
                                #calculate available length
                                line = result[len(prefix):]
                                length = max_width + 2 - szlastline + len(prefix)
                                line = line[:length] 
                                
                                if len(line) < length:
                                    #get full line
                                    last_pos = len(line)-1
                                else:
                                    #get last space to break line
                                    last_pos = line.rfind(SINGLESPACE)
                                
                                #terminates with single space
                                if last_pos == -1:
                                    if szlastline + len(prefix) <= max_width:
                                        fresult += '%s' % prefix
                                        result = '%s%s'%(nspaces,result[len(prefix):])
                                    lastline = ''
                                    fresult += LeafNode.linesep
                                    
                                else:
                                    first_word = line[:last_pos+1]
                                    #put prefix         
                                    if szlastline + len(first_word) + len(prefix) <= max_width:
                                        lastline = ''
                                        result = (result[len(prefix)+len(first_word):])
                                        result = nspaces + result 
                                        fresult += '%s%s%s'%(prefix,first_word,LeafNode.linesep) 
                                    else:
                                        apply_spaces = EMPTYSPACES
                        else:
                            apply_spaces = EMPTYSPACES
                    else:
                        apply_spaces = EMPTYSPACES
                        
                        #if not spaces in result and last line, force break line
                        if lastline and szlastline + len(result) > max_width and \
                           lastline[-1] != SINGLESPACE and result.find(SINGLESPACE) == -1:
                            lastline = ''
                            fresult += LeafNode.linesep
                    
                    if len(lastline) > max_width:
                        result = fresult
                    else:
                        #single vfield value
                        if not lastline and len(result) < max_width and not workarea:
                            result = result[len(fspaces):]
                        else:
                            #do break line field
                            result = fresult + do_break_line(apply_spaces,format_spaces,result,lastline,max_width,nspaces)                        
                else:
                    #just returns field value and conditional literal
                    result += self.conditionalsuffix
                    #apply spaces if last line terminates with \n 
                    if lastline and lastline[-1] == LeafNode.linesep:
                        result = nspaces + result
                    
            elif isinstance(result, MasterContainerField):
                self.masterfield = True
                temp_result = []
                for i in result:
                    if has_subfield:
                        try:
                            data = i[params['subfield']]
                        except KeyError:
                            continue
                    else:
                        data = i.data
                    #do slice before suffix and prefix
                    if has_slicer:
                        data = do_slicer(params, data)
                    temp_result.append(data)
                
                result = temp_result
                if self.r_repeatableLiteral or self.l_repeatableLiteral:
                    fresult = ''
                    for index, data in enumerate(result):
                        if prefix:
                            if self.r_repeatableLiteral.plus and not index:
                                final_prefix = ''
                            else:
                                final_prefix = prefix
                        else:
                            final_prefix = ''
                        if suffix:
                            if self.l_repeatableLiteral.plus and index == len(result)-1:
                                final_suffix = ''
                            else:
                                final_suffix = suffix
                        else:
                            final_suffix = ''
                        
                        field_txt = final_prefix + data + final_suffix
                        if not szlastline:
                            field_txt = fspaces + field_txt
                        if index == len(result)-1:
                            field_txt += self.conditionalsuffix
                        
                        if LeafNode.proc_chain:
                            fresult += field_txt
                            continue

                        if szlastline + len(field_txt) > max_width+1 or\
                           szlastline + len(field_txt) > max_width and \
                           lastline[-1] == SINGLESPACE:

                            if szlastline > 0:
                                apply_spaces = EMPTYSPACES
                            new_pieces = break_line(lastline+field_txt, max_width, nspaces)
                            
                            if lastline.find(new_pieces[0]) >=0:
                                fresult += '%s%s%s' % (LeafNode.linesep,fspaces,field_txt)
                                lastline = '%s%s' % (fspaces,field_txt)
                                szlastline = len(lastline)
                                continue 
                            
                            for idx,word in enumerate(new_pieces):
                                if not idx:
                                    word = word[szlastline:] 
                                lastline = word
                                fresult += word 
                                if idx < len(new_pieces)-1:
                                    fresult += LeafNode.linesep
                        else:
                            lastline += field_txt
                            fresult += field_txt
                        szlastline = len(lastline)
                               
                    result = fresult
                    
                # otherwise
                else:
                    tmp_result = ''
                    try:
                        chain_mode = chain.mode
                    except:
                        chain_mode = ''
                    if chain_mode == 'D':
                        for (index,data) in enumerate(result):
                            if index != len(result)-1:
                                tmp_result += format_mode(data)
                            else:
                                tmp_result += data
                    else:
                        tmp_result = ''.join([data for data in result])        
                    result = tmp_result + self.conditionalsuffix
            else:           
                raise Exception(_('Unexpected type %s') % (type(result)))

        return result

    def max_repeat(self,record):
        try:
            field = record[self.value['tag']]
        except KeyError:
            return 0
        if isinstance(field, MasterContainerField):
            return len(field)
        else:
            return 1

class Mode(LeafNode):
    def __init__(self, pair):
        self.mode, self.case = pair[1:] # discard m
        self.mode = self.mode.upper()
        self.case = self.case.upper()

    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Modify global mode parameters stored in the workarea.
        """
        chain.mode = self.mode
        chain.case = self.case

    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        """Mode nodes do not generate output by themselves"""
        chain.mode = self.mode
        chain.case = self.case
        return ''

    def max_repeat(self,record):
        return 1

class ConditionalLiteral(LeafNode):
    """A conditional literal. If it is associated with
    a Field Node, then self.field was correctly set
    during parsing."""
    
    def __init__(self,value,suffix=False):
        self.value = value
        self.suffix = suffix
        self.field_filled  = False
        
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        
        if not self.field or self.field_filled:
            # no field associated with this conditional literal in the expression
            return ''
        try:
            chain_case = chain.case
        except:
            chain_case = '' 
        if chain_case=="U":
            value = self.value.upper()
        else:
            value = self.value
        
        field_value = self.field.eval(record, mst, workarea, chain, pos, occ, debug)

        # have field associate with conditional
        if (field_value and self.field.value['type'] in ('d','v')) or\
           (not field_value and self.field.value['type']=='n'):
            #conditional literal suffix handled by field
            max_width = mst.config.MAX_LINE_WIDTH
            if self.suffix:
                self.field.conditionalsuffix = value
                self.field_filled = True
                return ''
            else:
                if LeafNode.proc_chain:
                    return value
                lastline = get_last_line(workarea)
                szlastline = len(lastline)
                
                if szlastline > max_width:
                    return value
                
                elif szlastline + len(value) > max_width and szlastline == max_width:
                   
                   #value ref from other database
                   if workarea[-1] == LeafNode.last_field_value:
                       LeafNode.fix_conditional_literal = True
                       
                elif szlastline == max_width-1:
                    value = '%s%s' %(LeafNode.linesep,value)

                return value
        else:
            # dummy evaluates to false
            return ''

    def max_repeat(self,record):
        return 1

class RepeatableLiteral(LeafNode):
    """A repeatable literal. Instances of this class
    should set the .plus boolean attribute flagging the
    presence or absence of "+" in the original expression.
    The .kind attribute can be: prefix or postfix
    """
    def __init__(self, value):
        self.value = value
        self.field_filled = False 
    
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        # if the Field node is a repeatable field he should check
        # its adjacent siblings. In case they are RepeatableLiteral (RL)
        # nodes, the Field node itsel will use the information and
        # the RLs nodes will do nothing.
        # If the Field node is a non-repeatable field, than RL nodes
        # will evaluate themselves.
        try:
            if not self.field_filled:
                if self.kind == 'postfix':
                    self.field.l_repeatableLiteral = self
                else:
                    self.field.r_repeatableLiteral = self
                self.field_filled = True
            return ''
        except AttributeError:
            # no field associated with this repeatable literal in the expression
            return ''

    def max_repeat(self,record):
        return 1

class InconditionalLiteral(LeafNode):
    """Show inconditionally the single-quoted text.
    Can be placed anywhere in the format and used to pass parameters to
    functions.
    """
    def __init__(self, value):
        self.value = value
        self.apply_format = True
        self.reset_last_spaces = False
    
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        if chain.case=="U":
            try:
                value = self.value.upper()
            except:
                value = self.value
        else:
            value = self.value
        
        if self.apply_format and not LeafNode.proc_chain:

            lastline = get_last_line(workarea)
            max_width = mst.config.MAX_LINE_WIDTH
            szlastline = len(lastline)
            if not isinstance(value, str):
                szvalue = len(str(value))
            else:
                szvalue = len(value)

            if workarea:
                last_wa_item = workarea[-1]
            else:
                last_wa_item = None
            
            if not szlastline and last_wa_item and last_wa_item not in (LeafNode.linesep,'') and \
               last_wa_item.find(LeafNode.linesep) not in (0, len(last_wa_item)-1) and \
               last_wa_item.count(LeafNode.linesep) == 2:
                if len(last_wa_item) + szvalue >= max_width:
                    return '%s%s' % (LeafNode.linesep,value)
            
            elif last_wa_item not in ('\n','') and szlastline == 0:
                sznl = 0
                result = ''.join(workarea)
                if result:
                    if result[-1] == LeafNode.linesep:
                        sznl = 1
                        result = result [:-1]
                    position = result.rfind(LeafNode.linesep) + 1
                    last_line = result[position:]
                    if len(last_line) > 1 and len(last_line) + szvalue + sznl >= max_width:
                        return '%s%s' % (LeafNode.linesep,value)
            
            elif szlastline == max_width - 1 and szvalue == 2:
                return '%s%s' % (LeafNode.linesep,value)

            elif (not szlastline and szvalue < max_width) or \
               (szlastline + szvalue == max_width and szvalue == 2):
                return value
            
            elif szlastline + szvalue > max_width and max_width - szlastline < szvalue and \
                 last_wa_item != '\n' and szvalue < max_width - 1:
                return '%s%s' % (LeafNode.linesep,value)
            
            elif szlastline + szvalue > max_width and lastline.find('\n') == -1 or\
                szvalue > max_width:
                fresult = ''
                new_pieces = break_line(lastline+value, max_width)
                if lastline.find(new_pieces[0])==0:
                    return '%s%s' % (LeafNode.linesep,value)
                for idx,word in enumerate(new_pieces):
                    fresult += word[szlastline:]
                    szlastline = 0
                    if idx < len(new_pieces)-1:
                        fresult += LeafNode.linesep               
                return fresult
            
            elif lastline:
                temp_line = lastline.rstrip()
                self.reset_last_spaces = not temp_line
                position_newline = temp_line.rfind('\n')
                if position_newline < 0:
                    temp_line = lastline
                else:
                    lastline = lastline[position_newline:]
                if len(lastline) < max_width and len(lastline) + szvalue >= max_width:
                    value = '%s%s' % (LeafNode.linesep,value)
                                   
            #elif lastline and \
            #  (szlastline < max_width and (szlastline + szvalue == max_width and value[-1] != SINGLESPACE) or \
            #  (szlastline < max_width and szlastline + szvalue > max_width)):
            #    value = '%s%s' % (LeafNode.linesep,value)
                
        return value

    def max_repeat(self,record):
        return 1

class Break(LeafNode):
    """Break
    """
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        raise BreakException(None)

    def max_repeat(self,record):
        return 1

class Continue(LeafNode):
    """Continue
    """
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        raise ContinueException(None)

    def max_repeat(self,record):
        return 1

class Mfn(LeafNode):

    def __init__(self, value, slash=None):
        self.value = value
        self.slash = slash
    
    def format(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        
        value = self.eval(record, mst, workarea, chain, pos, occ, debug)
        digits = self.value-len(unicode(value))
        
        if digits<=0:
            current = unicode(value)
        else:
            current = '0'*digits + unicode(value)
            
        new_pieces = break_line(current, mst.config.MAX_LINE_WIDTH)
        if len(new_pieces)!=1:
            workarea.append(LeafNode.linesep.join(new_pieces))
        else:
            workarea.append(current)

        if self.slash:
            workarea.append(LeafNode.linesep)
            
    def eval(self, record, mst, workarea, chain, pos, occ=0, debug=False):
        return record.mfn

    def max_repeat(self,record):
        return 1


NUMERIC_PATTERNS = (# number
                    re.compile(r'([-+]?[0-9]*\.?[0-9]+([eE][-+]?[0-9]+)?)'),
                    # hex_number
                    re.compile(r"(0[xX][0-9a-fA-F]+[lL]?)"),
                    )

def break_line(line, max_width, spaces=''):
    """Return a list of line pieces where no piece is
    longer than max_width. Lines are broken at word boundaries.
    If the line is smaller than max_width (or max_width==0), the line
    is returned as the single element of the resulting list.
    """
    if len(line) <= max_width or max_width <= 0: #and line[-1]=='.':
        # Do not apply line breaking algorithm
        # max_width can be negative if the config.MAX_LINE_WIDTH is
        # set to zero
        return [line,]
    
    else:
        result = []
        cut_pos = line.rfind(SINGLESPACE, 0, max_width+1)
        #to break in two spaces
        try:
            if line[cut_pos+1] == SINGLESPACE:
                cut_pos = line[:cut_pos].rfind(SINGLESPACE, 0, max_width+1)
        except:
            pass
        if cut_pos <= 0:
           # handle special case of unbreakable long string
            cut_pos = max_width

        if line[:cut_pos].strip() == '':
            cut_pos = max_width - 1
        
        result.append(line[:cut_pos+1])
        rest = spaces+line[cut_pos+1:]
        if rest:
            result.extend(break_line(rest, max_width, spaces))
        return result


def format_chain(rec, mst, chain, debug=False, workarea=[]):
    """Function that processes every node in the chain
    and applies formatting to the mst and record given.
    Each node is responsible to insert its representation into
    the given workarea(list of strings).
    """
    if mst is None:
        # try Master from record
        mst = rec.mst
        if mst is None:
            # If no mst given, create a dummy with default configuration
            class DummyMst(object):
                pass
            mst = DummyMst()
            mst.config = engine.Engine.config

    # Prepare chain to hold mode params
    if workarea:
        local_workarea = workarea
    else:
        local_workarea = []
    # default mpl - proof mode, data left unchanged
    chain.mode = 'p'
    chain.case = 'l'
    chain.variables = {} # dict to hold evaluated variables
    chain.summary = None
    chain.branch = False
    chain.dont_apply_format = False
    sweepRepeatableLiteral(rec, mst, local_workarea, chain, occ=0, debug=debug)
    for pos, node in enumerate(chain):
        if isinstance(node, RepeatableLiteral):
            continue
        node.format(rec, mst, local_workarea, chain, pos, occ=0, debug=debug)
        chain.summary = None
        chain.branch = False
    output = "".join(local_workarea)
    return output


def sweepRepeatableLiteral(rec, mst, workarea, chain, occ=0, debug=False):
    """Sweep all Repeatable and Conditional literal elements to set field reference
    """
    
    try:
        for pos, node in enumerate(chain):
            if isinstance(node, (RepeatableLiteral,ConditionalLiteral)):
                node.eval(rec, mst, workarea, chain, pos, occ=0, debug=debug)
    except TypeError:
        pass


def decorate(node, func):
    """Recursively browse the tree applying func to all nodes
    """
    if isinstance(node, LeafNode):
        func(node)
    elif isinstance(node, Sequence):
        for child in node:
            decorate(child, func)

def flatten(node):
    """Recursively flatten the tree under node"""
    chain = Sequence()
    LeafNode.linesep = '\n'
    if not node:
        pass
    elif isinstance(node, LeafNode):
        chain.append(node)
    elif isinstance(node, Sequence):
        if len(node)==1:
            return node[0]
        else:
            for child in node:
                chain.extend(flatten(child))
    return chain


def search_path(mst, sfname, extension):
    """Search filename in config SEARCH_PATH option"""
    
    filename = '%s.%s' % (join(mst.basepath,sfname), extension)
    if exists(filename):
        return filename
    else:
        filename = ''
        search_path_list = mst.config.SEARCH_PATH.split(';')
        for spath in search_path_list:
            tmpfname = '%s.%s' % (join(spath, sfname), extension) 
            if exists(tmpfname):
                filename = tmpfname
                break    
    
    return filename


class PftCompiler(object):

    def compile_code(self, chain):
        """Create a formatting function that holds the chain"""
        def f(rec, mst, debug=False):
            _chain = chain
            return format_chain(rec, mst, _chain, debug)
        return f
