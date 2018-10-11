'''
Use on publications that have authors related multiple times.
This tool is for when a single instance of an author is listed multiple times.
Produces a file to sub out triples 
'''
from datetime import datetime
import os.path
import urllib
import sys
import requests
import yaml

from vivo_utils.queries import get_all_triples
from vivo_utils.connections.vivo_connect import Connection

def get_config(config_path):
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.load(config_file.read())
    except Exception as e:
        print("Error: Check config file")
        exit(e)
    return config

def make_folders(top_folder, sub_folders=None):
    if not os.path.isdir(top_folder):
        os.mkdir(top_folder)

    if sub_folders:
        sub_top_folder = os.path.join(top_folder, sub_folders[0])
        top_folder = make_folders(sub_top_folder, sub_folders[1:])

    return top_folder

def parse_json(data, search):
    try:
        value = data[search]['value']
    except KeyError as e:
        value = ''

    return value

def get_trips(connection, subject):
    q = '''\
    SELECT ?author ?relation
    WHERE {{
      <{}> <http://vivoweb.org/ontology/core#relatedBy> ?relation .
      ?relation <http://vivoweb.org/ontology/core#relates> ?author .
      ?author <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://xmlns.com/foaf/0.1/Person> .
    }}
    '''.format(subject)

    res = connection.run_query(q)
    auth_dump = res.json()
    authors = {}
    triples = []
    for listing in auth_dump['results']['bindings']:
        uri = parse_json(listing, 'author')
        relation = parse_json(listing, 'relation')
        if uri not in authors.keys():
            authors[uri] = relation
        else:
            trip_params = get_all_triples.get_params(connection)
            trip_params['Thing'].n_number = relation.rsplit('/', 1)[-1]
            triples += get_all_triples.run(connection, **trip_params)
    return triples

def create_sub_file(triples, sub_file):
    with open(sub_file, 'a+') as rdf:
        rdf.write(" . \n".join(triples))
        rdf.write(" . \n")

def main(config_path):
    subject = 'http://vivo.ufl.edu/individual/n6396189090'
    config= get_config(config_path)

    sub_n = subject.split('/')[-1]
    timestamp = datetime.now().strftime("%Y_%m_%d")
    path = make_folders('data_out', [timestamp, sub_n])
    sub_file = os.path.join(path, 'sub_single_pub_dupes.rdf')
    connection = Connection(config.get('namespace'), config.get('email'), config.get('password'), config.get('update_endpoint'), config.get('query_endpoint'))

    triples = get_trips(connection, subject)
    create_sub_file(triples, sub_file)

if __name__ == '__main__':
    main(sys.argv[1])