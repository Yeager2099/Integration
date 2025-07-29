from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from datetime import datetime
import json
import time
import os
import sys
from dotenv import load_dotenv

# Load .env environment variables
load_dotenv()

# Connect to chain using Infura API URLs
def connect_to(chain):
    if chain == 'source':
        api_url = "https://avalanche-fuji.infura.io/v3/5e1abd5de2ac4dbda6e952eddc4394ca"
    elif chain == 'destination':
        api_url = "https://bsc-testnet.infura.io/v3/5e1abd5de2ac4dbda6e952eddc4394ca"
    else:
        return None

    w3 = Web3(Web3.HTTPProvider(api_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3

# Load contract info from JSON file
def get_contract_info(chain=None, contract_info="contract_info.json"):
    try:
        with open(contract_info, 'r') as f:
            contracts = json.load(f)
    except Exception as e:
        print(f"Failed to read contract_info.json: {e}")
        return 0

    if chain:
        return contracts.get(chain, {})
    return contracts

# Scan chain blocks and handle events
def scan_blocks(chain, contract_info="contract_info.json"):
    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return 0

    contracts = get_contract_info(None, contract_info)

    # Get private key
    warden_pk = os.getenv("PRIVATE_KEY")
    if not warden_pk:
        print("Missing PRIVATE_KEY in .env file")
        return 0

    # Connect to both chains
    current_w3 = connect_to(chain)
    target_chain = 'destination' if chain == 'source' else 'source'
    target_w3 = connect_to(target_chain)

    current_contract = current_w3.eth.contract(
        address=contracts[chain]["address"],
        abi=contracts[chain]["abi"]
    )

    target_contract = target_w3.eth.contract(
        address=contracts[target_chain]["address"],
        abi=contracts[target_chain]["abi"]
    )

    warden_addr = current_w3.eth.account.from_key(warden_pk).address
    print(f"🔐 Warden Address: {warden_addr}")

    # Handle Deposit Event
    def handle_deposit(event):
        token_id = event["args"]["token"]
        amount = event["args"]["amount"]
        user = event["args"]["recipient"]
        print(f"[{datetime.now()}] Deposit detected → token={token_id}, amount={amount}, user={user}")

        try:
            wrapped_token = target_contract.functions.underlying_tokens(token_id).call()

            tx = target_contract.functions.wrap(
                token_id, user, amount
            ).build_transaction({
                "from": warden_addr,
                "nonce": target_w3.eth.get_transaction_count(warden_addr),
                "gas": 300000,
                "gasPrice": target_w3.eth.gas_price
            })

            signed_tx = target_w3.eth.account.sign_transaction(tx, warden_pk)
            tx_hash = target_w3.eth.send_raw_transaction(signed_tx.raw_tx)
            print(f"🟢 Wrap transaction sent: {tx_hash.hex()}")

            receipt = target_w3.eth.wait_for_transaction_receipt(tx_hash)
            print("✅ Wrap successful" if receipt.status == 1 else "❌ Wrap failed")
            time.sleep(10)

        except Exception as e:
            print(f"❗ Wrap failed: {str(e)}")

    # Handle Unwrap Event
    def handle_unwrap(event):
        token_id = event["args"]["wrapped_token"]
        amount = event["args"]["amount"]
        user = event["args"]["to"]
        print(f"[{datetime.now()}] Unwrap detected → token={token_id}, amount={amount}, user={user}")

        try:
            underlying_token = target_contract.functions.wrapped_tokens(token_id).call()

            tx = current_contract.functions.withdraw(
                underlying_token, user, amount
            ).build_transaction({
                "from": warden_addr,
                "nonce": current_w3.eth.get_transaction_count(warden_addr),
                "gas": 300000,
                "gasPrice": current_w3.eth.gas_price
            })

            signed_tx = current_w3.eth.account.sign_transaction(tx, warden_pk)
            tx_hash = current_w3.eth.send_raw_transaction(signed_tx.raw_tx)
            print(f"🟢 Withdraw transaction sent: {tx_hash.hex()}")

            receipt = current_w3.eth.wait_for_transaction_receipt(tx_hash)
            print("✅ Withdraw successful" if receipt.status == 1 else "❌ Withdraw failed")
            time.sleep(10)

        except Exception as e:
            print(f"❗ Withdraw failed: {str(e)}")

    # Start block scanning
    start_block = current_w3.eth.block_number - 5
    print(f"📡 Scanning {chain} from block {start_block}...")

    while True:
        try:
            if chain == 'source':
                logs = current_contract.events.Deposit.get_logs(
                    from_block=start_block,
                    to_block='latest'
                )
                for log in logs:
                    handle_deposit(log)

            elif chain == 'destination':
                logs = current_contract.events.Unwrap.get_logs(
                    from_block=start_block,
                    to_block='latest'
                )
                for log in logs:
                    handle_unwrap(log)

            start_block = current_w3.eth.block_number
            time.sleep(5)

        except Exception as e:
            print(f"⚠️ Error while scanning: {str(e)}")
            time.sleep(10)

# Entrypoint
if __name__ == "__main__":
    if len(sys.argv) > 1:
        chain_arg = sys.argv[1]
        if chain_arg in ['source', 'destination']:
            scan_blocks(chain_arg)
        else:
            print("Usage: python bridge.py [source|destination]")
    else:
        print("Usage: python bridge.py [source|destination]")
