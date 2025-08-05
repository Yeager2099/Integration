from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from dotenv import load_dotenv
import os
import json

load_dotenv()

def connect_to(chain):
    if chain == 'source':  # AVAX Testnet
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc"
    elif chain == 'destination':  # BSC Testnet
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/"
    else:
        raise Exception("Unknown chain name.")

    w3 = Web3(Web3.HTTPProvider(api_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info="contract_info.json"):
    try:
        with open(contract_info, 'r') as f:
            contracts = json.load(f)
    except Exception as e:
        print(f"Failed to read contract info:\n{e}")
        return None
    return contracts[chain]


def scan_blocks(chain, contract_info="contract_info.json"):
    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return

    # Load credentials
    PRIVATE_KEY = os.getenv("Private key")
    if not PRIVATE_KEY:
        print("Missing private key in .env file")
        return
    acct = Account.from_key(PRIVATE_KEY)

    # Connect to current and opposite chains
    w3 = connect_to(chain)
    w3_other = connect_to('destination' if chain == 'source' else 'source')

    # Load contracts
    this_info = get_contract_info(chain, contract_info)
    other_info = get_contract_info('destination' if chain == 'source' else 'source', contract_info)
    if not this_info or not other_info:
        print("Failed to load contract info")
        return

    contract = w3.eth.contract(address=this_info["address"], abi=this_info["abi"])
    other_contract = w3_other.eth.contract(address=other_info["address"], abi=other_info["abi"])

    # Block range for scanning
    latest_block = w3.eth.block_number
    from_block = max(0, latest_block - 5)
    to_block = latest_block

    print(f"\n>>> Scanning {chain} blocks {from_block} to {to_block}")

    if chain == 'source':
        # Handle Deposit -> wrap on destination
        events = contract.events.Deposit().get_logs(fromBlock=from_block, toBlock=to_block)
        for e in events:
            token = e["args"]["token"]
            recipient = e["args"]["recipient"]
            amount = e["args"]["amount"]
            print(f"[SOURCE] Detected Deposit | Token: {token} | Recipient: {recipient} | Amount: {amount}")

            nonce = w3_other.eth.get_transaction_count(acct.address)
            tx = other_contract.functions.wrap(token, recipient, amount).build_transaction({
                'chainId': w3_other.eth.chain_id,
                'gas': 500000,
                'gasPrice': w3_other.eth.gas_price,
                'nonce': nonce
            })
            signed_tx = w3_other.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = w3_other.eth.send_raw_transaction(signed_tx.rawTransaction)
            print(f"[DESTINATION] Sent wrap() tx: {tx_hash.hex()}")

    elif chain == 'destination':
        # Handle Unwrap -> withdraw on source
        events = contract.events.Unwrap().get_logs(fromBlock=from_block, toBlock=to_block)
        for e in events:
            token = e["args"]["underlying_token"]
            recipient = e["args"]["to"]
            amount = e["args"]["amount"]
            print(f"[DESTINATION] Detected Unwrap | Token: {token} | Recipient: {recipient} | Amount: {amount}")

            nonce = w3_other.eth.get_transaction_count(acct.address)
            tx = other_contract.functions.withdraw(token, recipient, amount).build_transaction({
                'chainId': w3_other.eth.chain_id,
                'gas': 500000,
                'gasPrice': w3_other.eth.gas_price,
                'nonce': nonce
            })
            signed_tx = w3_other.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
            tx_hash = w3_other.eth.send_raw_transaction(signed_tx.rawTransaction)
            print(f"[SOURCE] Sent withdraw() tx: {tx_hash.hex()}")


if __name__ == "__main__":
    scan_blocks('source')      # handle AVAX->BSC
    scan_blocks('destination') # handle BSC->AVAX
