#!/usr/bin/env python
import sys, argparse, uuid, json, os

from pyisis.files import MasterFile
from pyisis.records import MasterRecord
from pyisis.fields import MasterField
from pyisis.fields import MasterContainerField
from pyisis.engine import Engine
import pyisis

"""

Original source code Luciano Ramalho for the Bireme in:
http://reddes.bvsalud.org/projects/isisnbp/browser/tools

"""

SKIP_INACTIVE = True
DEFAULT_QTY = sys.maxint
ISIS_MFN_KEY = 'mfn'
ISIS_ACTIVE_KEY = 'active'
master_file_name = 'isis%scds.mst'%os.sep

def iterRecords(master_file_name):
    config = pyisis.config.config
    config.load("isis/cds.ini")
    Engine.setup(config)
    mst = MasterFile(master_file_name, config=config)
    for record in mst:
        fields = {}
        if SKIP_INACTIVE and (record.status != 0): 
            continue
        else:
            fields[ISIS_ACTIVE_KEY] = record.status == 0
        fields[ISIS_MFN_KEY] = record.mfn
        for field in record:
            field_key = str(field.tag)
            field_occurrences = fields.setdefault(field_key,[])
            subfields = {}
            for key in field._get_subfields(field.data).keys():
                subfield_key = key
                if key == '*':
                    subfields['_'] = field._get_subfields(field.data)[key]
                else:   
                    subfield_occurrences = subfields.setdefault(subfield_key,[])
                    subfield_occurrences.append(field._get_subfields(field.data)[key])
                field_occurrences.append(subfields)
        yield fields
            
def writeJsonArray(master_file_name, output, qty, skip, id_tag, gen_uuid, mongo, mfn):
    start = skip
    end = start + qty
    if not mongo:
        output.write('[\n')
    if id_tag:
        id_tag = str(id_tag)
        ids = set()
    else:
        id_tag = ''    
    for i, record in enumerate(iterRecords(master_file_name)):
        if i >= end: 
            break
        if i > start and not mongo:
            output.write(',')
        output.write('\n')
        if start <= i < end:
            if id_tag:
                occurrences = record.get(id_tag, None)
                if occurrences is None:
                    msg = 'id tag #%s not found in mfn=%s'
                    raise KeyError(msg % (id_tag, record[ISIS_MFN_KEY]))
                if len(occurrences) > 1:
                    msg = 'multiple id tags #%s found in mfn=%s'
                    raise TypeError(msg % (id_tag, record[ISIS_MFN_KEY]))
                else:
                    id = occurrences[0]['_']
                    if id in ids:
                        msg = 'duplicate id %s in tag #%s, mfn=%s'
                        raise TypeError(msg % (id, id_tag, record[ISIS_MFN_KEY]))
                    record['_id'] = id
                    ids.add(id)
            elif gen_uuid:
                record['_id'] = unicode(uuid4())
            elif mfn:
                record['_id'] = record[ISIS_MFN_KEY]
            output.write(json.dumps(record).encode('utf-8'))
    if not mongo:
        output.write('\n]')
    output.write('\n')

if __name__ == '__main__':

    # create the parser
    parser = argparse.ArgumentParser(
        description='Output an ISIS .mst file to a JSON array')

    # add the arguments
    parser.add_argument(
        'master_file_name', metavar='INPUT.mst', help='.mst file to read')
    parser.add_argument(
        '-q', '--qty', type=int, default=DEFAULT_QTY,
        help='maximum quantity of records to read (default=ALL)')
    parser.add_argument(
        '-s', '--skip', type=int, default=0,
        help='records to skip from start of .mst (default=0)')
    parser.add_argument( # TODO: implement this option
        '-r', '--repeat', type=int, default=1,
        help='repeat operation, saving multiple JSON files '
             '(default=1, use -r 0 to repeat until end of input)')
    parser.add_argument(
        '-o', '--out', type=argparse.FileType('w'), default=sys.stdout,
        metavar='OUTPUT.json',
        help='the file where the JSON output should be written '
             '(default: write to stdout)')
    parser.add_argument(
        '-b', '--bulk', const=True, action='store_const',
        help='output array within a "docs" item in a JSON document '
             'for bulk insert to CouchDB via POST to db/_bulk_docs')
    parser.add_argument(
        '-i', '--id', type=int, metavar='TAG_NUMBER', default=0,
        help='generate an "_id" from the given unique TAG field number '
             'for each record')
    parser.add_argument(
        '-n', '--mfn', const=True, action='store_const',
        help='generate an "_id" from the MFN of each record')
    parser.add_argument(
        '-u', '--uuid', const=True, action='store_const',
        help='generate an "_id" with a random UUID for each record')
    parser.add_argument(
        '-m', '--mongo', const=True, action='store_const',
        help='output individual records as JSON dictionaries, one per line'
             'for bulk insert to MongoDB via mongoimport utility')
    
    # parse the command line
    args = parser.parse_args()
    if args.bulk:
        args.out.write('{ "docs" : ')
    writeJsonArray(args.master_file_name, args.out, args.qty, args.skip, 
        args.id, args.uuid, args.mongo, args.mfn)
    if args.bulk:
        args.out.write('}\n')
    args.out.close()

    
    