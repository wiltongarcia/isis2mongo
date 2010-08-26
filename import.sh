./pyisis2json.py isis/cds.mst -m -n >cds.json
mongoimport -d bireme -c cds --drop --file cds.json
./isis-mongo-index.py