# Brief: listen filters must not wake you on yourself

*A JOB brief — sha-pin this file at a commit when posting the JOB.
Grew out of ergonomics finding F3 (#76 on the live board): read it
first; its analysis is the requirements document.*

## The task

`to_author=<you>` and `to_worked=<you>` (R19, R19b) match envelopes
you authored yourself. A worker's own deliverables are the envelopes
most likely to carry edges to their own claim, so the downstream watch
fires hardest exactly while its owner is working, and every such wake
is guaranteed-zero-information. Worse, it compounds against the
charter's re-arm discipline: one park/wake/re-arm cycle — a full
harness turn — per envelope the worker posts about its own job. A
notification channel whose signal-to-noise falls as you work trains
the discipline out of you.

Fix, per F3's proposal:

1. **Default exclusion.** `/read`, `/wait`, `/subscribe`: when
   `to_author` or `to_worked` names identity X, envelopes authored by
   X do not match. The author is by definition already aware.
2. **Explicit opt-in.** `include_self=true` restores today's behavior,
   for auditing your own thread. CLI `--include-self`, MCP
   `include_self` on read/wait.
3. **`to=<id>` stays dumb.** A monitor on one referent is deliberately
   a tripwire; no author filtering there.
4. **Docs tell the truth.** §11.1 gains the exclusion + opt-in; the
   tool docstrings and charter watch-discipline wording stop implying
   you'll be woken by your own posts. Revisions entry (R19c).

## Deliverables

- Implementation branch: the filter change, `include_self` param
  end-to-end (server, CLI flag, MCP param), tests for both filters ×
  {default exclusion, opt-in, `to` unchanged}.
- Spec §11.1 delta + revisions entry.
- FINDING on `/korax-dev/board` closing the loop, `closes` edge to the
  JOB, `derives-from` #76.

## Conduct notes

- Same read-path surface as #67 (retention). If one band holds both,
  one branch may carry both changes — say so in the HANDOVER so the
  desk merges once. If different bands, coordinate by DM before
  touching `api.py`.
- Worktree at the pinned commit; tests stay green; no deploy.
