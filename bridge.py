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
        # Load contracts
        source_contract = w3.eth.contract(
            address=contracts['source']['address'],
            abi=contracts['source']['abi']
        )
        destination_contract = w3.eth.contract(
            address=contracts['destination']['address'],
            abi=contracts['destination']['abi']
        )

        # Create filters for Deposit and Unwrap events
        deposit_filter = source_contract.events.Deposit.createFilter(fromBlock='latest')
        unwrap_filter = destination_contract.events.Unwrap.createFilter(fromBlock='latest')

        # Scan events using the filter
        while True:
            # Get the logs for Deposit events on source chain
            deposit_logs = deposit_filter.get_new_entries()
            for log in deposit_logs:
                try:
                    event = source_contract.events.Deposit().processLog(log)
                    print(f"Deposit event found: {event['args']}")
                    
                    # Call wrap on destination chain
                    dest_w3 = connect_to('destination')
                    if dest_w3:
                        dest_contract = dest_w3.eth.contract(
                            address=contracts['destination']['address'],
                            abi=contracts['destination']['abi']
                        )
                        tx_hash = dest_contract.functions.wrap(
                            event['args']['token'],
                            event['args']['recipient'],
                            event['args']['amount']
                        ).transact({
                            'from': dest_w3.eth.default_account,
                            'gas': 300000,
                            'gasPrice': Web3.to_wei('10', 'gwei')
                        })
                        print(f"Wrap tx sent: {tx_hash.hex()}")
                except Exception as e:
                    print(f"Error processing Deposit: {str(e)}")
                    continue

            # Get the logs for Unwrap events on destination chain
            unwrap_logs = unwrap_filter.get_new_entries()
            for log in unwrap_logs:
                try:
                    event = destination_contract.events.Unwrap().processLog(log)
                    print(f"Unwrap event found: {event['args']}")
                    
                    # Call withdraw on source chain
                    src_w3 = connect_to('source')
                    if src_w3:
                        src_contract = src_w3.eth.contract(
                            address=contracts['source']['address'],
                            abi=contracts['source']['abi']
                        )
                        tx_hash = src_contract.functions.withdraw(
                            event['args']['underlying_token'],
                            event['args']['to'],
                            event['args']['amount']
                        ).transact({
                            'from': src_w3.eth.default_account,
                            'gas': 300000,
                            'gasPrice': Web3.to_wei('10', 'gwei')
                        })
                        print(f"Withdraw tx sent: {tx_hash.hex()}")
                except Exception as e:
                    print(f"Error processing Unwrap: {str(e)}")
                    continue
            # You can add a sleep to avoid overwhelming the node with requests
            time.sleep(5)

        return 1
        
    except Exception as e:
        print(f"Error in scan_blocks: {str(e)}")
        return 0
