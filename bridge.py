from web3 import Web3
import json
import time
import sys
import os
from dotenv import load_dotenv

# 加载.env中的私钥
load_dotenv()
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# 读取ABI
with open("contract_info.json", "r") as f:
    bridge_abi = json.load(f)

# 链接设置
CHAINS = {
    "source": {
        "name": "AVAX Fuji",
        "rpc": "https://api.avax-test.network/ext/bc/C/rpc",
        "contract_address": "0x1CEbD30A2F15C33a3d6D9A10bC75d1c6Ff91A59B"
    },
    "destination": {
        "name": "BSC Testnet",
        "rpc": "https://data-seed-prebsc-1-s1.binance.org:8545/",
        "contract_address": "0x514C850B8c113f74cbB29Ee8bE8120f2a33C20e5"
    }
}

# 链接 Web3
def connect(chain_name):
    chain = CHAINS[chain_name]
    w3 = Web3(Web3.HTTPProvider(chain["rpc"]))
    assert w3.is_connected(), f"Failed to connect to {chain_name}"
    contract = w3.eth.contract(address=Web3.to_checksum_address(chain["contract_address"]), abi=bridge_abi)
    return w3, contract

# 处理 Deposit 事件
def handle_deposit(event, current_chain, target_chain):
    print(f"\n⛓️ Detected deposit event on {current_chain}:")
    print(event)
    from_addr = event["args"]["from"]
    to_addr = event["args"]["to"]
    amount = event["args"]["amount"]

    # 构造目标链交易
    target_w3, target_contract = connect(target_chain)
    warden = target_w3.eth.account.from_key(PRIVATE_KEY)
    nonce = target_w3.eth.get_transaction_count(warden.address)

    tx = target_contract.functions.wrap(from_addr, to_addr, amount).build_transaction({
        "from": warden.address,
        "nonce": nonce,
        "gas": 300000,
        "gasPrice": target_w3.to_wei("5", "gwei")
    })

    signed_tx = target_w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = target_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"✅ Wrap transaction sent to {target_chain}. Tx hash: {tx_hash.hex()}")

# 处理 Unwrap 事件
def handle_unwrap(event, current_chain, target_chain):
    print(f"\n⛓️ Detected unwrap event on {current_chain}:")
    print(event)
    from_addr = event["args"]["from"]
    to_addr = event["args"]["to"]
    amount = event["args"]["amount"]

    current_w3, current_contract = connect(current_chain)
    warden = current_w3.eth.account.from_key(PRIVATE_KEY)
    nonce = current_w3.eth.get_transaction_count(warden.address)

    tx = current_contract.functions.release(from_addr, to_addr, amount).build_transaction({
        "from": warden.address,
        "nonce": nonce,
        "gas": 300000,
        "gasPrice": current_w3.to_wei("5", "gwei")
    })

    signed_tx = current_w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = current_w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"✅ Release transaction sent to {current_chain}. Tx hash: {tx_hash.hex()}")

# 监听事件
def watch_events(chain_name):
    current_chain = chain_name
    target_chain = "destination" if current_chain == "source" else "source"

    w3, contract = connect(current_chain)

    print(f"🔍 Listening for events on {current_chain} chain...")

    last_block = w3.eth.block_number

    while True:
        try:
            new_block = w3.eth.block_number
            if new_block > last_block:
                for block_num in range(last_block + 1, new_block + 1):
                    deposit_logs = contract.events.Deposit().get_logs(from_block=block_num, to_block=block_num)
                    for event in deposit_logs:
                        handle_deposit(event, current_chain, target_chain)

                    unwrap_logs = contract.events.Unwrap().get_logs(from_block=block_num, to_block=block_num)
                    for event in unwrap_logs:
                        handle_unwrap(event, current_chain, target_chain)

                last_block = new_block

            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Error while watching events: {e}")
            time.sleep(5)

# 启动脚本
if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in CHAINS:
        print("Usage: python bridge.py [source|destination]")
        sys.exit(1)

    chain_name = sys.argv[1]
    watch_events(chain_name)
