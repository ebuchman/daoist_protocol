import time
import rlp
import trie
import db
import utils
import processblock
import transactions


INITIAL_DIFFICULTY = 2 ** 12
GENESIS_PREVHASH = "\x00" * 32
GENESIS_COINBASE = "0" * 40
GENESIS_NONCE = utils.sha3(chr(42))
GENESIS_TX_LIST_ROOT = "" # \x00" * 32
GENESIS_GAS_LIMIT = 10 ** 6
BLOCK_REWARD = 10 ** 18
BLOCK_DIFF_FACTOR = 1024
GASLIMIT_EMA_FACTOR = 1024
GENESIS_MIN_GAS_PRICE = 0
BLKLIM_FACTOR_NOM = 6
BLKLIM_FACTOR_DEN = 5

GENESIS_INITIAL_ALLOC = \
    {"8a40bfaa73256b60764c1bf40675a99083efb075": 2 ** 200,
     "e6716f9544a56c530d868e4bfbacb172315bdead": 2 ** 200,
     "1e12515ce3e0f817a4ddef9ca55788a1d66bd2df": 2 ** 200,
     "1a26338f0d905e295fccb71fa9ea849ffa12aaf4": 2 ** 200}

block_structure = [
    ["prevhash", "bin", ""],
    ["uncles_hash", "bin", utils.sha3(rlp.encode([]))],
    ["coinbase", "addr", GENESIS_COINBASE],
    ["state_root", "trie_root", ''],
    ["tx_list_root", "trie_root", ''],
    ["difficulty", "int", INITIAL_DIFFICULTY],
    ["number", "int", 0],
    ["min_gas_price", "int", GENESIS_MIN_GAS_PRICE],
    ["gas_limit", "int", GENESIS_GAS_LIMIT],
    ["gas_used", "int", 0],
    ["timestamp", "int", 0],
    ["extra_data", "bin", ""],
    ["nonce", "bin", ""],
]

block_structure_rev = {}
for i, (name, typ, default) in enumerate(block_structure):
    block_structure_rev[name] = [i, typ, default]

acct_structure = [
    ["balance", "int", 0],
    ["nonce", "int", 0],
    ["storage", "trie_root", ""],
    ["code", "bin", ""],
]

acct_structure_rev = {}
for i, (name, typ, default) in enumerate(acct_structure):
    acct_structure_rev[name] = [i, typ, default]


def calc_difficulty(parent, timestamp):
    offset = parent.difficulty / BLOCK_DIFF_FACTOR
    sign = 1 if timestamp - parent.timestamp < 42 else -1
    return parent.difficulty + offset * sign


def calc_gaslimit(parent):
    prior_contribution = parent.gas_limit * (GASLIMIT_EMA_FACTOR - 1)
    new_contribution = parent.gas_used * BLKLIM_FACTOR_NOM / BLKLIM_FACTOR_DEN
    return (prior_contribution + new_contribution) / GASLIMIT_EMA_FACTOR


class UnknownParentException(Exception):
    pass


