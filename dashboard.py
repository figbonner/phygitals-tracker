#!/usr/bin/env python3
"""
Phygitals Tracker - dashboard.py
Generates a self-contained HTML dashboard from the SQLite database.
Run: python3 dashboard.py  � outputs dashboard.html
"""

import sqlite3
import json
from datetime import datetime, timezone

DB_PATH = "phygitals.db"
MY_WALLET = "9Y7KcsQ8XvkAdFpTDQpeTQtqMxcVXvFWEi66R7872kr1"

def q(conn, sql, params=()):
    try:
        return conn.execute(sql, params).fetchall()
    except Exception as e:
        return []

def get_data(conn):
    d = {}

    # Latest pack EVs  official packs
    d["packs"] = q(conn, """
        SELECT pack_name, category, mint_price, ev, min_ev, max_ev,
               ev_ratio, buyback_pct, num_pulls_7d, in_stock, last_pull,
               COALESCE(is_creator, 0), COALESCE(creator_name, '')
        FROM pack_ev
        WHERE ts = (SELECT MAX(ts) FROM pack_ev)
          AND COALESCE(is_creator, 0) = 0
        ORDER BY ev_ratio DESC
    """)

    # Latest pack EVs  creator/repack packs
    d["creator_packs"] = q(conn, """
        SELECT pack_name, category, mint_price, ev, min_ev, max_ev,
               ev_ratio, buyback_pct, num_pulls_7d, in_stock, last_pull,
               COALESCE(is_creator, 0), COALESCE(creator_name, '')
        FROM pack_ev
        WHERE ts = (SELECT MAX(ts) FROM pack_ev)
          AND COALESCE(is_creator, 0) = 1
        ORDER BY num_pulls_7d DESC
    """)

    # My rank history (last 200 points)
    d["my_rank"] = q(conn, """
        SELECT ts, weekly_rank, weekly_volume, weekly_pulls, weekly_points,
               alltime_rank, alltime_volume, alltime_points, gap_to_next, gap_from_prev
        FROM my_rank_history ORDER BY ts DESC LIMIT 200
    """)

    # Latest weekly leaderboard
    d["weekly_lb"] = q(conn, """
        SELECT rank, username, address, volume_usd, pulls, points
        FROM leaderboard_weekly
        WHERE ts = (SELECT MAX(ts) FROM leaderboard_weekly)
        ORDER BY rank LIMIT 20
    """)

    # Latest alltime leaderboard
    d["alltime_lb"] = q(conn, """
        SELECT rank, username, address, volume_usd, pulls, points
        FROM leaderboard_alltime
        WHERE ts = (SELECT MAX(ts) FROM leaderboard_alltime)
        ORDER BY rank LIMIT 20
    """)

    # Current prizes
    d["prizes"] = q(conn, """
        SELECT week, rank, prize, description, points_req
        FROM prizes
        WHERE ts = (SELECT MAX(ts) FROM prizes)
        ORDER BY rowid
    """)

    # My stats over time
    d["my_stats"] = q(conn, """
        SELECT ts, total_listed, total_sold, total_bought, total_bought_usd, total_sold_usd
        FROM my_stats ORDER BY ts DESC LIMIT 1
    """)

    # Pack EV over time (last 50 snapshots per pack)
    d["pack_ev_history"] = q(conn, """
        SELECT pack_name, ts, ev, ev_ratio, num_pulls_7d
        FROM pack_ev
        ORDER BY pack_name, ts DESC
    """)

    # Marketplace: undervalued listings (price < FMV)
    d["deals"] = q(conn, """
        SELECT card_name, price, fmv, price_to_fmv, category, grade, grader, rarity, set_name
        FROM marketplace_listings
        WHERE ts = (SELECT MAX(ts) FROM marketplace_listings)
          AND fmv > 0 AND price > 0 AND price_to_fmv < 0.9
        ORDER BY price_to_fmv ASC LIMIT 30
    """)

    return d


