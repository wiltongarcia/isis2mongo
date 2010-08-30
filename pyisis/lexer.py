# -*- coding: utf-8 -*-

"""
Handling of formatting language. Lexer.
"""

__updated__ = "2008-10-13"
__created__ = "2007-01-21"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

import re
from pyisis.ply import lex

tokens = ['VFIELD', 'NUMBER','MFN', 
          'XSPACER', 'CSPACER',
          'COMMA', 'COLON',  'SLASH', 'SHARP', 'PERCENT',
          'PLUS', 'MINUS', 'ASTERISK',
          'RPAREN', 'LPAREN', 'RBRACKET', 'LBRACKET',
          'EQUALS', 'DIFFERENT',
          'LESS', 'LESSEQUAL', 'GREAT', 'GREATEQUAL',
          'CONDITIONALLITERAL', 'INCONDITIONALLITERAL', 'REPEATABLELITERAL',
          'SVARIABLE', 'EVARIABLE', 'ATTR', 'DBSELECTION',
          ]

# Reserved word handling
# Translate groups of words into group TOKENS
def build_dict(funclist, tokentype, tokens, reserved):
    """ Creates a dict mapping a reserved word to the
    respective token type identifier that should be generated
    by the lexer.
    Eg.: {"P":"FUNCBOOL", ... }
    """
    tokens.append(tokentype)
    d = dict([(i.upper(), tokentype) for i in funclist])
    reserved.update(d)

reserved = {}

# functions with general signature

#build_dict(["mfn"], 'FUNCMFN', tokens, reserved)

build_dict(["date"], 'FUNCDATE', tokens, reserved)

build_dict(["proc"], 'FUNCPROC', tokens, reserved)

build_dict(["instr"], 'FUNCNUMINSTR', tokens, reserved)

build_dict(["mstname", "break", "continue"], 'FUNCSTRN', tokens, reserved)

build_dict(["s", "mid", "f", "left", "right", "replace",
            "datex", "cat", "type", "newline", "lw"], 'FUNCSTR', tokens, reserved)

build_dict(["rsum","rmax","rmin","ravr","val","size","seconds","nocc",
            "iocc"],'FUNCNUM', tokens, reserved)

# functions with special signature or restricted parameters
build_dict(["p","a"], 
           'FUNCBOOL', tokens, reserved)

build_dict(["ref"], 'FUNCREF', tokens, reserved)

build_dict(["l"], 'FUNCSEARCH', tokens, reserved)

build_dict(["npost"], 'FUNCNPOST', tokens, reserved)


# MODE variants
build_dict(["mpu","mpl","mhu","mhl","mdu","mdl"], 'MODE', tokens, reserved)

# Translate words into identical TOKENS
def build_words(wordlist, tokens, reserved):
    for word in wordlist:
        tok = word.upper()
        reserved[tok]=tok
        tokens.append(tok)

build_words(('if', 'then', 'else', 'fi',
             'or','and','not', 'xor', 'while',
             'select','case','elsecase','endsel',
             'dateonly','datetime',),
            tokens, reserved)

literals = ['=','-','(',')','*','.']

precedence = (
    ('left','*','.','^'),
    ('left','ASTERISK','SLASH'), # TIMES, DIVIDE
    ('left','PLUS','MINUS'),
    )

# Tokens
t_COMMA = r','
t_COLON = r'\:'
t_SLASH = r'/'
t_SHARP = r'\#'
t_PERCENT = r'%'
t_ASTERISK = r"\*"
t_LPAREN = r'\('
t_RPAREN = r'\)'
t_LBRACKET = r'\['
t_RBRACKET = r'\]'
t_DBSELECTION = r'(->\w+)'

t_ATTR     = re.escape(':=')

t_PLUS = re.escape("+")
t_MINUS = re.escape("-")

t_EQUALS = re.escape('=')
t_DIFFERENT = re.escape('<>')
t_LESS = re.escape('<')
t_LESSEQUAL = re.escape('<=')
t_GREAT = re.escape('>')
t_GREATEQUAL = re.escape('>=')

t_ignore = "\t\n\r\b\f "
#t_STRING1  = r'\".*?\"'

# Handle literals
# Declare the state
states = (
  ('repeatableLiteral','exclusive'),
  ('conditionalLiteral','exclusive'),
  ('inconditionalLiteral','exclusive'),
  ('tagfield','exclusive'),
)

# C-style comments
def t_ccomment(t):
   r'/\*([^*]|[\r\n]|(\*+([^*/]|[\r\n])))*\*+/'


# Match the first |. Enter conditional_literal state.
def t_repeatableLiteral(t):
    r'\|'
    t.lexer.literal_start = t.lexer.lexpos   # Record the starting position
    t.lexer.level = 1                     # Initial pipe level
    t.lexer.push_state('repeatableLiteral')  # change state

