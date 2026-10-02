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

def download_api_response():
    url = 'https://www.delhisldc.org/dc_schedule.aspx'
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        html = resp.read().decode('utf-8', errors='ignore')

    m_vs = re.search(r'name=["\']__VIEWSTATE["\'][^>]+value=["\']([^"\']*)["\']', html)
    m_ev = re.search(r'name=["\']__EVENTVALIDATION["\'][^>]+value=["\']([^"\']*)["\']', html)
    m_vg = re.search(r'name=["\']__VIEWSTATEGENERATOR["\'][^>]+value=["\']([^"\']*)["\']', html)

    if not m_vs:
        raise ValueError("Could not find __VIEWSTATE in the page HTML. The page structure may have changed.")
    if not m_ev:
        raise ValueError("Could not find __EVENTVALIDATION in the page HTML. The page structure may have changed.")

    post_data = {
        '__EVENTTARGET': 'ctl00$ContentPlaceHolder2$GridView1',
        '__EVENTARGUMENT': 'download$0',
        '__VIEWSTATE': m_vs.group(1),
        '__VIEWSTATEGENERATOR': m_vg.group(1) if m_vg else '',
        '__EVENTVALIDATION': m_ev.group(1),
        'ctl00$ContentPlaceHolder2$SelectedDate': ''
    }
    encoded = urllib.parse.urlencode(post_data).encode('utf-8')
    post_req = urllib.request.Request(url, data=encoded, headers=headers)
    with urllib.request.urlopen(post_req, context=ctx, timeout=15) as resp:
        data = resp.read()
        print(f"Downloaded row 0: {len(data)} bytes, Content-Type: {resp.headers.get('Content-Type')}, Content-Disposition: {resp.headers.get('Content-Disposition')}")
        print("Sample data (first 500 chars):")
        try:
            text = data.decode('utf-8', errors='ignore')
            print(text[:500])
        except Exception as e:
            print("Could not decode as text:", e)

    # Also test row 1 (BRPLDS)
    post_data['__EVENTARGUMENT'] = 'download$1'
    encoded = urllib.parse.urlencode(post_data).encode('utf-8')
    post_req = urllib.request.Request(url, data=encoded, headers=headers)
    with urllib.request.urlopen(post_req, context=ctx, timeout=15) as resp:
        data_csv = resp.read()
        print(f"\nDownloaded row 1 (BRPLDS): {len(data_csv)} bytes, Content-Disposition: {resp.headers.get('Content-Disposition')}")
        text_csv = data_csv.decode('utf-8', errors='ignore')
        print("Sample CSV:\n", text_csv[:500])

if __name__ == '__main__':
    download_api_response()
