import time
import serpent
from pyethereum import transactions, blocks, processblock, utils
import bitcoin


key = utils.sha3('cow') # generate private key using 'brain wallet' seed (should be high entropy)
addr = utils.privtoaddr(key) # get address from private key


gen = blocks.genesis({addr: 10**60})



assembly = serpent.compile_to_assembly(open('tester.se').read())
print assembly
code = serpent.assemble(assembly)
print code


msg_hash = utils.sha3('heres a message')
v, r, s = bitcoin.ecdsa_raw_sign(msg_hash, key)
pub = bitcoin.privkey_to_pubkey(key)
verified = bitcoin.ecdsa_raw_verify(msg_hash, (v, r, s), pub)
print verified

tx_make_root = transactions.contract(0,10,10**30, 10**30, code).sign(key)
success, root_contract = processblock.apply_tx(gen, tx_make_root)

#tx_init_root = transactions.Transaction(1, 100, 10**40, root_contract, 0, serpent.encode_datalist([msg_hash, v, r, s])).sign(key)
#tx_init_root = transactions.Transaction(1, 100, 10**40, root_contract, 0, serpent.encode_datalist(['hi', 'bye'])).sign(key)
tx_init_root = transactions.Transaction(1, 100, 10**40, root_contract, 0, serpent.encode_datalist([2, '139dcd5cc79e260272e05147c349ab5f2db3f102', 1])).sign(key)
#tx_init_root = transactions.Transaction(1, 100, 10**40, root_contract, 0, serpent.encode_datalist([2, 1])).sign(key)
print assembly
success, ans = processblock.apply_tx(gen, tx_init_root)
print ans
data = serpent.decode_datalist(ans)
print data
print hex(data[0])
quit()
print ans.encode('hex')
data = serpent.decode_datalist(ans)
print 'raw decoded data:', data
print 'data as hex:'
print map(hex, data)
#print ('%02x'%data).decode('hex')
print assembly
print data
print 'correct: ' , utils.sha3('\x00'*30+'hi').encode('hex')




