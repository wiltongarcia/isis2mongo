"""
Definition of data files that belong to ISIS CDS/ISIS 1989
"""

__updated__ = "2009-07-30"
__created__ = "2007-01-25"
__author__  = "Rodrigo Senra <rsenra@acm.org>"

from os import fstat, SEEK_END, remove
from stat import ST_SIZE
from os.path import dirname, basename, exists, join, splitext
from struct import unpack, pack, calcsize
from glob import glob
from logging import debug, info, warning, error
from itertools import imap
from unicodedata import normalize, category
import re

import pyisis.session
import pyisis.config
import pyisis.engine
from pyisis.records import MasterRecord, XrfRecord, ACTIVE, LOGICALLY_DELETED

#from ZODB import FileStorage, DB
#from persistent.list import PersistentList
#from BTrees.OOBTree import OOBTree
#import transaction
#import cPickle



#re to techniques 1001-1008
find_IT1000 = re.compile(r"^(\d+)\s*(100\d+)[\s\,]*(\'.\')[\s\,]*(.*)[\s\,]*(\3)[\s\,]*(.*)")
find_field  = re.compile("^.*([vV]\d*).*$")
find_prefix = re.compile("^[\"|\'].([?:;<>!@&+$=%\-.,\w*\s*]+).[\"|\']")

#Inverted file cache
_cache = {}


class Collection(object):
    """Collection has a name (used in URIs) and encapsulates
    a list of paths where databases can be found.

    @type name: string
    @param name: identifier used in URLs

    @type path_list: list of strings
    @param path_list: list of absolute paths where to find files
                      to include in this collection

    Instances of this class will have the atttribute "database",
  which is a dict-like structure holding the names (keys) and objects (values)
  for all identified databases in the give path_list.
    """
    def __init__(self, name, path_list):
        self.name = name
        self.path_list = path_list
        self.databases = {}


class IsisCollection(Collection):
    """Collection that holds a logically related group
    of Isis database files.
    """
    def __init__(self, name, path_list, config=None):
        Collection.__init__(self, name, path_list)
        for path in path_list:
            path = path.strip()
            fullpath = join(path, "*.mst")
            for f in glob(fullpath):
                fname = basename(f)
                try:
                    #debug(_("Opening file %s for collection %s") % (fname, name))
                    mf = MasterFile(f, collection_name=name, config=config)
                    self.databases[fname] = mf
                    # Shortcut to access databases without using operator[]
                    setattr(self, fname[:-4], mf)
                except IOError, ex:
                    warning(_("Failed to open %s: %s") % (name, ex))

    def __unicode__(self):
        return _(u"Collection %s with databases: %s") % (self.name,
                 u", ".join(self.databases.keys()))

    def __str__(self):
        return _("Databases: %s") % (", ".join([splitext(fname)[0] for fname in self.databases.keys()]))


    def __getitem__(self, name):
        """Delegate to inner database attribute.
        This allows access to MasterFiles inner instances using
        dictionary like syntax.
        """
        names = self.databases.keys()
        for dbname in names:
            if name==dbname or name==dbname[:-4]:
                try:
                    return self.databases[dbname]
                except KeyError:
                    # try it without the extension
                    # using the shortcut
                    return getattr(self, name)

        raise KeyError(_("%s is not an attribute of the collection %s")\
                       %(name, self.name))


