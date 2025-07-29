from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
import json
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 获取环境变量中的 PRIVATE_KEY
private_key = os.getenv("PRIVATE_KEY")
if not private_key:
    raise ValueError("Private key is not set in the environment variables.")
else:
    print("Private key loaded successfully.")

def connect_to(chain):
    if chain == 'source':  # AVAX C-chain testnet
        api_url = "https://api.avax-test.network/ext/bc/C/rpc"
    elif chain == 'destination':  # BSC testnet
        api_url = "https://data-seed-prebsc-1-s1.binance.org:8545/"
    else:
        return None

    w3 = Web3(Web3.HTTPProvider(api_url))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not w3.is_connected():
        print(f"Failed to connect to {chain} chain")
        return None
    
    # 从环境变量中获取私钥
    private_key = os.getenv("PRIVATE_KEY")
    if private_key:
        account = w3.eth.account.from_key(private_key)
        w3.eth.default_account = account.address
    return w3


def get_contract_info(contract_info="contract_info.json"):
    try:
        with open(contract_info) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading contract info: {e}")
        return None


def scan_blocks(chain, contract_info="contract_info.json"):
    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return 0

    w3 = connect_to(chain)
    if not w3:
        return 0

    contracts = get_contract_info(contract_info)
    if not contracts:
        return 0

    try:
        # Load contracts
        source_contract = w3.eth.contract(
            address=contracts['source']['address'],
            abi=contracts['source']['abi']
        )
        destination_contract = w3.eth.contract(
            address=contracts['destination']['address'],
            abi=contracts['destination']['abi']
        )

        # 设置起始和结束区块（根据需求设置）
        start_block = w3.eth.block_number - 5  # 最近5个区块
        end_block = w3.eth.block_number

        # 使用过滤器创建监听 Deposit 事件
        deposit_filter = source_contract.events.Deposit.create_filter(
            from_block=start_block,
            to_block=end_block
        )

        # 获取所有 Deposit 事件
        for event in deposit_filter.get_all_entries():
            print(f"Deposit event found: {event.args}")
            # 处理 Deposit 事件，调用 wrap 函数
            dest_w3 = connect_to('destination')
            if dest_w3:
                dest_contract = dest_w3.eth.contract(
                    address=contracts['destination']['address'],
                    abi=contracts['destination']['abi']
                )
                tx_hash = dest_contract.functions.wrap(
                    event.args.token,
                    event.args.recipient,
                    event.args.amount
                ).transact({
                    'from': dest_w3.eth.default_account,
                    'gas': 300000,
                    'gasPrice': Web3.to_wei('10', 'gwei')
                })
                print(f"Wrap tx sent: {tx_hash.hex()}")

        # 使用过滤器创建监听 Unwrap 事件
        unwrap_filter = destination_contract.events.Unwrap.create_filter(
            from_block=start_block,
            to_block=end_block
        )

        # 获取所有 Unwrap 事件
        for event in unwrap_filter.get_all_entries():
            print(f"Unwrap event found: {event.args}")
            # 处理 Unwrap 事件，调用 withdraw 函数
            src_w3 = connect_to('source')
            if src_w3:
                src_contract = src_w3.eth.contract(
                    address=contracts['source']['address'],
                    abi=contracts['source']['abi']
                )
                tx_hash = src_contract.functions.withdraw(
                    event.args.underlying_token,
                    event.args.to,
                    event.args.amount
                ).transact({
                    'from': src_w3.eth.default_account,
                    'gas': 300000,
                    'gasPrice': Web3.to_wei('10', 'gwei')
                })
                print(f"Withdraw tx sent: {tx_hash.hex()}")

        return 1

    except Exception as e:
        print(f"Error in scan_blocks: {str(e)}")
        return 0
