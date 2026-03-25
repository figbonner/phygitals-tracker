#!/usr/bin/env python3
"""
Phygitals Tracker - scraper.py
Polls all public + authenticated endpoints and stores data in SQLite.
Run: python3 scraper.py [--auth-token "Bearer eyJ..."] [--loop] [--interval 15]

Auth token is auto-refreshed from Chrome's localStorage if token_refresh.py is present.
"""

import requests
import sqlite3
import json
import time
import argparse
import sys
from datetime import datetime, timezone

# ─── CONFIG ──────────────────────────────────────────────────────────────────
API_BASE       = "https://api.phygitals.com/api"
MY_WALLET      = "9Y7KcsQ8XvkAdFpTDQpeTQtqMxcVXvFWEi66R7872kr1"
DB_PATH        = "phygitals.db"
LEADERBOARD_N  = 50   # how many players to track
MARKETPLACE_N  = 200  # listings to snapshot

def _load_token_from_config():
    """Read AUTH_TOKEN from config.py if present."""
    try:
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("config", os.path.join(os.path.dirname(__file__), "config.py"))
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        return getattr(cfg, "AUTH_TOKEN", None)
    except Exception:
        return None

def _auto_refresh_token():
    """
    Try to get a fresh token from Chrome via token_refresh.py.
    Falls back to config.py value if refresh fails.
    """
    try:
        import importlib.util, os
        spec = importlib.util.spec_from_file_location("token_refresh", os.path.join(os.path.dirname(__file__), "token_refresh.py"))
        tr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tr)
        token = tr.refresh(verbose=False)
        if token:
            return token
    except Exception:
        pass
    return _load_token_from_config()

# ─── DATABASE SETUP ──────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    type        TEXT NOT NULL,   -- 'leaderboard_weekly' | 'leaderboard_alltime' | 'pack' | 'marketplace' | 'prizes' | 'my_stats' | 'my_inventory' | 'my_offers'
    data        TEXT NOT NULL    -- JSON blob
);

CREATE TABLE IF NOT EXISTS leaderboard_weekly (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    rank        INTEGER,
    address     TEXT,
    username    TEXT,
    volume_usd  REAL,
    pulls       INTEGER,
    points      INTEGER
);

CREATE TABLE IF NOT EXISTS leaderboard_alltime (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    rank        INTEGER,
    address     TEXT,
    username    TEXT,
    volume_usd  REAL,
    pulls       INTEGER,
    points      INTEGER
);

CREATE TABLE IF NOT EXISTS pack_ev (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    pack_id         TEXT,
    pack_name       TEXT,
    slug            TEXT,
    category        TEXT,
    mint_price      REAL,
    ev              REAL,
    min_ev          REAL,
    max_ev          REAL,
    ev_ratio        REAL,   -- ev / mint_price
    buyback_pct     REAL,
    num_pulls_7d    INTEGER,
    in_stock        INTEGER,
    last_pull       TEXT,
    rarity_dist     TEXT,   -- JSON
    is_creator      INTEGER DEFAULT 0,  -- 1 = creator/repack pack
    creator_name    TEXT                -- creator username if available
);

CREATE TABLE IF NOT EXISTS marketplace_listings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    listing_id      TEXT,
    price           REAL,
    fmv             REAL,
    price_to_fmv    REAL,
    category        TEXT,
    card_name       TEXT,
    grade           TEXT,
    grader          TEXT,
    rarity          TEXT,
    set_name        TEXT,
    seller          TEXT
);

CREATE TABLE IF NOT EXISTS prizes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    week        TEXT,
    rank        TEXT,
    prize       TEXT,
    description TEXT,
    points_req  INTEGER
);

CREATE TABLE IF NOT EXISTS my_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    total_listed    INTEGER,
    total_sold      INTEGER,
    total_bought    INTEGER,
    total_bought_usd REAL,
    total_sold_usd  REAL
);

