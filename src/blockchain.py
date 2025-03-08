import hashlib
import json
import requests
from textwrap import dedent
from time import time
from uuid import uuid4

from flask import Flask, jsonify, request
from urllib.parse import urlparse

class Blockchain(object):

    def __init__(self):
        self.chain = []
        self.current_transactions = []
        self.nodes = set()

        # Create the genesis block
        self.new_block(previous_hash=1, proof=100)

    def register_node(self, address: str) -> None:
        # Add a new node to the list of nodes
        parsed_url = urlparse(address)
        if parsed_url.netloc:
            self.nodes.add(parsed_url.netloc)
        elif parsed_url.path:
            # Accepts an URL without a scheme like "192.168.0.1:5000"
            self.nodes.add(parsed_url.path)
        else:
            raise ValueError("Invalid URL")

    def new_block(self, proof: int, previous_hash: str =None) -> dict:
        # Creates a new Block and adds it to the chain
        
        block = {
            "index": len(self.chain) + 1,
            "timestamp": time(),
            "transactions": self.current_transactions,
            "proof": proof,
            "previous_hash": previous_hash or self.hash(self.chain[-1]),
        }

        # Reset the current list of transactions
        self.current_transactions = []

        self.chain.append(block)
        return block

    def new_transaction(self, sender: str, recipient: str, amount: int) -> int:
        # Adds a new transaction to the list of transactions
        
        self.current_transactions.append({
            "sender": sender,
            "recipient": recipient,
            "amount": amount,
        })

        return self.last_block["index"] + 1

    def proof_of_work(self, last_block: dict) -> int:
        # Simple Proof of Work Algorithm:
        # - Find a number p' such that hash(pp') contains leading 4 zeroes, where p is the previous p'
        # - p is the previous proof, and p' is the new proof

        last_proof = last_block["proof"]
        last_hash = self.hash(last_block)

        proof = 0
        while self.valid_proof(last_proof, proof, last_hash) is False:
            proof += 1

        return proof
    
    def valid_chain(self, chain: list) -> bool:
        # Determine if a given blockchain is valid
        last_block = chain[0]
        current_index = 1

        while current_index < len(chain):
            block = chain[current_index]
            print(f"{last_block}")
            print(f"{block}")
            print("\n-----------\n")
            # Check that the hash of the block is correct
            last_block_hash = self.hash(last_block)
            if block["previous_hash"] != last_block_hash:
                return False
            
            # Check that the Proof of Work is correct
            if not self.valid_proof(last_block["proof"], block["proof"], last_block_hash):
                return False
            
            last_block = block
            current_index += 1
        
        return True
    
    def resolve_conflicts(self) -> bool:
        # This is the Consensus Algorithm, it resolves conflicts
        # by replacing our chain with the longest one in the network

        neighbours = self.nodes
        new_chain = None

        # We're only looking for chains longer than ours
        max_length = len(self.chain)

        # Grab and verify the chains from all the nodes in our network
        for node in neighbours:
            response = requests.get(f"http://{node}/chain")

            if response.status_code == 200:
                length = response.json()["length"]
                chain = response.json()["chain"]

                # Check if the length is longer and the chain is valid
                if length > max_length and self.valid_chain(chain):
                    max_length = length
                    new_chain = chain
        
        # Replace our chain if we discovered a new, valid chain longer than ours
        if new_chain:
            self.chain = new_chain
            return True
        
        return False

    @staticmethod
    def valid_proof(last_proof: int, proof: int, last_hash: str) -> bool:
        # Validates the Proof: Does hash(last_proof, proof) contain 4 leading zeroes?
        guess = f"{last_proof}{proof}{last_hash}".encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:6] == "000000"

    @staticmethod
    def hash(block: dict) -> str:
        # Creates a SHA-256 hash of a block
        block_string = json.dumps(block, sort_keys = True).encode()
        return hashlib.sha256(block_string).hexdigest()

    @property
    def last_block(self):
        # Returns the last Block in the chain
        return self.chain[-1]
    
# Instantiate our Node
app = Flask(__name__)

# Generate a globally unique address for this node
node_identifier = str(uuid4()).replace('-', '')

# Instantiate the Blockchain
blockchain = Blockchain()

@app.route('/mine', methods=['GET'])
def mine():
    #We run the proof of work algorithm to get the next proof...
    last_block = blockchain.last_block
    proof = blockchain.proof_of_work(last_block)

    # We must receive a reward for finding the proof
    # The sender is "0" to signify that this node has mined a new coin
    blockchain.new_transaction(
        sender="0",
        recipient=node_identifier,
        amount=1,
    )

    # Forge the new Block by adding it to the chain
    previous_hash = blockchain.hash(last_block)
    block = blockchain.new_block(proof, previous_hash)

    response = {
        "message": "New Block Forged",
        "index": block["index"],
        "transactions": block["transactions"],
        "proof": block["proof"],
        "previous_hash": block["previous_hash"],
    }
    return jsonify(response), 200

@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.get_json()

    # Check that the required fields are in the POST'ed data
    required = ["sender", "recipient", "amount"]
    if not all(field in values for field in required):
        return "Missing values", 400
    
    # Create a new Transaction
    index = blockchain.new_transaction(values["sender"], values["recipient"], values["amount"])
    response = {"message": f"Transaction will be added to Block {index}"}
    return jsonify(response), 201

@app.route('/chain', methods=['GET'])
def full_chain():
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200

@app.route('/nodes/register', methods=['POST'])
def register_nodes():
    values = request.get_json()

    nodes = values.get("nodes")
    if nodes is None:
        return "Error: Please supply a valid list of nodes", 400
    
    for node in nodes:
        blockchain.register_node(node)
    
    response = {
        "message": "New nodes have been added",
        "total_nodes": list(blockchain.nodes),
    }
    return jsonify(response), 201

@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    replaced = blockchain.resolve_conflicts()

    if replaced:
        response = {
            "message": "Our chain was replaced",
            "new_chain": blockchain.chain
        }
    else:
        response = {
            "message": "Our chain is authoritative",
            "chain": blockchain.chain
        }
    
    return jsonify(response), 200

if __name__ == '__main__':
    from argparse import ArgumentParser

    #initialize multiple nodes on different ports "python3 blockchain.py -p 500X"
    parser = ArgumentParser()
    parser.add_argument('-p', '--port', default=5000, type=int, help='port to listen on')
    args = parser.parse_args()
    port = args.port

    app.run(host='0.0.0.0', port=port)