import urllib.request
import urllib.parse
import ssl
import re

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

def inspect_dc_schedule():
    url = 'https://www.delhisldc.org/dc_schedule.aspx'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='ignore')

    # Find GridView1
    m = re.search(r'<table[^>]+id=["\']ContentPlaceHolder2_GridView1["\'][^>]*>(.*?)</table>', html, re.S | re.I)
    if m:
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S | re.I)
        print(f"GridView1 rows: {len(rows)}")
        for r in rows[:6]:
            cells = [re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', ' ') for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S | re.I)]
            print("  Row:", cells)
    else:
        print("GridView1 not found")

if __name__ == '__main__':
    inspect_dc_schedule()