CREATE TABLE IF NOT EXISTS my_rank_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    weekly_rank     INTEGER,
    weekly_volume   REAL,
    weekly_pulls    INTEGER,
    weekly_points   INTEGER,
    alltime_rank    INTEGER,
    alltime_volume  REAL,
    alltime_pulls   INTEGER,
    alltime_points  INTEGER,
    gap_to_next     REAL,    -- volume gap to rank above (weekly)
    gap_from_prev   REAL     -- volume gap from rank below (weekly)
);
"""

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn

# ─── HTTP HELPERS ─────────────────────────────────────────────────────────────

def get(path, params=None, auth_token=None):
    headers = {"Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = auth_token
    url = f"{API_BASE}{path}"
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"  ✗ {r.status_code} {url}")
            return None
    except Exception as e:
        print(f"  ✗ Error {url}: {e}")
        return None

def now():
    return datetime.now(timezone.utc).isoformat()

# ─── SCRAPERS ────────────────────────────────────────────────────────────────

def scrape_packs(conn):
    print("  📦 Scraping pack EV data (official + creator/repacks)...")
    ts = now()
    # includeRepacks=true gets all 80 packs including creator packs
    data = get("/vm/available", params={"includeRepacks": "true"})
    if not data:
        return

    # Store raw snapshot
    conn.execute("INSERT INTO snapshots(ts,type,data) VALUES(?,?,?)",
                 (ts, "pack", json.dumps(data)))

    for p in data:
        mint_price = float(p.get("mint_price", 0) or 0)
        ev = float(p.get("ev", 0) or 0)
        ev_ratio = round(ev / mint_price, 4) if mint_price > 0 else 0
        creator_profile = p.get("creator_profile") or {}
        creator_name = (creator_profile.get("username") or
                        creator_profile.get("name") or
                        creator_profile.get("displayName") or "")
        is_creator = 1 if p.get("repack") else 0

        conn.execute("""
            INSERT INTO pack_ev(ts,pack_id,pack_name,slug,category,mint_price,
                ev,min_ev,max_ev,ev_ratio,buyback_pct,num_pulls_7d,in_stock,last_pull,
                rarity_dist,is_creator,creator_name)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ts,
            str(p.get("id","")),
            p.get("name",""),
            p.get("slug",""),
            p.get("category",""),
            mint_price,
            ev,
            float(p.get("min_ev",0) or 0),
            float(p.get("max_ev",0) or 0),
            ev_ratio,
            float(p.get("buyback_percent",0) or 0),
            int(p.get("num_pulls_7d",0) or 0),
            1 if p.get("in_stock") else 0,
            p.get("last_pull",""),
            json.dumps(p.get("rarity_distribution",[])),
            is_creator,
            creator_name
        ))
    conn.commit()
    print(f"    ✓ {len(data)} packs stored")


def scrape_leaderboard(conn):
    print("  🏆 Scraping leaderboard...")
    ts = now()

    for mode, table, path in [
        ("weekly", "leaderboard_weekly", "/marketplace/leaderboard/weekly"),
        ("alltime", "leaderboard_alltime", "/marketplace/leaderboard"),
    ]:
        data = get(path, params={"page":0, "limit": LEADERBOARD_N, "amount": LEADERBOARD_N})
        if not data:
            continue

        rows = data if isinstance(data, list) else data.get("leaderboard", data.get("data", []))
        conn.execute("INSERT INTO snapshots(ts,type,data) VALUES(?,?,?)",
                     (ts, f"leaderboard_{mode}", json.dumps(rows)))

        for i, entry in enumerate(rows):
            # volume is in micro-USD (divide by 1,000,000)
            raw_vol = entry.get("volume", entry.get("totalVolume", 0)) or 0
            vol_usd = float(raw_vol) / 1_000_000 if float(raw_vol) > 10_000 else float(raw_vol)

            username = (entry.get("username") or entry.get("name") or
                       entry.get("profile", {}).get("username", "") or "")
            address  = entry.get("address", entry.get("wallet", ""))

            conn.execute(f"""
                INSERT INTO {table}(ts,rank,address,username,volume_usd,pulls,points)
                VALUES(?,?,?,?,?,?,?)
            """, (ts, i+1, address, username,
                  round(vol_usd, 2),
                  int(entry.get("packs", entry.get("pulls", 0)) or 0),
                  int(entry.get("points", 0) or 0)))

        conn.commit()
        print(f"    ✓ {mode}: {len(rows)} entries")

    # Update my rank history
    _update_my_rank_history(conn, ts)


