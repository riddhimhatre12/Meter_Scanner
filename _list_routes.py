import re
with open('app.py', encoding='utf-8') as f:
    content = f.read()
routes = re.findall(r"@app\.route\('([^']+)'", content)
for r in routes:
    print(r)
