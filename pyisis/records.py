# -*- coding: utf-8 -*-
"""
Definition of data records that occur in ISIS Files (.mst and .xrf).
"""

__updated__ = "$Id$"
__created__ = "2007-01-25"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

from weakref import ref
from struct import unpack, pack, calcsize
#from logging import debug
import pyisis.engine
from pyisis.config import safe_encoding
from pyisis.fields import MasterField, MasterContainerField
import pyisis.session
from itertools import izip, imap, groupby
from operator import getslice
from os import path

# Constants
ACTIVE  = 0
LOGICALLY_DELETED = 1
PHYSICALLY_DELETED = 2

class Dummy(object):
    "Used just for performance tests."
    def __init__(self, tag, data):
        self.tag = tag
        self.data = data

class Corrupted(Exception):
    """Raised when anything goes wrong while parsing the master file."""
    pass

class XrfRecord(object):
    """Represents each entry in a  cross-reference file (.xrf)
    """
    __slots__ = ('extra_large','block', 'offset', 'status',
                 'new_flag', 'modified_flag', 'mfn', 'config')

    @staticmethod
    def _get_record_offset(config, mfn):
        """Calculate the block number and offset position
        within block and absolute offset of a given xrf record
        that should point to the given mfn record.
        Returns:
           block_idx, relative_offset, absolute_offset
        """
        BLOCK_SIZE  = config.BLOCK_SIZE
        # Each pointer in xref have 4 bytes (int 32-bits)
        # And the first byte in the block is the block number.
        POINTER_PER_BLOCK = config.POINTER_PER_BLOCK
        block_idx, offset = divmod(mfn-1, POINTER_PER_BLOCK)

        # Adjust offset, compensanting the unused first slot (+1)
        # and convert it to bytes (*4)
        relative_offset = (offset + 1) * config.POINTER_SIZE
        absolute_offset = block_idx*BLOCK_SIZE + relative_offset

        block_idx +=1 # first block is 1 not 0
        return block_idx, relative_offset, absolute_offset

    @staticmethod
    def decode_status(block, offset):
        """Convert block+offset values in status string"""
        status = 'active'
        if block<0 and offset>0:
            # abs(self.block)+ self.offset -> record
            status = 'logically deleted'
        elif block==-1 and offset==0:
            status = 'physically deleted'
        elif block==0 and offset==0:
            status = 'inexistent'
        elif block==0:
            # This is an undocumented feature.
            # CHECK with specialists what it means !
            status = 'invalid'
        return status


    def __init__(self, mfn, value, extra_large, config=None):
        """Internal function to decode xrf values to MFN record
        """
        # set configuration settings
        if config is None:
            self.config = pyisis.engine.Engine.config
        else:
            self.config = config

        self.mfn = mfn
        self.extra_large = extra_large
        self.block, self.offset, self.new_flag, self.modified_flag = self.decode(value, extra_large)
        self.status = XrfRecord.decode_status(self.block, self.offset)

    def update(self, abs_mst_offset, status, new=False, modified=False):
        """Set values in XrfRecord."""
        if status=='active':
            self.block, self.offset =  divmod(abs_mst_offset, self.config.BLOCK_SIZE)
            self.block +=1 # block numbers start from 1
        elif status in ('logically deleted', 'physically deleted', 'invalid', 'inexistent'):
            raise ValueError('Invalid status %s'%status)

        self.status = status
        self.new_flag = new
        self.modified_flag = modified

    def decode(self, value, extra_large):
        """Convert binary value into distinct variables and flags"""
        config = self.config
        if extra_large:
            block  = value / (config.XRF_BLOCK >> extra_large)
            offset = (abs(value) & (config.XRF_OFFSET >> extra_large)) << extra_large
            new_flag = (abs(value) & (config.XRF_NEW_FLAG >> extra_large)) << extra_large
            modified_flag = (abs(value) & (config.XRF_MODIFIED_FLAG >> extra_large)) << extra_large
        else:
            block  = abs(value) / config.XRF_BLOCK
            offset = (abs(value) & (config.XRF_OFFSET >> extra_large)) << extra_large
            #offset = abs(value & config.XRF_OFFSET)
            new_flag = abs(value & config.XRF_NEW_FLAG) == config.XRF_NEW_FLAG
            modified_flag = abs(value & config.XRF_MODIFIED_FLAG) == config.XRF_MODIFIED_FLAG

        return block, offset, new_flag, modified_flag


    def encode(self):
        """Convert distinct variables and flags into value"""
        extra_large = self.extra_large

        if self.status=='inexistent':
            return 0
        if self.status=='physically deleted':
            return (-1 * 2048) | 0

        if extra_large:
            xrmfp = (self.offset & (0x000001FF >> extra_large)) << extra_large
        else:
            xrmfp = self.offset & 0x000001FF

        if self.new_flag:
            xrmfp += 1024
        if self.modified_flag:
            xrmfp += 512

        if extra_large:
            value = (self.block * (2048 >> extra_large))  | xrmfp
        else:
            value = (self.block * 2048) | xrmfp

        return value

    def _write(self, xrf_fd):
        """Write the record to the given xrf file descriptor (xrf_fd)
        in the correct position.
        """
        # discard xrf_block and xrf_relative_offset
        _, _, abs_offset = XrfRecord._get_record_offset(self.config, self.mfn)
        xrf_fd.seek(abs_offset)
        if self.status == 'logically deleted':
            status = ~self.encode() + 1
            record = pack(self.config.BYTE_ORDER_PRFIX + "i", status*256>>8)
        else:
            status = self.encode()
            record = pack(self.config.BYTE_ORDER_PRFIX + "i", status)
        xrf_fd.write(record)
        xrf_fd.flush()

    def __unicode__(self):
        return u"<XrfRecord mfn:%d block:%d offset:%d status:%s>"%\
               (self.mfn, self.block, self.offset, self.status)