class Block(object):

    def __init__(self,
                 prevhash='',
                 uncles_hash=block_structure_rev['uncles_hash'][2],
                 coinbase=block_structure_rev['coinbase'][2],
                 state_root='',
                 tx_list_root='',
                 difficulty=block_structure_rev['difficulty'][2],
                 number=0,
                 min_gas_price=block_structure_rev['min_gas_price'][2],
                 gas_limit=block_structure_rev['gas_limit'][2],
                 gas_used=0, timestamp=0, extra_data='', nonce='',
                 transaction_list=[],
                 uncles=[]):

        self.prevhash = prevhash
        self.uncles_hash = uncles_hash
        self.coinbase = coinbase
        self.difficulty = difficulty
        self.number = number
        self.min_gas_price = min_gas_price
        self.gas_limit = gas_limit
        self.gas_used = gas_used
        self.timestamp = timestamp
        self.extra_data = extra_data
        self.nonce = nonce
        self.uncles = uncles

        self.transactions = trie.Trie(utils.get_db_path(), tx_list_root)
        self.transaction_count = 0

        self.state = trie.Trie(utils.get_db_path(), state_root)

        if transaction_list:
            # support init with transactions only if state is known
            assert len(self.state.root) == 32 and \
                self.state.db.has_key(self.state.root)
            for tx_serialized, state_root, gas_used_encoded in transaction_list:
                self._add_transaction_to_list(
                    tx_serialized, state_root, gas_used_encoded)

        # make sure we are all on the same db
        assert self.state.db.db == self.transactions.db.db

        # Basic consistency verifications
        if len(self.state.root) == 32 and \
                not self.state.db.has_key(self.state.root):
            raise Exception(
                "State Merkle root not found in database! %r" % self)
        if tx_list_root != self.transactions.root:
            raise Exception("Transaction list root hash does not match!")
        if len(self.transactions.root) == 32 and not self.is_genesis() and\
                not self.transactions.db.has_key(self.transactions.root):
            raise Exception(
                "Transactions root not found in database! %r" % self)
        if utils.sha3(rlp.encode(self.uncles)) != self.uncles_hash:
            raise Exception("Uncle root hash does not match!")
        if len(self.extra_data) > 1024:
            raise Exception("Extra data cannot exceed 1024 bytes")
        if self.coinbase == '':
            raise Exception("Coinbase cannot be empty address")
        if not self.is_genesis() and self.nonce and not self.check_proof_of_work(self.nonce):
            raise Exception("PoW check failed")

    def is_genesis(self):
        return self.prevhash == GENESIS_PREVHASH and \
            self.nonce == GENESIS_NONCE

    def check_proof_of_work(self, nonce):
        prefix = self.serialize_header_without_nonce()
        h = utils.sha3(utils.sha3(prefix + nonce))
        l256 = utils.big_endian_to_int(h)
        return l256 < 2 ** 256 / self.difficulty

    @classmethod
    def deserialize(cls, rlpdata):
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        assert len(header_args) == len(block_structure)
        kargs = dict(transaction_list=transaction_list, uncles=uncles)
        # Deserialize all properties
        for i, (name, typ, default) in enumerate(block_structure):
            kargs[name] = utils.decoders[typ](header_args[i])

        # if we don't have the state we need to replay transactions
        _db = db.DB(utils.get_db_path())
        if len(kargs['state_root']) == 32 and _db.has_key(kargs['state_root']):
            return Block(**kargs)
        elif kargs['prevhash'] == GENESIS_PREVHASH:
            return Block(**kargs)
        else:  # no state, need to replay
            try:
                parent = get_block(kargs['prevhash'])
            except KeyError:
                raise UnknownParentException(kargs['prevhash'].encode('hex'))
            return parent.deserialize_child(rlpdata)

    def deserialize_child(self, rlpdata):
        """
        deserialization w/ replaying transactions
        """
        header_args, transaction_list, uncles = rlp.decode(rlpdata)
        assert len(header_args) == len(block_structure)
        kargs = dict(transaction_list=transaction_list, uncles=uncles)
        # Deserialize all properties
        for i, (name, typ, default) in enumerate(block_structure):
            kargs[name] = utils.decoders[typ](header_args[i])

        block = Block.init_from_parent(self, kargs['coinbase'],
                                       extra_data=kargs['extra_data'],
                                       timestamp=kargs['timestamp'])
        block.finalize()  # this is the first potential state change
        # replay transactions
        for tx_serialized, _state_root, _gas_used_encoded in transaction_list:
            tx = transactions.Transaction.deserialize(tx_serialized)
            processblock.apply_tx(block, tx)
            assert _state_root == block.state.root
            assert utils.decode_int(_gas_used_encoded) == block.gas_used

        # checks
        assert block.prevhash == self.hash
        assert block.state.root == kargs['state_root']
        assert block.tx_list_root == kargs['tx_list_root']
        assert block.gas_used == kargs['gas_used']
        assert block.gas_limit == kargs['gas_limit']
        assert block.timestamp == kargs['timestamp']
        assert block.difficulty == kargs['difficulty']
        assert block.number == kargs['number']
        assert block.extra_data == kargs['extra_data']
        assert utils.sha3(rlp.encode(block.uncles)) == kargs['uncles_hash']

        block.uncles_hash = kargs['uncles_hash']
        block.nonce = kargs['nonce']
        block.min_gas_price = kargs['min_gas_price']

        return block

    @classmethod
    def hex_deserialize(cls, hexrlpdata):
        return cls.deserialize(hexrlpdata.decode('hex'))

    # _get_acct_item(bin or hex, int) -> bin
    def _get_acct_item(self, address, param):
        ''' get account item
        :param address: account address, can be binary or hex string
        :param param: parameter to get
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        decoder = utils.decoders[acct_structure_rev[param][1]]
        return decoder(acct[acct_structure_rev[param][0]])

    # _set_acct_item(bin or hex, int, bin)
    def _set_acct_item(self, address, param, value):
        ''' set account item
        :param address: account address, can be binary or hex string
        :param param: parameter to set
        :param value: new value
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        encoder = utils.encoders[acct_structure_rev[param][1]]
        acct[acct_structure_rev[param][0]] = encoder(value)
        self.state.update(address, acct)

    # _delta_item(bin or hex, int, int) -> success/fail
    def _delta_item(self, address, param, value):
        ''' add value to account item
        :param address: account address, can be binary or hex string
        :param param: parameter to increase/decrease
        :param value: can be positive or negative
        '''
        if len(address) == 40:
            address = address.decode('hex')
        acct = self.state.get(address) or ['', '', '', '']
        index = acct_structure_rev[param][0]
        if utils.decode_int(acct[index]) + value < 0:
            return False
        acct[index] = utils.encode_int(utils.decode_int(acct[index]) + value)
        self.state.update(address, acct)
        return True

    def _add_transaction_to_list(self, tx_serialized, state_root, gas_used_encoded):
        # adds encoded data # FIXME: the constructor should get objects
        data = [tx_serialized, state_root, gas_used_encoded]
        self.transactions.update(
            utils.encode_int(self.transaction_count), data)
        self.transaction_count += 1

    def add_transaction_to_list(self, tx):
        # used by processblocks apply_tx only. not atomic!
        self._add_transaction_to_list(tx.serialize(),
                                      self.state_root,
                                      utils.encode_int(self.gas_used))

    def _list_transactions(self):
        # returns [[tx_serialized, state_root, gas_used_encoded],...]
        txlist = []
        for i in range(self.transaction_count):
            txlist.append(self.transactions.get(utils.encode_int(i)))
        return txlist

    def get_transactions(self):
        return [transactions.Transaction.deserialize(tx) for
                tx, s, g in self._list_transactions()]

    def apply_transaction(self, tx):
        return processblock.apply_tx(self, tx)

    def get_nonce(self, address):
        return self._get_acct_item(address, 'nonce')

    def increment_nonce(self, address):
        return self._delta_item(address, 'nonce', 1)

    def decrement_nonce(self, address):
        return self._delta_item(address, 'nonce', -1)

    def get_balance(self, address):
        return self._get_acct_item(address, 'balance')

    def set_balance(self, address, value):
        self._set_acct_item(address, 'balance', value)

    def delta_balance(self, address, value):
        return self._delta_item(address, 'balance', value)

    def get_code(self, address):
        codehash = self._get_acct_item(address, 'code')
        return self.state.db.get(codehash) if codehash else ''

    def set_code(self, address, value):
        self.state.db.put(utils.sha3(value), value)
        self.state.db.commit()
        self._set_acct_item(address, 'code', utils.sha3(value))

    def get_storage(self, address):
        storage_root = self._get_acct_item(address, 'storage')
        return trie.Trie(utils.get_db_path(), storage_root)

    def get_storage_data(self, address, index):
        t = self.get_storage(address)
        val = t.get(utils.coerce_to_bytes(index))
        return utils.decode_int(val) if val else 0

    def set_storage_data(self, address, index, val):
        t = self.get_storage(address)
        if val:
            t.update(utils.coerce_to_bytes(index), utils.encode_int(val))
        else:
            t.delete(utils.coerce_to_bytes(index))
        self._set_acct_item(address, 'storage', t.root)

    def _account_to_dict(self, acct):
        med_dict = {}
        for i, (name, typ, default) in enumerate(acct_structure):
            med_dict[name] = utils.decoders[typ](acct[i])
        chash = med_dict['code']
        strie = trie.Trie(utils.get_db_path(), med_dict['storage']).to_dict()
        med_dict['code'] = \
            self.state.db.get(chash).encode('hex') if chash else ''
        med_dict['storage'] = {
            utils.decode_int(k): utils.decode_int(strie[k]) for k in strie
        }
        return med_dict

    def account_to_dict(self, address):
        acct = self.state.get(address.decode('hex')) or ['', '', '', '']
        return self._account_to_dict(acct)

    # Revert computation
    def snapshot(self):
        return {
            'state': self.state.root,
            'gas': self.gas_used,
            'txs': self.transactions,
            'txcount': self.transaction_count,
        }

    def revert(self, mysnapshot):
        self.state.root = mysnapshot['state']
        self.gas_used = mysnapshot['gas']
        self.transactions = mysnapshot['txs']
        self.transaction_count = mysnapshot['txcount']

    def finalize(self):
        self.delta_balance(self.coinbase, BLOCK_REWARD)

    def serialize_header_without_nonce(self):
        return rlp.encode(self.list_header(exclude=['nonce']))

    @property
    def state_root(self):
        return self.state.root

    @property
    def tx_list_root(self):
        return self.transactions.root

    def list_header(self, exclude=[]):
        self.uncles_hash = utils.sha3(rlp.encode(self.uncles))
        header = []
        for name, typ, default in block_structure:
            # print name, typ, default , getattr(self, name)
            if not name in exclude:
                header.append(utils.encoders[typ](getattr(self, name)))
        return header

    def serialize(self):
        # Serialization method; should act as perfect inverse function of the
        # constructor assuming no verification failures
        return rlp.encode([self.list_header(), self._list_transactions(), self.uncles])

    def hex_serialize(self):
        return self.serialize().encode('hex')

    def to_dict(self):
        b = {}
        for name, typ, default in block_structure:
            b[name] = getattr(self, name)
        state = self.state.to_dict(True)
        b["state"] = {}
        for s in state:
            b["state"][s.encode('hex')] = self._account_to_dict(state[s])
        # txlist = []
        # for i in range(self.transaction_count):
        #     txlist.append(self.transactions.get(utils.encode_int(i)))
        # b["transactions"] = txlist
        return b

    @property
    def hash(self):
        return utils.sha3(self.serialize())

    def hex_hash(self):
        return self.hash.encode('hex')

    def get_parent(self):
        if self.number == 0:
            raise UnknownParentException('Genesis block has no parent')
        try:
            parent = get_block(self.prevhash)
        except KeyError:
            raise UnknownParentException(self.prevhash.encode('hex'))
        assert parent.state.db.db == self.state.db.db
        return parent

    def has_parent(self):
        try:
            self.get_parent()
            return True
        except UnknownParentException:
            return False

    def chain_difficulty(self):
            # calculate the summarized_difficulty (on the fly for now)
        if self.is_genesis():
            return self.difficulty
        else:
            return self.difficulty + self.get_parent().chain_difficulty()

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.hash == other.hash

    def __ne__(self, other):
        return not self.__eq__(other)

    def __gt__(self, other):
        return self.number > other.number

    def __lt__(self, other):
        return self.number < other.number

    def __repr__(self):
        return '<Block(#%d %s %s)>' % (self.number, self.hex_hash()[:4], self.prevhash.encode('hex')[:4])

    @classmethod
    def init_from_parent(cls, parent, coinbase, extra_data='',
                         timestamp=int(time.time())):
        return Block(
            prevhash=parent.hash,
            uncles_hash=utils.sha3(rlp.encode([])),
            coinbase=coinbase,
            state_root=parent.state.root,
            tx_list_root='',
            difficulty=calc_difficulty(parent, timestamp),
            number=parent.number + 1,
            min_gas_price=0,
            gas_limit=calc_gaslimit(parent),
            gas_used=0,
            timestamp=timestamp,
            extra_data=extra_data,
            nonce='',
            transaction_list=[],
            uncles=[])

# put the next two functions into this module to support Block.get_parent
# should be probably be in chainmanager otherwise


def get_block(blockhash):
    return Block.deserialize(db.DB(utils.get_db_path()).get(blockhash))


def has_block(blockhash):
    return db.DB(utils.get_db_path()).has_key(blockhash)


def genesis(initial_alloc=GENESIS_INITIAL_ALLOC):
    print initial_alloc
    # https://ethereum.etherpad.mozilla.org/11
    block = Block(prevhash=GENESIS_PREVHASH, coinbase=GENESIS_COINBASE,
                tx_list_root=GENESIS_TX_LIST_ROOT,
                  difficulty=INITIAL_DIFFICULTY, nonce=GENESIS_NONCE,
                  gas_limit=GENESIS_GAS_LIMIT)
    for addr in initial_alloc:
        block.set_balance(addr, initial_alloc[addr])
        print addr
        print block.get_balance(addr)
    return block
