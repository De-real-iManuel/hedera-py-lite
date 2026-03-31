"""Example: Send HBAR to another account using hedera-py-lite."""
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

# Recipient account — change this to a real account ID
recipient = os.environ.get("HEDERA_RECIPIENT_ID", "0.0.98")
amount_hbar = float(os.environ.get("HEDERA_TRANSFER_AMOUNT", "1.0"))

client = HederaClient(operator_id, operator_key, network=network)

print(f"Sending {amount_hbar} HBAR to {recipient} on {network}...")
tx_id = client.transfer_hbar(to=recipient, amount=amount_hbar, memo="hedera-py-lite example")

print(f"Transaction ID : {tx_id}")
print("Transfer submitted successfully.")
