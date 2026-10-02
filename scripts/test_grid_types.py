import urllib.request
import ssl
import json

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

for test_type in ['DAILY_PSP_REPORT', 'DAILY_REPORT', 'PSP_REPORT', 'PSP', 'MONTHLY_PSP_REPORT']:
    body = json.dumps({'_source': 'GRDW', '_type': test_type}).encode('utf-8')
    req = urllib.request.Request('https://webapi.grid-india.in/api/v1/file', data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    try:
        resp = urllib.request.urlopen(req, context=ctx, timeout=8)
        res = json.loads(resp.read().decode())
        count = len(res.get("retData", []))
        print(f"Type {test_type}: {count} files")
        if count > 0:
            print("  Sample file:", res["retData"][0])
    except Exception as e:
        print(f"Type {test_type} failed: {e}")
