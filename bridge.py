from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware  # Necessary for POA chains
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is AVAX
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc"  # AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is BSC
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/"  # BSC testnet

    if chain in ['source', 'destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r') as f:
            contracts = json.load(f)
    except Exception as e:
        print(f"Failed to read contract info\nPlease contact your instructor\n{e}")
        return 0
    return contracts[chain]


def scan_blocks(chain, contract_info="contract_info.json"):
    """
        chain - (string) should be either "source" or "destination"
        Scan the last 5 blocks of the source and destination chains
        Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain
        When Deposit events are found on the source chain, call the 'wrap' function the destination chain
        When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain
    """

    # Check if the input chain is valid
    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return 0

    # Connect to the respective chain
    w3 = connect_to(chain)
    contracts = get_contract_info(chain, contract_info)

    # Retrieve contract ABI and address from the contract_info.json
    if chain == 'source':
        source_contract_address = contracts['source_contract_address']
        source_contract_abi = contracts['source_contract_abi']
        destination_contract_address = contracts['destination_contract_address']
        destination_contract_abi = contracts['destination_contract_abi']
    else:
        source_contract_address = contracts['source_contract_address']
        source_contract_abi = contracts['source_contract_abi']
        destination_contract_address = contracts['destination_contract_address']
        destination_contract_abi = contracts['destination_contract_abi']

    # Debug: Print the source contract address to ensure it's correct
    print(f"Source contract address: {source_contract_address}")

    # Instantiate the contracts
    source_contract = w3.eth.contract(address=source_contract_address, abi=source_contract_abi)
    destination_contract = w3.eth.contract(address=destination_contract_address, abi=destination_contract_abi)

    # Fetch the last 5 blocks for event scanning
    latest_block = w3.eth.blockNumber
    blocks_to_scan = [latest_block - i for i in range(5)]

    for block_number in blocks_to_scan:
        # Get block details
        block = w3.eth.getBlock(block_number, full_transactions=True)

        # Check for Deposit events on the source chain
        if chain == 'source':
            for tx in block.transactions:
                if tx.to == source_contract_address:
                    receipt = w3.eth.getTransactionReceipt(tx.hash)
                    # Look for the Deposit event
                    for log in receipt.logs:
                        event = source_contract.events.Deposit().processLog(log)
                        if event:
                            print(f"Deposit event detected on source chain at block {block_number}")
                            # Call the 'wrap()' function on the destination contract
                            wrap_function = destination_contract.functions.wrap(event['args'].amount)
                            tx_hash = wrap_function.transact({'from': w3.eth.defaultAccount})
                            print(f"Transaction hash for wrap: {tx_hash}")

        # Check for Unwrap events on the destination chain
        if chain == 'destination':
            for tx in block.transactions:
                if tx.to == destination_contract_address:
                    receipt = w3.eth.getTransactionReceipt(tx.hash)
                    # Look for the Unwrap event
                    for log in receipt.logs:
                        event = destination_contract.events.Unwrap().processLog(log)
                        if event:
                            print(f"Unwrap event detected on destination chain at block {block_number}")
                            # Call the 'withdraw()' function on the source contract
                            withdraw_function = source_contract.functions.withdraw(event['args'].amount)
                            tx_hash = withdraw_function.transact({'from': w3.eth.defaultAccount})
                            print(f"Transaction hash for withdraw: {tx_hash}")
