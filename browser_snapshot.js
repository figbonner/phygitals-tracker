/**
 * Phygitals Browser Snapshot Tool
 * ─────────────────────────────────
 * Paste this entire script into the Chrome DevTools Console
 * while on any phygitals.com page. It will pull all data
 * and download it as phygitals_snapshot.json
 *
 * Also works with auth — uses your existing logged-in session.
 */

(async () => {
  const BASE = "https://api.phygitals.com/api";
  const MY_WALLET = "9Y7KcsQ8XvkAdFpTDQpeTQtqMxcVXvFWEi66R7872kr1";
  const snap = { generated: new Date().toISOString(), data: {} };

  const get = async (path, params = {}) => {
    const url = new URL(BASE + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    try {
      const r = await fetch(url.toString());
      if (r.ok) return r.json();
      console.warn("✗", r.status, url.toString());
      return null;
    } catch (e) {
      console.error("✗", path, e.message);
      return null;
    }
  };

  console.log("🚀 Starting Phygitals snapshot...");

  // 1. All packs + EV — includeRepacks=true gets all 80 (official + creator packs)
  console.log("  📦 Fetching all packs (official + creator)...");
  snap.data.packs = await get("/vm/available", { includeRepacks: "true" });
  snap.data.packs_official_only = (snap.data.packs || []).filter(p => !p.repack);
  snap.data.packs_creator = (snap.data.packs || []).filter(p => p.repack);
  console.log(`    ✓ ${snap.data.packs?.length || 0} total (${snap.data.packs_official_only.length} official, ${snap.data.packs_creator.length} creator)`);

  // 2. Weekly leaderboard (top 50)
  console.log("  🏆 Fetching weekly leaderboard...");
  snap.data.leaderboard_weekly = await get("/marketplace/leaderboard/weekly", { page: 0, limit: 50, amount: 50 });

  // 3. All-time leaderboard (top 50)
  console.log("  🏆 Fetching all-time leaderboard...");
  snap.data.leaderboard_alltime = await get("/marketplace/leaderboard", { page: 0, limit: 50, amount: 50 });

  // 4. Prizes
  const week = (() => {
    const now = new Date();
    const start = new Date(now.getFullYear(), 0, 1);
    return `${now.getFullYear()}-${Math.ceil((((now - start) / 86400000) + start.getDay() + 1) / 7)}`;
  })();
  console.log(`  🎁 Fetching prize data for week ${week}...`);
  snap.data.prizes = await get("/marketplace/prize-data", { week });

  // 5. Marketplace listings (top 200)
  console.log("  🛒 Fetching marketplace listings...");
  snap.data.marketplace = await get("/marketplace/marketplace-listings", {
    searchTerm: "",
    sortBy: "price-low-high",
    itemsPerPage: 200,
    page: 0,
    metadataConditions: JSON.stringify({ set:[], grader:[], grade:[], rarity:[], type:[], "set release date":[], "grade type":[], language:[], category:[] }),
    priceRange: "[null,null]",
    fmvRange: "[null,null]",
    listedStatus: "any",
    collectionAddresses: "[]"
  });

  // 6. My stats
  console.log("  👤 Fetching my marketplace stats...");
  snap.data.my_stats = await get("/marketplace/stats", { wallets: MY_WALLET });

  // 7. My inventory (authenticated)
  console.log("  🃏 Fetching my inventory...");
  snap.data.my_inventory = await get(`/users/i/${MY_WALLET}`, {
    searchTerm: "", sortBy: "", itemsPerPage: 1000, page: 0,
    metadataConditions: JSON.stringify({}),
    priceRange: "[]", fmvRange: "[]",
    listedStatus: "any", showPending: "true", externalOnly: "false",
    collectionIds: "[]",
    vaults: JSON.stringify(["psa","fanatics","alt","cc","fwog","in-transit"])
  });

  // 8. My offers
  console.log("  💬 Fetching my offers...");
  snap.data.my_offers = await get("/marketplace/user-offers", { wallets: MY_WALLET });

  // 9. My packs
  console.log("  📬 Fetching my packs...");
  snap.data.my_packs = await get(`/users/packs/${MY_WALLET}`);

  // 10. My profile
  console.log("  👤 Fetching my profile...");
  snap.data.my_profile = await get(`/users/p/${MY_WALLET}`);

  // ─── Compute quick summary ─────────────────────────────────────────────

  const summary = {};

  // My rank
  const wlb = Array.isArray(snap.data.leaderboard_weekly)
    ? snap.data.leaderboard_weekly
    : snap.data.leaderboard_weekly?.leaderboard || [];

  const myWeekly = wlb.findIndex(e => e.address === MY_WALLET);
  if (myWeekly >= 0) {
    const me = wlb[myWeekly];
    const above = wlb[myWeekly - 1];
    summary.weekly_rank = myWeekly + 1;
    summary.weekly_volume_usd = (me.volume / 1_000_000).toFixed(2);
    summary.weekly_pulls = me.packs;
    summary.weekly_points = me.points;
    summary.gap_to_next_usd = above ? ((above.volume - me.volume) / 1_000_000).toFixed(2) : null;
  }

  // Best pack EV/price ratio
  const packs = snap.data.packs || [];
  const ranked = packs
    .filter(p => p.ev && p.mint_price)
    .map(p => ({ name: p.name, price: p.mint_price, ev: p.ev, ratio: (p.ev / p.mint_price * 100).toFixed(1) }))
    .sort((a,b) => b.ratio - a.ratio);
  summary.best_ev_pack = ranked[0] || null;
  summary.pack_ev_ranking = ranked;

  snap.summary = summary;

  // ─── Print summary ─────────────────────────────────────────────────────
  console.log("\n" + "=".repeat(50));
  console.log("✅ SNAPSHOT COMPLETE");
  console.log("=".repeat(50));
  if (summary.weekly_rank) {
    console.log(`📍 Rank: #${summary.weekly_rank} weekly`);
    console.log(`💵 Volume: $${summary.weekly_volume_usd}`);
    console.log(`🎯 Points: ${summary.weekly_points?.toLocaleString()}`);
    console.log(`📦 Pulls: ${summary.weekly_pulls}`);
    if (summary.gap_to_next_usd) console.log(`⬆️  Gap to #${summary.weekly_rank-1}: $${summary.gap_to_next_usd}`);
  }
  if (summary.best_ev_pack) {
    console.log(`🏆 Best EV Pack: ${summary.best_ev_pack.name} — ${summary.best_ev_pack.ratio}% EV/Price`);
  }

  // ─── Download as JSON ──────────────────────────────────────────────────
  const blob = new Blob([JSON.stringify(snap, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `phygitals_snapshot_${new Date().toISOString().slice(0,16).replace("T","_")}.json`;
  a.click();
  console.log(`\n💾 Snapshot downloaded: ${a.download}`);
  console.log(`   Packs: ${packs.length} | Marketplace: ${(snap.data.marketplace?.listings || snap.data.marketplace || []).length} listings`);

  window.__phygSnap = snap;
  return snap;
})();
