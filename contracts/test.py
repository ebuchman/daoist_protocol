import serpent
from pyethereum import transactions, blocks, processblock, utils
import bitcoin

key = utils.sha3('aimfesidfd')
addr = utils.privtoaddr(key)

def pad32(n):
	if type(n) ==str:
		h = n.encode('hex')
	else:
		h = "%02x"%n
	l = len(h)
	return "0"*(32-l)+h

nargs = pad32(1)
d0 = pad32('hi')
print nargs, d0
msg_hash = utils.sha3(nargs+d0)
v, r, s = bitcoin.ecdsa_raw_sign(msg_hash, key)
pubkey = bitcoin.privkey_to_pubkey(key)
verified = bitcoin.ecdsa_raw_verify(msg_hash, (v,r,s), pubkey)

gen = blocks.genesis({addr: 10**18})

print serpent.compile_to_assembly(open("DAOist.se").read())
DAOcode = serpent.compile(open("DAOist.se").read())

DAOcontract = transactions.contract(0, 1, 10**12, 100, DAOcode)

DAOcontract.sign(key)

success, contract_address = processblock.apply_tx(gen, DAOcontract)

DCP = transactions.Transaction(1,10**12, 10000, contract_address, 0, serpent.encode_datalist([1,1,v,r,s,1,'hi']))
DCP.sign(key)

success, result = processblock.apply_tx(gen, DCP)

print "success: ", success
print serpent.decode_datalist(result)
