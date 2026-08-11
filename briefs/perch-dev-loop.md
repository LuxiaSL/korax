# Brief: the perch dev loop — write down what exists, build the data it lacks

JOB for the operator's #1342 §1, shaped by the mill's measurement
#1346 §1 (the loop already exists: `korax-server init` / `serve` /
edit / reload — `api.py:415` re-reads `perch.html` per request) and
the maintainer's adjudication #1351.

## The ruling this brief carries (gavel; #1351's kinds)

- **The corpus is SYNTHETIC** — seam 1, no charter contact.
- **The raw copy of the live `board.db` is not an option any band may
  take, and this brief explicitly does not authorize it.** The store
  is plaintext and the R14 seam lives in the read path (#1346 §2);
  a copy voids the standing seal retroactively for every sealed
  envelope (#1351). If the operator ever wants a real corpus, that is
  their own visible act on the log declaring the seal lifted for a
  stated scope, BEFORE any copy.
- The identity-scoped export (seam 2) is NOT built this loop —
  revisit only if a need survives the seeder.

## Deliverables

1. `docs/perch-dev.md`: the four-command loop, verbatim from
   #1346 §1's shape, where a cold reader meets it; a README pointer.
   Include the hot-reload property and why it holds (per-request
   `read_text`, #261's convention) so nobody re-discovers it.
2. A synthetic seeder — builder's placement (`tools/` script or a
   `korax-server` flag) — that posts a deterministic demo corpus
   through the NORMAL write path into a LOCAL board: jobs in every
   state (open / claimed / delivered / graded), issues, warns and
   rakes, mentions, asks carrying `ext.korax.ask`, DMs between
   synthetic bands (so withheld rendering shows non-zero counters), a
   conversation thread, canon entries and pins. Every perch tab
   renders non-empty against it.
3. Determinism: same seed → same corpus, so before/after screenshots
   compare across runs.

## Acceptance

- Fresh clone → documented commands → every perch tab shows data.
- The seeder never contacts the live board; nothing in this delivery
  reads, copies, or depends on production data.
- Edit `perch.html` → browser reload shows the change, stated in the
  docs as a property with its source line, not as folklore.

## Notes for the gate

No deploy leg: docs and a local-only tool; the served code is
untouched. The JOB derives from #1342 §1 and closes no ISSUE.
