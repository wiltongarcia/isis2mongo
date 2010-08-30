# -*- coding: utf-8 -*-

"""
Handling of formatting language. Parser.
"""

__updated__ = "2009-07-28"
__created__ = "2007-01-21"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

import re
from pyisis.ply import yacc
from pyisis.lexer import tokens
from pyisis.ast import *

#----- Utilities
def decorate_field(root, field):
    """Utility function to decorate every node in the given tree
    with an attribute named 'field' pointing to the given field node.
    """
    def set_field(node):
        setattr(node, 'field', field)
    decorate(root, set_field)


# eliminates shift/reduce conflicts
precedence = (
    ('left','OR','AND'),
    ('left','DBSELECTION','PLUS','MINUS'),
    ('left','ASTERISK','SLASH','PERCENT'),
    ('right','UMINUS'),
    ('right', 'COMMA'),
)

def p_statement_expr(p):
    'statement : isisfmt'
    p[0] = p[1]


def p_isisfmt(p):
    """isisfmt : fmtlist emptycomma
    """
    p[0] = p[1]


def p_fmtlist(p):
    """fmtlist : fmtelem emptycomma
               | fmtlist emptycomma fmtelem emptycomma
    """
    if len(p)==3:
        p[0] = p[1]
    else:
        p[0] = p[1].merge(p[3])


def p_paramfmt(p):
    """paramfmt : paramexpr COMMA paramfmt
               |  paramexpr"""
    if len(p)==4:
        p[0] = p[1].merge(p[3])
    else:
        p[0] = p[1] # root node

def p_emptycomma(p):
    """emptycomma : COMMA
                  | emptycomma COMMA
                  |
    """
    pass


def p_spacingstr(p):
    """ spacingstr : spacingparam spacingstr
                   | spacingparam
    """
    if len(p)==2:
        p[0] = p[1]
    else:
        p[0] = p[1].merge(p[2])

def p_spacingparam(p):
    """ spacingparam : SLASH
                     | SHARP
                     | PERCENT
    """
    p[0] = Spacer(p[1])

def p_spacingparam_xspacer(p):
    """ spacingparam : XSPACER
    """
    p[0] = XSpacer(p[1])

def p_spacingparam_cspacer(p):
    """ spacingparam : CSPACER
    """
    p[0] = CSpacer(p[1])

def p_expression_paramexpr(p):
    """paramexpr : boolexpr
                 | strexpr
                 | numexpr
    """
    p[0] = p[1]

def p_expression_fmtelem(p):
    """fmtelem : boolexpr
               | strexpr
               | numexpr
               | attribexpr
               | repeatablegroup
               | spacingstr
               | ifstatement
               | whilestatement
               | selectstatement
               | procfunc
    """
    p[0] = p[1]


def p_expression_mode(p):
    "fmtelem : MODE"
    p[0] = Mode(p[1])


def p_attribexpr(p):
    """attribexpr : SVARIABLE ATTR fmtelem
                  | EVARIABLE ATTR fmtelem
    """
    p[0] = Attr(p[1], p[3])


# Can be achieved by the reduction chain:
# ilit -> fieldselector -> strexpr -> fmtelem -> isisfmt
#def p_expression_uliteral(p):
#    "fmtelem : ilit"
#    p[0] = p[1]


def p_repeatablegroup(p):
    """repeatablegroup : LPAREN isisfmt RPAREN
                       | LPAREN emptycomma isisfmt RPAREN
                       | LPAREN isisfmt emptycomma RPAREN
                       | LPAREN emptycomma isisfmt emptycomma RPAREN
                       | emptycomma LPAREN emptycomma isisfmt RPAREN
                       | emptycomma LPAREN isisfmt emptycomma RPAREN
                       | emptycomma LPAREN emptycomma isisfmt emptycomma RPAREN
    """
    for idx in range(0,len(p)):
        if p[idx] not in ('(',',',')',None):
            p[0] = RepeatableGroup(p[idx])
            break
    #p[0] = RepeatableGroup(p[2])


def p_ilit(p):
    """ilit : INCONDITIONALLITERAL
            | INCONDITIONALLITERAL ilit"""
    if len(p)==2:
        p[0] = InconditionalLiteral(p[1])
    else:
        p[0] = InconditionalLiteral(p[1]).merge(p[2])



def p_fieldselector_ilit(p):
    """ fieldselector : ilit """
    p[0] = p[1]

def p_fieldselector_prefix(p):
    """ fieldselector : prefix field
                      | ilit field
    """
    p[0] = p[1].merge(p[2])
    decorate_field(p[1], p[2])

def p_fieldselector_suffix(p):
    """ fieldselector : field suffix """
    p[0] = p[1].merge(p[2])
    decorate_field(p[2], p[1])

