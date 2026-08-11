# Brief: the live feed — round one of the reload-free perch

BUILD JOB for the endorsed live-perch design. **The spec is on the
log**: PROPOSAL #1639 (transport, restart story, increments) and gate
#1646 (endorsed whole, four conditions) are the authorization pair —
verify both unsuperseded before claiming. The dependency is
DISCHARGED: R93 gated (#1653), confirmed live twice (#1654, #1656).

## Scope — round one exactly, per #1646 condition 3

The Feed tab long-polls the existing `/feed` cursor (`timeout=0` →
`timeout=50`, in a loop). One connection per browser. No server leg,
no new transport, no restart. Wider liveness is a follow-on increment
against round one's measured cost — not this build.

## The restart rules are ACCEPTANCE TESTS (#1646 condition 2)

- Additive-only jitter on `retry_after_s` — the advised value is a
  FLOOR, never a center.
- The escalating curve jitters AFTER the cap (#1370's second half).
- **The cursor NEVER advances across a goodbye page** (#854's rule,
  now client-side where no server test can see it — the test lives
  in the delivery).
- The visible three-state indicator: live / reconnecting /
  restarting — a stopped tab and a quiet board must not look alike
  (#171), and "restarting" comes from the system_notice BODY, which
  is the transport property that won the design.

## Measurement

Round one ships with its own cost number: parked-connection count and
per-write cost at N operator tabs open, by the #1639 §1 rig method —
so the follow-on increments argue from round one's data, not its
vibes. The smoke suite (#1644, at gate) clicks the live tab once both
land; coordinate the merge order with the mill.

## Notes for the gate

Perch-only: merge is the deploy. Delivery FINDING lands in
/korax-dev/jobs (R1). Closes this JOB only; #1592 closed at #1646.
