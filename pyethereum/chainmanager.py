import logging
import time
import struct
import string
from dispatch import receiver
from stoppable import StoppableLoopThread
import signals
from db import DB
import utils
import rlp
import blocks
import processblock
from transactions import Transaction
from bitcoin import ecdsa_raw_recover, ecdsa_raw_verify
import serpent
import sys

logger = logging.getLogger(__name__)

rlp_hash_hex = lambda data: utils.sha3(rlp.encode(data)).encode('hex')

privkey = utils.sha3('brain wallet')
self_addr = utils.privtoaddr(privkey)

def byte_arrays_to_string(arr):
    stri = ''
    for d in arr:
        stri += string.join(map(chr, d), '')
    return stri

def byte_array_to_string(arr):
    return string.join(map(chr, arr), '')

class Miner():

    """
    Mines on the current head
    Stores received transactions
    """

    def __init__(self, parent, coinbase):
        self.nonce = 0
        block = self.block = blocks.Block.init_from_parent(parent, coinbase)
        block.finalize()  # order?
        logger.debug('Mining #%d %s', block.number, block.hex_hash())
        logger.debug('Difficulty %s', block.difficulty)

    def add_transaction(self, transaction):
        """
        (1) The transaction signature is valid;
        (2) the transaction nonce is valid (equivalent to the
            sender accounts current nonce);
        (3) the gas limit is no smaller than the intrinsic gas,
            g0 , used by the transaction;
        (4) the sender account balance contains at least the cost,
            v0, required in up-front payment.
        """
        try:
            success, res = self.block.apply_transaction(transaction)
            assert transaction in self.block.get_transactions()
        except Exception, e:
            logger.debug('rejected transaction %r: %s', transaction, e)
            return False
        if not success:
            logger.debug('transaction %r not applied', transaction)
        else:
            logger.debug(
                'transaction %r applied to %r res: %r',
                transaction, self.block, res)
        return success

    def get_transactions(self):
        return self.block.get_transactions()

    def mine(self, steps=1000):
        """
        It is formally defined as PoW: PoW(H, n) = BE(SHA3(SHA3(RLP(Hn)) o n))
        where:
        RLP(Hn) is the RLP encoding of the block header H, not including the
            final nonce component;
        SHA3 is the SHA3 hash function accepting an arbitrary length series of
            bytes and evaluating to a series of 32 bytes (i.e. 256-bit);
        n is the nonce, a series of 32 bytes;
        o is the series concatenation operator;
        BE(X) evaluates to the value equal to X when interpreted as a
            big-endian-encoded integer.
        """

        pack = struct.pack
        sha3 = utils.sha3
        beti = utils.big_endian_to_int
        block = self.block

        nonce_bin_prefix = '\x00' * (32 - len(pack('>q', 0)))
        prefix = block.serialize_header_without_nonce() + nonce_bin_prefix

        target = 2 ** 256 / block.difficulty

        for nonce in range(self.nonce, self.nonce + steps):
            h = sha3(sha3(prefix + pack('>q', nonce)))
            l256 = beti(h)
            if l256 < target:
                block.nonce = nonce_bin_prefix + pack('>q', nonce)
                assert block.check_proof_of_work(block.nonce) is True
                assert block.get_parent()
                logger.debug(
                    'Nonce found %d %r', nonce, block)
                return block

        self.nonce = nonce
        return False