def t_repeatableLiteral_close(t):
    r'\|'
    # If closing pipe, return the string fragment
    t.value = t.lexer.lexdata[t.lexer.literal_start:t.lexer.lexpos-1]
    t.type = "REPEATABLELITERAL"
    t.lexer.lineno += t.value.count('\n')
    t.lexer.pop_state()
    return t

def t_repeatableLiteral_continue(t):
   r'[^\|]'
   #t.type = "REPEATABLELITERAL_CONTINUE"
   #return t

t_repeatableLiteral_ignore = r''

# For bad characters, we just skip over it
def t_repeatableLiteral_error(t):
    raise SyntaxError(_("Invalid repeatable literal {%s}") % t.value)
    #t.lexer.skip(1)

#--------------------------------------------------------------------------
def t_conditionalLiteral(t):
    r'\"'
    t.lexer.literal_start = t.lexer.lexpos   # Record the starting position
    t.lexer.level = 1                     # Initial pipe level
    t.lexer.push_state('conditionalLiteral')  # change state

def t_conditionalLiteral_close(t):
    r'\"'
    # If closing pipe, return the string fragment
    t.value = t.lexer.lexdata[t.lexer.literal_start:t.lexer.lexpos-1]
    t.type = "CONDITIONALLITERAL"
    t.lexer.lineno += t.value.count('\n')
    t.lexer.pop_state()
    return t

t_conditionalLiteral_ignore = r''

def t_conditionalLiteral_continue(t):
   r'[^\"]'
   #t.type = "CONDITIONALLITERAL_CONTINUE"
   #return t

# For bad characters, we just skip over it
def t_conditionalLiteral_error(t):
    raise SyntaxError(_("Invalid conditional literal {%s}") % t.value)
    #t.lexer.skip(1)

#--------------------------------------------------------------------------
def t_inconditionalLiteral(t):
    r"\'"
    t.lexer.literal_start = t.lexer.lexpos   # Record the starting position
    t.lexer.level = 1                     # Initial pipe level
    t.lexer.push_state('inconditionalLiteral')  # change state

def t_inconditionalLiteral_close(t):
    r"\'"
    # If closing pipe, return the string fragment
    t.value = t.lexer.lexdata[t.lexer.literal_start:t.lexer.lexpos-1]
    t.type = "INCONDITIONALLITERAL"
    t.lexer.lineno += t.value.count('\n')
    t.lexer.pop_state()
    return t

def t_inconditionalLiteral_continue(t):
   r"[^\']"
   #t.type = "INCONDITIONALLITERAL_CONTINUE"
   #return t

# Ignored characters (whitespace)
t_inconditionalLiteral_ignore = ""

# For bad characters, we just skip over it
def t_inconditionalLiteral_error(t):
    raise SyntaxError(_("Invalid inconditional literal {%s}") % t.value)
#--------------------------------------------------------------------------
# Handle Spacers
def t_XSPACER(t):
    r'[xX]\d+'
    t.value = int(t.value[1:])
    t.type = 'XSPACER'
    return t

def t_CSPACER(t):
    r'[cC]\d+'
    t.value = int(t.value[1:])
    t.type = 'CSPACER'
    return t


# Handle fields (including dummy fields)
def t_VFIELD(t):
    r'[vVdDnN]\d+'
    # create auxiliary dict to hold field optional attributes
    t.lexer.tagfield = {'tag': int(t.value[1:]),
                        'type':t.value[0].lower()} # type = v or d or n
    t.lexer.push_state('tagfield')
    if t.lexer.lexdata.endswith(t.value) or t.lexer.lexdata[t.lexer.lexmatch.end()] == ',':
        return finish_tagfield(t)

def t_tagfield_subfield(t):
    r'\^[\w*]'
    t.lexer.tagfield['subfield']= t.value[1]
    if t.lexer.lexdata.endswith(t.value):
        return finish_tagfield(t)

def t_tagfield_occurence(t):
    r'\[([0-9e]+\.\.[0-9e]+)\]|\[([0-9e]+\.\.LAST)\]|\[([0-9e]+\.\.)\]|\[([0-9e]+)\]|\[(LAST)\]'
    group = t.lexer.lexmatch.group()[1:-1] # strip off []
    try:
        begin, end = group.split("..")
        if begin:
            try:
                begin = int(begin)
            except ValueError:
                pass
        if end:
            try:
                end = int(end)
            except ValueError:
                pass
        result = (begin, end)
    except ValueError:
        try:
            result = (int(group),'')
        except ValueError:
            result = (group,'')

    t.lexer.tagfield['occurence']= result
    if t.lexer.lexdata.endswith(t.value):
        return finish_tagfield(t)

