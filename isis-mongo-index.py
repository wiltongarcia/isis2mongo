#!/usr/bin/env python
import pymongo, re
#from tio import tioclient
from unicodedata import normalize

def remover_acentos(txt, codif='utf-8'): 
    unicode('\xe1', errors='ignore')
    return normalize('NFKD', txt.decode(codif)).encode('ASCII','ignore') 

def index_tec_0(id, field, text):
    #Quantidade de caracteres indexados pela tecnica 0
    LIMIT = 30
    text = re.sub("[\<\>\:\(\)\"\'\,]"," ",text)
    text = remover_acentos(text.encode("utf-8")).replace("  "," ").upper()
    save({'cds_id':id,'field':field,'text':text[:LIMIT].strip()})

def index_tec_2(id, field, text):
    text = re.sub("[\:\(\)\"\'\,]"," ",text)
    text = remover_acentos(text.encode("utf-8")).replace("  "," ").upper()
    for t in re.findall('\<[A-Z\ 0-9\.]{1,100}\>',text.strip()):
        t = re.sub("[\<\>]"," ",t)
        save({'cds_id':id,'field':field,'text':t.strip()})
            
def index_tec_4(id, field, text):
    for t in re.split('[ \.\n\,\<\>]',text):
        t = remover_acentos(t.encode("utf-8")).replace("  "," ").upper()
        save({'cds_id':id,'field':field,'text':t.strip()})
        
def save(tj):
    try:
        db.index.find(tj).next()
    except:
        db.index.save(tj)

mongo = pymongo.Connection("localhost", 27017)
db = mongo.bireme


for document in db.cds.find({}):
    id = document['_id']
    for field in document.keys():
        if not field == "mfn" and not field == "_id" and not field == "active":
            for i in range(len(document[field])):
                for k in document[field][i]:
                    if type(document[field][i][k]) is list:
                        index_tec_0(id, field, document[field][i][k][0])
                        index_tec_2(id, field, document[field][i][k][0])
                        index_tec_4(id, field, document[field][i][k][0])
                        

#http://www.mongodb.org/display/DOCS/Advanced+Queries
#for document in idx.cds.find({}):
#    print document
#for i in dm.index.find({'text':{'$regex':'^STOCKHOLM INTERNA'}},{"cds_id":True}):
#    for d in db.cds.find({"_id":i['cds_id']}):
#        print d

