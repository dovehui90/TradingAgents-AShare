import sqlite3
import json

conn = sqlite3.connect('/opt/tradingagents/tradingagents.db')

# Show all users
print("=== Users ===")
cur = conn.execute("SELECT id, email FROM users LIMIT 10")
for r in cur.fetchall():
    print(f"  {r[0]} | {r[1]}")

print("\n=== Watchlist (all users) ===")
cur = conn.execute("""
    SELECT u.email, w.symbol, w.notes, w.id
    FROM watchlist_items w
    JOIN users u ON w.user_id = u.id
    ORDER BY u.email, w.sort_order, w.created_at
""")
for r in cur.fetchall():
    print(f"  {r[0]} | {r[1]} | notes={r[2]}")

conn.close()
