from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware  # Necessary for POA chains
from datetime import datetime
import json
import pandas as pd
import os


def connect_to(chain):
    if chain == 'source':  # The source contract chain is AVAX
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc"  # AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is BSC
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/"  # BSC testnet

    if chain in ['source', 'destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        # Load private key and set default account
        private_key = os.getenv("PRIVATE_KEY")
        if private_key:
            warden_account = w3.eth.account.from_key(private_key)
            w3.eth.default_account = warden_account.address
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r') as f:
            contracts = json.load(f)
            print(f"Loaded contracts: {contracts}")  # Debug output
    except Exception as e:
        print(f"Failed to read contract info\nPlease contact your instructor\n{e}")
        return 0
    return contracts.get(chain, {})


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
    if not w3.isConnected():
        print(f"Failed to connect to {chain} chain")
        return 0

    contracts = get_contract_info(chain, contract_info)
    if not contracts:
        print(f"Failed to load contract info for chain: {chain}")
        return 0

    # Load both source and destination contracts for cross-chain operations
    all_contracts = get_contract_info('all', contract_info)  # Load all contracts
    if not all_contracts:
        with open(contract_info, 'r') as f:
            all_contracts = json.load(f)

    try:
        # Get contract addresses and ABIs
        source_contract_address = all_contracts['source']['address']
        source_contract_abi = all_contracts['source']['abi']
        destination_contract_address = all_contracts['destination']['address']
        destination_contract_abi = all_contracts['destination']['abi']

        # Instantiate contracts
        source_contract = w3.eth.contract(address=source_contract_address, abi=source_contract_abi)
        destination_contract = w3.eth.contract(address=destination_contract_address, abi=destination_contract_abi)

    except KeyError as e:
        print(f"KeyError: Missing {e} in contract info")
        return 0
    except Exception as e:
        print(f"Error initializing contracts: {e}")
        return 0

    # Fetch the last 5 blocks for event scanning
    latest_block = w3.eth.blockNumber
    blocks_to_scan = [latest_block - i for i in range(5)]

    for block_number in blocks_to_scan:
        # Get block details
        try:
            block = w3.eth.getBlock(block_number, full_transactions=True)
        except Exception as e:
            print(f"Error getting block {block_number}: {e}")
            continue

        # Check for Deposit events on the source chain
        if chain == 'source':
            for tx in block.transactions:
                if tx.to and tx.to.lower() == source_contract_address.lower():
                    try:
                        receipt = w3.eth.getTransactionReceipt(tx.hash)
                        # Look for the Deposit event
                        for log in receipt.logs:
                            try:
                                event = source_contract.events.Deposit().processLog(log)
                                if event:
                                    print(f"Deposit event detected on source chain at block {block_number}")
                                    print(f"Event details: {event['args']}")
                                    
                                    # Call the 'wrap()' function on the destination contract
                                    wrap_function = destination_contract.functions.wrap(
                                        event['args']['token'],
                                        event['args']['recipient'],
                                        event['args']['amount']
                                    )
                                    tx_hash = wrap_function.transact({'from': w3.eth.default_account})
                                    print(f"Wrap transaction hash: {tx_hash.hex()}")
                            except Exception as e:
                                print(f"Error processing Deposit event: {e}")
                                continue
                    except Exception as e:
                        print(f"Error processing transaction {tx.hash.hex()}: {e}")
                        continue

        # Check for Unwrap events on the destination chain
        elif chain == 'destination':
            for tx in block.transactions:
                if tx.to and tx.to.lower() == destination_contract_address.lower():
                    try:
                        receipt = w3.eth.getTransactionReceipt(tx.hash)
                        # Look for the Unwrap event
                        for log in receipt.logs:
                            try:
                                event = destination_contract.events.Unwrap().processLog(log)
                                if event:
                                    print(f"Unwrap event detected on destination chain at block {block_number}")
                                    print(f"Event details: {event['args']}")
                                    
                                    # Call the 'withdraw()' function on the source contract
                                    withdraw_function = source_contract.functions.withdraw(
                                        event['args']['underlying_token'],
                                        event['args']['to'],
                                        event['args']['amount']
                                    )
                                    tx_hash = withdraw_function.transact({'from': w3.eth.default_account})
                                    print(f"Withdraw transaction hash: {tx_hash.hex()}")
                            except Exception as e:
                                print(f"Error processing Unwrap event: {e}")
                                continue
                    except Exception as e:
                        print(f"Error processing transaction {tx.hash.hex()}: {e}")
                        continue

    return 1
