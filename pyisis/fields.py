# -*- coding: utf-8 -*-
"""
Definition of data fields that occur in ISIS Records.
"""

__updated__ = "$Id$"
__created__ = "2008-05-15"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

from operator import getslice
from itertools import izip, imap, groupby
from config import config as global_config


class MasterField(object):
    """A MasterField can have string-based subfields, separated by SUBFIELD_DELIMITER
    and named with a letter. Each field has a tag represented by an integer
    value. If a string is passed as tag, then a integer conversion will be
    attempted implicitly. The data should be in unicode, otherwise the
    INPUT_ENCODING (global config) will be used to do the conversion.
    The encoding parameter will be used while printing, and if not
    specified the OUTPUT_ENCODING from config param will be used.
    """
    __slots__ = ('tag', 'data', 'order', 'encoding', 'input_encoding',
                 'delimiter',)

    def __init__(self, tag, data=u'', config=None):
        self.tag = int(tag)   # identifier of the field must be conversible to integer

        # Override specific configurations
        if config is None:
            self.encoding = global_config.OUTPUT_ENCODING
            self.input_encoding = global_config.INPUT_ENCODING
            self.delimiter = global_config.SUBFIELD_DELIMITER
        else:
            self.encoding = config.OUTPUT_ENCODING
            self.input_encoding = config.INPUT_ENCODING
            self.delimiter = config.SUBFIELD_DELIMITER

        if type(data)==unicode:
            self.data = data # raw field data
        else:
            self.data = data.decode(self.input_encoding)

        self.order = [] # subfield tags in order of appearance


    def _get_subfields(self, data):
        """Private function to extract subfields.
        Returns a dictionary (dict) containing the
        subfield identifier (key) and the subfield's data (value).
        """
        self.order = []
        # parse subfields
        # This can be memoized in the future for optimization purposes.
        subfields = dict()
        if not data.startswith(self.delimiter):
            # single value == single anonymous subfield
            data = self.delimiter + " " + data

        pairs = [(i[0].lower().strip(), i[1:])\
                for i in data.split(self.delimiter) if i]

        for key, values in groupby(pairs, lambda x: getslice(x, 0, 1)):
            subkey = key[0]
            # preserve order of subfields
            self.order.append(subkey)
            value = list(imap(lambda x: getslice(x,1,2)[0], values))
            if len(value)==1:
                # single values are not wrapped in lists
                value = value[0]
            subfields[subkey] = value

        # support ^* == first subfield
        subfields['*'] = subfields[self.order[0]]

        return subfields


    def _get_subfield(self, key, data):
        """Private function to extract subfield
        """
        #if data.find(self.delimiter) >= 0:
        return self._get_subfields(data)[key]
        #else:
        #    return data


    def __cmp__(self, other):
        """Comparison operator that uses tag as sorting criterion,
        and if both fields have the same tag, them the data is used.
        """
        if self.tag==other.tag:
            return cmp(self.data, other.data)
        else:
            return cmp(self.tag, other.tag)

    def __getitem__(self, key):
        """Override index operator[] to access subfields.
        key is char: return subfield
        """
        return self._get_subfield(key, self.data)

    def __getattr__(self, name):
        """Handle subfields as automatically generated attributes
         of directory entry."""
        return self._get_subfield(name, self.data)

    def __unicode__(self):
        return self.data

    def __repr__(self):
        return "MasterField(%d, '%s')"%(self.tag, self.data.encode(self.encoding))

    def __str__(self):
        return self.data.encode(self.encoding)

    def __len__(self):
        """To know the length of data, use len(self.data)"""
        return 1

    def to_xml(self):
        ftemplate = '<field tag="%d"><occ>%s</occ></field>'
        stemplate = '<subfield tag="%s"><![CDATA[%s]]></subfield>'

        fields = []
        for k,v in self._get_subfields(self.data).items():
            if k != '*':
                fields.append(stemplate % (k,v))

        return ftemplate % (self.tag, "".join(fields))


class MasterContainerField(list):
    """This is a specialized list just to mark field containment,
    used also to accomodate repetition."""
    def __init__(self, tag, sequence=None, config=None):
        self.tag = tag
        if sequence is not None:
            for i in sequence:
                if type(i)==MasterField:
                    self.append(i)
                else:
                    self.append(MasterField(tag, i, config=config))

    def __getslice__(self, begin, end):
        if begin==0 and end==0:
            return MasterField(0,'')
        if begin==0:
            begin=1
        return list.__getslice__(self, begin-1, end)

    def __getitem__(self, index):
        "ISIS indexes start from 1. Index zero must return empty string"
        if index==0:
            return MasterField(0,'')
        else:
            return list.__getitem__(self, index-1)

    def _get_data(self, separator=u""):
        """Loop through the list and concatenate values
        separated by <separator> parameter, whose default
        value is the empty string."""
        return separator.join([i.data for i in self])

    # create property to support same interface as MasterField
    data = property(_get_data)

    def __unicode__(self):
        """Generate a unicode-aware string representation"""
        return self._get_data()

    def to_xml(self):
        ftemplate = '<field tag="%d">%s</field>'
        otemplate = '<occ>%s</occ>'
        stemplate = '<subfield tag="%s"><![CDATA[%s]]></subfield>'

        occs = []
        for field in self:
            sfields = []
            for k,v in field._get_subfields(field.data).items():
                if k != '*':
                    sfields.append(stemplate % (k,v))
            occs.append(otemplate % ("".join(sfields)))

        return ftemplate % (self.tag, "".join(occs))
