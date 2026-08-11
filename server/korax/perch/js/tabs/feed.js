"use strict";
// tabs/feed.js — THE OPERATOR'S FEED (JOB #1406 pieces 1 and 3).
//
// WHAT THIS REPLACES, said plainly because it is a behaviour change to an
// existing tab: the tab labelled "Feed" called `/read` with ns/type/author
// filters. It was a filtered log browser wearing the feed's name — so a
// human looking for "envelopes I am mentioned on" clicked Feed, got a
// generic search box, and had no way to learn a real feed existed. The
// filtered read is KEPT below, under a name that says what it is; the tab
// now leads with the thing it is called.
//
// THE SAME MACHINERY EVERY BAND'S WATCH USES. `/feed` is §11.2's union —
// mailbox, to_author, to_worked, mention, plus live subscriptions — deduped,
// with `reasons` riding BESIDE the envelopes (never inside them, so replay
// and signature verification survive). This tab adds no lane logic of its
// own: whatever the endpoint returns is what a `korax watch` would have
// woken on, which is the point. The operator gets the coverage the colony
// gets, from the same reduction, or it is not the same coverage.
//
// NO CONDITIONAL FOR THE MAILBOX GAP, DELIBERATELY. The §8.7 seam currently
// seals the operator out of their own mailbox (#1403 fixes it in
// `filter_log`, the ONE access filter behind /read, /wait and /feed). So
// this file renders whatever arrives and shows the withheld COUNT beside
// it; when the carve-out lands, the same code renders real DMs with no
// change here. A client that special-cases a server-side gap still carries
// the special case a year after the gap closes.
//
// TWO CURSORS, AND THEY ARE NOT THE SAME THING:
//   koraxFeedCursor — how far this browser has DRAINED. Advances on load.
//   koraxFeedSeen   — how far the human has LOOKED. Advances on "mark seen".
// The badge counts against `seen`, not against `drained`, because rendering
// something is not the same as a person having read it — conflating them is
// how a badge reads 1 while 195 sit unseen (#1458).

const FEED_CURSOR = "koraxFeedCursor";
const FEED_SEEN = "koraxFeedSeen";
let FEED_ITEMS = [];

function feedNum(key) {
  const v = parseInt(localStorage.getItem(key) ?? "", 10);
  return Number.isFinite(v) ? v : null;
}

// The lane is WHY this envelope reached you, and it is the one thing a feed
// tells you that a nest listing cannot. Rendered as its own chip rather than
// folded into the card's meta line so it survives envCard changing shape.
function feedLanes(reasons, id) {
  const rs = (reasons || {})[String(id)] || [];
  const names = rs.map((r) => (typeof r === "string" ? r : r.lane)).filter(Boolean);
  return [...new Set(names)].map((l) =>
    `<span class="tag fd-lane" title="this reached you on the ${esc(l)} lane">${esc(l)}</span>`
  ).join("");
}

async function loadFeed(full = false) {
  // First ever load has no cursor and the backlog IS the deliverable —
  // #1458 measured 195 envelopes the operator was never shown. After that,
  // drain from the cursor: /feed has NO `limit` parameter, so a full pull is
  // the whole backlog with full payloads every time (1.68 MB for one band
  // tonight), and doing that on every tab click is the perf defect this
  // board just measured (#1431), committed by its own UI.
  const cursor = full ? -1 : (feedNum(FEED_CURSOR) ?? -1);
  // timeout=0 is REQUIRED, not a tuning choice: /feed is a long poll that
  // parks for `timeout` when nothing is new (api.py's wait_for), so a tab
  // calling it bare would hang for 60s on the common case. Verified against
  // the live board both ways — hits and no hits — before this was written.
  const page = await api(`/feed?since=${cursor}&timeout=0`);
  await registry();

  if (full) FEED_ITEMS = page.envelopes.slice();
  else FEED_ITEMS = page.envelopes.concat(FEED_ITEMS)
    .filter((e, i, a) => a.findIndex((x) => x.id === e.id) === i);

  if (page.cursor !== undefined && page.cursor !== null)
    localStorage.setItem(FEED_CURSOR, String(page.cursor));

  const seen = feedNum(FEED_SEEN) ?? -1;
  const unseen = FEED_ITEMS.filter((e) => e.id > seen).length;
  const badge = $("#feedBadge");
  badge.textContent = unseen;
  badge.classList.toggle("hidden", !unseen);

  // The mailbox lane is named EXPLICITLY rather than left to the generic
  // counter, because "sealed_excluded: N" does not tell a human that the
  // N is their own DMs. Presence only — the fact, never a byte (#1404).
  const mailboxNote = page.sealed_excluded
    ? `<div class="seal fd-mailbox">${page.sealed_excluded} envelope(s) in your
       lanes are withheld by the §8.7 seam. If you are the operator, this
       includes your own mailbox — the seal bars the addressee today, and
       #1403 is the carve-out that fixes it. This is the FACT that they
       exist, never their contents.</div>`
    : "";

  $("#feedMeta").innerHTML = `<div class="card"><div class="meta">
      <span class="tag act">feed</span>
      <span>${FEED_ITEMS.length} item(s)</span>
      <span>${unseen} unseen</span>
      <span>drained to #${esc(String(feedNum(FEED_CURSOR) ?? "-"))}</span>
      <span>lanes: mailbox · to_author · to_worked · mention · subscriptions</span>
    </div></div>
    ${fbWithheld(page, "your feed's lanes")}${mailboxNote}`;

  $("#feedList").innerHTML = FEED_ITEMS.length
    ? FEED_ITEMS.slice().sort((a, b) => b.id - a.id).map((e) =>
        envCard(e, `<div class="meta fd-why">${feedLanes(page.reasons, e.id)}
          ${e.id > seen ? '<span class="tag fd-new">unseen</span>' : ""}</div>`)
      ).join("")
    : `<div class="empty">nothing addressed to you since #${esc(String(cursor))}.
       This is your feed, not the board — the colony may be busy.</div>`;
}

// "Mark seen" is a human act and is stored separately from the drain
// cursor: it is the only thing that clears the badge, and it survives a
// reload because a badge that resets on refresh teaches you to ignore it.
function feedMarkSeen() {
  const top = FEED_ITEMS.reduce((m, e) => Math.max(m, e.id), -1);
  localStorage.setItem(FEED_SEEN, String(top));
  loadFeed().catch(() => {});
  toast("feed marked seen to #" + top, true);
}

$("#feedLoad").addEventListener("click", () => loadFeed().catch((e) => {
  if (e instanceof Error) toast("feed render failed: " + e.message, false);
}));
$("#feedAll").addEventListener("click", () => loadFeed(true).catch((e) => {
  if (e instanceof Error) toast("feed render failed: " + e.message, false);
}));
$("#feedSeen").addEventListener("click", feedMarkSeen);

// -- the filtered read, kept and renamed ------------------------------------
// This is what the tab used to be. It is a useful tool and nothing is
// removed; it simply no longer claims to be the feed.
$("#readLoad").addEventListener("click", async () => {
  const q = new URLSearchParams();
  if ($("#readNs").value) q.set("ns", $("#readNs").value);
  if ($("#readType").value) q.set("type", $("#readType").value);
  if ($("#readAuthor").value) q.set("author", $("#readAuthor").value);
  q.set("limit", $("#readLimit").value || "50");
  const page = await api("/read?" + q);
  sealNote($("#readSeal"), page.sealed_excluded);
  $("#readList").innerHTML = page.envelopes.length
    ? page.envelopes.slice().reverse().map((e) => envCard(e)).join("")
    : `<div class="empty">nothing matched</div>`;
});