def t_tagfield_slicer(t):
    r'\*(?P<slicer_begin1>\d+)\.(?P<slicer_end1>\d+)|\*(?P<slicer_begin2>\d+)|\.(?P<slicer_end2>\d+)'
    groupdict = t.lexer.lexmatch.groupdict()
    try:
        begin = int(groupdict['slicer_begin1'])
    except TypeError:
        # expception - try other rule
        try:
            begin = int(groupdict['slicer_begin2'])
        except TypeError:
            # No match - use default value
            begin = 0

    try:
        end = int(groupdict['slicer_end1'])
    except TypeError:
        # expception - try other rule
        try:
            end = int(groupdict['slicer_end2'])
        except TypeError:
            # No match - use default value
            end = ''
    t.lexer.tagfield['slicer']= (begin,end)
    if t.lexer.lexdata.endswith(t.value):
        return finish_tagfield(t)

def t_tagfield_alignment(t):
    r'\((?P<alignment>\d+\,\d+)\)|\((?P<alignment2>\d+)\)'
    try:
        begin, end = t.lexer.lexmatch.groupdict()['alignment'].split(',')
    except AttributeError:
        begin, end = t.lexer.lexmatch.groupdict()['alignment2'], 0
    t.lexer.tagfield['alignment']= (int(begin), int(end))
    if t.lexer.lexdata.endswith(t.value):
        return finish_tagfield(t)

def t_tagfield_end(t):
    r"."
    t.lexer.lexpos -= 1 # push caracter back
    return finish_tagfield(t)

def finish_tagfield(t):
    t.value = t.lexer.tagfield
    del t.lexer.tagfield
    t.lexer.pop_state()
    t.type = 'VFIELD'
    return t

t_tagfield_ignore = r''

def t_tagfield_error(t):
    raise SyntaxError(_("Invalid field expression {%s}") % t.value)

#-----------------------------------------------------

def t_VARIABLE(t):
    r'[eEsS]\d+'
    if t.value[0].upper()== 'S':
        t.type = 'SVARIABLE'
    else:
        t.type = 'EVARIABLE'
    return t


def t_MFN(t):
    r'mfn\(\d+\)|MFN\(\d+\)|MFN|mfn'
    if len(t.value)==3:
        t.value=6 # default length
    else:
        t.value = int(t.value[4:-1])
        t.type = 'MFN'
    return t

def t_NUMBER(t):
    r'\d*\.?\d+([eE][-+]?\d+)?'
    # r'[-+]?\d*\.?\d+([eE][-+]?\d+)?'
    # Avoid initial [-+]? to recognise operators
    try:
        t.value = eval(t.value)
    except SyntaxError:
        raise SyntaxError(_("Value is not recognised as a valid number") % t.value)
    return t

def t_KEYWORD(t):
    r'[a-zA-Z_][a-zA-Z_0-9]*'
    key = t.value.upper()
    t.type = reserved.get(key, 'KEYWORD')
    if not t.type:
        raise SyntaxError(_('Word %s is not recognised as a valid keyword') % t.value)
    return t

def t_error(t):
    value  = t.value[0]
    raise SyntaxError(_("Illegal character '%s' at position %d in expression {%s}")\
                       % (value, t.lexer.lexpos, t.lexer.lexdata))
    #t.lexer.skip(1)

# Auxiliary routines

def _new_token(type, lineno):
    "Create an extended Token object"
    tok = lex.LexToken()
    tok.type = type
    tok.value = None
    tok.lineno = lineno
    tok.lexpos = -100
    return tok

def _add_endmarker(token_stream):
    "Put a sentinel marker add the end of the token_stream"
    tok = None
    for tok in token_stream:
        yield tok
    if tok is not None:
        lineno = tok.lineno
    else:
        lineno = 1
    yield _new_token("ENDMARKER", lineno)

def make_token_stream(lexer, add_endmarker = True):
    "Browse through the token stream and do preprocessing."
    token_stream = (i for i in iter(lexer.token, None))

    return token_stream

class PftLexer(object):
    """Wrapper class to default PLY lexer"""
    def __init__(self, lexer = None):
        if lexer is None:
            lexer = lex.lex(optimize=1)#debug=1)
            lexer.lexreflags = re.UNICODE
        self.lexer = lexer
        self.lexer.paren_count = 0
        self.token_stream = None

    def input(self, data, add_endmarker=True):
        self.lexer.input(data)
        self.token_stream = make_token_stream(self.lexer, add_endmarker=True)

    def token(self):
        try:
            x = self.token_stream.next()
            return x
        except AttributeError:
            return ""
        except StopIteration:
            return None

    def __iter__(self):
        return self.token_stream

