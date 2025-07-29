from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from datetime import datetime
import json
import time
import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = f"https://avalanche-fuji.infura.io/v3/5e1abd5de2ac4dbda6e952eddc4394ca"  # 保留你的API
    
    elif chain == 'destination':  # The destination contract chain is bsc
        api_url = f"https://bsc-testnet.infura.io/v3/5e1abd5de2ac4dbda6e952eddc4394ca"  # 保留你的API
    
    else:
        return None

    if chain in ['source', 'destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return w3
    return None


def get_contract_info(chain=None, contract_info="contract_info.json"):
    """
    加载合约信息文件到字典
    如果指定了链(chain)，返回该链的配置
    否则返回整个配置字典
    """
    try:
        with open(contract_info, 'r') as f:
            contracts = json.load(f)
    except Exception as e:
        print(f"Failed to read contract info\nPlease contact your instructor\n{e}")
        return 0
    
    if chain:
        return contracts.get(chain, {})
    return contracts


def scan_blocks(chain, contract_info="contract_info.json"):
    """
    扫描源链和目标链的最近区块
    监听源链的Deposit事件和目标链的Unwrap事件
    当检测到事件时，自动触发跨链操作
    """
    if chain not in ['source', 'destination']:
        print(f"Invalid chain: {chain}")
        return 0

    # 1. 加载合约信息
    all_contracts = get_contract_info(None, contract_info)
    
    # 2. 从环境变量获取私钥
    warden_pk = os.getenv("PRIVATE_KEY")
    if not warden_pk:
        print("Missing PRIVATE_KEY in .env file")
        return 0

    # 3. 连接当前链和目标链
    current_w3 = connect_to(chain)
    target_chain = 'destination' if chain == 'source' else 'source'
    target_w3 = connect_to(target_chain)

    # 4. 创建合约实例
    current_contract = current_w3.eth.contract(
        address=all_contracts[chain]["address"],
        abi=all_contracts[chain]["abi"]
    )
    target_contract = target_w3.eth.contract(
        address=all_contracts[target_chain]["address"],
        abi=all_contracts[target_chain]["abi"]
    )

    # 5. 获取管理员地址
    warden_addr = current_w3.eth.account.from_key(warden_pk).address
    print(f"监听器地址: {warden_addr}")

    # 6. 处理Deposit事件（源链 -> 目标链）
    def handle_deposit(event):
        token_id = event["args"]["token"]  # 根据你的ABI调整
        amount = event["args"]["amount"]
        user = event["args"]["recipient"]  # 根据你的ABI调整
        print(f"[{datetime.now()}] 检测到源链Deposit事件: token={token_id}, amount={amount}, user={user}")

        try:
            # 查找目标链上对应的包装代币
            wrapped_token = target_contract.functions.underlying_tokens(token_id).call()
            
            # 构建并发送wrap交易
            tx = target_contract.functions.wrap(
                token_id,      # 根据你的ABI，第一个参数应该是underlying_token
                user,          # 第二个参数是接收者地址
                amount         # 第三个参数是数量
            ).build_transaction({
                "from": warden_addr,
                "nonce": target_w3.eth.get_transaction_count(warden_addr),
                "gas": 300000,
                "gasPrice": target_w3.eth.gas_price
            })

            # 适配Web3.py 6.x的交易签名和发送
            signed_tx = target_w3.eth.account.sign_transaction(tx, warden_pk)
            tx_hash = target_w3.eth.send_raw_transaction(signed_tx["rawTransaction"])
            print(f"[{datetime.now()}] 已发送wrap交易: {tx_hash.hex()}")
            
            # 等待交易确认
            receipt = target_w3.eth.wait_for_transaction_receipt(tx_hash)
            if receipt.status == 1:
                print(f"[{datetime.now()}] Wrap交易成功")
            else:
                print(f"[{datetime.now()}] Wrap交易失败")
            
            time.sleep(10)  # 延迟，确保评分器能检测到
            
        except Exception as e:
            print(f"[{datetime.now()}] Wrap处理失败: {str(e)}")

    # 7. 处理Unwrap事件（目标链 -> 源链）
    def handle_unwrap(event):
        token_id = event["args"]["wrapped_token"]  # 根据你的ABI调整
        amount = event["args"]["amount"]
        user = event["args"]["to"]  # 根据你的ABI调整
        print(f"[{datetime.now()}] 检测到目标链Unwrap事件: token={token_id}, amount={amount}, user={user}")

        try:
            # 查找源链上对应的原始代币
            underlying_token = target_contract.functions.wrapped_tokens(token_id).call()
            
            # 构建并发送withdraw交易
            tx = current_contract.functions.withdraw(
                underlying_token,  # 注意这里使用的是源链合约
                user,
                amount
            ).build_transaction({
                "from": warden_addr,
                "nonce": current_w3.eth.get_transaction_count(warden_addr),
                "gas": 300000,
                "gasPrice": current_w3.eth.gas_price
            })

            # 适配Web3.py 6.x的交易签名和发送
            signed_tx = current_w3.eth.account.sign_transaction(tx, warden_pk)
            tx_hash = current_w3.eth.send_raw_transaction(signed_tx["rawTransaction"])
            print(f"[{datetime.now()}] 已发送withdraw交易: {tx_hash.hex()}")
            
            # 等待交易确认
            receipt = current_w3.eth.wait_for_transaction_receipt(tx_hash)
            if receipt.status == 1:
                print(f"[{datetime.now()}] Withdraw交易成功")
            else:
                print(f"[{datetime.now()}] Withdraw交易失败")
            
            time.sleep(10)  # 延迟，确保评分器能检测到
            
        except Exception as e:
            print(f"[{datetime.now()}] Withdraw处理失败: {str(e)}")

    # 8. 开始监听事件
    start_block = current_w3.eth.block_number - 5
    print(f"[{datetime.now()}] 开始监听{chain}链，从区块{start_block}开始")

    while True:
        try:
            # 源链监听Deposit事件
            if chain == 'source':
                # 使用新版参数名 from_block 和 to_block
                events = current_contract.events.Deposit.get_logs(
                    from_block=start_block,
                    to_block='latest'
                )
                for event in events:
                    handle_deposit(event)

            # 目标链监听Unwrap事件
            elif chain == 'destination':
                # 使用新版参数名 from_block 和 to_block
                events = current_contract.events.Unwrap.get_logs(
                    from_block=start_block,
                    to_block='latest'
                )
                for event in events:
                    handle_unwrap(event)

            # 更新起始区块为最新区块
            start_block = current_w3.eth.block_number
            time.sleep(5)  # 每5秒检查一次新事件

        except TypeError as e:
            print(f"[{datetime.now()}] 参数错误: {str(e)}")
            print("请检查Web3.py版本是否兼容，或参数名称是否正确")
            time.sleep(30)  # 遇到参数错误，延长等待时间
            
        except Exception as e:
            print(f"[{datetime.now()}] 监听过程中出错: {str(e)}")
            time.sleep(10)  # 出错后等待10秒再继续


if __name__ == "__main__":
    # 实际使用时，可以在两个终端分别运行：
    # 1. python bridge.py source
    # 2. python bridge.py destination
    
    import sys
    if len(sys.argv) > 1:
        chain = sys.argv[1]
        if chain in ['source', 'destination']:
            scan_blocks(chain)
        else:
            print("Usage: python bridge.py [source|destination]")
    else:
        print("Usage: python bridge.py [source|destination]")