class XrfCache(object):
    """Cache of Xrf records supporting a dictionary-like interface.
    Records from the .xrf file are read on demand and them cached.
    """

    def __init__(self, basepath, name, extra_large, config=None, readonly=False):
        """prepare self.xrf_fd file, the whole .xrf file will not
        be loaded into memory, but read on demand.
        """
        filename = join(basepath, name+'.xrf')

        # set configuration settings
        if config is None:
            self.config = pyisis.engine.Engine.config
        else:
            self.config = config

        # Dictionary of XRef records
        # Initialize xrf list with invalid record
        # because MFN's begin from 1
        self._xrf = {0: XrfRecord(0, 0, 0, self.config)}

        if readonly:
            mode = "rb"
        else:
            mode = "r+b"

        self.extra_large = extra_large
        try:
            self._fd = open(filename, mode)
            if fstat(self._fd.fileno())[ST_SIZE]==0:
                # file exists but it is empty
                # take action to create at least one block
                raise IOError(_('Empty %s file') % filename)
        except IOError:
            # create a default empty .xrf file
            self._fd = open(filename, 'w+b')
            self._add_empty_block()

    def _add_empty_block(self):
        """Prior to masterfile records creation there should be the
        respective empty entries in the .xrf file. This routine adds
        a new empty XRF block to .xrf .
        """
        BLOCK_SIZE = (self.config.POINTER_PER_BLOCK+1)*4
        # Position in the end of the file
        self._fd.seek(0, SEEK_END)
        # write at least one block with inexistent records entries
        fd_pos = self._fd.tell()
        if not fd_pos:
            self._fd.write(pack(self.config.BYTE_ORDER_PRFIX + "i",
                                self.config.LAST_XRF_BLOCK)) # block ID
        else:
            self._fd.write(pack(self.config.BYTE_ORDER_PRFIX + "i",
                                ((fd_pos/BLOCK_SIZE) + 1) * -1 ))

        self._fd.write(pack(self.config.BYTE_ORDER_PRFIX + "i"*self.config.POINTER_PER_BLOCK,
                            *([0]*self.config.POINTER_PER_BLOCK)))

        # Fix previous block number
        # if this is not the first block added.
        if self._fd.tell()>=(BLOCK_SIZE*2):
            # go to block before last
            self._fd.seek(-BLOCK_SIZE*2, SEEK_END)
            # calculate block number
            block_number = (self._fd.tell()/BLOCK_SIZE) +1
            self._fd.write(pack(self.config.BYTE_ORDER_PRFIX + "i", block_number))
        try:
            self._fd.flush()
        except IOError:
          pass # Ok if read-only

    def __getitem__(self, mfn):
        """Try to find the corresponding xrf record in the
        self._xrf dictionary cache, otherwise load it from disk
        and put it inside the cache.
        """
        try:
            return self._xrf[mfn]
        except KeyError:
            self._read_block(mfn)
            return self._xrf[mfn]

    def _read_block(self, mfn):
        """Read the appropriate xrf records from the corresponding file
        and add them to the cache, using the block where mfn is in.
        """
        BLOCK_SIZE = self.config.BLOCK_SIZE
        POINTER_PER_BLOCK = self.config.POINTER_PER_BLOCK
        fd = self._fd

        block_idx, relative_offset, absolute_offset = \
        XrfRecord._get_record_offset(self.config, mfn)

        for i in (1, 2):
            # This is a disguised go to!
            # Loop to add blocks to .xrf if necessary
            # This should not loop over 2 times
            # first pass if block is found
            # second pass if a new block was needed
            fd.seek((block_idx-1) * BLOCK_SIZE)
            raw_block = fd.read(BLOCK_SIZE)
            if not raw_block:
                # Add a new block on demand
                self._add_empty_block()
            else:
                break

        block = unpack(self.config.BYTE_ORDER_PRFIX + "i"*(BLOCK_SIZE/4),
                       raw_block)
        first_mfn_in_block = POINTER_PER_BLOCK * (block_idx-1) + 1
        mfns_in_block =  range(first_mfn_in_block,
                               first_mfn_in_block + POINTER_PER_BLOCK)

        # loop through pointers but skip first (block ID)
        for mfn, value in zip(mfns_in_block, block[1:]):
            self._xrf[mfn] = XrfRecord(mfn, value, self.extra_large,
                                       config=self.config)

    def __iter__(self):
        """Build an iterator instance (in this particular case a generator)
        to loop through all entries in the underlying xrf file.
        """
        fd = self._fd
        size = fstat(fd.fileno())[ST_SIZE] # file size
        num_blocks, rest = divmod(size, self.config.BLOCK_SIZE)
        for rec in range(num_blocks*self.config.POINTER_PER_BLOCK):
            yield self.__getitem__(rec)


