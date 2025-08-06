from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from dotenv import load_dotenv
import os
import json
import time

load_dotenv()

def connect_to(chain):
    if chain == 'source':  # AVAX Testnet
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
    elif chain == 'destination':  # BSC Testnet
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
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
    return contracts.get(chain)

def handle_source():
    chain = 'source'
    PRIVATE_KEY = os.getenv("PRIVATE_KEY")
    if not PRIVATE_KEY:
        print("Missing private key in .env file")
        return
    acct = Account.from_key(PRIVATE_KEY)

    w3 = connect_to(chain)
    w3_other = connect_to('destination')

    this_info = get_contract_info(chain)
    other_info = get_contract_info('destination')
    if not this_info or not other_info:
        print("Failed to load contract info")
        return

    contract = w3.eth.contract(address=this_info["address"], abi=this_info["abi"])
    other_contract = w3_other.eth.contract(address=other_info["address"], abi=other_info["abi"])

    latest_block = w3.eth.block_number
    from_block = max(0, latest_block - 5)
    to_block = latest_block

    print(f"\n>>> Scanning {chain} blocks from {from_block} to {to_block}")

    nonce = w3_other.eth.get_transaction_count(acct.address)

    # 监听 Deposit 事件，触发 wrap 交易
    event_filter = contract.events.Deposit.create_filter(from_block=from_block, to_block=to_block)
    events = event_filter.get_all_entries()
    for e in events:
        token = e["args"]["token"]
        recipient = e["args"]["recipient"]
        amount = e["args"]["amount"]
        print(f"[SOURCE] Detected Deposit | Token: {token} | Recipient: {recipient} | Amount: {amount}")

        tx = other_contract.functions.wrap(token, recipient, amount).build_transaction({
            'chainId': w3_other.eth.chain_id,
            'gas': 500000,
            'gasPrice': w3_other.eth.gas_price,
            'nonce': nonce
        })
        signed_tx = w3_other.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3_other.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"[DESTINATION] Sent wrap() tx: {tx_hash.hex()}")

        receipt = w3_other.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            print("[DESTINATION] wrap() transaction confirmed.")
        else:
            print("[DESTINATION] wrap() transaction failed.")

        nonce += 1

    # 监听 Withdrawal 事件，调试用，非必须，但方便验证事件触发
    withdrawal_filter = contract.events.Withdrawal.create_filter(from_block=from_block, to_block=to_block)
    withdrawals = withdrawal_filter.get_all_entries()
    for w in withdrawals:
        print(f"[SOURCE] Withdrawal event detected: Token {w['args']['token']} Recipient {w['args']['recipient']} Amount {w['args']['amount']}")

def handle_destination():
    chain = 'destination'
    PRIVATE_KEY = os.getenv("PRIVATE_KEY")
    if not PRIVATE_KEY:
        print("Missing private key in .env file")
        return
    acct = Account.from_key(PRIVATE_KEY)

    w3 = connect_to(chain)
    w3_other = connect_to('source')

    this_info = get_contract_info(chain)
    other_info = get_contract_info('source')
    if not this_info or not other_info:
        print("Failed to load contract info")
        return

    contract = w3.eth.contract(address=this_info["address"], abi=this_info["abi"])
    other_contract = w3_other.eth.contract(address=other_info["address"], abi=other_info["abi"])

    latest_block = w3.eth.block_number
    from_block = max(0, latest_block - 5)
    to_block = latest_block

    print(f"\n>>> Scanning {chain} blocks from {from_block} to {to_block}")

    nonce = w3_other.eth.get_transaction_count(acct.address)

    # 监听 Unwrap 事件，触发 withdraw 交易
    event_filter = contract.events.Unwrap.create_filter(from_block=from_block, to_block=to_block)
    events = event_filter.get_all_entries()
    for e in events:
        token = e["args"]["underlying_token"]
        recipient = e["args"]["to"]
        amount = e["args"]["amount"]
        print(f"[DESTINATION] Detected Unwrap | Token: {token} | Recipient: {recipient} | Amount: {amount}")

        tx = other_contract.functions.withdraw(token, recipient, amount).build_transaction({
            'chainId': w3_other.eth.chain_id,
            'gas': 500000,
            'gasPrice': w3_other.eth.gas_price,
            'nonce': nonce
        })
        signed_tx = w3_other.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
        tx_hash = w3_other.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"[SOURCE] Sent withdraw() tx: {tx_hash.hex()}")

        receipt = w3_other.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            print("[SOURCE] withdraw() transaction confirmed.")
        else:
            print("[SOURCE] withdraw() transaction failed.")

        nonce += 1

if __name__ == "__main__":
    handle_source()
    time.sleep(3)  # 等待几秒，避免 nonce 重复或交易拥堵
    handle_destination()
