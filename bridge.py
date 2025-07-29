from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
import os
import csv
from dotenv import load_dotenv

# 初始化环境
load_dotenv()
private_key = os.getenv("PRIVATE_KEY")
if not private_key:
    raise ValueError("PRIVATE_KEY not found in .env")

# 链配置
CHAIN_CONFIG = {
    'source': {
        'rpc': "https://api.avax-test.network/ext/bc/C/rpc",
        'name': 'AVAX',
        'explorer': 'https://testnet.snowtrace.io/tx/'
    },
    'destination': {
        'rpc': "https://data-seed-prebsc-1-s1.binance.org:8545/",
        'name': 'BSC',
        'explorer': 'https://testnet.bscscan.com/tx/'
    }
}

def connect_to_chain(chain):
    """连接区块链并返回Web3实例和账户"""
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
    """加载合约信息"""
    try:
        with open('contract_info.json') as f:
            return json.load(f)
    except Exception as e:
        raise IOError(f"Error loading contract_info.json: {e}")

def load_tokens():
    """加载代币映射"""
    try:
        with open('erc20s.csv') as f:
            return list(csv.reader(f))
    except Exception as e:
        raise IOError(f"Error loading erc20s.csv: {e}")

def verify_token_registration():
    """验证代币是否已正确注册"""
    contracts = load_contracts()
    tokens = load_tokens()
    
    for chain in ['source', 'destination']:
        w3, _ = connect_to_chain(chain)
        contract = w3.eth.contract(
            address=contracts[chain]['address'],
            abi=contracts[chain]['abi']
        )
        
        for token in tokens:
            if chain == 'source':
                registered = contract.functions.registeredTokens(token[1]).call()
                print(f"{token[0]} on {chain}: Registered={registered}")
            else:
                exists = contract.functions.tokenMapping(token[2]).call()
                print(f"{token[0]} on {chain}: Exists={bool(exists)}")

def process_event(event, target_chain, action):
    """处理事件并发送跨链交易"""
    contracts = load_contracts()
    w3, account = connect_to_chain(target_chain)
    
    contract = w3.eth.contract(
        address=contracts[target_chain]['address'],
        abi=contracts[target_chain]['abi']
    )
    
    try:
        if action == 'wrap':
            tx = contract.functions.wrap(
                event['args']['token'],
                event['args']['recipient'],
                event['args']['amount']
            ).build_transaction({
                'chainId': w3.eth.chain_id,
                'gas': 500000,
                'gasPrice': Web3.to_wei('20', 'gwei'),
                'nonce': w3.eth.get_transaction_count(account.address),
            })
        elif action == 'withdraw':
            tx = contract.functions.withdraw(
                event['args']['underlying_token'],
                event['args']['to'],
                event['args']['amount']
            ).build_transaction({
                'chainId': w3.eth.chain_id,
                'gas': 500000,
                'gasPrice': Web3.to_wei('20', 'gwei'),
                'nonce': w3.eth.get_transaction_count(account.address),
            })
        
        signed_tx = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        
        print(f"{action.upper()} success! {CHAIN_CONFIG[target_chain]['explorer']}{tx_hash.hex()}")
        return receipt.status == 1
    except Exception as e:
        print(f"{action.upper()} failed: {str(e)}")
        return False

def scan_blocks(chain):
    """监听指定链的事件"""
    if chain not in ['source', 'destination']:
        raise ValueError("Chain must be 'source' or 'destination'")
    
    contracts = load_contracts()
    w3, _ = connect_to_chain(chain)
    contract = w3.eth.contract(
        address=contracts[chain]['address'],
        abi=contracts[chain]['abi']
    )
    
    # 监听最近200个区块确保覆盖测试交易
    latest_block = w3.eth.block_number
    start_block = max(latest_block - 200, 0)
    
    print(f"Scanning {chain} chain (blocks {start_block}-{latest_block})")
    
    if chain == 'source':
        events = contract.events.Deposit.get_logs(fromBlock=start_block)
        print(f"Found {len(events)} Deposit events")
        for event in events:
            print(f"Processing Deposit: {event}")
            process_event(event, 'destination', 'wrap')
    else:
        events = contract.events.Unwrap.get_logs(fromBlock=start_block)
        print(f"Found {len(events)} Unwrap events")
        for event in events:
            print(f"Processing Unwrap: {event}")
            process_event(event, 'source', 'withdraw')

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'verify_tokens':
        verify_token_registration()
    elif len(sys.argv) > 1 and sys.argv[1] in ['source', 'destination']:
        scan_blocks(sys.argv[1])
    else:
        print("Usage:")
        print("  python bridge.py verify_tokens  # 验证代币注册状态")
        print("  python bridge.py source        # 监听源链")
        print("  python bridge.py destination   # 监听目标链")