'''
    Notes about DCP Handling
         manager should init the dcp_list by refering to a file or checking the route contract
         each dcp should be an empty transaction addressed to the appropriate DAO
         when a dc comes in, check if its dest is on the list.  if not, add (if you want to be risky) or ignore
         add a dc to the dcp by:
            check sig
            parse msg args
            add msg args to dcp tx
            broadcast/save new tx to replace old one

'''
class ChainManager(StoppableLoopThread):

    """
    Manages the chain and requests to it.
    """

    def __init__(self):
        super(ChainManager, self).__init__()
        # initialized after configure
        self.miner = None
        self.blockchain = None
        self.dcp_list = {} # addr:tx
        self.route_risk = 1

    def configure(self, config):
        self.config = config
        logger.info('Opening chain @ %s', utils.get_db_path())
        self.blockchain = DB(utils.get_db_path())
        logger.debug('Chain @ #%d %s', self.head.number, self.head.hex_hash())
        self.log_chain()
        self.new_miner()
        self.init_dcp_list()

    def init_dcp_list(self):
        pass

    @property
    def head(self):
        if 'HEAD' not in self.blockchain:
            self._initialize_blockchain()
        ptr = self.blockchain.get('HEAD')
        return blocks.get_block(ptr)

    def _update_head(self, block):
        bh = block.hash
        self.blockchain.put('HEAD', block.hash)
        self.blockchain.commit()
        self.new_miner()  # reset mining

    def get(self, blockhash):
        return blocks.get_block(blockhash)

    def has_block(self, blockhash):
        return blockhash in self.blockchain

    def __contains__(self, blockhash):
        return self.has_block(blockhash)

    def _store_block(self, block):
        self.blockchain.put(block.hash, block.serialize())
        self.blockchain.commit()
        assert block == blocks.get_block(block.hash)

    def _initialize_blockchain(self):
        logger.info('Initializing new chain @ %s', utils.get_db_path())
        genesis = blocks.genesis({self_addr: 10**18})
        self._store_block(genesis)
        self._update_head(genesis)
        self.blockchain.commit()

    def synchronize_blockchain(self):
        logger.info('synchronize requested for head %r', self.head)

        signals.remote_chain_requested.send(
            sender=None, parents=[self.head.hash], count=256)

    def loop_body(self):
        ts = time.time()
        pct_cpu = self.config.getint('misc', 'mining')
        if pct_cpu > 0:
            self.mine()
            delay = (time.time() - ts) * (100. / pct_cpu - 1)
            time.sleep(min(delay, 1.))
        else:
            time.sleep(.01)

    def new_miner(self):
        "new miner is initialized if HEAD is updated"
        miner = Miner(self.head, self.config.get('wallet', 'coinbase'))
        if self.miner:
            for tx in self.miner.get_transactions():
                miner.add_transaction(tx)
        self.miner = miner

    def remove_old_tx(self, addr):
        print 'old nonce', self.miner.block.get_nonce(self_addr)
        miner = Miner(self.head, self.config.get('wallet', 'coinbase'))
        for tx in self.miner.get_transactions():
            if not tx.to == addr:
                miner.add_transaction(tx)
        self.miner = miner
        print 'new nonce', self.miner.block.get_nonce(self_addr)
        self.miner.block.decrement_nonce(self_addr)


    def mine(self):
        with self.lock:
            block = self.miner.mine()
            if block:
                # create new block
                self.add_block(block)
                logger.debug("broadcasting new %r" % block)
                signals.send_local_blocks.send(
                    sender=None, blocks=[block])  # FIXME DE/ENCODE

    def receive_chain(self, blocks):
        old_head = self.head
        # assuming chain order w/ newest block first
        for block in blocks:
            if block.hash in self:
                logger.debug('Known %r', block)
            else:
                if block.has_parent():
                    # add block & set HEAD if it's longest chain
                    success = self.add_block(block)
                    if success:
                        logger.debug('Added %r', block)
                else:
                    logger.debug('Orphant %r', block)
        if self.head != old_head:
            self.synchronize_blockchain()

    def add_block(self, block):
        "returns True if block was added sucessfully"
        # make sure we know the parent
        if not block.has_parent() and not block.is_genesis():
            logger.debug('Missing parent for block %r', block.hex_hash())
            return False

        # check PoW
        if not len(block.nonce) == 32:
            logger.debug('Nonce not set %r', block.hex_hash())
            return False
        elif not block.check_proof_of_work(block.nonce) and\
                not block.is_genesis():
            logger.debug('Invalid nonce %r', block.hex_hash())
            return False

        if block.has_parent():
            try:
                processblock.verify(block, block.get_parent())
            except AssertionError, e:
                logger.debug('verification failed: %s', str(e))
                processblock.verify(block, block.get_parent())
                return False

        self._store_block(block)
        # set to head if this makes the longest chain w/ most work
        if block.chain_difficulty() > self.head.chain_difficulty():
            logger.debug('New Head %r', block)
            self._update_head(block)
        return True

    def init_dcp(self, addr):
        nonce = self.miner.block.get_nonce(self_addr) #self.config.get('wallet', 'coinbase'))
        print 'init nonce for dcp', nonce
        GASPRICE = 100
        print 'addr!'
        print addr
        new_dcp = Transaction(nonce, GASPRICE, 10**5, addr, 0, serpent.encode_datalist([0])).sign(privkey) #encode datalist...
        print 'sender', new_dcp.sender
        print 'self addr', self_addr
        self.dcp_list[addr] = new_dcp

    def _add_dc_to_dcp(self, to_addr, from_addr, sig, msghash, msgsize, data):
        assert(self.verify_dc_sig(sig, msghash, msgsize, from_addr, data))
        tx = self.dcp_list[to_addr]
        txdata = serpent.decode_datalist(tx.data)
        txdata[0] += 1 #increment dc count
        #append dc data to dcp tx
        strings = byte_arrays_to_string(data) # data contains from_addr, msg_size, [args]
        map(txdata.append, strings)
        self.dcp_list[to_addr].data = serpent.encode_datalist(txdata)
        self.dcp_list[to_addr].sign(privkey)


    def verify_dc_sig(self, sig, msghash, msgsize, from_addr, data):
        # data comes in as array of byte array (bytes as ints, from js)
        tohash = byte_arrays_to_string(data)
        assert (msghash == utils.sha3(tohash))
        X, Y = ecdsa_raw_recover(msghash, sig)
        pX = utils.int_to_big_endian(X).encode('hex')
        pY = utils.int_to_big_endian(Y).encode('hex')
        pub = '04'+pX+pY
        return ecdsa_raw_verify(msghash, sig, pub.decode('hex'))
        
        # replace dcp transaction
    
    def unpackage_dc(self, dc):
        print dc
        nonce = dc['nonce']
        to_addr = dc['to_addr']
        from_addr = dc['from_addr']
        sig = int(dc['v'], 16), int(dc['r'], 16), int(dc['s'], 16)
        msghash = str(dc['hash']).decode('hex')
        msgsize = dc['msgsize']
        data = dc['data']
        return nonce, to_addr, from_addr, sig, msghash, msgsize, data

    def handle_new_dc(self, dc):
        nonce, to_addr, from_addr, sig, msghash, msgsize, data = self.unpackage_dc(dc)
        print data
        if self.dcp_list.has_key(to_addr):
            print 'addr exists! adding dc'
            self._add_dc_to_dcp(to_addr, from_addr, sig, msghash, msgsize, data)
        elif self.route_risk:
            print 'addr does not exist.  adding new dcp'
            self.init_dcp(to_addr)
            self._add_dc_to_dcp(to_addr, from_addr, sig, msghash, msgsize, data)
        else:
            return

        self.remove_old_tx(to_addr)
        self.dcp_list[to_addr].nonce = self.miner.block.get_nonce(self_addr) # add nonce here since we removed a transaction (maybeS)
        success, ans = processblock.apply_tx(self.miner.block, self.dcp_list[to_addr])
        print success, ans 
        # broadcast

    def add_transaction(self, transaction):
        logger.debug("add transaction %r" % transaction)
        with self.lock:
            res = self.miner.add_transaction(transaction)
            if res:
                logger.debug("broadcasting valid %r" % transaction)
                signals.send_local_transactions.send(
                    sender=None, transactions=[transaction])

    def get_transactions(self):
        logger.debug("get_transactions called")
        return self.miner.get_transactions()

    def get_chain(self, start='', count=256):
        "return 'count' blocks starting from head or start"
        logger.debug("get_chain: start:%s count%d", start.encode('hex'), count)
        blocks = []
        block = self.head
        if start:
            if start not in self:
                return []
            block = self.get(start)
            if not self.in_main_branch(block):
                return []
        for i in range(count):
            blocks.append(block)
            if block.is_genesis():
                break
            block = block.get_parent()
        return blocks

    def in_main_branch(self, block):
        if block.is_genesis():
            return True
        return block == self.get_descendents(block.get_parent(), count=1)[0]

    def get_descendents(self, block, count=1):
        logger.debug("get_descendents: %r ", block)
        assert block.hash in self
        # FIXME inefficient implementation
        res = []
        cur = self.head
        while cur != block:
            res.append(cur)
            if cur.has_parent():
                cur = cur.get_parent()
            else:
                break
            if cur.number == block.number and cur != block:
                # no descendents on main branch
                logger.debug("no descendents on main branch for: %r ", block)
                return []
        res.reverse()
        return res[:count]

    def log_chain(self):
        num = self.head.number + 1
        for b in reversed(self.get_chain(count=num)):
            logger.debug(b)
            for tx in b.get_transactions():
                logger.debug('\t%r', tx)


