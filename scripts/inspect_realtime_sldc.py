import re
# pyrefly: ignore [missing-import]

# pyrefly: ignore [missing-import]
from app.workers.sldc_worker import _fetch_url

html = _fetch_url('https://www.delhisldc.org/Redirect.aspx?Loc=0804')
if not html:
    print("Could not fetch Loc=0804")
    exit(0)

# 1. Total Delhi Load
m_load = re.search(r'id=["\']ContentPlaceHolder3_LblLoad["\'][^>]*>([^<]+)<', html)
m_alloc = re.search(r'id=["\']ContentPlaceHolder3_LblCurrScheduledAllocation["\'][^>]*>([^<]+)<', html)
m_time = re.search(r'id=["\']ContentPlaceHolder3_ddtime["\'][^>]*>([^<]+)<', html)
print(f"Delhi Real-time Load: {m_load.group(1) if m_load else 'N/A'} MW at {m_time.group(1) if m_time else 'N/A'}")
print(f"Scheduled Allocation: {m_alloc.group(1) if m_alloc else 'N/A'} MW")

# 2. DISCOM Drawl Table
m_discom = re.search(r'<table[^>]+id=["\']ContentPlaceHolder3_DDISCOM["\'][^>]*>(.*?)</table>', html, re.S)
if m_discom:
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m_discom.group(1), re.S)
    print("\nDISCOM Drawal Table:")
    for r in rows:
        cells = [re.sub(r'<[^>]+>', '', c).strip().replace("&nbsp;", " ") for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        if cells:
            print("  ", cells)

# 3. GENCO Table
m_genco = re.search(r'<table[^>]+id=["\']ContentPlaceHolder3_dgenco["\'][^>]*>(.*?)</table>', html, re.S)
if m_genco:
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m_genco.group(1), re.S)
    print("\nDelhi Generation Table:")
    for r in rows:
        cells = [re.sub(r'<[^>]+>', '', c).strip().replace("&nbsp;", " ") for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S)]
        if cells:
            print("  ", cells)
