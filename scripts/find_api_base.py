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

# Search for api base url
urls = re.findall(r'https?://[a-zA-Z0-9\.\-_]+(?::\d+)?(?:/[a-zA-Z0-9_\-\./]*)?', text)
filtered = [u for u in set(urls) if not any(x in u for x in ['w3.org', 'google', 'facebook', 'twitter', 'jsdelivr', 'cloudflare', 'unpkg'])]
print("Internal / Service URLs in Grid India:")
for u in filtered:
    print(" ", u)