chain_manager = ChainManager()


@receiver(signals.local_chain_requested)
def handle_local_chain_requested(sender, peer, blocks, count, **kwargs):
    """
    [0x14, Parent1, Parent2, ..., ParentN, Count]
    Request the peer to send Count (to be interpreted as an integer) blocks
    in the current canonical block chain that are children of Parent1
    (to be interpreted as a SHA3 block hash). If Parent1 is not present in
    the block chain, it should instead act as if the request were for Parent2
    &c.  through to ParentN.

    If none of the parents are in the current
    canonical block chain, then NotInChain should be sent along with ParentN
    (i.e. the last Parent in the parents list).

    If the designated parent is the present block chain head,
    an empty reply should be sent.

    If no parents are passed, then reply need not be made.
    """
    logger.debug(
        "local_chain_requested: %r %d",
        [b.encode('hex') for b in blocks], count)
    res = []
    for i, b in enumerate(blocks):
        if b in chain_manager:
            block = chain_manager.get(b)
            logger.debug("local_chain_requested: found: %r", block)
            res = chain_manager.get_descendents(block, count=count)
            if res:
                logger.debug("sending: found: %r ", res)
                res = [rlp.decode(b.serialize()) for b in res]  # FIXME
                # if b == head: no descendents == no reply
                with peer.lock:
                    peer.send_Blocks(res)
                return

    if len(blocks):
        #  If none of the parents are in the current
        logger.debug("Sending NotInChain: %r", blocks[-1].encode('hex')[:4])
        peer.send_NotInChain(blocks[-1])
    else:
        # If no parents are passed, then reply need not be made.
        pass


