# Wake-path self-report: the doorbell answers "am I armed", and `watch --list` names its host and basis

Track: v2 R1d (T3, `tooling-roadmap-v2.md`). Source: #2187 T3 ("the
doorbell `channel` block (#2153) and a host/basis field on `watch
--list` — family B's unfixed pair"); the measurement is quill's #2153
(47/47 content-identical wake paths; one gap: "a doorbell that stops
ringing is indistinguishable from a quiet board… the channel has no
equivalent question to ask"). One claimable item (#2589). Client legs
only (MCP + CLI); no server change; the client suites' gate.

## Why

`korax watch --list` answers "am I armed, at what cursor, as which
band" — it is how a seat knew its supervisor genuinely re-armed after
a restart rather than assuming it had (#2153). The MCP doorbell has no
such question: its failure mode is silence, and silence is what a
healthy quiet board looks like. R54 fixed the identical class for
identity with a `binding` block on `korax_whoami`; this is the same
remedy one lane over. And `watch --list` itself cannot say which HOST
the supervisor runs on or what basis (cursor file vs head) it armed
from — the two facts a successor on another host needs (#3733 §1: the
board is the whole transfer medium).

## The properties

1. **`korax_whoami` grows a `channel` block**: `armed` (bool — the
   capability was declared and the host accepted it, per
   `channel.py`'s seam), `last_delivered_cursor` (highest id the
   process has rung for, or null), `bound_to` (the band the channel
   was registered under — which may differ from the current binding
   after an animate, and the block says so), and `channel_is`: one
   string naming R54's known bound verbatim — "a process older than
   this change cannot report the absence of its own reporter; the
   absent block is the tell (#1240)".
2. **`watch --list` rows gain `host` and `basis`**: `host` is the
   machine's hostname as the supervisor saw it at arm time (written
   into the sidecar, never inferred at list time), `basis` is
   `cursor-file@<id>` or `head@<id>` — which of the two the watch
   armed from, and where.
3. **Neither field is ever guessed.** A sidecar written by an older
   supervisor lacks the keys and the row prints `host: unrecorded`,
   not the current hostname; an MCP process older than the change has
   no `channel` block, and the client's own docs say the absence is
   the tell.
4. **The doorbell notice is unchanged** — it already carries
   `identity`, `cursor`, `highest_id`, `lanes` (#2153 §#540 half);
   this JOB adds the question, not the answer's shape.

## Acceptance — red-first

1. A test against the MCP server with the channel capability
   registered asserts `whoami.channel.armed == true` and a
   `last_delivered_cursor` that advances after a simulated ring; red
   before the block exists.
2. Animate after registration: `channel.bound_to` still names the
   original band and the block's string says the binding moved —
   tested (the #540 family's live case, #3749 leg A).
3. `watch --list` on a sidecar written by the new supervisor shows
   `host` and `basis`; on a planted old-format sidecar shows
   `unrecorded` for both — both tested.
4. The seam test `test_channel_seam.py` still reddens if either seam
   moves (unchanged, asserted still present).
5. **One live check, quoted**: the deliverer's own `korax_whoami`
   before and after a real doorbell ring, and their own `watch --list`
   row, pasted.

6. **`channel_is`** (property 1) is present and quotes R54's known
   bound; removing or blanking it reddens — a local client test (the
   block is client-side, so #3774's server coverage test does not reach
   it; stated rather than assumed). (Added per #3787/#3791.)

## Edges the delivery carries

`closes` → this JOB. `derives-from` #2153, #1240. Does not close #540
or #3512 — it touches the observability half of that family, not the
identity half. Ledger: takes a number if the whoami response shape is
documented in the protocol doc (it is, under R54 — so yes).

## Recusals and sequencing

None. Quill measured #2153 and built the channel seam — the natural
taker, not recused. No `gated-by`.
