from datetime import datetime
import os
import logging
import yaml
import sys
import argparse
import optparse
import importlib
sys.path.append('.')

from utils import Aide
import audits
from audits.pub_audits import clean_pubs_dupe_authorships  # put in init.py
from audits.pub_audits import clean_pubs_author_bombs  # put in init.py
from audits import pub_audits
from audits import person_audits
from audits import misc_audits


def main():

    opts = parse_args()
    configure_logging(opts.quiet)
    config = get_config(opts.config)

    multishot(config, logging, opts.uri, opts.oneshots, opts.queries, opts.quiet)

    logging.info("Finished MultiShot... data_out file has triples to upload")
    return

def parse_args(args=sys.argv[1:]) -> (list, list):
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixUri", type=parse_lists, dest="uri", default="", help="Pick uris to input")
    parser.add_argument("--oneShots", type=parse_lists, dest="oneshots", default="", help="Pick oneshots to run")
    parser.add_argument("--query", type=parse_lists, dest="queries", default="", help="Pick a query to feed Uri into oneshots")
    parser.add_argument("--quiet", action="store_true", dest="quiet", default=False, help="Set this flagg to quiet terminal output")
    parser.add_argument("--config", action="store", dest="config", default="config.yaml", help="")
    return parser.parse_args(args)


def configure_logging(quiet):
    fmt = '%(asctime)s  %(levelname)-9s  %(message)s'
    logfile = 'MultiShot.log'

    logging.basicConfig(level=logging.DEBUG, format=fmt, filename=logfile)

    if quiet:
        # Do not write logs to console; normal output still goes to stdout.
        return

    console = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(fmt)
    console.setFormatter(formatter)

    console.setLevel(logging.INFO)

    logging.getLogger().addHandler(console)
    return

def get_config(config_path):
    try:
        with open(config_path, 'r') as config_file:
            config = yaml.load(config_file.read())
    except Exception as e:
        print("Error: Check config file")
        exit(e)
    return config


def multishot(config, logging, uris, oneshots, queries, quiet):
    '''
    runs all multishot that apply to a given list of the *same type* of uris if applicable.
    '''

    aide = Aide(config.get('query_endpoint'), config.get('email'), config.get('password'), quiet)
    if uris != ['']:
        type = fetch_uri_type(aide, uris)
    else:
        type = 'None'

    oneshot_dir = 'audits/' + type + 'audits'
    query_dir = 'queries/'

    if queries == [''] and oneshots == [''] and uris == ['']:
        logging.error('Can not run all queries and all oneshots at once')
        sys.exit(2)
    
    if uris != [''] and oneshots != ['']:
        oneshots = [f[:-3] for f in oneshots if f.endswith('.py')]

    if uris != [''] and oneshots == ['']:
        oneshots = [f[:-3] for f in os.listdir(oneshot_dir) if f.endswith('.py') and f != '__init__.py']

    if queries[0].find('.rq') != -1 and queries != ['']:
        queries = [f[:-3] for f in queries if f.endswith('.rq')]
        oneshots = ['clean_' + f for f in queries]
        paris = match_oneshot_to_query(oneshots, queries)

    if oneshots[0].find('.py') != -1 and oneshots != [''] and uris == ['']:
        oneshots = [f[:-3] for f in oneshots if f.endswith('.py')]
        queries = [f[6:] for f in oneshots]
        paris = match_oneshot_to_query(oneshots, queries)
    
    oneshots.sort()

    for oneshot in oneshots:
        if queries != ['']:
            for query in queries:
                uris = query_list_uris(aide, query_dir, paris[query])
                cleaners(aide, oneshot, uris)
        else:
            cleaners(aide, oneshot, uris)

def query_list_uris(aide, query_dir, oneshot):
    quary_name = oneshot[6:]
    logging.info('Running query %s', quary_name)
    uris = query_uri(aide, query_dir + quary_name + '.rq')
    logging.info('Query was successful, %s dataproblems found in %s query', len(uris), quary_name)
    return uris

def match_oneshot_to_query(oneshots, queries):
    '''
    matches oneshot file name to query and return dictionary of query and oneshots
    '''
    pairs = {}
    for query in queries:
        if str('clean_' + query) in oneshots:
            pairs[query] = str('clean_' + query)
        else:
            logging.warn('Could not find matching oneshot for query %s', query)
    logging.debug('All Queries matched with OneShots')
    return pairs

def save_trips(aide, subject, triples, cleaner_name):
    '''
    saves trips to be uploaded in data_out directory
    '''
    if triples is not None:
        logging.debug('Saving tripples for %s', cleaner_name)
        timestamp = datetime.now().strftime("%Y_%m_%d")
        path = 'data_out/' + timestamp + '/' + subject.split('/')[-1]
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
        sub_file = os.path.join(path, cleaner_name + '.rdf')
        aide.create_file(sub_file, triples)
    else:
        logging.debug('Trips %s has not triples to save', cleaner_name)