class PostIndex(object):
    """Post information"""
    def __init__(self, mfn, extraction_id, occ, offset, technique, fieldno):
        self.mfn           = mfn
        self.extraction_id = extraction_id
        self.occ           = occ
        self.offset        = offset
        self.technique     = technique
        self.fieldno       = fieldno

    def __repr__(self):
        return """mfn:%s
    extraction_id:%s
    occ:%s
    offset:%s
    technique:%s
    field:%s"""%(self.mfn,self.extraction_id,self.occ,self.offset,self.technique,self.fieldno)


class MasterFile(object):
    """Encapsulates a traditional CSD/ISIS Master File.
    Holds the control information for the file.

    >>> from os.path import join
    >>> mf = MasterFile(join("sample","cds.mst"))
    >>> mf.name
    'cds'
    >>> mf.mftype
    0
    >>> mf.nxtmfn
    151
    >>> len(mf)
    150
    """
    def __init__(self, filepath,
                 mftype=0, collection_name='', config=None):
        # A database knows to which collection
        # it was created from. Useful for cross-db REF() expressions
        if splitext(basename(filepath))[1] == '':
            filepath += '.mst'
        self.collection_name = collection_name

        # set configuration settings
        if config is None:
            self.config = pyisis.engine.Engine.config
        else:
            self.config = config

        # Complete path to .mst
        self.filepath = filepath

        # Name of the master file without its extension
        #self.name = basename(filepath)[:-4]
        self.name, fextension = splitext(basename(filepath))
        # Path with the filename
        self.basepath = dirname(filepath)

        # Try to override configuration
        # if a <databasename>.ini is found in the same dir
        # as the master file
        # e.g: For cds.mst look for cds.ini
        cfgpath = join(self.basepath, self.name+'.ini')
        if exists(cfgpath):
            replica = pyisis.config.Config()
            replica.clone(self.config)
            replica.load(cfgpath)
            self.config = replica

        # Try to load .FDT
        self.fdt = {}
        self.fdt_field_names = []
        self.fdt_field_tags = []
        fdtpath = join(self.basepath, self.name+'.fdt')
        if exists(fdtpath):
            fdt_lines = [i.strip() for i in open(fdtpath).readlines()]
            for line in fdt_lines:
                m = self.config.FDT_LINE.match(line)
                if m:
                    d = m.groupdict()
                    self.fdt_field_tags.append(int(d['tag']))
                    self.fdt_field_names.append(d['name'])
                    self.fdt[d['tag']] = d
                    self.fdt[int(d['tag'])] = d
                    self.fdt[d['name']] = d

        # assume that bases are read-write by default
        self.readonly = False

        # file descriptor
        try:
            try:
                self.mst_fd = open(self.filepath, "r+b")
            except IOError, ex:
                if ex.strerror=='Permission denied':
                    # file is in read-only mode
                    self.mst_fd = open(self.filepath, "rb")
                    self.readonly = True
                else:
                    raise
            new_file = False
        except IOError, ex:
            # file does not exist -> create a new master file
            self.mst_fd = open(self.filepath, "w+b")
            new_file = True
            # file is stored as physical blocks of BLOCK_SIZE bytes
            self.mst_fd.write(pack(self.config.BYTE_ORDER_PRFIX + "B"*self.config.BLOCK_SIZE,
                                   *([0]*self.config.BLOCK_SIZE)))

        # Prepare Control fields
        self.ctlmfn = 0  # always 0
        self.nxtmfn = 1  # MFN to assign for next record
        self.nxtmfb = 1  # last block allocated (each 512 bytes)
        # offset available pos in last block
        self.nxtmfp = 64 #self.config.CTRL_SIZE
        # 0 == data base, 1 == sys msg file,  >1 == extra_large
        self.mftype = mftype
        self.reccnt = 0
        self.mfcxx1 = 0
        self.mfcxx2 = 0
        self.mfcxx3 = 0

        if new_file:
            self._write_control()
        else:
            self._read_control()

        if self.mftype>1:
            self.extra_large = self.mftype
        else:
            self.extra_large = 0

        # indicate that master file is extra-large by default
        # int value is used in XRF masking
        if self.config.LEADER_XL:
            self._leader_xl()

        else:
            self._leader_small()

        self.xrf = XrfCache(self.basepath,
                            self.name,
                            self.extra_large,
                            self.config,
                            self.readonly
                            )
        try:
            self.mst_fd.flush()
        except IOError:
          pass # Ok if file readonly

    def format(self, record, expr):
       """Apply formatting expression to the given record"""
       if type(record) is int: # given just mfn
           record = self[record]
       return pyisis.session.format(self, record, expr)
    # Create alias function .pft() == .format()
    pft = format

    def _write_control(self):
        """Persist the instance attribute values that correspond
        to the control header field in the file.
        """
        control = pack(self.config.CTRL_MASK,
                       self.ctlmfn, self.nxtmfn, self.nxtmfb,
                       self.nxtmfp, 0, self.mftype,
                       self.reccnt, self.mfcxx1,
                       self.mfcxx2, self.mfcxx3)
        # position in the beginning
        self.mst_fd.seek(0)
        self.mst_fd.write(control)
        # write padding
        pad_size = self.config.CTRL_SIZE - self.config.CTRL_MASK_SIZE
        pad_mask = self.config.BYTE_ORDER_PRFIX + "B"*pad_size
        padding = [0]*pad_size
        self.mst_fd.write(pack(pad_mask, *padding))

    def _read_control(self):
        """This method reads the input stream extracting the
        appropriate fields from the control section
        """
        fd = self.mst_fd
        self.ctlmfn, self.nxtmfn, self.nxtmfb, self.nxtmfp, _, self.mftype, \
        self.reccnt, self.mfcxx1, self.mfcxx2, self.mfcxx3 = \
        unpack(self.config.CTRL_MASK, fd.read(self.config.CTRL_MASK_SIZE))

        # discard data, should be a bunch of zeros
        # I have no documentation about what is left in this data block
        padding = fd.read(self.config.CTRL_SIZE - self.config.CTRL_MASK_SIZE)

    def __unicode__(self):
        """Textual representation of MasterFile objects"""
        return _(u"%s (next mfn:%s, type:%s) in %s") %\
               (self.name, self.nxtmfn, self.mftype, self.filepath)

    def _leader_xl(self):
        """(Default) Used to switch to large leader file format """
        self.LEADER_MASK =  self.config.LEADER_MASK_XL
        self.LEADER_SIZE =  self.config.LEADER_SIZE_XL

    def _leader_small(self):
        """Used to switch to traditional leader file format """
        self.LEADER_MASK =  self.config.LEADER_MASK
        self.LEADER_SIZE =  self.config.LEADER_SIZE

    def commit(self):
        """Ensure that changes are written to the disk"""
        self.mst_fd.flush()
        self.xrf._fd.flush()

    def __del__(self):
        """Clean up resources before gc deallocates this instance"""
        try:
          self.mst_fd.flush()
        except IOError:
          pass # Ok if read-only

        self.mst_fd.close()

    def __iter__(self):
        """Iterator Protocol"""
        return imap(self.__getitem__, xrange(1, self.nxtmfn))
        #for mfn in range(1, self.nxtmfn):
        #    yield self.__getitem__(mfn)

    def __len__(self):
        """Number of active records in the master file,
        *excluding* deleted records. This will wake up all blocks
        from the .xrf file
        """
        # This is a cache, so we must guarantee that
        # every page is loaded
        size = sum((1 for i in self if not i.status))
        return size

    def _get_record_offset(self, mfn):
        """Given the mfn return the (status, offset) of
        the respective record in the masterfile.
        """
        block_power = self.config.BLOCK_POWER
        xrf_rec = self.xrf[mfn]
        status = xrf_rec.status
        if status == 'active':
            block = xrf_rec.block
        elif status == 'logically deleted':
            block = abs(xrf_rec.block)
        elif status in ('inexistent', 'physically deleted'):
            pos = ((self.nxtmfb-1)<< block_power) + self.nxtmfp
            return (xrf_rec.status, pos)
        elif status == 'invalid':
            raise Exception(_('Not implemented xrf handling of invalid records.'))
        pos = ((block-1)<< block_power) + xrf_rec.offset
        return (status, pos)


    def __getitem__(self, mfn):
        """Uses _fetch to read a record from the master file
        given its MFN.
        """
        def fetch(mfn):
            """Routine that fetches a record given its mfn number.
            mfn is converted to int. If the record is either
            'invalid', 'inexistent' or 'physically deleted' then
            empty record with correct status value is returned.
            """
            mfn = int(mfn)
            status, pos = self._get_record_offset(mfn)
            if status in ('active',  'logically deleted'):
                self.mst_fd.seek(pos)
                rec = MasterRecord(mfn=mfn,
                                   status=status,
                                   config=self.config)
                rec.read(self)
                # set master
                rec.mst = self
                return rec
            if status in ('physically deleted'):
                rec = MasterRecord(mfn=mfn, status=status, config=self.config)
                rec.mst = self
                return rec
            if status in ('invalid', 'inexistent'):
                return None


        try:
            return fetch(mfn)
        except TypeError, ex:
            # Optimized out: if type(mfn)==slice:
            result_set = []
            if not mfn.start:
                start = 1
            else:
                start = mfn.start

            if not mfn.stop:
                stop = self.nxtmfn
            else:
                stop = mfn.stop

            if not mfn.step:
                step = 1
            else:
                step = mfn.step

            for idx in range(start, stop, step):
                result_set.append(fetch(idx))
            return result_set

    #def __setitem__(self, mfn, record):
    #    """Updates or creates a new record in a persistent way.
    #    The parameter mfn is converted to int, and slices are
    #    not accepted.
    #    """
    #    old_record = self._fetch(mfn)

    def add(self, record):
        """Create a new entry in the MasterFile from the
        given record. Record should be an instance from
        MasterRecord class.
        """
        record.mst = self
        record.save(self)

    def delete(self, mfn):
        """Mark the record corresponding to the given MFN as
        logically deleted. This implicates in writing to the record
        in the master file, and to the record in the xrf file.
        """
        mfn = int(mfn)
        status, pos = self._get_record_offset(mfn)
        if status !='active':
            raise Exception("Asked to delete record flagged as %s"%status)
        # [:-1] == offset before status field in leader
        leader_offset_status = calcsize(self.LEADER_MASK[:-1])
        self.mst_fd.seek(pos+leader_offset_status)
        self.mst_fd.write(pack(self.config.BYTE_ORDER_PRFIX + self.LEADER_MASK[-1], LOGICALLY_DELETED))

        # Adjust xrf file
        xrf_rec = self.xrf[mfn]
        xrf_rec.status = 'logically deleted'
        xrf_rec._write(self.xrf._fd)

    def undelete(self, mfn):
        """Mark the record corresponding to the given MFN if
        logically deleted as active. This implicates in writing to the record
        in the master file, and to the record in the xrf file.
        """
        mfn = int(mfn)
        status, pos = self._get_record_offset(mfn)
        if status !='logically deleted':
            raise Exception(_("Asked to undelete record flagged as %s") % status)
        # [:-1] == offset before status field in leader
        leader_offset_status = calcsize(self.LEADER_MASK[:-1])
        self.mst_fd.seek(pos+leader_offset_status)
        self.mst_fd.write(pack(self.config.BYTE_ORDER_PRFIX + self.LEADER_MASK[-1], ACTIVE))

        # Adjust xrf file
        xrf_rec = self.xrf[mfn]
        xrf_rec.status = 'active'
        xrf_rec._write(self.xrf._fd)

    def previous(self, record):
        """Return previous version of the given record
        as it were before the last save (update), otherwise return None.
        """
        if record.mfbwb==0 and record.mfbwp==0:
            return None
        else:
            pos = (record.mfbwb-1)*self.config.BLOCK_SIZE + record.mfbwp
            self.mst_fd.seek(pos)
            rec = MasterRecord(mfn=record.mfn, config=self.config)
            rec.read(self)
            rec.mst = self
            return rec

    def pack(self):
        """Creates a temporary copy of the database. Copy only
        active records to it, when finished transform the temporary
        copy into the current database. This operation eliminates logically
        deleted records and prevents undelete operations.
        """
        raise NotImplementedError()

    def to_xml(self):
        template = '<database name="%s">%s</database>'
        recs = []
        for i in self:
            recs.append(i.to_xml())
        return template % (self.name, "".join(recs))


    def existsfile(self,fname):
        """file exists test"""
        if not exists(fname):
            raise Exception(_("File %s not found!" % fname))


    def get_fstdata(self, base, fname):
        """Reads fstfile rules"""
        fstlist = []
        if fname:
            try:
                if exists(fname):
                    fstfile = fname
                else:
                    fstfile = join(base,  fname)
                    self.existsfile(fstfile)
                fstdata = open(fstfile).readlines()
                for line in fstdata:
                    fields = line.strip().split()
                    if not fields or line[0] == '#': continue
                    technique = int(fields[1])
                    if technique < 1000:
                        fst_extraction_id = fields[0].strip()
                        fst_technique = fields[1].strip()
                        rest = fields[2]
                        fst_expr = line[line.find(rest):].strip()
                        fstlist.append((fst_extraction_id, fst_technique, fst_expr))
                    else:
                        it1000 = find_IT1000.match(line)
                        if it1000:
                            #id technique expr mfnexpr
                            fstlist.append((it1000.group(1),it1000.group(2),it1000.group(6),\
                                            it1000.group(4)))
            except Exception, e:
                raise Exception (_('Invalid FST file! %s' % str(e) ))
        return fstlist


    def pcb(self,total,current):
        """Sample function callback"""
        print '%s/%s\r'%(current,total),


    def invertdb(self, expr="", extraction_id=1, technique=0,
                 filename=None, fst=None, mfnexpr="", callback=None):
        """Generates inverted file for current database
    Parameters:
        expr:          formatting language expression (default=""),
        extraction_id: extraction id (default=1),
        technique:     technique (default=0),
        filename:      inverted file name (default=/basepath/databasename.idx),
        fst:           fst file name (default=None),
        mfnexpr:       formatting expression to extract mfn (IT1000-1008)
        callback:      notify function (default=None), ex:
                       def cb(total,current):
                           print '%s/%s\\r'%(current,total),
        """

        def get_offset_field(key,field_data):
            """Get word offset field"""
            try:
                return field_data.encode(self.config.OUTPUT_ENCODING).upper().find(key) + 1
            except:
                return 0

        def putpost(rootobj, fkey, mfn, extract_id, occ, field_offset, technique, fieldno):
            """Add key and posting data"""
            post = PostIndex(mfn,extract_id, occ, field_offset, technique, fieldno)
            #fkey = fkey.encode('utf-8')
            try:
                rootobj[fkey].append(post)
            except KeyError:
                rootobj[fkey] = PersistentList()
                rootobj[fkey].append(post)

        fstlist = []
        if technique and technique >= 1000 and expr:
            if not mfnexpr:
                mfnexpr = 'mfn'
            fstlist.append((str(extraction_id), str(technique), expr, mfnexpr))

        elif expr:
            fstlist.append((str(extraction_id),str(technique),expr))

        else:
            #parse fst file
            if not fst:
                fst = '%s.fst' % self.name
            fstlist = self.get_fstdata(self.basepath, fst)

        #index file
        if not filename:
            filename = self.name
        filename = join(self.basepath,  filename + ".idx")

        #Remove old indexes files
        for extfile in ('','.index','.lock','.old','.tmp'):
            fname = filename + extfile
            if exists(fname):
                remove(fname)

        #stop words
        try:
            stw = open(join(self.basepath,  self.name + ".stw")).readlines()
            stopwords = [word.strip() for word in stw]
        except:
            stopwords = []

        storage = FileStorage.FileStorage(filename)
        db = DB(storage)
        connection = db.open()
        dbroot = connection.root()
        dbroot['isis'] = OOBTree()
        root = dbroot['isis']

        total = len(self)
        current = 1

        if not callback:
            callback = self.pcb

        for record in self:

            current_mfn = record.mfn

            #update xref and master file status flags
            record.save(record.mst, reset_flags = True)

            callback(total,current)
            current += 1

            for techrule in fstlist:
                #IT 0-8
                if int(techrule[1]) < 1000:
                    fst_extraction_id, fst_technique, fst_expr = techrule
                    mfn_expr = None

                #IT 1000-1008
                else:
                    fst_extraction_id, fst_technique, fst_expr, mfn_expr = techrule

                if mfn_expr:
                    mfn_num = int(record.format(mfn_expr))
                else:
                    mfn_num = record.mfn

                prefix = ''
                if fst_technique in ('0','5','6','7','8','1000','1005','1006','1007','1008'):
                    found_prefix = find_prefix.match(fst_expr)
                    if found_prefix:
                        prefix = found_prefix.group(1).upper()
                        fst_expr = fst_expr[len(prefix)+4:].replace('*','')
                        if fst_expr[0] == ',':
                            fst_expr = fst_expr[1:]

                try:
                    format_data = record.format(fst_expr).strip().split('\n')
                    field_tag = int(find_field.match(fst_expr).group(1).replace('v','').replace('V',''))
                    field = record[field_tag]
                except KeyError:#field not found
                    continue
                except:
                    pass

                if not format_data:
                    continue

                occ = 1

                #Get result as string
                #Extracts text between "<..>" or "/../"
                #
                if fst_technique in ('2','3','6','7','1002','1003','1006','1007'):
                    sep = {'2': ['<','>'], '3': ['/','/'],'6': ['<','>'], '7': ['/','/'],
                           '1002': ['<','>'], '1003': ['/','/'],'1006': ['<','>'], '1007': ['/','/']}

                    fdata = ''.join(format_data)
                    mdata = re.findall("%s[^%s]*%s"%(sep[fst_technique][0],
                                                     sep[fst_technique][1],
                                                     sep[fst_technique][1]),
                                                     fdata)
                    for key in mdata:
                        key = key.replace('<','').replace('>','').strip()
                        offset = get_offset_field(key,field.data)
                        fkey = prefix + normalize('NFKD', key.decode(self.config.OUTPUT_ENCODING)).encode('ascii','ignore').upper()
                        fkey_word = fkey[:60].strip()
                        putpost(root, fkey_word, mfn_num, fst_extraction_id, occ, offset,
                                fst_technique, field_tag)
                    continue

                #
                #all words of the format result
                #
                elif fst_technique in ('4','8','1004','1008'):
                    fdata = ''.join(format_data)
                    for word in fdata.split():
                        if not word or word in stopwords:
                            continue
                        fkey = ''
                        word = unicode(word.decode(self.config.OUTPUT_ENCODING))
                        key = normalize('NFKD', word).encode('ascii','ignore').upper()
                        for letter in key:
                            if category(unicode(letter)) in ('Ll','Lu'):
                                fkey += letter
                            else:
                                fkey += ' '
                        if not fkey: continue
                        new_keys = fkey.split()
                        for key_word in new_keys:
                            if key_word in stopwords:
                                continue
                            offset = get_offset_field(word,field.data)
                            key_word = prefix + key_word
                            fkey_word = key_word[:60].strip()
                            putpost(root,fkey_word,mfn_num,fst_extraction_id,occ,offset,
                                    fst_technique,field_tag)
                    continue

                #Get result as string list
                for fdata in format_data:
                    if not fdata:
                        continue
                    #
                    #field ipsis-literis
                    #
                    if fst_technique in ('0','1000'):
                        fkey = prefix + normalize('NFKD', fdata.decode(self.config.OUTPUT_ENCODING)).encode('ASCII','ignore').upper()
                        offset = get_offset_field(fdata,field.data)
                        fkey_word = fkey[:60].strip()
                        putpost(root, fkey_word, mfn_num, fst_extraction_id, occ,
                                offset, fst_technique, field_tag)
                    #
                    #subfields
                    #
                    elif fst_technique in ('1','5','1001','1005'):
                        fdata = field.data
                        subdelimiter = self.config.SUBFIELD_DELIMITER
                        if fdata.find(subdelimiter)>=0:
                            if not fdata.startswith(subdelimiter):
                                fdata = subdelimiter + " " + fdata

                            pairs = [(i[0].lower().strip(), i[1:])\
                                     for i in fdata.split(subdelimiter) if i]
                        else:
                            pairs = [('',fdata)]

                        for delim,subfield in pairs:
                            offset = get_offset_field(subfield,field.data)
                            key = unicode(subfield.strip()).encode(self.config.OUTPUT_ENCODING)
                            fkey = prefix + normalize('NFKD', key.decode(self.config.OUTPUT_ENCODING)).encode('ascii','ignore').upper()
                            fkey_word = fkey[:60].strip()
                            putpost(root, fkey_word, mfn_num, fst_extraction_id, occ,
                                    offset, fst_technique, field_tag)

                    else:
                        raise NotImplementedError
                    occ += 1

        transaction.commit()
        connection.close()
        db.pack()
        db.close()
        storage.close()


    def get_mfn_post(self, key, mst, filename=None):
        """Get data from inverted file by key
        Parameters:
            key:      key value,
            filename: inverted file name
        """
        key = normalize('NFKD', key.decode(mst.config.INPUT_ENCODING)).encode('ASCII','ignore').upper()[:60]

        try:
            fcache = _cache[filename]
        except KeyError:

            try:
                storage = FileStorage.FileStorage(filename)
                db = DB(storage)
                connection = db.open()
                dbroot = connection.root()
                fcache = dbroot['isis']
                _cache[filename] = fcache

            except:
                fcache = None
        try:
            mfn = fcache[key][0].mfn
        except:
            mfn = 0
        return mfn

    def search_index(self, key, filename=None):
        """Get iterator postings from inverted file by key
        Parameters:
            key:      key value,
            filename: inverted file name
        """
        if not filename:
            filename = self.name
        filename = join (self.basepath, filename + ".idx")
        self.existsfile(filename)
        db = None
        storage = None
        connection = None
        try:
            try:
                storage = FileStorage.FileStorage(filename)
                db = DB(storage)
                connection = db.open()
                dbroot = connection.root()
                root = dbroot['isis']
                try:
                    return root[key].data.__iter__()
                except KeyError:
                    raise Exception (_("Invalid key"))
            except Exception, e:
                raise Exception(str(e))
        finally:
            if connection:
                connection.close()
            if db:
                db.close()
            if storage:
                storage.close()


    def search(self, key, extraction_id=None, filename=None):
        """Get iterator fields from current database by inverted file key
        Parameters:
            key:           key value,
            extraction_id: extraction id filter (default None),
            filename:      inverted file name (Default None).
        """
        if not filename:
            filename = self.name
        filename = join (self.basepath,  filename + ".idx")
        self.existsfile(filename)
        records = []
        db = None
        storage = None
        connection = None
        try:
            try:
                storage = FileStorage.FileStorage(filename)
                db = DB(storage)
                connection = db.open()
                dbroot = connection.root()
                root = dbroot['isis']
                try:
                    result = root[key].data.__iter__()
                    for data in result:
                        if extraction_id:
                            if data.extraction_id == str(extraction_id):
                                records.append(self[data.mfn])
                                yield self[data.mfn]
                        else:
                            yield self[data.mfn]
                except KeyError:
                    raise Exception (_("Invalid key"))
            except Exception, e:
                raise Exception(str(e))
        finally:
            if connection:
                connection.close()
            if db:
                db.close()
            if storage:
                storage.close()


    def listkeys(self, postings=False, filename=None):
        """List all keys and postings of the inverted file
        Parameters:
            postings: returns postings (default=False),
            filename: inverted file name (default=None)
        """
        if not filename:
            filename = self.name
        filename = join (self.basepath,  filename + ".idx")
        self.existsfile(filename)
        db = None
        storage = None
        connection = None
        try:
            try:
                storage = FileStorage.FileStorage(filename)
                db = DB(storage)
                connection = db.open()
                dbroot = connection.root()
                root = dbroot['isis']
                for key in root.iterkeys():
                    if postings:
                        yield (key,root[key].data)
                    else:
                        yield key
            except Exception, e:
                raise Exception(str(e))
        finally:
            if connection:
                connection.close()
            if db:
                db.close()
            if storage:
                storage.close()



if __name__ == "__main__":
    import doctest
    doctest.testmod()