def _update_my_rank_history(conn, ts):
    """Find Figbonner in both leaderboards and record rank + gaps."""
    for mode, table in [("weekly", "leaderboard_weekly"), ("alltime", "leaderboard_alltime")]:
        rows = conn.execute(f"""
            SELECT rank, address, volume_usd, pulls, points
            FROM {table} WHERE ts=? ORDER BY rank
        """, (ts,)).fetchall()

        my_row = next((r for r in rows if r[1] == MY_WALLET), None)
        if not my_row:
            continue

        my_rank, _, my_vol, my_pulls, my_pts = my_row
        above = next((r for r in rows if r[0] == my_rank - 1), None)
        below = next((r for r in rows if r[0] == my_rank + 1), None)
        gap_up   = round(above[2] - my_vol, 2) if above else 0
        gap_down = round(my_vol - below[2], 2) if below else 0

        if mode == "weekly":
            w_rank, w_vol, w_pulls, w_pts = my_rank, my_vol, my_pulls, my_pts
            w_gap_up, w_gap_down = gap_up, gap_down
        else:
            a_rank, a_vol, a_pulls, a_pts = my_rank, my_vol, my_pulls, my_pts

    # Check if we got both, then insert
    try:
        conn.execute("""
            INSERT INTO my_rank_history(ts,weekly_rank,weekly_volume,weekly_pulls,weekly_points,
                alltime_rank,alltime_volume,alltime_pulls,alltime_points,gap_to_next,gap_from_prev)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (ts, w_rank, w_vol, w_pulls, w_pts,
              a_rank, a_vol, a_pulls, a_pts,
              w_gap_up, w_gap_down))
        conn.commit()
        print(f"    ✓ My rank: weekly #{w_rank} | all-time #{a_rank} | gap to #{w_rank-1}: ${w_gap_up:,.2f}")
    except Exception:
        pass


def scrape_prizes(conn):
    print("  🎁 Scraping prize data...")
    ts = now()
    # Current ISO week
    week_num = datetime.now().isocalendar()[1]
    year = datetime.now().year
    week_str = f"{year}-{week_num}"

    data = get(f"/marketplace/prize-data", params={"week": week_str})
    if not data:
        return

    conn.execute("INSERT INTO snapshots(ts,type,data) VALUES(?,?,?)",
                 (ts, "prizes", json.dumps(data)))
    for p in data.get("prizes", []):
        conn.execute("""
            INSERT INTO prizes(ts,week,rank,prize,description,points_req)
            VALUES(?,?,?,?,?,?)
        """, (ts, data.get("week",""), p.get("rank",""),
              p.get("prize",""), p.get("description",""),
              p.get("points") or 0))
    conn.commit()
    print(f"    ✓ {len(data.get('prizes',[]))} prize tiers for week {week_str}")


def scrape_marketplace(conn):
    print("  🛒 Scraping marketplace listings...")
    ts = now()
    params = {
        "searchTerm": "",
        "sortBy": "price-low-high",
        "itemsPerPage": MARKETPLACE_N,
        "page": 0,
        "metadataConditions": json.dumps({
            "set":[], "grader":[], "grade":[], "rarity":[],
            "type":[], "set release date":[], "grade type":[],
            "language":[], "category":[]
        }),
        "priceRange": "[null,null]",
        "fmvRange": "[null,null]",
        "listedStatus": "any",
        "collectionAddresses": "[]"
    }
    data = get("/marketplace/marketplace-listings", params=params)
    if not data:
        return

    listings = data if isinstance(data, list) else data.get("listings", data.get("data", []))
    conn.execute("INSERT INTO snapshots(ts,type,data) VALUES(?,?,?)",
                 (ts, "marketplace", json.dumps(listings[:50])))  # store subset

    for item in listings:
        price = float(item.get("price", item.get("listingPrice", 0)) or 0)
        fmv   = float(item.get("fmv", item.get("marketValue", 0)) or 0)
        ratio = round(price / fmv, 3) if fmv > 0 else None

        meta = item.get("metadata", item.get("card", {})) or {}
        conn.execute("""
            INSERT INTO marketplace_listings(ts,listing_id,price,fmv,price_to_fmv,
                category,card_name,grade,grader,rarity,set_name,seller)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ts,
            str(item.get("id", item.get("listingId",""))),
            price, fmv, ratio,
            item.get("category", meta.get("category","")),
            item.get("name", meta.get("name","")) or "",
            str(item.get("grade", meta.get("grade","")) or ""),
            item.get("grader", meta.get("grader","")) or "",
            item.get("rarity", meta.get("rarity","")) or "",
            item.get("set", meta.get("set","")) or "",
            item.get("seller", item.get("sellerAddress","")) or ""
        ))
    conn.commit()
    print(f"    ✓ {len(listings)} listings stored")