def query_uri(aide, file) -> (list):
    uris = []
    f = open(file, 'r')
    query = f.read()
    res = aide.do_query(query)
    uri_type = parse_uri_type(res)
    for listing in res['results']['bindings']:
        uris.append(aide.parse_json(listing, uri_type))
    return uris

def load_oneshots(queries_path, oneShot_path, logging):
    # defualt - go to every folder that ends with _audits and pull all .py files except
    try:
        if oneShot_path == 'audits':
            files = [f for f in os.listdir('audits') if f.endswith('_audits')]
            all_oneshots = []
            for file in files:
                all_oneshots += ([f for f in os.listdir('audits/' + file) if f.endswith('.py') and f != '__init__.py'])
            all_oneshots.sort()
        # input path -  go to input path and do same thing
        else:
            all_oneshots = [f for f in os.listdir(oneShot_path) if f.endswith('.py') and f != '__init__.py']
            all_oneshots.sort()

        all_queries = [f for f in os.listdir(queries_path) if f.endswith('.rq')]
        all_queries.sort()
    except Exception:
        logging.error('Failed to load all queries and oneshots')
        sys.exit(2)

    return all_oneshots, all_queries

def parse_uri_type(res):
    type = list(res['results']['bindings'][0])[0]
    return type

def check_cleaner_type(cleaner_name):
    '''
    check what type of cleaner given name
    '''
    if 'pubs_' in cleaner_name:
        type = 'pub_audits'
    elif 'person_' in cleaner_name:
        type = 'person_audits'
    elif 'misc_' in cleaner_name:
        type = 'misc_audits'
    else:
        type = 'misc_audits'
        logging.error('Could not find cleaner %s', cleaner_name)
    return type

def fetch_uri_type(aide, uris) -> str:
    '''
    queries the uri to find if its a pub, author, ext..
    currently only suppoprts person and accademicartical type
    '''
    q = '''\
    SELECT ?types
    WHERE {{
    <{}> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?types .
    }}
        '''.format(uris[0])
    res = aide.do_query(q)
    for type in res['results']['bindings']:
        uri_type = type['types']['value']
        # TODO add test to see if multiple types at once
        if 'Person' in uri_type:
            return 'person_'
        elif 'AcademicArticle' in uri_type:
            return 'pub_'
    logging.error('Could not find type for %s', uris)
    sys.exit(2)

def cleaners(aide, oneshot_name, uris):
    '''
    Takes in cleaner name and list of uris and outputs the triples to be removed and added
    '''
    logging.info('Starting oneshot for %s', oneshot_name)
    # TODO Change when using ABC
    type = check_cleaner_type(oneshot_name)
    files = getattr(audits, type)
    oneShot = getattr(files, oneshot_name)

    # remove this bit of code when turning to abc
    hasCleaner = False
    try:
        add_function = getattr(oneShot, 'get_add_trips')
        hasCleaner = True
    except AttributeError:
        logging.warn('Cleaner %s does not have get_add_trips function', oneshot_name)
        add_function = None
    try:
        sub_function = getattr(oneShot, 'get_sub_trips')
        hasCleaner = True
    except AttributeError:
        logging.warn('Cleaner %s does not have get_add_trips function', oneshot_name)
        sub_function = None
    # remove this bit of code when turning to abc

    count = 0
    for uri in uris:
        if add_function != None:
            try:
                add_trips = add_function(aide, uri)
                count += len(add_trips)
            except Exception:
                logging.error('Cleaner %s failed, skipping uri %s', oneshot_name, uri)
        else:
            logging.warn('uri %s does not neede to run %s ', uri, oneshot_name)

        if sub_function != None:
            try:
                sub_trips = sub_function(aide, uri)
                count += len(sub_trips)
            except Exception:
                logging.error('Cleaner %s failed, skipping uri %s', oneshot_name, uri)
        else:
            logging.warn('uri %s does not neede to run %s ', uri, oneshot_name)

        if add_function != None:
            save_trips(aide, uri, add_trips, oneshot_name + '_add')
        if sub_function != None:
            save_trips(aide, uri, sub_trips, oneshot_name + '_sub')
    return count

def parse_lists(text: str):
    ''' Parse the uris and returns a list of uris '''
    clean_uris = text.strip().replace(' ', '')
    uri_list = []
    if text[:1] == '@':
        uri_list = parse_list_file(clean_uris)
    else:
        uri_list = clean_uris.split(',')
    if len(uri_list) > 9999:
        raise argparse.ArgumentError('Too many items to parse')
    return uri_list

def parse_list_file(file):
    ''' Opens given file with list of uri and reads them all '''
    with open(file, 'r') as f:
        return[line.strip() for line in f.readLines()]

if __name__ == '__main__':
    main()
