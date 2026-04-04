"""Example: Export all messages from an HCS topic as JSON and CSV."""
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
topic_id = os.environ.get("HEDERA_TOPIC_ID", "0.0.1234")

client = HederaClient(operator_id, operator_key, network=network)

# --- JSON export ---
json_output = client.export_topic_messages(topic_id, fmt="json")
with open("topic_messages.json", "w", encoding="utf-8") as f:
    f.write(json_output)
print("Written: topic_messages.json")

# --- CSV export ---
csv_output = client.export_topic_messages(topic_id, fmt="csv")
with open("topic_messages.csv", "w", encoding="utf-8", newline="") as f:
    f.write(csv_output)
print("Written: topic_messages.csv")

# --- Date-range export ---
json_range = client.export_topic_messages(
    topic_id,
    start_time="2024-01-01T00:00:00Z",
    end_time="2024-12-31T23:59:59Z",
    fmt="json",
)
print(f"Messages in 2024: {__import__('json').loads(json_range)['summary']['total_messages']}")