@receiver(signals.config_ready)
def config_chainmanager(sender, config, **kwargs):
    chain_manager.configure(config)


@receiver(signals.peer_handshake_success)
def new_peer_connected(sender, peer, **kwargs):
    logger.debug("received new_peer_connected")
    # request transactions
    with peer.lock:
        logger.debug("send get transactions")
        peer.send_GetTransactions()
    # request chain
    blocks = [b.hash for b in chain_manager.get_chain(count=256)]
    with peer.lock:
        peer.send_GetChain(blocks, count=256)
        logger.debug("send get chain %r", [b.encode('hex') for b in blocks])


@receiver(signals.remote_transactions_received)
def remote_transactions_received_handler(sender, transactions, **kwargs):
    "receives rlp.decoded serialized"
    txl = [Transaction.deserialize(rlp.encode(tx)) for tx in transactions]
    logger.debug('remote_transactions_received: %r', txl)
    for tx in txl:
        chain_manager.add_transaction(tx)


@receiver(signals.local_transaction_received)
def local_transaction_received_handler(sender, transaction, **kwargs):
    "receives transaction object"
    logger.debug('local_transaction_received: %r', transaction)
    chain_manager.add_transaction(transaction)


@receiver(signals.gettransactions_received)
def gettransactions_received_handler(sender, peer, **kwargs):
    transactions = chain_manager.get_transactions()
    transactions = [rlp.decode(x.serialize()) for x in transactions]
    peer.send_Transactions(transactions)

@receiver(signals.dao_command_received)
def dao_command_received_handler(sender, dao_command, **kwargs):
    chain_manager.handle_new_dc(dao_command)

@receiver(signals.remote_blocks_received)
def remote_blocks_received_handler(sender, block_lst, peer, **kwargs):
    logger.debug("received %d remote blocks", len(block_lst))

    old_head = chain_manager.head
    # assuming chain order w/ newest block first
    for block_data in reversed(block_lst):
        try:
            block = blocks.Block.deserialize(rlp.encode(block_data))
        except blocks.UnknownParentException:
            # no way to ask peers for older parts of chain
            bhash = utils.sha3(rlp.encode(block_data)).encode('hex')[:4]
            phash = block_data[0][0].encode('hex')[:4]
            number = utils.decode_int(block_data[0][6])
            if phash == blocks.GENESIS_PREVHASH:
                logger.debug('Incompatible Genesis %r', block)
                peer.send_Disconnect(reason='Wrong genesis block')
            else:
                logger.debug('Block(#%d %s %s) with unknown parent, requesting ...',
                         number, bhash, phash.encode('hex')[:4])
                chain_manager.synchronize_blockchain()
            break
        if block.hash in chain_manager:
            logger.debug('Known %r', block)
        else:
            if block.has_parent():
                # add block & set HEAD if it's longest chain
                success = chain_manager.add_block(block)
                if success:
                    logger.debug('Added %r', block)
            else:
                logger.debug('Orphant %r', block)
    if chain_manager.head != old_head:
        chain_manager.synchronize_blockchain()
