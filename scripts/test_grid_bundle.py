import urllib.request
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0'
}

def analyze():
    b_req = urllib.request.Request('https://grid-india.in/assets/index-BYJJycyS.js', headers=headers)
    with urllib.request.urlopen(b_req, context=ctx, timeout=15) as b_resp:
        bundle = b_resp.read().decode('utf-8', errors='ignore')
    
    print("Bundle size:", len(bundle))
    # Look for http, baseUrl, psp, uploads, etc.
    matches = set()
    for m in re.findall(r'["\'](https?://[^"\']+|/[^"\']+)["\']', bundle):
        if any(k in m.lower() for k in ['psp', 'report', 'delhi', 'grid', 'upload', 'pdf', 'excel', 'json']):
            matches.add(m)
    print("Matches:")
    for m in sorted(list(matches))[:25]:
        print(" ", m)

if __name__ == '__main__':
    analyze()
