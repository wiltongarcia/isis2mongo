./pyisis2json.py isis/cds.mst -m -n >cds.json
mongoimport -d bireme -c cds --drop --file cds.json
./isis-mongo-index.py

#teste de pesquisa
./test_search.py "MEASUREMENT AND INSTRUMENTS"

#teste de pesquisa com filtro de campos
./test_search.py "MEASUREMENT AND INSTRUMENTS" 69

#teste de pesquisa simulando o dicionario do winisis
./test_search_suggest.py "MEAS"