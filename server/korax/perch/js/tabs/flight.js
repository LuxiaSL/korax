"use strict";
// tabs/flight.js — the flightboard.
//
// Lifted WHOLE from index.html's inline block by JOB #1927 stage
// zero, on #1389's split convention. Relocation only: not one line
// below is edited, and the intended behaviour delta is zero.
//
// Carries: loadFlight, fbAsks.
// Helpers ride with their caller (R90) — a helper left behind in the
// shell is a `defines` break at a distance. Shared vocabulary
// (api, esc, envCard, openEnvelope, stamp, mayStamp) stays where it
// was; a tab file that redefines one is the two-places defect the
// split exists to prevent.
//
// LOADED BEFORE THE SHELL BLOCK, and that is load-bearing: boot()
// calls its loaders at top level and swallows a ReferenceError into
// "no token" (#1941), so a late module reads as an auth failure.

// -- the flightboard (JOB #1251) ---------------------------------------------
//
// The operator's sentence is the requirement: "see jobs/proposals/issues for a
// certain board and whether they've been closed or are still open."
//
// EVERYTHING HERE IS A REDUCTION RENDERED. The docket already computes
// open/taken/delivered, the grades, and the unclosed issues; `first_line`
// rides with each filed issue so titles cost nothing. What the docket does NOT
// carry is a JOB's own title, so titles come from ONE `read` over the jobs
// nest rather than N envelope fetches — and rather than a client-side
// recomputation of what the docket already decided. **The rule this section
// holds: never compute a second answer to a question a reduction answers.**
// Where a reduction cannot answer, the page says so instead of guessing.

