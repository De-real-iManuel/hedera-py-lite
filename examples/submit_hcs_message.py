"""Example: Submit a message to a Hedera Consensus Service topic using hedera-py-lite."""
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

# HCS topic ID — change this to an existing topic on your network
topic_id = os.environ.get("HEDERA_TOPIC_ID", "0.0.1234")

client = HederaClient(operator_id, operator_key, network=network)

payload = {"event": "hello", "source": "hedera-py-lite", "version": "0.1.0"}

print(f"Submitting HCS message to topic {topic_id} on testnet...")
result = client.submit_hcs_message(topic_id, payload)

if result["submitted"]:
    print(f"Topic ID        : {result['topic_id']}")
    print(f"Sequence number : {result['sequence_number']}")
    print(f"Transaction ID  : {result['tx_id']}")
else:
    print("Message submission failed — check logs for details.")
