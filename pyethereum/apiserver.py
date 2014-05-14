import logging
import threading
import json

import bottle

from pyethereum.chainmanager import chain_manager
from pyethereum.peermanager import peer_manager
import pyethereum.dispatch as dispatch
from pyethereum.blocks import block_structure
import pyethereum.signals as signals
from pyethereum.transactions import Transaction

logger = logging.getLogger(__name__)
base_url = '/api/v0alpha'

app = bottle.Bottle()
app.config['autojson'] = True


class ApiServer(threading.Thread):

    def __init__(self):
        super(ApiServer, self).__init__()
        self.daemon = True
        self.listen_host = '127.0.0.1'
        self.port = 30203

    def configure(self, config):
        self.listen_host = config.get('api', 'listen_host')
        self.port = config.getint('api', 'listen_port')

    def run(self):
        middleware = CorsMiddleware(app)
        bottle.run(middleware, server='waitress',
                   host=self.listen_host, port=self.port)

# ###### create server ######

api_server = ApiServer()


@dispatch.receiver(signals.config_ready)
def config_api_server(sender, config, **kwargs):
    api_server.configure(config)


# #######cors##############
class CorsMiddleware:
    HEADERS = [
        ('Access-Control-Allow-Origin', '*'),
        ('Access-Control-Allow-Methods', 'GET, POST, OPTIONS'),
        ('Access-Control-Allow-Headers',
         'Origin, Accept, Content-Type, X-Requested-With, X-CSRF-Token')
    ]

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        if environ["REQUEST_METHOD"] == "OPTIONS":
            start_response('200 OK',
                           CorsMiddleware.HEADERS + [('Content-Length', "0")])
            return ""
        else:
            def my_start_response(status, headers, exc_info=None):
                headers.extend(CorsMiddleware.HEADERS)

                return start_response(status, headers, exc_info)
            return self.app(environ, my_start_response)


# ######### Utilities ########
def load_json_req():
    json_body = bottle.request.json
    if not json_body:
        json_body = json.load(bottle.request.body)
    return json_body


# ######## Blocks ############
def make_blocks_response(blocks):
    objs = []
    for block in blocks:
        obj = block.to_dict()
        for item_name, item_type, _ in block_structure:
            if item_type in ["bin", "trie_root"]:
                obj[item_name] = obj[item_name].encode('hex')
        objs.append(obj)

    return dict(blocks=objs)


@app.get(base_url + '/blocks/')
def blocks():
    logger.debug('blocks/')
    return make_blocks_response(chain_manager.get_chain(start='', count=20))


@app.get(base_url + '/blocks/<blockhash>')
def block(blockhash=None):
    logger.debug('blocks/%s', blockhash)
    blockhash = blockhash.decode('hex')
    if blockhash in chain_manager:
        return make_blocks_response(chain_manager.get(blockhash))
    else:
        return bottle.abort(404, 'No block with id %s' % blockhash)


# ######## Transactions ############
@app.put(base_url + '/transactions/')
def transactions():
    # request.json FIXME / post json encoded data? i.e. the representation of
    # a tx
    hex_data = bottle.request.body.read()
    logger.debug('PUT transactions/ %s', hex_data)
    tx = Transaction.hex_deserialize(hex_data)
    signals.local_transaction_received.send(sender=None, transaction=tx)
    return bottle.redirect(base_url + '/transactions/' + tx.hex_hash())


# ######## Accounts ############
@app.get(base_url + '/accounts/')
def accounts():
    logger.debug('accounts')
    pass


@app.get(base_url + '/accounts/<address>')
def account(address=None):
    logger.debug('account/%s', address)
    pass


# ######## Peers ###################
def make_peers_response(peers):
    objs = [dict(ip=ip, port=port, node_id=node_id.encode('hex'))
            for (ip, port, node_id) in peers]
    return dict(peers=objs)


@app.get(base_url + '/peers/connected')
def connected_peers():
    return make_peers_response(peer_manager.get_connected_peer_addresses())


@app.get(base_url + '/peers/known')
def known_peers():
    return make_peers_response(peer_manager.get_known_peer_addresses())


# ######## DC msg ############
@app.post(base_url + '/dc/')
def dc():
    indata = bottle.request.body.read()
    data = json.loads(json.loads(indata))
    signals.dao_command_received.send(sender=None, dao_command=data)
    return data
