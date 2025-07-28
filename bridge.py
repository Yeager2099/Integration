from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
import json
import os
from dotenv import load_dotenv  # 导入dotenv模块
import time

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
        # 区分源合约和目标合约逻辑
        if chain == 'source':
            contract = w3.eth.contract(
                address=contracts['source']['address'],
                abi=contracts['source']['abi']
            )
            # 监听 Deposit 事件，触发目标链的 wrap
            event = contract.events.Deposit
            target_chain = 'destination'
            target_func = 'wrap'
        else:
            contract = w3.eth.contract(
                address=contracts['destination']['address'],
                abi=contracts['destination']['abi']
            )
            # 监听 Unwrap 事件，触发源链的 withdraw
            event = contract.events.Unwrap
            target_chain = 'source'
            target_func = 'withdraw'

        # 创建事件过滤器，从最新区块开始监听
        filter = event.create_filter(fromBlock='latest')

        while True:
            # 获取新产生的事件
            for log in filter.get_new_entries():
                # 解析事件参数
                event_args = event().process_log(log)['args']
                print(f"Caught {event.__name__} event: {event_args}")

                # 连接目标链
                target_w3 = connect_to(target_chain)
                if not target_w3:
                    continue

                # 拿到目标合约实例
                target_contract = target_w3.eth.contract(
                    address=contracts[target_chain]['address'],
                    abi=contracts[target_chain]['abi']
                )

                # 根据事件类型构造参数，调用目标函数
                if chain == 'source':
                    # Deposit 事件参数对应 wrap 函数
                    tx = target_contract.functions.wrap(
                        event_args['token'],
                        event_args['recipient'],
                        event_args['amount']
                    ).transact({
                        'from': target_w3.eth.default_account,
                        'gas': 300000,
                        'gasPrice': Web3.to_wei('10', 'gwei')
                    })
                else:
                    # Unwrap 事件参数对应 withdraw 函数
                    tx = target_contract.functions.withdraw(
                        event_args['underlying_token'],
                        event_args['to'],
                        event_args['amount']
                    ).transact({
                        'from': target_w3.eth.default_account,
                        'gas': 300000,
                        'gasPrice': Web3.to_wei('10', 'gwei')
                    })

                print(f"Sent {target_func} transaction: {tx.hex()}")

            # 避免高频请求，休眠 5 秒
            time.sleep(5)

        return 1
    except Exception as e:
        print(f"Error in scan_blocks: {str(e)}")
        return 0
