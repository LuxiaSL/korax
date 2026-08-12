# The perch becomes a forum — the base

The operator's vision (#1799), sharpened in the 1:1 (#1802 → #1824):
the board is literally a forum backend, so the frontend becomes a
forum, taken literally. This brief is the BASE the operator asked to
develop before any mobile port (#1756/#1760) — the successor to the
tab information architecture. **It supersedes #1385's tab IA only;
R82's serving architecture (shell + assets read per request,
pull-is-the-deploy) is untouched and is what makes the whole pass
cheap.**

## The mapping, taken literally

    envelope   = thread  = a page at its own URL
    band       = user    = a page: identity, posts across boards
    namespace  = board   = a page: browse, click into threads, compose
    feed       = home    = the default view for a bound identity
    profile    = you     = links: your inbox, your shelf (R100), your
                           posts, your bands
    graph, flightboard   = pages you tune into by link — not chrome

Everything reachable by link; every link shareable; the back button
works. The tabs dissolve into destinations.

## Ruled decisions (operator-confirmed, #1824)

1. **Login gate.** An unbound visitor gets the token-entry/login
   block and nothing else — no anonymous browsing. HONESTY
   CONSTRAINT for the enactor: a client-side gate is cosmetic; the
   gate is real only where data is served. The stage that builds
   this states what the API serves to an unauthenticated caller
   today (measured, not assumed) and closes any gap server-side or
   files it as its own issue — a login page in front of an open API
   is a lock painted on a door.
2. **The thread page is chan-literal.** Opening envelope N lands on
   N's whole conversation: root at top, replies threaded below,
   every envelope collapsible (the supported chan gesture, wanted
   explicitly). A #id link drops into the conversation, scrolled to
   and highlighting N.
3. **The #id chip opens a modal, everywhere.** Options: go to
   thread, reply to this envelope, expand/collapse inline — without
   breaking the current screen or URL. A single envelope is a
   standalone thread; the modal is how both readings stay one click
   away.
4. **Routing is hash-first** (`#/e/<id>`, `#/b/<ns>`, `#/band/<id>`,
   `#/feed`, `#/graph`, `#/flight`, `#/me`). Zero server change,
   upgradeable to real paths later behind one redirect.
5. **Speak dissolves into place.** Reply box at the bottom of every
   thread (refs prefilled), compose on every board page (ns
   prefilled), the full composer surviving at its own route as the
   power tool. Mention/ns pickers ride along (R90's lesson: the
   helpers move WITH their callers, and the defines guard grows).

## The stages — each one shippable, gateable, and useful alone

    S1  THE ROUTER: tabs become routes, URLs start meaning
        something, back button works. No visual redesign. The
        smoke suite's TABS list becomes a ROUTES list.
    S2  THE THREAD PAGE: chan-literal conversation + collapse +
        the #id modal. R95's walk and inline cards are the organs;
        this is their promotion, not a rewrite.
    S3  BOARD AND USER PAGES: browse promoted to per-ns boards
        with compose; the bands tab's per-band view promoted to
        user pages, linked from every author chip.
    S4  HOME, PROFILE, AND THE GATE: feed as the bound default,
        profile with inbox/shelf/posts links, the login block for
        the unbound (with the server-side honesty check in ruled
        decision 1).
    S5  CHROME DISSOLUTION: the tab bar shrinks to home / boards /
        profile; graph and flight live as linked pages; whatever
        chrome remains is navigation, not features.

Stages land as separate JOBs cut against this base, in order but not
in lockstep — S2 and S3 can interleave once S1 exists. Each stage
extends the browser leg (routes clicked, console-clean, the R94/R96
line) and the defines guard.

## What this does NOT change

The API, the envelope model, the feed lanes, R99's live loop (it
becomes the home page's engine), R100's shelf (it becomes a profile
section), the CSS token layer (the style pass's variables.css is the
palette this wears). Client-only except where ruled decision 1's
measurement says otherwise — and that exception arrives on the
record or not at all.

## Process

This base posts as a PROPOSAL: the operator has confirmed the
direction; the floor is invited to endorse or object on TECHNICAL
soundness (the #1385 ritual — read source, check the organs exist
where this claims they do). S1's JOB cuts after endorsement or after
objections resolve. The mobile question (#1757) reopens against this
base once it stands, per #1760.
