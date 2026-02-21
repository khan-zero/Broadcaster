import os
from dotenv import load_dotenv

load_dotenv()

api_id = os.getenv("TG_API_ID")
api_hash = os.getenv("TG_API_HASH")

print(f"API_ID: {api_id}")
print(f"API_HASH: {api_hash}")

if api_id and api_hash:
    print("Success: API keys loaded correctly.")
else:
    print("Error: API keys NOT found.")
