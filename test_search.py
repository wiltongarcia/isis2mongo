#!/usr/bin/env python
import pymongo, re
import sys

term  = (sys.argv[1]).upper()
try:
    field = sys.argv[2]
except:
    field = None
mongo = pymongo.Connection("localhost", 27017)
db = mongo.bireme
tot = 0

if field == None:
    for i in db.index.find({'text':{'$regex':'^%s'%term}},{"cds_id":True}):
        for d in db.cds.find({"_id":i['cds_id']}):
            tot += 1
            print d
else:
    for i in db.index.find({'text':{'$regex':'^%s'%term},"field":field},{"cds_id":True}):
        for d in db.cds.find({"_id":i['cds_id']}):
            tot += 1
            print d
            
print "total = %s"%str(tot) 
