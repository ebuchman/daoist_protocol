Next generation cryptocurrency network
=======================================
Ethereum Python Client + DAOist Protocol for ether-free usage of ethereum network via routers.

.. image:: https://travis-ci.org/ethereum/pyethereum.png?branch=master
   :target: https://travis-ci.org/ethereum/pyethereum

.. image:: https://coveralls.io/repos/ethereum/pyethereum/badge.png
  :target: https://coveralls.io/r/ethereum/pyethereum


Install
=========
Python2.7 is required.

pip install -r requirements.txt

see github.com/ethereum/pyethereum for more details

Features
=============
- ECRECOVER, ECVERIFY, and PUB2ADDR opcodes for recovering public key from signature, verifying signature, and getting address from pubkey
- infrastructure for routing DaoCommands from users (without ether!) to DAOs: DaoCommandPackets (in progress)
- JS scripts for sending signed DaoCommands from a user to a daoist pyethereum node
- Contracts (written in serpent) to simulate routing through the DAOist Protocol. Note that these contracts require the ecverify branch of serpent at github.com/ebuchman/serpent be installed on the system

