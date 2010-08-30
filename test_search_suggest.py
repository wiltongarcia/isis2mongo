#!/usr/bin/env python
import pymongo, re
import sys

term  = (sys.argv[1]).upper()

mongo = pymongo.Connection("localhost", 27017)
db = mongo.bireme
l = []
for i in db.index.find({'text':{'$regex':'^%s'%term}},{"text":True}):
    if not i["text"] in l:
        l.append(i["text"])
l.sort()
    
for x in l: print x