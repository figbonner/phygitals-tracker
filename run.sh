#!/bin/bash
# Phygitals Tracker — quick launcher
# Usage: ./run.sh           (single snapshot, auto-grabs token from Chrome)
#        ./run.sh --loop    (runs every 15 min continuously)

cd "$(dirname "$0")"

# Install deps if needed
pip3 install requests --quiet 2>/dev/null || pip install requests --quiet 2>/dev/null

# Auto-refresh token from Chrome localStorage (requires phygitals.com open in Chrome)
echo "🔑 Refreshing auth token from Chrome..."
python3 token_refresh.py

if [[ "$1" == "--loop" ]]; then
  # In loop mode, scraper auto-refreshes token each run
  python3 scraper.py --loop --interval 15
else
  # Single run — scraper picks up token from config.py
  python3 scraper.py

  # Generate dashboard
  python3 dashboard.py

  echo ""
  echo "📊 Opening dashboard..."
  open dashboard.html 2>/dev/null || xdg-open dashboard.html 2>/dev/null || echo "   → open dashboard.html manually"
fi