def p_fieldselector(p):
    """ fieldselector : field
                      | prefix field suffix
                      | ilit field suffix
    """
    if len(p)==2:
        p[0] = p[1]
    elif len(p)==4:
        prefix = p[1]
        field = p[2]
        suffix = p[3]
        p[0] = prefix.merge(field).merge(suffix)
        decorate_field(prefix, field)
        decorate_field(suffix, field)


def p_field(p):
    """field : VFIELD"""
    p[0] = Field(p[1])


def p_prefix(p):
    """ prefix : cstring
               | cstring rprelit
               | rprelit
    """
    if len(p)==2:
        p[0] = p[1]
    else:
        p[0] = p[1].merge(p[2])


def p_cstring(p):
    """ cstring : CONDITIONALLITERAL
                | CONDITIONALLITERAL cgroup
                | CONDITIONALLITERAL cstring
                | CONDITIONALLITERAL emptycomma
    """
    if len(p)==2:
        p[0] = ConditionalLiteral(p[1])
    else:
        if p[2] == None:
            p[0] = ConditionalLiteral(p[1])
        else:
            p[0] = ConditionalLiteral(p[1]).merge(p[2])


def p_rprelit(p):
    """ rprelit : REPEATABLELITERAL
                | REPEATABLELITERAL PLUS
                | emptycomma REPEATABLELITERAL PLUS
                | emptycomma REPEATABLELITERAL
                | REPEATABLELITERAL PLUS emptycomma
                | REPEATABLELITERAL emptycomma
    """
    if len(p)==2:
        result = RepeatableLiteral(p[1])
        result.plus = False
    elif len(p)==4:
        if p[1] == None:
            result = RepeatableLiteral(p[2])
        else:
            result = RepeatableLiteral(p[1])
        result.plus = True
    else:
        if p[2] == '+':
            result = RepeatableLiteral(p[1])
            result.plus = True
        else:
            if not p[2]:
                result = RepeatableLiteral(p[1])
            else:
                result = RepeatableLiteral(p[2])
            result.plus = False
    result.kind = 'prefix'
    p[0] = result

def p_cgroup(p):
    """ cgroup : cfmt
               | cfmt cgroup
    """
    if len(p)==2:
        p[0] = p[1]
    else:
        p[0] = p[1].merge(p[2])

# FIXME esc-string missing below!
def p_cfmt(p):
    """ cfmt : spacingstr
             | MODE
    """
    p[0] = p[1]

def p_suffix(p):
    """ suffix : rposlit
               | CONDITIONALLITERAL
               | ilit
               | rposlit CONDITIONALLITERAL
    """
    if len(p)==2:
        if isinstance(p[1], (str,unicode)):
            p[0] = ConditionalLiteral(p[1],True)
        else:
            p[0] = p[1]
    else:
        p[0] = p[1].merge(ConditionalLiteral(p[2],True))


def p_rposlit(p):
    """ rposlit : REPEATABLELITERAL
                | PLUS REPEATABLELITERAL
                | REPEATABLELITERAL emptycomma
                | PLUS REPEATABLELITERAL emptycomma
    """
    result = RepeatableLiteral(None)
    result.plus = p[1] == '+'
    if result.plus:
        result.value = p[2]
    else:
        result.value = p[1]
    result.kind = 'postfix'
    p[0] = result

def p_expression_paramstrnum(p):
    """paramstrnum : INCONDITIONALLITERAL
                   | numexpr
    """
    p[0] = p[1]

#-------- Expression handling
def p_groupcase(p):
    """ groupcasestatement : casestatement
                           | casestatement groupcasestatement
    """
    if len(p)==2:
        p[0] = [p[1],]
    else:
        p[2].append(p[1])
        p[0] = p[2]

def p_case(p):
    """ casestatement : CASE paramstrnum COLON isisfmt
    """
    p[0] = (InconditionalLiteral(p[2]),p[4])


def p_selectstatement(p):
    """ selectstatement : SELECT paramexpr groupcasestatement ENDSEL
                        | SELECT paramexpr groupcasestatement emptycomma ENDSEL
    """
    p[0] = Select(p[2], p[3])

def p_selectelsecasestatement(p):
    """ selectstatement : SELECT paramexpr groupcasestatement ELSECASE isisfmt ENDSEL
    """
    p[0] = Select(p[2], p[3], p[5])

def p_whilestatement(p):
    """ whilestatement : WHILE boolexpr LPAREN isisfmt RPAREN
    """
    p[0] = WhileLoop(p[2], p[4])

def p_ifstatement(p):
    """ ifstatement : IF boolexpr THEN isisfmt FI
                    | IF boolexpr THEN emptycomma isisfmt FI
    """
    p[0] = Branch(p[2], p[len(p) - 2], None)



