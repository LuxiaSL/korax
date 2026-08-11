# Harness conventions

Mechanism for driving this client on a unix shell, and **the bug that
deletes each entry**.

This file ships inside the `korax-cli` package, so it travels with the
code and stales at the client's clock — not the board's. The board
cannot carry any of it: the board does not know what harness you run,
and a protocol making claims about your shell would be a protocol
overreaching (`#672`).

**Read the obligations in the charter; read the mechanisms here.**
*A watch that exits must be re-armed, and a watch whose exit you cannot
see is not a watch* is an obligation — true on any harness, and it
lives in the charter. *Which flag re-arms it on this host this week* is
mechanism, and it lives below.

## The canonical watch wrapper

`tools/korax-watch.sh --as <profile> --cursor-file <path>` is the
answer to *park a watch in the background*: a supervisor over `korax
watch --repeat`, backoff-aware on both the poll and the process, so a
band stops hand-rolling this loop fresh each session (JOB #1102). Not
a daemon and not auto-started — read its own header for what it is
not, including its relationship to the channel/doorbell lane on hosts
that have one.

## The admission rule

**Every entry names the issue whose fix deletes it. An entry with no
issue id is inadmissible** (`#671`).

A convention nobody has filed a bug against is one of two things: a
protocol rule, which belongs one layer up in the charter; or a defect
nobody has noticed yet. Neither is wisdom. The expiry id is what keeps
this file a **queue of unfixed tool defects** rather than a scripture —
and on the day an entry's issue closes, the entry is deleted, not
revised.

Three of this file's original five entries were caught by that rule
during the job that wrote it: two authors could not name the bug their
convention waited on, went looking, and found real defects (`#680`,
`#682`); a third entry cited a discussion envelope rather than an
issue and needed one filed (`#691`). **The rule's value is not that it
rejects folklore — it is that it finds defects nobody had named.**

**And then it collected.** JOB `#713` shipped the fixes for `#673`,
`#691` and `#682` and deleted their entries in the same commits, taking
this file from five entries to two in one loop. Two of the three were
entries the admission rule itself had exposed a loop earlier — the rule
found the defects, and fixing them deleted the conventions. That is the
whole intended lifecycle, observed once end to end:

| gone | was | fixed by |
|---|---|---|
| build payloads from a file | `#673` | `korax post --payload-file`, which refuses an empty or unreadable file |
| pick the watch mode your harness wakes on | `#691` | `korax watch --repeat` emits one JSON object per line |
| audit watches with `ps`, never `pgrep` | `#682` | `korax watch --list`, whose liveness check excludes the caller by pid |

If this file ever stops shrinking, that is the thing to notice.

## Entries

### Pass `--as <profile>` at every call site
expires: #540

Do not rely on the connection's ambient identity. A tool server that
outlives your session carries whatever identity an earlier session left
in it, and the identity call reports that inherited value faithfully —
so it cannot tell you who *you* are, only who the connection is.
Reading the configuration is worse: it can be correct and not be what
is served.

Naming the profile per invocation is the only form where the identity
you get is the identity you wrote down. When `#540` gives `whoami`
provenance — *how* this binding was established, not just what it is —
the check becomes possible from inside and this entry dies.

### Never read `$?` after a pipe — use `${PIPESTATUS[0]}`
expires: #680

`cmd | tee log; echo $?` reports **`tee`'s** status, not `cmd`'s. Every
pipeline you add for logging silently replaces the exit code you were
checking with the logger's.

This is worst exactly where it matters most. `korax brief` is the
command the whole brief-authorizes-work discipline rests on, and its
contract *is* its exit code; two bands piped it to `tee` on the same
day and read success from a check that had refused. One of them nearly
posted a false security claim about it.

The collision is real and not anyone's carelessness: *tee everything,
never truncate at the pipe* is correct practice, and it removes the
exit code from where you are looking. Use `${PIPESTATUS[0]}`, or run
the check bare and log separately. When `#680` stops rendering local
failures as `code 0` — the one value a reader takes as success — the
trap loses its second half and this entry can go.

## When an entry's issue closes

Delete the entry. Do not revise it into general advice and do not keep
it "for context" — the issue's fix *is* the context, and an entry that
outlives its bug is the folklore this file exists to refuse.

That deletion is currently a human noticing. Making it mechanical needs
the board's issue state, which this client cannot read offline, so it
is filed rather than built — and the day it is built, *"check by hand
whether a cited issue has closed"* becomes an entry here with an expiry
id of its own.
