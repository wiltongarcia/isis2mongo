# -*- coding: utf-8 -*-

"""
Configuration info for pyisis.
"""

__updated__ = "2008-07-22"
__created__ = "2008-04-02"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

import re
import sys
import os
import logging
import tempfile
from math import log
from os.path import join, dirname, split
from struct import calcsize
from ConfigParser import ConfigParser, NoSectionError, NoOptionError
from codecs import lookup


class ConfigError(Exception):
    pass

class Config(object):
    """ This class maps the information available in a confioguration file
    (*.ini) into an instance holding configuration attributes.
    Some parameters require pre-processing to convert text from the configuration
    file into appropriate Python values.
    """
    def __init__(self):
        """Set reasonable default values. If no configuration file (.ini)
        is found later, then use these values.
        """
        self.COLLECTIONS = []

        self.INPUT_ENCODING = 'utf-8'
        self.LANGUAGE = 'en'
        
        if sys.platform == 'win32':
            basepath = self.basepath = join(sys.prefix, 'lib','site-packages','pyisis')
            self.OUTPUT_ENCODING = 'cp850'
        else:
            basepath = self.basepath = os.path.abspath(os.path.dirname(__file__))
            self.OUTPUT_ENCODING = 'utf-8'
        
        self.FDT_LINE = r"(?P<name>\w[\w\s]*?\w)\s+(?P<subfields>\w*)\s+(?P<tag>\d*)\s+(?P<size>\d*)\s+(?P<etype>\d+)\s+(?P<repeat>\d+)"
        self.SILENT_EXCEPTIONS = False
        self.POINTER_SIZE = 4
        self.LAST_XRF_BLOCK = -1
        self.PARSER_AUXFILES_DIR = tempfile.gettempdir()
        self.YACC_DEBUG = False
        self.LOG_LEVEL = logging.DEBUG
        self.LOG_PATH = join(tempfile.gettempdir(), "pymx.log")
        self.HTTP_PORT = 8080
        self.SSH_PORT = 2222
        self.USERNAME = 'admin'
        self.PASSWORD = 'admin'
        self.BLOCK_SIZE = 512
        self.BLOCK_ALIGN = False
        self.SUBFIELD_DELIMITER = "^"
        self.CTRL_SIZE = 64
        self.BYTE_ORDER = "little" #  or "big"
        self.BYTE_ORDER_PRFIX = "<" # default standard native
        self.CTRL_MASK = self.BYTE_ORDER_PRFIX + "iiiHBBiiii"
        self.DIR_MASK = self.BYTE_ORDER_PRFIX + "HHH"
        self.LEADER_MASK = self.BYTE_ORDER_PRFIX + "iHiHHHH"
        #self.LEADER_MASK_XL = self.BYTE_ORDER_PRFIX + "iHiiHHH"
        self.LEADER_MASK_XL = self.BYTE_ORDER_PRFIX + "iHHiHHHH"
        self.LEADER_XL = True
        self.XRF_BLOCK = 2048
        self.XRF_OFFSET = 0x000001FF
        self.XRF_NEW_FLAG = 0x00000400
        self.XRF_MODIFIED_FLAG = 0x00000200
        self.SEARCH_PATH = ''

        self._recalculate_dependent_params()

        # django template settings
        self.HTML_DEBUG = True
        # always use Unix style slashes
        self.HTML_TEMPLATE_DIRS = (basepath+'/web/isis/templates',)
        self.MEDIA_ROOT = basepath+'/web/isis/media'
        self.WEB_LOG = join(tempfile.gettempdir(), "isisweb.log")

        # formatting language
        self.MAX_LINE_WIDTH = 79

    def clone(self, srcobj):
        """Method to generate another Config() instance with the
        same values existing in the current self instance.
        """
        for attr in [i for i in dir(srcobj) if not i.startswith('_')]:
            value = getattr(srcobj, attr)
            if not callable(value):
                setattr(self, attr,  value)


    def _safe_set(self, attribute, cfg, section, option, validation=None):
        """Try to set attribute with cfg.get(section, option) or
        fail silently if configuration not found.
        """
        try:
            if validation is None:
                value = cfg.get(section, option)
            else:
                value = validation(cfg, section, option)
            setattr(self, attribute, value)
        except (NoSectionError, NoOptionError):
            pass

    def validate_encoding(self, cfg, section, param):
        """Validates string codecs"""
        try:
            lookup(cfg.get(section, param))
        except LookupError:
            msg = invalid_encoding%(configfile, param)
            raise ConfigError(msg)

        else:
            return value

    def validate_mask(self, cfg, section, param):
        """Validates MASK string if it is coherent with BYTE_ORDER
        and BYTE_ORDER_MASK"""
        convert = {"little":"<", "big":">"}
        byte_order_mask = cfg.get('IsisDB', 'BYTE_ORDER_MASK')
        value = cfg.get(section, param)
        if value[0]!='=' and convert[value]!=byte_order_mask:
            raise ConfigError("Inconsist byte order mask for %s and %s, expected %s"%(value, byte_order_mask, convert[value]))
        else:
            return value


    def validate_bool(self, cfg, section, param):
        """Validates boolean values converting from str to int"""
        try:
            value =  eval(cfg.get(section, param))
        except NameError:
            msg = invalid_bool%(configfile, param)
            raise ConfigError(msg)
        else:
            return value

    def validate_int(self, cfg, section, param):
        """Validates integer values converting from str to int"""
        value = cfg.get(section, param)
        try:
            value = int(value)
        except ValueError:
            msg = invalid_int%(configfile, param)
            raise ConfigError(msg)
        return value

    def _recalculate_dependent_params(self):
        """Some parameters are a function of configurable parameters.
        If the configuration changes, these values must be recalculated.
        """
        self.POINTER_PER_BLOCK = self.BLOCK_SIZE/self.POINTER_SIZE - 1
        self.BLOCK_POWER =  int(log(self.BLOCK_SIZE, 2))
        self.CTRL_MASK_SIZE = calcsize(self.CTRL_MASK)
        self.LEADER_SIZE =  calcsize(self.LEADER_MASK)
        self.LEADER_SIZE_XL =  calcsize(self.LEADER_MASK_XL)
        self.DIR_SIZE =  calcsize(self.DIR_MASK)
        if type(self.FDT_LINE)==str:
            self.FDT_LINE = re.compile(self.FDT_LINE)

    def load(self, configfile):
        """Override default values with settings from configfile"""
        cfg = ConfigParser()
        cfg.readfp(open(configfile))

        # Build collections
        try:
            for name in cfg.options("Collections"):
                value = cfg.get("Collections", name)
                # check if entry if formatted correctly
                # expects <typename>,<path>
                if "," not in value:
                    msg = invalid_collection%(configfile, value)
                    raise ConfigError(msg)

                basetype, path = [i.strip() for i in value.split(',')]

                # For the time being the config file supports only a
                # single directory per collection. However, the IsisCollection
                # constructor already accepts a list of directory paths where
                # to look for bases to include in the collection.
                # The limitation is just in the .ini and here
                self.COLLECTIONS.append((basetype, name, [path]))
        except (NoSectionError, NoOptionError):
            pass

        # Build Engine params

        # Define encodings
        self._safe_set('INPUT_ENCODING', cfg, 'Engine','INPUT_ENCODING')
        self._safe_set('OUTPUT_ENCODING', cfg, 'Engine','OUTPUT_ENCODING')
        self._safe_set('LANGUAGE', cfg, 'Engine','LANGUAGE')
        self._safe_set('FDT_LINE', cfg, 'Engine','FDT_LINE')

        # Temporary directory for parser files
        self._safe_set('PARSER_AUXFILES_DIR', cfg, 'Engine','PARSER_AUXFILES_DIR')

        # Path where to generate log files
        self._safe_set('LOG_PATH', cfg, 'Engine','LOG_PATH')

        # Search path
        self._safe_set('SEARCH_PATH', cfg, 'Engine', 'SEARCH_PATH')

        # Define log level
        try:
            self.LOG_LEVEL = logging.__dict__.get(cfg.get('Engine', 'LOG_LEVEL'),
                                              logging.DEBUG)
        except (NoOptionError,NoSectionError), ex:
            self.LOG_LEVEL = logging.DEBUG

        # Enable formatting language debugging
        self._safe_set('YACC_DEBUG', cfg, 'Engine', 'YACC_DEBUG', self.validate_bool)
        self._safe_set('SILENT_EXCEPTIONS', cfg, 'Engine', 'SILENT_EXCEPTIONS', self.validate_bool)

        # Define networking ports
        self._safe_set('HTTP_PORT', cfg, 'Gateway', 'HTTP_PORT', self.validate_int)
        self._safe_set('SSH_PORT', cfg, 'Gateway', 'SSH_PORT', self.validate_int)
        self._safe_set('USERNAME', cfg, 'Gateway', 'USERNAME')
        self._safe_set('PASSWORD', cfg, 'Gateway', 'PASSWORD')

        # Build IsisDB params
        self._safe_set('SUBFIELD_DELIMITER', cfg,'IsisDB', 'SUBFIELD_DELIMITER')
        self._safe_set('BYTE_ORDER', cfg,'IsisDB', 'BYTE_ORDER')
        self._safe_set('XRF_BLOCK', cfg, 'IsisDB', 'XRF_BLOCK', self.validate_int)
        self._safe_set('XRF_OFFSET', cfg, 'IsisDB', 'XRF_OFFSET', self.validate_int)
        self._safe_set('XRF_NEW_FLAG', cfg, 'IsisDB', 'XRF_NEW_FLAG', self.validate_int)
        self._safe_set('XRF_MODIFIED_FLAG', cfg, 'IsisDB', 'XRF_MODIFIED_FLAG', self.validate_int)
        self._safe_set('BLOCK_SIZE', cfg, 'IsisDB', 'BLOCK_SIZE', self.validate_int)
        self._safe_set('POINTER_SIZE', cfg, 'IsisDB', 'POINTER_SIZE', self.validate_int)
        self._safe_set('BLOCK_ALIGN', cfg, 'IsisDB', 'BLOCK_ALIGN', self.validate_bool)
        self._safe_set('CTRL_MASK', cfg,'IsisDB', 'CTRL_MASK', self.validate_mask)
        self._safe_set('CTRL_MASK_SIZE', cfg, 'IsisDB', 'CTRL_MASK_SIZE', self.validate_int)
        self._safe_set('CTRL_SIZE', cfg, 'IsisDB', 'CTRL_SIZE', self.validate_int)
        self._safe_set('LEADER_MASK', cfg, 'IsisDB', 'LEADER_MASK', self.validate_mask)
        self._safe_set('LEADER_SIZE', cfg, 'IsisDB', 'LEADER_SIZE', self.validate_int)
        self._safe_set('LEADER_MASK_XL', cfg, 'IsisDB', 'LEADER_MASK_XL')
        self._safe_set('LEADER_SIZE_XL', cfg, 'IsisDB', 'LEADER_SIZE_XL', self.validate_int)
        self._safe_set('LEADER_XL', cfg, 'IsisDB', 'LEADER_XL', self.validate_bool)
        self._safe_set('DIR_MASK', cfg, 'IsisDB', 'DIR_MASK')
        self._safe_set('DIR_SIZE', cfg, 'IsisDB', 'DIR_SIZE', self.validate_int)
        self._recalculate_dependent_params()

    def __str__(self):
        """Dump configuration  as string"""
        lines = []
        for name in sorted(dir(self)):
            if name.startswith("__"):
                continue # ignore hidden attributes
            value = getattr(self, name)
            if callable(value):
                continue # ignore callable attributes
            lines.append(u"%20s: %s"%(name,value))
        return "\n".join(lines)

    def __unicode__(self):
        """Dump configuration as unicode string"""
        return unicode(str(self))


# Global config instance
config = Config()

def safe_encoding(mst):
    """Given a mst reference, return its OUTPUT_ENCODING
    or the value present in the global configuration object
    """
    try:
        return mst.config.OUTPUT_ENCODING
    except AttributeError:
        return config.OUTPUT_ENCODING