class MasterRecord(dict):
    """Encapsulates a single record from the Master File.
    This is a  dict of MasterFields indexed by tags.
    If a repeatable field is found, all entries are wrapped
    in a MasterContainerField list wrapper.
    """
    status2str = {0: "active",
                  1: "logically deleted",
                  2: "physically deleted"
                  }

    # reverse dictionary to translate string to value
    str2status = dict([(i,j) for j,i in status2str.items()])

    def __init__(self, mfn=0, status=0, config=None, fields=None):
        # initially records have no MasterFile set
        self.mst = None

        #To preserve key order
        self.last_insert_key = []
        # set configuration settings
        if config is None:
            self.config = pyisis.engine.Engine.config
        else:
            self.config = config

        # leader header
        self.mfn = mfn     # master file number (record number)
        # If mfn is None, the actual mfn number will be assigned
        # only when saving the record.

        self.mfbwb = 0  # backward pointer - block
        self.mfbwp = 0  # backward pointer - offset

        # base  is computed on demand, and only
        # when a reference to the MasterFile is available
        # self.nvf -> number of fields in record
        # self.mfrl -> packed record length
        # these fields are calculated on demand

        # set status as int value applying conversions if necessary
        if type(status)==int:
            self.status = status
        elif type(status)==str:
            self.status = MasterRecord.str2status[status]

        if fields is not None:
            self.update(fields)

    def __setattr__(self, name, value):
        """Hook that intercepts data insertion and updates automatically
        accounting fields.
        Same as __setitem__, but invoked for setting fields as:
        rec.v90 = "some value"
        """
        # Attributes starting with v or V are forbidden.
        if name.lower().startswith("v"):
            name = name[1:]
            nfield = self.__setitem__(name, value)
            return nfield
        else:
            dict.__setattr__(self, name, value)

    def __getattr__(self, name):
        """Dynamically calculate self.nvf.
        Handle fields  as automatically generated attributes.
        Example: self.v70 or self.V70 will turn into self["70"]
        """
        if name=="nvf":
            return sum([1 for f in self.get_fields()])
        elif name.lower().startswith("v"):
            name = name[1:]

        return self.__getitem__(name)

    def __iter__(self):
        """Iterator Protocol"""
        return self.get_fields()

    def get_fields(self):
        """Due to the existence of repeatable fields, it is better
        to use this function instead of self.values().
        This function returns a generator of a single flat sequence
        with all directory fields, including repeated ones.
        """
        for field in self.values():
            if type(field) is MasterContainerField:
                for repeated in field:
                    yield repeated
            else:
                yield field

    def get_tags(self):
        """Retrieve all field tags for this record. Repeatable
        fields will show as a single tag.
        """
        return self.keys()

    def __setitem__(self, key, value):
        """Hook that intercepts data insertion and updates automatically
        accounting fields.
        """
        encoding = safe_encoding(self.mst)
        try:
            # try to convert key into int if possible
            key = int(key)
        except ValueError:
            pass

        self.last_insert_key.append(key)

        if type(value) in (MasterField, MasterContainerField):
            # adjust encoding in fields
            value.encoding = encoding
            dict.__setitem__(self, key, value)
        elif type(value) in (list, tuple):
            # Build an appropriate MasterContainerField
            dict.__setitem__(self, key, MasterContainerField(key, value,
                                                             config=self.config))
        elif type(value) in (str, unicode):
            # received a simple string
            # delegate the operation to standard dict implementation
            # but create a MasterField instance wrapping the value.
            dict.__setitem__(self, key, MasterField(key, value, config=self.config))
        else:
            raise ValueError("Invalid type %s for field %s"%(type(value), key))



    def __getitem__(self, key):
        """Access fields in dictionary-like fashion, where
        (int) field number is key.
        For example: mf[1][26] -> record 1 field 26
        key is converted to int.
        """
        try:
            key = int(key)
        except ValueError:
            if key in self.mst.fdt_field_names:
                key = int(self.mst.fdt[key]['tag'])
        return dict.__getitem__(self, key)

    def __len__(self):
        return self.nvf

    def __str__(self):
        if self.mfn is None:
            mfn = 0
        else:
            mfn = self.mfn
        fields = "\n".join(["%d:%s"%(f.tag, f) for f in self.get_fields()])
        return "MFN: %d\n%s"%(mfn, fields)

    def __repr__(self):
        fields = ', '.join(["%d:%r"%(f.tag, f) for f in self.values()])
        return """MasterRecord(mfn=%d, status=%s, fields={%s})"""%\
               (self.mfn, self.status, fields)

    def __unicode__(self):
        if self.mfn is None:
            mfn = 0
        else:
            mfn = self.mfn
        _fields = self.get_fields()
        if _fields:
            # only show fields if there is something to be shown
            fields = u'\n'.join(u"%d: %s"%(field.tag, field.data) for field in _fields)
        else:
            fields = u''
        return u'mfn=%d (%s)\n'%(mfn,
                                 MasterRecord.status2str[self.status]) + fields


    def update(self, from_obj):
        """Loop through values in from_obj and wrap them in MasterFields
        if necessary (when from_obj is a standard dict).
        """
        for key, value in from_obj.items():
            # this will trigger __setitem__ hook
            self[key]=value



    def save(self, mst, encoding='', reset_flags=False):
        """Write the record to the disk in its corresponding MasterFile."""
        newFlag = False
        modifiedFlag = False

        # assume comfiguration of destination file
        self.config = mst.config

        base = mst.LEADER_SIZE + (self.config.DIR_SIZE * self.nvf)

        if not encoding:
            encoding = mst.config.INPUT_ENCODING

        #fd = mst.mst_fd
        # Grab a MFN if None is defined
        if self.mfn == 0:
            self.mfn = mst.nxtmfn

        # Find the position where to place the record,
        # and if there is some record already there
        status, pos = mst._get_record_offset(self.mfn)

        if status in ('inexistent', 'physically deleted'):
            # New record !
            newFlag = True
            self.mfbwb = 0
            self.mfbwp = 0

            # update control record in masterfile and make it persistent
            mst.nxtmfn += 1

        elif status in ('logically deleted', 'active'):
            # Update !
            # There is already a record at the position
            #previous_rec = mst[self.mfn]
            # adjust backward pointer (block, offset)
            try:
                xrfstat = self.mst.xrf[self.mfn]
            except:
                xrfstat = mst.xrf[self.mfn]
            if reset_flags:
                newFlag = False
                modifiedFlag = False
                self.mfbwb = 0
                self.mfbwp = 0

            elif xrfstat.new_flag:
                newFlag = True
                modifiedFlag = False
                self.mfbwb = 0
                self.mfbwp = 0
            else:
                newFlag = False
                modifiedFlag = True
                if not self.mfbwb:
                    self.mfbwb, self.mfbwp = divmod(pos, self.config.BLOCK_SIZE)
                    self.mfbwb += 1 # block numbers begin in 1, adjust it

            # Adjust status of MasterRecord in disk to logically deleted
            if status=='active':
                leader_offset_status = calcsize(mst.LEADER_MASK[:-1])
                mst.mst_fd.seek(pos+leader_offset_status)
                try:
                    mst.mst_fd.write(pack(self.config.BYTE_ORDER_PRFIX+mst.LEADER_MASK[-1],
                                          LOGICALLY_DELETED))
                except IOError:
                    raise Exception(_('Read-only database'))

            if not reset_flags:
                # redefine pos to point to last available position in file
                pos = mst.nxtmfb*self.config.BLOCK_SIZE + mst.nxtmfp


        elif status=='invalid':
            raise Exception(_("Tried to save record flagged as invalid."))

        fields = list(self.get_fields())

        # calculate mfrl according to encoding of mst
        dir_size = (len(fields) * self.config.DIR_SIZE)
        mfrl = mst.LEADER_SIZE + dir_size + sum([len(f.data.encode(encoding)) for f in fields])

        # Write record to the disk
        STATUS_ACTIVE = 0
        leader = pack(mst.LEADER_MASK,
                      self.mfn, mfrl, 1,
                      self.mfbwb, self.mfbwp,
                      base, self.nvf,
                      STATUS_ACTIVE)

        # Write directory
        dir_entries = []
        relative_offset = 0
        for field in fields:
            tag = field.tag
            data = field.data.encode(encoding)
            length = len(data)
            dir_entries.append(pack(self.config.DIR_MASK,
                                    int(tag),
                                    relative_offset,
                                    length))
            relative_offset += length

        raw_data = "".join([field.data for field in fields])
        record = leader + "".join(dir_entries) + raw_data.encode(encoding)

        try:
            actual_mst_size = path.getsize(path.join(mst.basepath,'%s.mst' % mst.name))
        except:
            actual_mst_size = 0

        test_pos = pos % self.config.BLOCK_SIZE

        #see MSNVSPLT in cisis.h
        if self.config.DIR_MASK == 'iii': #FFI
            end_block = 493
        else:
            end_block = 497
        if test_pos >= end_block and test_pos <= 511:
            pos = self.config.BLOCK_SIZE * ((pos/self.config.BLOCK_SIZE) + 1)

        if len(record) + pos >= actual_mst_size:
            mst.mst_fd.seek(actual_mst_size)

            try:
                mst.mst_fd.write(pack(self.config.BYTE_ORDER_PRFIX + "B"*self.config.BLOCK_SIZE,
                                       *([0]*self.config.BLOCK_SIZE)))
            except IOError:
                raise Exception(_('Read-only database'))

        # Write record to the disk
        mst.mst_fd.seek(pos)
        try:
            mst.mst_fd.write(record)
        except IOError:
            raise Exception(_('Read-only database'))

        # Recalculate control header params
        blocks, offset = divmod(mst.mst_fd.tell(), self.config.BLOCK_SIZE)
        mst.nxtmfb = blocks + 1
        if not offset:
            offset = 1
        mst.nxtmfp = offset
        mst._write_control()
        mst.mst_fd.flush()

        # update current xrf record
        xrf_rec = mst.xrf[self.mfn]
        xrf_rec.update(pos, 'active', new=newFlag, modified=modifiedFlag)
        xrf_rec._write(mst.xrf._fd)


    def _read_leader(self, mst):
        """This method reads the input stream extracting the
        appropriate fields from the leader section.
        @mst - MasterFile from where to retrieve the record
        return (base, nvf, mfrl) values read.
        """
        fd = mst.mst_fd
        # extract fixed-length leader header
        # nvf and mfrl are used only locally, the self.nvf will be set
        # by the __setitem__ method
        dados = fd.read(mst.LEADER_SIZE)
        self.mfn, mfrl, flag, self.mfbwb, self.mfbwp, base, nvf, \
            self.status = unpack(mst.LEADER_MASK, dados )

        expected_base = mst.LEADER_SIZE + self.config.DIR_SIZE*nvf
        assert (base != 0) and\
               (base == expected_base), "base==%d != calculated==%d"%\
               (base, expected_base)
        return base, nvf, mfrl

    def format(self, expr):
        "Wraps formatting function as record instance menthod."
        return pyisis.session.format(expr, self)
    pft = format

    def read(self, mst):
        """ Parse the contents of the master file, filling the associated
        data structures. File descriptor (fd) must be at the correct position
        (start of a new record). The parameter mst is a reference to the
        MasterFile instance.
        """
        def load_data():
            fd = mst.mst_fd
            base, nvf, mfrl = self._read_leader(mst)
            SKIP_SIZE = mst.LEADER_SIZE
            dir_plus_data = fd.read(mfrl-SKIP_SIZE)

            if base==0:
                return

            # Generate a single mask for the whole directory
            whole_dir_mask = self.config.BYTE_ORDER_PRFIX + \
                             (nvf * self.config.DIR_MASK.replace(self.config.BYTE_ORDER_PRFIX,""))
            whole_dir_size = nvf * self.config.DIR_SIZE
            # and read it all at once (one single read)
            dir_data = dir_plus_data[:whole_dir_size]
            raw_data = dir_plus_data[whole_dir_size:]

            # assemble field entries
            whole_dir = unpack(whole_dir_mask, dir_data)

            return base, nvf, mfrl, whole_dir, raw_data

        base, nvf, mfrl, whole_dir, raw_data = load_data()

        input_encoding = mst.config.INPUT_ENCODING

