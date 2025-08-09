from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
import os
import json
import time

# 硬编码测试网私钥（仅用于作业测试，实际项目中永远不要硬编码私钥！）
PRIVATE_KEY = "0x950dd91788d82b9ca2eb2417d2b26e9a3bea12d0f37b7b5e417ae87a1630f52c"

def connect_to(chain):
    if chain == 'source':
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
    elif chain == 'destination':
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

def scan_blocks(chain, contract_info="contract_info.json"):
    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return

    # 直接使用硬编码的私钥
    if not PRIVATE_KEY:
        print("Error: Private key not set")
        return
    acct = Account.from_key(PRIVATE_KEY)

    w3 = connect_to(chain)
    other_chain = 'destination' if chain == 'source' else 'source'
    w3_other = connect_to(other_chain)

    this_info = get_contract_info(chain, contract_info)
    other_info = get_contract_info(other_chain, contract_info)
    if not this_info or not other_info:
        print("Failed to load contract info")
        return

    contract = w3.eth.contract(address=this_info["address"], abi=this_info["abi"])
    other_contract = w3_other.eth.contract(address=other_info["address"], abi=other_info["abi"])

    latest_block = w3.eth.block_number
    from_block = max(0, latest_block - 20)  # 扫描最近20个区块
    to_block = latest_block

    print(f"\n>>> Scanning {chain} blocks from {from_block} to {to_block}")

    nonce = w3_other.eth.get_transaction_count(acct.address)

    if chain == 'source':
        event_filter = contract.events.Deposit.create_filter(from_block=from_block, to_block=to_block)
        events = event_filter.get_all_entries()
        for e in events:
            token = e["args"]["token"]
            recipient = e["args"]["recipient"]
            amount = e["args"]["amount"]
            print(f"[SOURCE] Detected Deposit | Token: {token} | Recipient: {recipient} | Amount: {amount}")

            # 检查目标链是否已注册该代币
            try:
                wrapped_token = other_contract.functions.wrapped_tokens(token).call()
                if wrapped_token == '0x0000000000000000000000000000000000000000':
                    print(f"Token {token} not registered on destination chain")
                    continue
            except Exception as e:
                print(f"Error checking token registration: {e}")
                continue

            try:
                tx = other_contract.functions.wrap(token, recipient, amount).build_transaction({
                    'chainId': w3_other.eth.chain_id,
                    'gas': 800000,
                    'gasPrice': w3_other.eth.gas_price,
                    'nonce': nonce
                })
                signed_tx = w3_other.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
                tx_hash = w3_other.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = w3_other.eth.wait_for_transaction_receipt(tx_hash)
                print(f"[DESTINATION] Wrap tx confirmed in block {receipt['blockNumber']}")
                print(f"Transaction Hash: {tx_hash.hex()}")
            except Exception as e:
                print(f"Error executing wrap: {e}")
                continue

            nonce += 1

    elif chain == 'destination':
        event_filter = contract.events.Unwrap.create_filter(from_block=from_block, to_block=to_block)
        events = event_filter.get_all_entries()
        for e in events:
            token = e["args"]["underlying_token"]
            recipient = e["args"]["to"]
            amount = e["args"]["amount"]
            print(f"[DESTINATION] Detected Unwrap | Token: {token} | Recipient: {recipient} | Amount: {amount}")

            # 检查源链是否已批准该代币
            try:
                is_approved = other_contract.functions.approved(token).call()
                if not is_approved:
                    print(f"Token {token} not approved on source chain")
                    continue
            except Exception as e:
                print(f"Error checking token approval: {e}")
                continue

            try:
                tx = other_contract.functions.withdraw(token, recipient, amount).build_transaction({
                    'chainId': w3_other.eth.chain_id,
                    'gas': 800000,
                    'gasPrice': w3_other.eth.gas_price,
                    'nonce': nonce
                })
                signed_tx = w3_other.eth.account.sign_transaction(tx, private_key=PRIVATE_KEY)
                tx_hash = w3_other.eth.send_raw_transaction(signed_tx.raw_transaction)
                receipt = w3_other.eth.wait_for_transaction_receipt(tx_hash)
                print(f"[SOURCE] Withdraw tx confirmed in block {receipt['blockNumber']}")
                print(f"Transaction Hash: {tx_hash.hex()}")
            except Exception as e:
                print(f"Error executing withdraw: {e}")
                continue

            nonce += 1

    print(">>> Scan completed")
