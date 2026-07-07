import requests, re, time
from bs4 import BeautifulSoup
headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://q.10jqka.com.cn/"}
for page in range(1, 10):
    if page > 1:
        time.sleep(0.6)
    url = f"http://q.10jqka.com.cn/gn/detail/code/308614/?pn={page}"
    r = requests.get(url, headers=headers, timeout=10)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", class_=re.compile("m-table"))
    if not table:
        print(f"Page {page}: NO TABLE len={len(r.text)}")
        break
    trs = table.find_all("tr")[1:]
    pi = soup.find(class_="page_info")
    pinfo = pi.text.strip() if pi else "NONE"
    print(f"Page {page}: {len(trs)} rows, page_info={pinfo}")
    if pi:
        parts = pinfo.split("/")
        if len(parts) == 2 and int(parts[0]) >= int(parts[1]):
            print("Last page!")
            break