#        def prepare_tagval_list_slow():
#            pairs = []
#            sz = len(whole_dir)+1
#            triplet_list = imap(lambda x: getslice(whole_dir,*x),
#                               izip(range(0,sz,3), range(3,sz,3)))
#            pairs = [(tag, raw_data[pos:pos+length].decode(input_encoding)) \
#                     for tag, pos, length in triplet_list]
#            return pairs

        def prepare_tagval_list():
            pairs = []
            for entry in range(0, len(whole_dir), 3):
                tag, pos, length = whole_dir[entry:entry+3]
                value = raw_data[pos:pos+length]
                value = value.decode(input_encoding)
                pairs.append((tag & 0xffff , value))
            return pairs

        pairs = prepare_tagval_list()


        def assemble_record(pairs):
            encoding = safe_encoding(self.mst)
            for key, values in groupby(pairs, lambda x: getslice(x, 0, 1)):
                key = key[0]
                fields = [MasterField(tag, data, config=self.config) \
                          for tag,data in  values]
                if len(fields)==1:
                    # single values are not wrapped in lists
                    new_field = fields[0]
                else:
                    new_field = MasterContainerField(key, sequence=fields,
                                                     config=self.config)
                dict.__setitem__(self, key, new_field)
        assemble_record(pairs)

    def to_xml(self):
        template = '<record mfn="%d" status="%s">%s</record>'
        fields = []
        for k,v in self.items():
            fields.append(v.to_xml())
        return template % (self.mfn, MasterRecord.status2str[self.status], "".join(fields))



# Old Assemble code (slow)
#--------------------------
#        for entry in range(0, len(whole_dir), 3):
#            tag, pos, length = whole_dir[entry:entry+3]
#            value = raw_data[pos:pos+length].decode(input_encoding)
#            try:
#                # handling repeatable fields
#                # replace MasterField for MasterContainerField (list)
#                old_field = self[tag]
#                if type(old_field) is MasterContainerField:
#                    # container field (old_field) already set
#                    new_field = MasterField(tag, value)
#                    # add new field to container
#                    old_field.append(new_field)
#                else:
#                    # first collision, replace existing field for container
#                    container = MasterContainerField(tag)
#                    dict.__setitem__(self, tag, container)
#
#                    # add pre-existing field to container
#                    container.append(old_field)
#                    new_field = MasterField(tag, value)
#                    container.append(new_field)
#            except KeyError:
#                # first entry, create field
#                new_field = MasterField(tag, value)
#                dict.__setitem__(self, tag, new_field)


# records always end with even numbers
# so decide to skip a byte (or not)
# This was necessary while rebuilding the database from scratch
# without the help of xrf file
# if fd.tell()%2!=0:
#    fd.read(1)
#    debug("Adjust even alignment")

