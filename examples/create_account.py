"""Example: Create a new Hedera account using hedera-py-lite."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from hedera_py_lite import HederaClient

operator_id = os.environ["HEDERA_OPERATOR_ID"]
operator_key = os.environ["HEDERA_OPERATOR_KEY"]
network = os.environ.get("HEDERA_NETWORK", "testnet")

client = HederaClient(operator_id, operator_key, network=network)

print(f"Creating account on {network} with 10 HBAR initial balance...")
account_id, private_key_hex = client.create_account(initial_balance_hbar=10.0)

print(f"New account ID : {account_id}")
print(f"Private key    : {private_key_hex}")
print("Store the private key securely — it will not be shown again.")
