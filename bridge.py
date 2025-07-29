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
        # 区分源链和目标链的合约和事件
        if chain == 'source':
            contract = w3.eth.contract(
                address=contracts['source']['address'],
                abi=contracts['source']['abi']
            )
            event_name = 'Deposit'
            target_chain = 'destination'
            target_function = 'wrap'
        else:
            contract = w3.eth.contract(
                address=contracts['destination']['address'],
                abi=contracts['destination']['abi']
            )
            event_name = 'Unwrap'
            target_chain = 'source'
            target_function = 'withdraw'

        # 创建事件过滤器
        event_filter = contract.events[event_name].create_filter(fromBlock='latest')
        print(f"Started listening for {event_name} events on {chain} chain")

        while True:
            # 获取新事件
            for event in event_filter.get_new_entries():
                print(f"New {event_name} event detected: {event}")
                event_args = event['args']

                # 连接目标链
                target_w3 = connect_to(target_chain)
                if not target_w3:
                    print(f"Failed to connect to {target_chain} chain")
                    continue

                # 获取目标合约
                target_contract = target_w3.eth.contract(
                    address=contracts[target_chain]['address'],
                    abi=contracts[target_chain]['abi']
                )

                # 根据事件类型准备参数
                if event_name == 'Deposit':
                    # 调用目标链的 wrap 函数
                    tx_args = [
                        event_args['token'],       # 源链代币地址
                        event_args['recipient'],   # 接收者地址
                        event_args['amount']       # 金额
                    ]
                else:
                    # 调用源链的 withdraw 函数
                    tx_args = [
                        event_args['underlying_token'],  # 源链代币地址
                        event_args['to'],                # 接收者地址
                        event_args['amount']             # 金额
                    ]

                # 发送交易
                try:
                    # 估算 gas
                    gas_estimate = target_contract.functions[target_function](*tx_args).estimate_gas({
                        'from': target_w3.eth.default_account
                    })
                    
                    # 发送交易
                    tx_hash = target_contract.functions[target_function](*tx_args).transact({
                        'from': target_w3.eth.default_account,
                        'gas': int(gas_estimate * 1.2),  # 添加 20% 的缓冲
                        'gasPrice': Web3.to_wei('10', 'gwei')
                    })
                    
                    print(f"Sent {target_function} transaction: {tx_hash.hex()}")
                    
                except Exception as e:
                    print(f"Failed to send {target_function} transaction: {str(e)}")

            time.sleep(5)  # 避免频繁查询

        return 1
        
    except Exception as e:
        import traceback
        print(f"Error in scan_blocks: {str(e)}")
        traceback.print_exc()  # 打印完整错误堆栈
        return 0
