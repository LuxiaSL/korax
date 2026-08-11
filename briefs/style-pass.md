# The style pass — tokens, type, and spacing; zero tab logic

**JOB shape:** perch CSS only. The operator's slate #1342 §4, the
last unstarted item of it, sequenced after the mobile pass per #1387
— mobile is merged. Delivery is a sha-pinned branch to the gate;
delivery FINDING in /korax-dev/jobs.

## Scope

- `server/korax/perch/css/variables.css` — the token layer. R92
  deliberately left it byte-clean so this pass owns it whole. Bring
  the palette, radii, shadows and spacing scale toward the register
  of the worked example the operator already likes:
  `~/projects/aethera-server/admin/public/css/variables.css`
  (2,724 bytes, read it rather than imagine it — it is on this
  host). "Toward the register" means the same feel and discipline,
  not a copy-paste of another product's brand.
- `css/base.css` — typography and spacing rhythm: consistent type
  scale, line-height, form-control and button coherence, table
  density.
- `css/pages/*` — only where a page hardcodes a value the new token
  layer now owns; the diff there should be substitutions, not
  redesigns.

## Constraints

- **Zero tab logic.** No JS, no HTML restructuring, no behavior. If
  a style fix seems to need markup, that is a separate issue to
  file, not a rider.
- Dark-theme discipline: whatever theme machinery variables.css
  already carries stays coherent — no color defined only on one side
  of it.
- Mobile survives: the pass must not undo the mobile pass's
  breakpoints; check the narrow widths it added.

## Acceptance

- Browser leg (R94/R96): every tab opens console-clean at desktop
  and at the mobile pass's narrow width.
- Visual claims in the delivery are screenshots, not adjectives —
  before/after pairs for the tabs the pass most changes.
- Zero diff outside `server/korax/perch/css/`.

## Allocation

Quill's by announcement — freed this hour after the live feed
(#1727); any band otherwise (#1610's shape).
