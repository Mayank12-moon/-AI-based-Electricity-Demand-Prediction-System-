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

# Search for webapi.grid-india.in context
endpoints = set()
for m in re.finditer(r'webapi\.grid-india\.in/api/v1/([a-zA-Z0-9_\-/]+)', text):
    endpoints.add(m.group(1))

print(f"Found {len(endpoints)} webapi endpoints:")
for ep in sorted(endpoints):
    print(" ", ep)

# Also search for relative endpoints if baseURL is set
for m in re.finditer(r'baseURL:\s*["\']([^"\']+)["\']', text):
    print("BaseURL:", m.group(1))
