from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()
private_key = os.getenv("PRIVATE_KEY")
if not private_key:
    raise ValueError("Private key not found in .env")

# 链配置
CHAIN_CONFIG = {
    'source': {
        'rpc': "https://api.avax-test.network/ext/bc/C/rpc",
        'name': 'AVAX'
    },
    'destination': {
        'rpc': "https://data-seed-prebsc-1-s1.binance.org:8545/",
        'name': 'BSC'
    }
}

def connect_to_chain(chain):
    """连接指定链并返回 Web3 实例和账户"""
    if chain not in CHAIN_CONFIG:
        raise ValueError(f"Unsupported chain: {chain}")
    
    w3 = Web3(Web3.HTTPProvider(CHAIN_CONFIG[chain]['rpc']))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not w3.is_connected():
        raise ConnectionError(f"Failed to connect to {CHAIN_CONFIG[chain]['name']}")
    
    account = w3.eth.account.from_key(private_key)
    w3.eth.default_account = account.address
    return w3, account

def load_contracts():
    """从 contract_info.json 加载合约信息"""
    try:
        with open('contract_info.json') as f:
            contracts = json.load(f)
        return contracts
    except Exception as e:
        raise IOError(f"Error loading contract info: {e}")

def process_deposit_event(event, dest_w3, dest_contract):
    """处理源链 Deposit 事件，调用目标链的 wrap 函数"""
    tx = dest_contract.functions.wrap(
        event['args']['token'],
        event['args']['recipient'],
        event['args']['amount']
    ).build_transaction({
        'chainId': dest_w3.eth.chain_id,
        'gas': 300000,
        'gasPrice': Web3.to_wei('10', 'gwei'),
        'nonce': dest_w3.eth.get_transaction_count(dest_w3.eth.default_account),
    })
    signed_tx = dest_w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = dest_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    print(f"Bridged to {CHAIN_CONFIG['destination']['name']}: {tx_hash.hex()}")

def process_unwrap_event(event, src_w3, src_contract):
    """处理目标链 Unwrap 事件，调用源链的 withdraw 函数"""
    tx = src_contract.functions.withdraw(
        event['args']['underlying_token'],
        event['args']['to'],
        event['args']['amount']
    ).build_transaction({
        'chainId': src_w3.eth.chain_id,
        'gas': 300000,
        'gasPrice': Web3.to_wei('10', 'gwei'),
        'nonce': src_w3.eth.get_transaction_count(src_w3.eth.default_account),
    })
    signed_tx = src_w3.eth.account.sign_transaction(tx, private_key)
    tx_hash = src_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
    print(f"Bridged back to {CHAIN_CONFIG['source']['name']}: {tx_hash.hex()}")

def scan_blocks(chain, contract_info="contract_info.json"):
    contracts = load_contracts()
    w3, _ = connect_to_chain(chain)
    
    # 设置更大的区块范围（确保覆盖测试交易）
    latest_block = w3.eth.block_number
    start_block = latest_block - 100  # 检查最近100个区块
    end_block = latest_block

    if chain == 'source':
        contract = w3.eth.contract(
            address=contracts['source']['address'],
            abi=contracts['source']['abi']
        )
        # 监听Deposit事件（添加argument_filters）
        event_filter = contract.events.Deposit.create_filter(
            from_block=start_block,
            to_block=end_block,
            argument_filters={}
        )
        events = event_filter.get_all_entries()
        print(f"Found {len(events)} Deposit events")
        
        for event in events:
            print(f"Processing Deposit: {event}")
            dest_w3, _ = connect_to_chain('destination')
            dest_contract = dest_w3.eth.contract(
                address=contracts['destination']['address'],
                abi=contracts['destination']['abi']
            )
            # 增加Gas限制和重试机制
            try:
                tx = dest_contract.functions.wrap(
                    event['args']['token'],
                    event['args']['recipient'],
                    event['args']['amount']
                ).build_transaction({
                    'chainId': dest_w3.eth.chain_id,
                    'gas': 500000,  # 提高Gas限制
                    'gasPrice': Web3.to_wei('20', 'gwei'),  # 提高Gas价格
                    'nonce': dest_w3.eth.get_transaction_count(dest_w3.eth.default_account),
                })
                signed_tx = dest_w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = dest_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                print(f"Wrap tx sent: {tx_hash.hex()}")
            except Exception as e:
                print(f"Wrap failed: {str(e)}")

    elif chain == 'destination':
        contract = w3.eth.contract(
            address=contracts['destination']['address'],
            abi=contracts['destination']['abi']
        )
        # 监听Unwrap事件
        event_filter = contract.events.Unwrap.create_filter(
            from_block=start_block,
            to_block=end_block,
            argument_filters={}
        )
        events = event_filter.get_all_entries()
        print(f"Found {len(events)} Unwrap events")
        
        for event in events:
            print(f"Processing Unwrap: {event}")
            src_w3, _ = connect_to_chain('source')
            src_contract = src_w3.eth.contract(
                address=contracts['source']['address'],
                abi=contracts['source']['abi']
            )
            try:
                tx = src_contract.functions.withdraw(
                    event['args']['underlying_token'],
                    event['args']['to'],
                    event['args']['amount']
                ).build_transaction({
                    'chainId': src_w3.eth.chain_id,
                    'gas': 500000,
                    'gasPrice': Web3.to_wei('20', 'gwei'),
                    'nonce': src_w3.eth.get_transaction_count(src_w3.eth.default_account),
                })
                signed_tx = src_w3.eth.account.sign_transaction(tx, private_key)
                tx_hash = src_w3.eth.send_raw_transaction(signed_tx.rawTransaction)
                print(f"Withdraw tx sent: {tx_hash.hex()}")
            except Exception as e:
                print(f"Withdraw failed: {str(e)}")
