"""THS concept constituent stocks scraper using Playwright browser automation."""
import time
import re

def scrape_ths_constituents(board_name: str) -> list[dict]:
    """Scrape all constituent stocks from THS concept page using headless browser.
    Returns list of {代码, 名称, 最新价, 涨跌幅}.
    """
    from playwright.sync_api import sync_playwright

    # Get THS code from name
    import akshare as ak
    code_map = ak.stock_board_concept_name_ths()
    if board_name not in code_map["name"].values:
        return []
    ths_code = code_map[code_map["name"] == board_name]["code"].values[0]

    all_stocks = []
    seen = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium-browser")
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 800})

        url = f"http://q.10jqka.com.cn/gn/detail/code/{ths_code}/"
        page.goto(url, timeout=15000, wait_until="networkidle")

        # Get total pages from page info
        page_info = page.query_selector(".page_info")
        total_pages = 1
        if page_info:
            text = page_info.inner_text().strip()
            parts = text.split("/")
            if len(parts) == 2:
                total_pages = int(parts[1])

        for _ in range(total_pages):
            # Extract rows from current table
            table = page.query_selector("table.m-table")
            if not table:
                break
            rows = table.query_selector_all("tr")
            new_found = 0
            for row in rows[1:]:
                cells = row.query_selector_all("td")
                if len(cells) >= 4:
                    code = cells[1].inner_text().strip()
                    if code not in seen and code.isdigit():
                        seen.add(code)
                        new_found += 1
                        all_stocks.append({
                            "代码": code,
                            "名称": cells[2].inner_text().strip(),
                            "最新价": cells[3].inner_text().strip(),
                            "涨跌幅": cells[4].inner_text().strip(),
                        })
            if new_found == 0:
                break

            # Click "下一页" to go to next page
            next_btn = page.query_selector("text=下一页")
            if not next_btn:
                break
            next_btn.click()
            page.wait_for_timeout(600)

        browser.close()

    return all_stocks


if __name__ == "__main__":
    stocks = scrape_ths_constituents("PCB概念")
    print(f"Scraped {len(stocks)} stocks from PCB概念")
    for s in stocks[:3]:
        print(f"  {s['代码']} {s['名称']} {s['最新价']} {s['涨跌幅']}%")