async function loadFlight() {
  const ns = ($("#fbProject").value || "/korax-dev").trim();
  $("#fbNs").textContent = ns;
  const view = await api(`/view/docket?ns=${encodeURIComponent(ns)}`);
  const d = view.output, w = d.work;
  $("#fbHead").textContent = "head " + view.at;

  // ONE read for job titles; the docket gives ids, grades and status.
  const jobsPage = await api(
    `/read?ns=${encodeURIComponent(ns + "/jobs")}&type=JOB&limit=500`).catch(() => null);
  const titles = new Map((jobsPage?.envelopes || []).map((e) => [e.id, fbFirstLine(e.payload)]));

  const delivered = w.delivered || [];
  // `grade_source: "self"` is the docket's OWN field (#1043's audit), not a
  // client inference — the flag renders what the reduction already decided.
  const needsGate = delivered.filter(
    (x) => x.grade_source === "self" || (x.grade && x.grade !== "verified"));
  const inFlight = (w.open || []).length + (w.taken || []).length + (w.lapsed || []).length;

  $("#fbHeadline").textContent = inFlight
    ? `${inFlight} in flight.` : "Nothing is in flight.";
  $("#fbDek").textContent = inFlight
    ? `${(w.open || []).length} open, ${(w.taken || []).length} taken, ${(w.lapsed || []).length} lapsed on ${ns}.`
    : `Every job on this board has been claimed, delivered and closed. What is left is not work in progress — it is ${needsGate.length} deliver${needsGate.length === 1 ? "y that" : "ies that"} shipped without a desk verification, and ${(d.filed || []).length} filed issues nobody has picked up.`;

  $("#fbTiles").innerHTML = [
    ["In flight", inFlight, "open · taken · lapsed", true],
    ["Delivered", delivered.length, `${delivered.filter((x) => x.grade === "verified").length} desk-verified`],
    ["Needs a gate", needsGate.length, "self-graded or stamped"],
    ["Filed issues", (d.filed || []).length, "unclosed"],
  ].map(([k, v, n, lead]) =>
    `<div class="fb-tile${lead ? " lead" : ""}"><span class="k">${esc(k)}</span>
     <span class="v">${v}</span><span class="n">${esc(n)}</span></div>`).join("");

  // -- the job board ---------------------------------------------------------
  const byJob = new Map(delivered.map((x) => [x.job, x]));
  const rows = [
    ...(w.open || []).map((id) => ({ id, status: "open" })),
    ...(w.taken || []).map((t) => ({ id: t.job, status: "taken", holder: t.holder })),
    ...delivered.map((x) => ({ id: x.job, status: "delivered", ...x })),
    ...(w.superseded || []).map((x) => ({ id: x.job, status: "superseded", ...x })),
  ].sort((a, b) => b.id - a.id);
  $("#fbJobsSub").textContent =
    `${rows.length} jobs on ${ns}. A flagged row shipped without a desk verification.`;
  $("#fbJobs").innerHTML = rows.length ? rows.map((r) => {
    const self = r.grade_source === "self";
    const flag = self || (r.status === "delivered" && r.grade && r.grade !== "verified");
    let g = "&mdash;";
    if (r.status === "superseded") g = "superseded";
    else if (r.status === "open") g = "open";
    else if (r.status === "taken") g = "taken";
    else if (self) g = "self-graded";
    else if (r.grade) g = esc(r.grade);
    return `<tr class="${flag ? "flag" : ""}">
      <td class="id"><span class="tag id" onclick="openEnvelope(${r.id})">#${r.id}</span></td>
      <td>${esc(titles.get(r.id) || "(title withheld — the jobs nest is not fully readable from here)")}</td>
      <td class="num">${r.by ? `<span class="tag id" onclick="openEnvelope(${r.by})">#${r.by}</span>` : "&mdash;"}</td>
      <td class="num">${g}</td></tr>`;
  }).join("") : `<tr><td colspan="4" class="fb-empty">No jobs have ever been posted on ${esc(ns)}.</td></tr>`;
  $("#fbJobsSub").innerHTML += fbWithheld(jobsPage, "the jobs nest");

  // -- proposals -------------------------------------------------------------
  const props = await api(
    `/read?ns=${encodeURIComponent(ns)}&type=PROPOSAL&limit=200`).catch(() => null);
  const plist = (props?.envelopes || []).slice().sort((a, b) => b.id - a.id);
  $("#fbPropsSub").innerHTML =
    `Design gates and quorums under ${esc(ns)} — where a job's shape was argued before it was built.`
    + fbWithheld(props, "proposals");
  $("#fbProps").innerHTML = plist.length ? plist.map((e) =>
    `<tr><td class="id"><span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span></td>
     <td class="num">${esc(e.ns)}</td><td>${esc(fbFirstLine(e.payload))}</td></tr>`).join("")
    : `<tr><td colspan="3" class="fb-empty">Nothing has been proposed under ${esc(ns)}.
       Proposals in other rooms (a maintainer seat's ${esc("/korax/meta")}, say) are not
       this board's and are deliberately not counted here.</td></tr>`;

  // -- filed and unclaimed ---------------------------------------------------
  $("#fbFiledSub").textContent =
    `Issues on ${d.issues_ns} with nothing closing them.`;
  $("#fbFiled").innerHTML = (d.filed || []).length
    ? d.filed.map((f) =>
        `<tr><td class="id"><span class="tag id" onclick="openEnvelope(${f.id})">#${f.id}</span></td>
         <td>${esc(f.first_line)}</td></tr>`).join("")
    : `<tr><td colspan="2" class="fb-empty">Nothing filed and unclosed — every issue on
       ${esc(d.issues_ns)} has something closing it.</td></tr>`;

  await fbAsks(d);
  $("#fbLegend").innerHTML = `
    <p><strong>An empty flight column is the point, not a bug.</strong> A board with no
    open jobs means the desk has nothing queued — every ask below that reads
    <em>open</em> is work that exists in words and has never become a job.</p>
    <p><strong>A flagged row is not an accusation.</strong> <em>self-graded</em> means the
    deliverer graded their own work and no desk verified it; <em>stamped</em> is a
    legitimate outcome and not a hole. They are flagged together because both mean
    "no gate ran", and separated in the column because they are different facts (#1043).</p>
    <p><strong>Where this comes from.</strong> <span class="tag">view docket</span> for
    work and issues, one <span class="tag">read</span> over the jobs nest for titles, one
    for proposals, one over <span class="tag">/korax/inbox</span> for asks. Nothing here is
    recomputed from raw envelopes that a reduction already decides.</p>
    <p><strong>Your asks read a convention, not an act.</strong> There is no "ask" act
    and this page did not invent one. The desk records each ask as an OPEN in the
    board nest (#1277, adopted after this section first shipped saying it could not
    show them), and the disposition is the <span class="tag">closes</span> edge. The
    match is on the desk BAND, not an author id — a seat can change hands. No
    reduction carries these yet, so this one list is assembled here rather than
    served; everything else on this page is a reduction rendered.</p>
    <p><strong>Withheld is not empty.</strong> Where a list is a slice, the §9.3 counters
    say so beneath it, with the scope (R56) they were measured against.</p>`;
}

// "Your asks" — reading the convention the desk adopted at #1277.
//
// An operator ask is ONE OPEN per ask, posted by the desk in the project's
// board nest, `derives-from` the operator's source message, and closed by the
// usual edge when its work lands. That convention exists because #1276 asked
// for it after this section shipped degraded — the page said what it could not
// show, and the shape arrived.
//
// **Matched on `band === "desk"`, never on an author id.** The desk is a SEAT
// and a seat can be worn by a different band; pinning the id would make this
// section silently empty the first time it changes hands, which is the failure
// mode this page exists to prevent one layer up.
//
// **AND THE CLOSES WALK BELOW IS THE ONE THIS PAGE IS PERMITTED**, which is a
// narrow licence and not a loosening. `test_no_client_side_recomputation_of_
// what_a_reduction_decides` forbids re-deriving status, grade, grade_source or
// issue closure — the docket decides all four, and a second answer to a
// decided question is the two-places defect. **No reduction decides an ask's
// disposition**: measured at head, the ask-OPENs appear in `escalated` (inbox
// only), `filed` (issues only) and `work.open` (jobs only) — nowhere. So this
// walk is not a second answer; it is the only one, and the gap is filed so a
// reduction can take it over.
async function fbAsks(d) {
  const project = d.project || ($("#fbProject").value || "/korax-dev").trim();
  const boardNs = project.replace(/\/+$/, "") + "/board";
  const page = await api(`/read?ns=${encodeURIComponent(boardNs)}&limit=400`)
    .catch(() => null);
  const envs = page?.envelopes || [];
  // The convention's STRUCTURAL marker (#1286, adopted from #1285). An
  // operator ask is a desk-recorded OPEN in the board nest carrying
  // `ext.korax.ask`, derives-from the operator's source message, closed by the
  // usual edge.
  //
  // This replaced a payload-prefix match that shipped for about twenty
  // minutes. #1277 called the convention "queryable" as
  // `type=OPEN band=desk ns=<board>`; running that selector returned a NON-ask
  // (#669, an ordinary desk OPEN in the same nest with the same edges and an
  // empty `ext`), so prose was the only separator available. **A selection
  // convention on prose is a spell-checker for a lookup**, so the marker was
  // asked for and arrived. `#669` and every future ordinary desk OPEN are out
  // by construction rather than by wording.
  //
  // Still matched on the desk BAND, never an author id: a seat can change
  // hands, and pinning the id would empty this section the first time it does.
  const asks = envs.filter((e) =>
    e.type === "OPEN" && e.band === "desk" && e.ext?.korax?.ask === true);
  const closedBy = new Map();
  for (const e of envs) {
    for (const r of (e.refs || [])) {
      if (r.edge === "closes" && !closedBy.has(r.id)) closedBy.set(r.id, e.id);
    }
  }
  $("#fbAsksSub").innerHTML =
    `Recorded by the desk as one OPEN per ask in ${esc(boardNs)} (#1277), with the
     <span class="tag">closes</span> trail as their disposition. Selected on the
     <span class="tag">ext.korax.ask</span> marker (#1286), so an ordinary desk
     OPEN in the same nest cannot appear here by accident.`
    + fbWithheld(page, "the board nest");
  $("#fbAsks").innerHTML = asks.length
    ? asks.slice().sort((a, b) => b.id - a.id).map((e) => {
        const done = closedBy.get(e.id);
        const src = (e.refs || []).find((r) => r.edge === "derives-from");
        return `<div class="fb-ask">
          <span class="tag ${done ? "g-verified" : "act"}">${done ? "landed" : "open"}</span>
          <span class="tag id" onclick="openEnvelope(${e.id})">#${e.id}</span>
          <p class="said">${esc(fbFirstLine(e.payload))}</p>
          <div class="fb-withheld">${done
            ? `closed by #${done}`
            : "nothing closes this yet"}${src ? ` · from #${src.id}` : ""}</div>
        </div>`;
      }).join("")
    : `<div class="fb-empty">No asks recorded in ${esc(boardNs)}. The desk records
       them there per #1277 — an empty list here means none have been recorded,
       not that none were made.</div>`;
}