def p_ifelsestatement(p):
    """ ifstatement : IF boolexpr THEN isisfmt ELSE isisfmt FI
                    | IF boolexpr THEN emptycomma isisfmt ELSE emptycomma isisfmt FI
                    | IF boolexpr THEN emptycomma isisfmt ELSE isisfmt FI
                    | IF boolexpr THEN isisfmt ELSE emptycomma isisfmt FI
                    | IF boolexpr THEN emptycomma ELSE isisfmt FI
                    | IF boolexpr THEN emptycomma ELSE emptycomma isisfmt FI
    """
    psz = len(p)
    if psz == 9:
        if p[5]=='else':
            statement = p[4]
        else:
            statement = p[5-int(p[6]==',')]
        p[0] = Branch(p[2], statement , p[7])
    elif psz == 10:
        p[0] = Branch(p[2], p[5], p[8])
    else:
        p[0] = Branch(p[2], p[4], p[6])


# Boolean expressions

def p_boolexpr(p):
    """ boolexpr : boolexpr OR boolexpr
                 | boolexpr AND boolexpr
                 | boolexpr XOR boolexpr
    """
    p[0] = BinOp(p[2], p[1], p[3])


def p_boolexpr_parens(p):
    """ boolexpr : LPAREN boolexpr RPAREN"""
    p[0] = p[2]


def p_notbool(p):
    """ boolexpr : NOT boolexpr
    """
    p[0] = Not(p[2])

def p_boolrelation(p):
    """ boolexpr : relation
    """
    p[0] = p[1]

def p_relation(p):
    """ relation : numexpr relop numexpr
                 | boolfunc
    """
    if len(p)==4:
        # numexpr relop numexpr
        p[0] = BinOp(p[2], p[1], p[3])
    else:
        # boolfunc
        p[0] = p[1]


def p_relation_strexpr(p):
    """ relation : strexpr strrelop strexpr
                 | datefunc strrelop strexpr
    """
    p[0] = BinOp(p[2], p[1], p[3])

# FIXME: Revise with BIREME
#    """ strexpr : strfactor strexpr
#                | strfactor
#    """
#    if len(p)==2:
#        p[0] = p[1]
#    else:
#        p[0] = p[1].merge(p[2])

def p_strexpr(p):
    """ strexpr : fieldselector
                | strfunc
                | datefunc
    """
    p[0] = p[1]

#Verificar
#def p_strexpr_parens(p):
#    """ strexpr : LPAREN strexpr RPAREN
#    """
#    p[0] = p[2]


def p_strexpr_svariable(p):
    """ strexpr : SVARIABLE"""
    p[0] = Variable(p[1])


def p_procfunc(p):
    """procfunc : FUNCPROC LPAREN isisfmt RPAREN
                | emptycomma FUNCPROC LPAREN isisfmt emptycomma RPAREN
                | FUNCPROC LPAREN isisfmt RPAREN emptycomma
                | emptycomma FUNCPROC LPAREN isisfmt RPAREN emptycomma
    """
    p[0] = Proc(p[3:-1])


def p_datefunc(p):
    """datefunc : FUNCDATE
                | FUNCDATE LPAREN DATEONLY RPAREN
                | FUNCDATE LPAREN DATETIME RPAREN
    """
    if len(p) == 2:
        p[0] = Date(None)
    else:
        p[0] = Date(p[3])

def p_instrfunc(p):
    """numfunc : FUNCNUMINSTR LPAREN paramexpr COMMA paramfmt RPAREN
    """
    p[0] = Instr(p[3],p[5])


def p_strfunc(p):
    """ strfunc : FUNCSTRN
    """
    fmap = {'MSTNAME': GetMSTName,
            'BREAK': Break,
            'CONTINUE': Continue,
           }
    key = unicode(p[1]).upper()
    p[0] = fmap[key](p[1])


def p_strfunc_s(p):
    """ strfunc : FUNCSTR LPAREN fmtlist RPAREN
    """

    #""" strfunc : FUNCSTR LPAREN paramfmt RPAREN
    #"""
    fmap = {'MID': Mid,
            'S':  lambda x: p[3], # return the unwrapped subtree
            'F': FFunc,
            'LEFT': Left,
            'RIGHT': Right,
            'REPLACE': Replace,
            'DATEX': Datex,
            'CAT': Cat,
            'TYPE': Type,
            'NEWLINE': Newline,
            'LW' : LineWidth,
        }
    key = unicode(p[1]).upper()
    p[0] = fmap[key](p[3])


def p_numfunc_nopar(p):
    """ numfunc : FUNCNUM
    """
    fmap = {'IOCC': Iocc,
           }
    key = unicode(p[1]).upper()
    p[0] = fmap[key](p[1])