def build_html(d):
    # Process rank history for charts
    rank_history = list(reversed(d["my_rank"][:50]))  # oldest first for chart
    rh_labels = [r[0][:16].replace("T"," ") for r in rank_history]
    rh_weekly_rank = [r[1] for r in rank_history]
    rh_weekly_vol = [r[2] for r in rank_history]
    rh_weekly_pts = [r[4] for r in rank_history]
    rh_gap = [r[8] for r in rank_history]

    # Latest rank snapshot
    cur = d["my_rank"][0] if d["my_rank"] else None
    my_weekly_rank = cur[1] if cur else "?"
    my_weekly_vol  = f"${cur[2]:,.2f}" if cur else "?"
    my_weekly_pts  = f"{cur[4]:,}" if cur else "?"
    my_at_rank     = cur[5] if cur else "?"
    gap_to_next    = f"${cur[8]:,.2f}" if cur and cur[8] else "?"

    # Pack table rows
    pack_rows = ""
    for p in d["packs"]:
        name, cat, price, ev, min_ev, max_ev, ratio, buyback, pulls7d, in_stock, last_pull = p
        ratio_pct = f"{ratio*100:.1f}%" if ratio else ""
        ratio_color = "#4ade80" if ratio and ratio >= 1.0 else "#f87171" if ratio and ratio < 0.85 else "#facc15"
        stock_badge = '<span style="color:#4ade80">�</span>' if in_stock else '<span style="color:#f87171">�</span>'
        pack_rows += f"""
        <tr>
          <td>{stock_badge} {name}</td>
          <td style="text-transform:capitalize">{cat}</td>
          <td>${price:,.0f}</td>
          <td>${ev:.2f}</td>
          <td>${min_ev:.2f}  ${max_ev:.2f}</td>
          <td style="color:{ratio_color};font-weight:700">{ratio_pct}</td>
          <td>{buyback*100:.0f}%</td>
          <td>{int(pulls7d):,}</td>
        </tr>"""

    # Weekly leaderboard rows
    lb_rows = ""
    for row in d["weekly_lb"]:
        rank, uname, addr, vol, pulls, pts = row
        is_me = addr == MY_WALLET
        style = 'style="background:rgba(250,204,21,0.08);font-weight:700"' if is_me else ""
        me_badge = " =H" if is_me else ""
        uname_display = (uname or addr[:8]+"...") + me_badge
        lb_rows += f"""
        <tr {style}>
          <td>#{rank}</td>
          <td>{uname_display}</td>
          <td>${vol:,.2f}</td>
          <td>{int(pulls):,}</td>
          <td>{int(pts):,}</td>
        </tr>"""

    # All-time leaderboard rows
    at_rows = ""
    for row in d["alltime_lb"]:
        rank, uname, addr, vol, pulls, pts = row
        is_me = addr == MY_WALLET
        style = 'style="background:rgba(250,204,21,0.08);font-weight:700"' if is_me else ""
        me_badge = " =H" if is_me else ""
        uname_display = (uname or addr[:8]+"...") + me_badge
        at_rows += f"""
        <tr {style}>
          <td>#{rank}</td>
          <td>{uname_display}</td>
          <td>${vol:,.2f}</td>
          <td>{int(pulls):,}</td>
          <td>{int(pts):,}</td>
        </tr>"""

    # Prize rows
    prize_rows = ""
    for row in d["prizes"]:
        week, rank, prize, desc, pts = row
        prize_rows += f"<tr><td>{rank}</td><td>{prize}</td><td>{desc}</td></tr>"

    # Deal rows
    deal_rows = ""
    for row in d["deals"]:
        name, price, fmv, ratio, cat, grade, grader, rarity, set_name = row
        discount = round((1 - ratio)*100, 1)
        deal_rows += f"""
        <tr>
          <td>{name}</td>
          <td style="text-transform:capitalize">{cat}</td>
          <td>${price:.2f}</td>
          <td>${fmv:.2f}</td>
          <td style="color:#4ade80;font-weight:700">-{discount:.1f}%</td>
          <td>{grade} ({grader})</td>
          <td>{rarity}</td>
        </tr>"""

    generated = datetime.now().strftime("%Y-%m-%d %H:%M UTC")

    stats_row = ""
    if d["my_stats"]:
        s = d["my_stats"][0]
        stats_row = f"""
        <div class="stat-card"><div class="stat-val">{s[1]}</div><div class="stat-label">Listed</div></div>
        <div class="stat-card"><div class="stat-val">{s[2]}</div><div class="stat-label">Sold</div></div>
        <div class="stat-card"><div class="stat-val">{s[3]}</div><div class="stat-label">Bought</div></div>
        <div class="stat-card"><div class="stat-val">${s[4]:,.2f}</div><div class="stat-label">Total Spent</div></div>
        <div class="stat-card"><div class="stat-val">${s[5]:,.2f}</div><div class="stat-label">Total Revenue</div></div>
        """

    # Build pack EV history for chart
    pack_names_set = list(dict.fromkeys(r[0] for r in d["pack_ev_history"]))[:8]
    pack_chart_datasets = []
    colors = ["#facc15","#60a5fa","#4ade80","#f87171","#c084fc","#fb923c","#34d399","#a78bfa"]
    for i, pname in enumerate(pack_names_set):
        pts = [(r[1][:16], r[2]) for r in d["pack_ev_history"] if r[0] == pname][:30]
        pts.reverse()
        pack_chart_datasets.append({
            "label": pname,
            "data": [p[1] for p in pts],
            "labels": [p[0] for p in pts],
            "borderColor": colors[i % len(colors)],
            "tension": 0.3,
            "fill": False
        })
    pack_labels_js = json.dumps([p[0] for p in [(r[1][:16], r[2]) for r in d["pack_ev_history"] if r[0] == (pack_names_set[0] if pack_names_set else "")][:30]][::-1]) if pack_names_set else "[]"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Phygitals Tracker  Figbonner</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin:0; padding:0; }}
  body {{ background:#0f1117; color:#e2e8f0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:14px; }}
  header {{ background:#1a1d2e; border-bottom:1px solid #2d3748; padding:16px 24px; display:flex; align-items:center; gap:16px; }}
  header h1 {{ font-size:20px; font-weight:700; color:#facc15; }}
  header .sub {{ font-size:12px; color:#718096; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; padding:20px 24px 0; }}
  .stat-card {{ background:#1a1d2e; border:1px solid #2d3748; border-radius:10px; padding:16px; }}
  .stat-val {{ font-size:22px; font-weight:800; color:#facc15; }}
  .stat-label {{ font-size:11px; color:#718096; margin-top:4px; text-transform:uppercase; letter-spacing:.05em; }}
  .section {{ margin:20px 24px; }}
  .section h2 {{ font-size:15px; font-weight:700; color:#a0aec0; text-transform:uppercase; letter-spacing:.08em; margin-bottom:10px; padding-bottom:6px; border-bottom:1px solid #2d3748; }}
  .chart-wrap {{ background:#1a1d2e; border:1px solid #2d3748; border-radius:10px; padding:16px; }}
  .chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media(max-width:900px){{ .chart-grid {{ grid-template-columns:1fr; }} }}
  table {{ width:100%; border-collapse:collapse; background:#1a1d2e; border:1px solid #2d3748; border-radius:10px; overflow:hidden; }}
  th {{ background:#2d3748; padding:8px 12px; text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:#a0aec0; }}
  td {{ padding:8px 12px; border-top:1px solid #1e2535; }}
  tr:hover td {{ background:#222840; }}
  .badge-green {{ background:#166534; color:#4ade80; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; }}
  .badge-red {{ background:#7f1d1d; color:#f87171; padding:2px 7px; border-radius:4px; font-size:11px; font-weight:600; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:10px; }}
  .tab-btn {{ background:#2d3748; border:none; color:#a0aec0; padding:6px 16px; border-radius:6px; cursor:pointer; font-size:13px; transition:all .15s; }}
  .tab-btn.active {{ background:#facc15; color:#0f1117; font-weight:700; }}
  .tab-pane {{ display:none; }} .tab-pane.active {{ display:block; }}
  .ts {{ font-size:11px; color:#4a5568; margin-left:auto; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>� Phygitals Tracker</h1>
    <div class="sub">Figbonner � {MY_WALLET[:12]}... � Generated {generated}</div>
  </div>
</header>

<!-- My rank hero stats -->
<div class="grid">
  <div class="stat-card"><div class="stat-val">#{my_weekly_rank}</div><div class="stat-label">Weekly Rank</div></div>
  <div class="stat-card"><div class="stat-val">{my_weekly_vol}</div><div class="stat-label">Weekly Volume</div></div>
  <div class="stat-card"><div class="stat-val">{my_weekly_pts}</div><div class="stat-label">Weekly Points</div></div>
  <div class="stat-card"><div class="stat-val">#{my_at_rank}</div><div class="stat-label">All-Time Rank</div></div>
  <div class="stat-card"><div class="stat-val" style="color:#f87171">{gap_to_next}</div><div class="stat-label">Gap to Next Rank �</div></div>
  {stats_row}
</div>

<!-- Rank + Volume over time -->
<div class="section">
  <h2>My Rank & Volume Over Time</h2>
  <div class="chart-grid">
    <div class="chart-wrap"><canvas id="rankChart" height="140"></canvas></div>
    <div class="chart-wrap"><canvas id="volChart" height="140"></canvas></div>
  </div>
</div>

<!-- Pack EV -->
<div class="section">
  <h2>Pack EV Dashboard</h2>
  <div class="chart-wrap" style="margin-bottom:14px"><canvas id="evChart" height="120"></canvas></div>
  <table>
    <thead><tr><th>Pack</th><th>Category</th><th>Price</th><th>EV</th><th>EV Range</th><th>EV/Price</th><th>Buyback</th><th>7d Pulls</th></tr></thead>
    <tbody>{pack_rows}</tbody>
  </table>
</div>

<!-- Leaderboards -->
<div class="section">
  <h2>Leaderboard</h2>
  <div class="tabs">
    <button class="tab-btn active" onclick="showTab('weekly')">Weekly</button>
    <button class="tab-btn" onclick="showTab('alltime')">All-Time</button>
  </div>
  <div id="tab-weekly" class="tab-pane active">
    <table>
      <thead><tr><th>Rank</th><th>Player</th><th>Volume</th><th>Pulls</th><th>Points</th></tr></thead>
      <tbody>{lb_rows}</tbody>
    </table>
  </div>
  <div id="tab-alltime" class="tab-pane">
    <table>
      <thead><tr><th>Rank</th><th>Player</th><th>Volume</th><th>Pulls</th><th>Points</th></tr></thead>
      <tbody>{at_rows}</tbody>
    </table>
  </div>
</div>

<!-- Prizes -->
<div class="section">
  <h2>Weekly Prizes</h2>
  <table>
    <thead><tr><th>Rank</th><th>Prize</th><th>Description</th></tr></thead>
    <tbody>{prize_rows}</tbody>
  </table>
</div>

<!-- Deals -->
<div class="section">
  <h2>Marketplace Deals (Price &lt; 90% FMV)</h2>
  <table>
    <thead><tr><th>Card</th><th>Category</th><th>Price</th><th>FMV</th><th>Discount</th><th>Grade</th><th>Rarity</th></tr></thead>
    <tbody>{"".join(deal_rows) or "<tr><td colspan=7 style='color:#718096;text-align:center;padding:20px'>No deals found this snapshot</td></tr>"}</tbody>
  </table>
</div>

<script>
const rankLabels = {json.dumps(rh_labels)};
const weeklyRank = {json.dumps(rh_weekly_rank)};
const weeklyVol  = {json.dumps(rh_weekly_vol)};
const weeklyPts  = {json.dumps(rh_weekly_pts)};
const gapData    = {json.dumps(rh_gap)};

const chartDefaults = {{
  responsive:true,
  plugins:{{ legend:{{ labels:{{ color:'#a0aec0', font:{{size:11}} }} }} }},
  scales:{{
    x:{{ ticks:{{ color:'#4a5568', maxTicksLimit:8 }}, grid:{{ color:'#1e2535' }} }},
    y:{{ ticks:{{ color:'#4a5568' }}, grid:{{ color:'#1e2535' }} }}
  }}
}};

// Rank chart (inverted y so #1 is top)
new Chart(document.getElementById('rankChart'), {{
  type:'line',
  data:{{ labels:rankLabels, datasets:[{{
    label:'Weekly Rank', data:weeklyRank,
    borderColor:'#facc15', tension:0.3, fill:false, pointRadius:3
  }}]}},
  options:{{...chartDefaults, plugins:{{...chartDefaults.plugins, title:{{display:true,text:'Weekly Rank (lower = better)',color:'#a0aec0'}}}}, scales:{{...chartDefaults.scales, y:{{ ...chartDefaults.scales.y, reverse:true }}}} }}
}});

// Volume chart
new Chart(document.getElementById('volChart'), {{
  type:'line',
  data:{{ labels:rankLabels, datasets:[{{
    label:'Weekly Volume ($)', data:weeklyVol,
    borderColor:'#60a5fa', tension:0.3, fill:true,
    backgroundColor:'rgba(96,165,250,0.08)', pointRadius:3
  }}]}},
  options:{{...chartDefaults, plugins:{{...chartDefaults.plugins, title:{{display:true,text:'Weekly Volume (USD)',color:'#a0aec0'}}}}}}
}});

// Pack EV chart
const packDs = {json.dumps(pack_chart_datasets)};
if (packDs.length > 0) {{
  new Chart(document.getElementById('evChart'), {{
    type:'line',
    data:{{ labels: packDs[0]?.labels || [], datasets: packDs.map(d => ({{ label:d.label, data:d.data, borderColor:d.borderColor, tension:0.3, fill:false, pointRadius:2 }})) }},
    options:{{...chartDefaults, plugins:{{...chartDefaults.plugins, title:{{display:true,text:'Pack Expected Value Over Time',color:'#a0aec0'}}}}}}
  }});
}}

function showTab(name) {{
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH)
    data = get_data(conn)
    conn.close()
    html = build_html(data)
    with open("dashboard.html", "w") as f:
        f.write(html)
    print(" dashboard.html generated")
