import urllib.request, json

url = "http://127.0.0.1:8088/v1/market/bollinger-deviation?symbol=300274.SZ&start_date=2026-05-01&end_date=2026-06-23&period=daily"
resp = urllib.request.urlopen(url, timeout=30)
data = json.loads(resp.read().decode())
points = data["points"]
print(f"Total: {len(points)} points")

for p in points[-5:]:
    print(f'  {p["date"]}: mccd={p["mccd"]:.0f}, ub={p["ub"]:.1f}, lb={p["lb"]:.1f}, uub={p["uub"]:.1f}, llb={p["llb"]:.1f}')

mccds = [p["mccd"] for p in points if p.get("mccd")]
ubs = [p["ub"] for p in points if p.get("ub")]
print(f"MCCD range: {min(mccds):.0f} ~ {max(mccds):.0f}")
print(f"UB range: {min(ubs):.1f} ~ {max(ubs):.1f}")
