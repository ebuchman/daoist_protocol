import time
import serpent
from pyethereum import transactions, blocks, processblock, utils
import bitcoin


key = utils.sha3('cows')
addr = utils.privtoaddr(key)

gen = blocks.genesis({addr: 10**60})
assembly = serpent.compile_to_assembly(open('tester.se').read())

code = serpent.assemble(assembly)

msg_hash = utils.sha3('heres a message')
v, r, s = bitcoin.ecdsa_raw_sign(msg_hash, key)
pub = bitcoin.privkey_to_pubkey(key)
verified = bitcoin.ecdsa_raw_verify(msg_hash, (v, r, s), pub)

tx_make_root = transactions.contract(0,10,10**30, 10**30, code).sign(key)
success, root_contract = processblock.apply_tx(gen, tx_make_root)

tx_init_root = transactions.Transaction(1, 100, 10**40, root_contract, 0, serpent.encode_datalist([msg_hash, v, r, s])).sign(key)
print assembly
success, ans = processblock.apply_tx(gen, tx_init_root)
data = serpent.decode_datalist(ans)
print 'raw decoded data:', data
print 'data as hex:'
print map(hex, data)
#print ('%02x'%data).decode('hex')
print assembly
print data
