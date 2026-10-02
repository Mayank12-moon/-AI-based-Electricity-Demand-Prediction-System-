import urllib.request
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {'User-Agent': 'Mozilla/5.0'}

req = urllib.request.Request('https://grid-india.in/assets/index-BYJJycyS.js', headers=headers)
with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
    text = resp.read().decode('utf-8', errors='ignore')

# Find dynamic import chunks (.js)
chunks = re.findall(r'assets/[a-zA-Z0-9_\-]+\.js', text)
print(f"Found {len(chunks)} chunk references:")
for c in set(chunks):
    print(" ", c)