def p_numfunc(p):
    """ numfunc : FUNCNUM LPAREN paramfmt RPAREN
                | FUNCNUM LPAREN datefunc RPAREN
                | FUNCNUM LPAREN isisfmt RPAREN
    """
    # FIXME: L
    fmap = {'VAL': NumFuncVal,
            # use lambda expression to wrap 2-param functions in
            # a single param function shell
            'RSUM': lambda node: NumFuncSeq(node, 'RSUM'),
            'RMAX': lambda node: NumFuncSeq(node, 'RMAX'),
            'RMIN': lambda node: NumFuncSeq(node, 'RMIN'),
            'RAVR': lambda node: NumFuncSeq(node, 'RAVR'),
            'SIZE': Size,
            'SECONDS': Seconds,
            'NPOST' : Npost,
            #'L': Search,
            'NOCC' : Nocc,
        }
    key = unicode(p[1]).upper()
    p[0] = fmap[key](p[3])


def p_strrelop(p):
    """ strrelop : relop
                 | COLON
    """
    p[0] = p[1]

def p_relop(p):
    """ relop : EQUALS
              | DIFFERENT
              | LESS
              | LESSEQUAL
              | GREAT
              | GREATEQUAL
    """
    p[0] = p[1]

def p_strfunc_ref(p):
    """ strfunc : FUNCREF LPAREN  paramexpr COMMA isisfmt  RPAREN
    """
    p[0] = Ref(p[3], p[5])

def p_strfunc_ref2(p):
    """ strfunc : FUNCREF LPAREN LBRACKET paramexpr RBRACKET  paramexpr COMMA isisfmt  RPAREN
                | FUNCREF DBSELECTION LPAREN paramexpr COMMA isisfmt RPAREN
    """
    #Trivial Sintax
    if p[2].startswith('->'):
        p[0] = Ref(p[4],p[6],p[2].replace('->',''))
    else:
        p[0] = Ref(p[6], p[8], p[4])


def p_strfunc_search(p):
    """ numfunc : FUNCSEARCH LPAREN isisfmt  RPAREN
    """
    p[0] = Search(p[3])

def p_strfunc_search2(p):
    """ numfunc : FUNCSEARCH LPAREN LBRACKET paramexpr RBRACKET  isisfmt  RPAREN
                | FUNCSEARCH DBSELECTION LPAREN  isisfmt  RPAREN
    """
    if p[2].startswith('->'):
        p[0] = Search(p[4],p[2].replace('->',''))
    else:
        p[0] = Search(p[6], p[4])


def p_strfunc_npost(p):
    """ numfunc : FUNCNPOST LPAREN isisfmt  RPAREN
    """
    p[0] = Npost(p[3])

def p_strfunc_npost2(p):
    """ numfunc : FUNCNPOST LPAREN LBRACKET paramexpr RBRACKET  isisfmt  RPAREN
    """
    p[0] = Npost(p[6], p[4])


def p_boolfunc(p):
    """ boolfunc : FUNCBOOL LPAREN field RPAREN
    """
    p[0] = BoolFunc(p[1], p[3])

# Numeric expressions

def p_numexpr(p):
    """numexpr : numexpr PLUS numexpr
               | numexpr MINUS numexpr
               | numexpr ASTERISK numexpr
               | numexpr PERCENT numexpr
               | numexpr SLASH numexpr
    """
    p[0] = BinOp(p[2], p[1], p[3])


def p_expression_group(p):
    '''numexpr : LPAREN numexpr RPAREN'''
    p[0] = p[2]


def p_numexpr_mfn(p):
    """numexpr : MFN
               | MFN SLASH
    """
    if len(p) == 2:
        p[0] = Mfn(p[1])
    else:
        p[0] = Mfn(p[1],p[2])


def p_numexpr_number(p):
    """numexpr : NUMBER
    """
    p[0] = Number(p[1])


def p_numexpr_numfunc(p):
    """numexpr : numfunc
    """
    p[0] = p[1]


def p_numexpr_uminus(p):
    """numexpr : MINUS numexpr %prec UMINUS
    """
    p[0] = Minus(p[2])


def p_numexpr_evariable(p):
    """numexpr : EVARIABLE"""
    p[0] = Variable(p[1])


#--end of field rules

def p_error(p):
    if p:
        print _("Syntax error at '%s'. Type: %s") % (p.value, type(p))
    else:
        print _("Syntax error. Empty production.")

class PftParser(object):
    """Wrapper class to default PLY yacc"""
    def __init__(self, lexer, debug=False, outputdir='', parser = None):
        """ lexer must be an object that supports the same API as PftLexer.
        """
        if not outputdir:
            outputdir = gettempdir()
        if parser is None:
            parser = yacc.yacc(debug=0,
                               optimize=1,
                               write_tables=0,
                               #method="SLR",
                               outputdir=outputdir)
        self._parser = parser
        self._lexer = lexer

    def parse(self, expr, debug=False):
        return self._parser.parse(expr, lexer=self._lexer, debug=debug)
