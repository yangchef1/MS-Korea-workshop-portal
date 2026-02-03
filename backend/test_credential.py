from azure.identity import AzureCliCredential

try:
    c = AzureCliCredential()
    t = c.get_token("https://management.azure.com/.default")
    print(f"Token acquired successfully! Token starts with: {t.token[:20]}...")
except Exception as e:
    print(f"Error: {e}")
