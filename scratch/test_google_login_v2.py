import os
import requests

def test_google_config():
    # Use absolute path to .env
    env_path = r"d:\Riddhi\Meter_Scanner\.env"
    print(f"Checking for .env at: {env_path}")
    if os.path.exists(env_path):
        print(".env file exists")
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
                    print(f"Loaded {k.strip()}")
    else:
        print(".env file does NOT exist")

    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', 'your-google-client-id')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', 'your-google-client-secret')
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    print(f"GOOGLE_CLIENT_ID: {GOOGLE_CLIENT_ID}")
    
    if GOOGLE_CLIENT_ID == 'your-google-client-id':
        print("FAIL: GOOGLE_CLIENT_ID is still the default value")
    else:
        print("SUCCESS: GOOGLE_CLIENT_ID is set")

    try:
        print(f"Attempting to fetch {GOOGLE_DISCOVERY_URL}...")
        response = requests.get(GOOGLE_DISCOVERY_URL, timeout=5)
        if response.status_code == 200:
            print("SUCCESS: Google OIDC config fetched")
        else:
            print(f"FAIL: Google OIDC config fetch returned status {response.status_code}")
    except Exception as e:
        print(f"FAIL: Failed to fetch Google OIDC config: {e}")

if __name__ == "__main__":
    test_google_config()
