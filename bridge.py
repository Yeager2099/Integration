from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
import json
import os
import time
from dotenv import load_dotenv

# 加载环境变量（从项目根目录）
load_dotenv()

# 全局配置
GAS_LIMIT = 300000
GAS_PRICE = Web3.to_wei('10', 'gwei')

def connect_to(chain):
    """安全连接到区块链网络"""
    providers = {
        'source': 'https://api.avax-test.network/ext/bc/C/rpc',  # AVAX C-chain
        'destination': 'https://data-seed-prebsc-1-s1.binance.org:8545/'  # BSC测试网
    }
    
    # 验证链类型
    chain = chain.lower()
    if chain not in providers:
        print(f"无效的链类型: {chain}")
        return None
    
    # 建立连接
    w3 = Web3(Web3.HTTPProvider(providers[chain]))
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    
    if not w3.is_connected():
        print(f"无法连接到{chain}网络")
        return None
    
    # 加载并验证私钥
    private_key = os.getenv('PRIVATE_KEY', '').strip('"\'')
    if not private_key.startswith('0x') or len(private_key) != 66:
        print("私钥格式错误！必须是以0x开头的64个字符")
        return None
    
    try:
        account = Account.from_key(private_key)
        w3.eth.default_account = account.address
        print(f"已连接到{chain} | 账户: {account.address}")
        return w3
    except ValueError as e:
        print(f"私钥验证失败: {str(e)}")
        return None

def load_contracts():
    """加载并验证合约信息"""
    try:
        with open("contract_info.json") as f:
            contracts = json.load(f)
        
        # 地址标准化
        contracts['source']['address'] = Web3.to_checksum_address(contracts['source']['address'])
        contracts['destination']['address'] = Web3.to_checksum_address(contracts['destination']['address'])
        
        return contracts
    except Exception as e:
        print(f"加载合约失败: {str(e)}")
        return None

def send_transaction(w3, contract_function):
    """通用交易发送函数"""
    try:
        tx = contract_function.build_transaction({
            'from': w3.eth.default_account,
            'gas': GAS_LIMIT,
            'gasPrice': GAS_PRICE,
            'nonce': w3.eth.get_transaction_count(w3.eth.default_account)
        })
        
        signed_tx = w3.eth.account.sign_transaction(
            tx, 
            os.getenv('PRIVATE_KEY').strip('"\'')
        )
        tx_hash = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        print(f"交易已发送: {tx_hash.hex()}")
        
        # 等待交易确认（最多等待2分钟）
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            print("✅ 交易成功")
            return True
        print("❌ 交易失败")
        return False
    except Exception as e:
        print(f"交易错误: {str(e)}")
        return False

def scan_blocks(chain):
    """主扫描函数"""
    print(f"\n{'='*30}")
    print(f"开始扫描 {chain} 链")
    print(f"{'='*30}")
    
    try:
        # 初始化连接
        w3 = connect_to(chain)
        contracts = load_contracts()
        if not w3 or not contracts:
            return 0
            
        # 获取合约实例
        contract = w3.eth.contract(
            address=contracts[chain]['address'],
            abi=contracts[chain]['abi']
        )
        
        # 扫描最新5个区块
        latest_block = w3.eth.block_number
        from_block = max(latest_block - 5, 0)
        print(f"扫描区块 {from_block} 到 {latest_block}")
        
        # 根据链类型设置事件
        event_type = contract.events.Deposit if chain == 'source' else contract.events.Unwrap
        
        # 创建事件过滤器
        event_filter = event_type.create_filter(fromBlock=from_block, toBlock='latest')
        
        # 处理事件
        for event in event_filter.get_all_entries():
            print(f"\n发现 {event['event']} 事件:")
            print(f"区块: {event['blockNumber']}")
            print(f"参数: {event['args']}")
            
            # 连接到目标链
            target_chain = 'destination' if chain == 'source' else 'source'
            target_w3 = connect_to(target_chain)
            if not target_w3:
                print(f"无法连接到{target_chain}链")
                continue
                
            target_contract = target_w3.eth.contract(
                address=contracts[target_chain]['address'],
                abi=contracts[target_chain]['abi']
            )
            
            # 执行跨链操作
            if chain == 'source':
                # Deposit -> Wrap
                success = send_transaction(
                    target_w3,
                    target_contract.functions.wrap(
                        event['args']['token'],
                        event['args']['recipient'],
                        event['args']['amount']
                    )
                )
            else:
                # Unwrap -> Withdraw
                success = send_transaction(
                    target_w3,
                    target_contract.functions.withdraw(
                        event['args']['underlying_token'],
                        event['args']['to'],
                        event['args']['amount']
                    )
                )
            
            if not success:
                return 0
            time.sleep(1)  # 避免速率限制
            
        return 1
        
    except Exception as e:
        print(f"扫描错误: {str(e)}")
        return 0
