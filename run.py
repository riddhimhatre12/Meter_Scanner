"""
run.py — Meter Scanner Pro launcher.
Loads .env if present, then starts Flask in debug mode.
"""
import os
import sys

# Load .env file if it exists (simple key=value parser, no extra deps)
env_file = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and not val.startswith('your-'):
                    os.environ.setdefault(key, val)
    print('[run.py] Loaded .env')
else:
    print('[run.py] No .env found — using environment variables as-is')

gcid = os.environ.get('GOOGLE_CLIENT_ID', '')
if gcid and not gcid.startswith('your-'):
    print(f'[run.py] Google OAuth: ENABLED (client_id ends with ...{gcid[-10:]})')
else:
    print('[run.py] Google OAuth: DISABLED (GOOGLE_CLIENT_ID not set)')
    print('         Set it in .env or as an environment variable to enable Google login.')

from app import app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