def scrape_my_stats(conn, auth_token=None):
    print("  👤 Scraping my stats...")
    ts = now()
    data = get(f"/marketplace/stats", params={"wallets": MY_WALLET}, auth_token=auth_token)
    if not data:
        return

    def to_usd(val):
        v = float(val or 0)
        return round(v / 1_000_000 if v > 10_000 else v, 2)

    conn.execute("""
        INSERT INTO my_stats(ts,total_listed,total_sold,total_bought,total_bought_usd,total_sold_usd)
        VALUES(?,?,?,?,?,?)
    """, (ts,
          int(data.get("totalListed",0) or 0),
          int(data.get("totalSold",0) or 0),
          int(data.get("totalBought",0) or 0),
          to_usd(data.get("totalBoughtValue",0)),
          to_usd(data.get("totalSoldValue",0))))
    conn.commit()
    print(f"    ✓ listed={data.get('totalListed')} sold={data.get('totalSold')} bought={data.get('totalBought')}")


def scrape_my_inventory(conn, auth_token):
    if not auth_token:
        return
    print("  🃏 Scraping my inventory...")
    ts = now()
    data = get(f"/users/i/{MY_WALLET}", params={
        "searchTerm": "", "sortBy": "", "itemsPerPage": 1000, "page": 0,
        "metadataConditions": json.dumps({}),
        "priceRange": "[]", "fmvRange": "[]",
        "listedStatus": "any", "showPending": "true", "externalOnly": "false",
        "collectionIds": "[]",
        "vaults": json.dumps(["psa","fanatics","alt","cc","fwog","in-transit"])
    }, auth_token=auth_token)
    if not data:
        return
    conn.execute("INSERT INTO snapshots(ts,type,data) VALUES(?,?,?)",
                 (ts, "my_inventory", json.dumps(data)))
    conn.commit()
    items = data if isinstance(data, list) else data.get("items", data.get("cards", []))
    print(f"    ✓ {len(items)} inventory items stored")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run_once(auth_token=None, verbose=True):
    print(f"\n{'='*50}")
    print(f"  Phygitals Tracker — {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'='*50}")

    # Auto-refresh token from Chrome if not provided
    if not auth_token:
        auth_token = _auto_refresh_token()
        if auth_token:
            print(f"  🔑 Token auto-loaded from Chrome")
        else:
            print(f"  ⚠️  No auth token — skipping personal data endpoints")

    conn = get_db()
    scrape_packs(conn)
    scrape_leaderboard(conn)
    scrape_prizes(conn)
    scrape_marketplace(conn)
    scrape_my_stats(conn, auth_token)
    if auth_token:
        scrape_my_inventory(conn, auth_token)
    conn.close()
    print("\n  ✅ All done.\n")


def run_loop(interval_minutes=15, auth_token=None):
    print(f"  Running every {interval_minutes} min. Ctrl+C to stop.")
    while True:
        run_once(auth_token)
        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phygitals Tracker")
    parser.add_argument("--auth-token", help="Bearer token from browser (for inventory)")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=15, help="Minutes between runs (default: 15)")
    args = parser.parse_args()

    if args.loop:
        run_loop(args.interval, args.auth_token)
    else:
        run_once(args.auth_token)
