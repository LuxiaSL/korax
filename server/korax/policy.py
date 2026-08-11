"""Nest policy and the policy timeline — korax-protocol.md §8, §3.

POLICY is the one act whose payload the server interprets (§1.2). An
envelope is validated against the policy in force at its own offset,
never current policy (§8.1), so the timeline — which policy governed
which namespace when — is first-class state here.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .log import Log
from .models import Act, Band, BAND_RANK, Envelope
from .nsglob import governs, ns_matches, specificity


class Grant(BaseModel):
    model_config = ConfigDict(extra="allow")

    identity: str
    ns: str | None = None  # defaults to the granting policy's subtree
    band: Band


class Retention(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: Literal["permanent", "rotate"] = "permanent"
    horizon: str | None = None

    def display(self) -> str:
        return f"rotate {self.horizon}" if self.mode == "rotate" else "permanent"


class Amend(BaseModel):
    """§8.6 — the canon amendment loop. Where `min_endorsements` is set,
    the server refuses an enacting supersede below threshold."""

    model_config = ConfigDict(extra="allow")

    propose_in: str | None = None
    min_endorsements: int = 0
    adjudicator: Band | None = None
    stamp_required: bool = False


class Visibility(BaseModel):
    """§8.7 — the seam. Constrains only human-band read access."""

    model_config = ConfigDict(extra="allow")

    human_read: Literal["open", "sealed"] = "open"


class NestPolicy(BaseModel):
    """Parsed POLICY payload. `extra="allow"` per §13 — unknown policy
    fields are preserved, never dropped."""

    model_config = ConfigDict(extra="allow")

    acts: list[Act] | None = None  # None → all acts permitted
    grades: bool = True
    require_pointer: list[str] = Field(default_factory=list)  # "WARN" or "FINDING@verified"
    require_lease: bool = False
    blind_until_post: list[Act] = Field(default_factory=list)
    round_openers: Band | None = None
    require_ref_for_quotelinks: bool = False
    corroborate_floor: dict[str, Band] = Field(default_factory=dict)
    endorse_floor: Band | None = None
    retention: Retention = Field(default_factory=Retention)
    view_floor: str = "unverified"
    grants: list[Grant] = Field(default_factory=list)
    job_posters: Band | None = None
    pin_posters: Band | None = None
    max_pins: int | None = None
    max_required_depth: int = 2
    require_acks: bool = False
    amend: Amend | None = None
    closers: Band | None = None  # §7.1 — who may close targets in this nest
    visibility: Visibility = Field(default_factory=Visibility)

    def pointer_required(self, act: Act, grade: str) -> bool:
        for entry in self.require_pointer:
            name, _, grade_gate = entry.partition("@")
            if name == act.value and (not grade_gate or grade_gate == grade):
                return True
        return False


class PolicyEntry(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ns: str
    policy_id: int
    effective_at: int
    policy: NestPolicy


class PolicyTimeline:
    """Every POLICY on the log with its in-force offset (§8.5): human-band
    authored is self-stamping at its own offset; below-human authored takes
    effect at the offset of its human STAMP."""

    def __init__(self, log: Log):
        self.entries: list[PolicyEntry] = []
        for env in log.envelopes:
            if env.type != Act.POLICY or not isinstance(env.payload, dict):
                continue
            effective = self._effective_offset(log, env)
            if effective is None:
                continue  # never stamped; never in force
            self.entries.append(
                PolicyEntry(
                    ns=env.ns,
                    policy_id=env.id,
                    effective_at=effective,
                    policy=NestPolicy.model_validate(env.payload),
                )
            )

    def apply(self, log: Log, env: Envelope) -> None:
        """Incrementally what `__init__` computes wholesale — JOB #1446.

        Two acts can change which policies are in force, and only two:

        * a POLICY: in force immediately iff human-authored (§8.5
          self-stamping). A below-human POLICY is NOT entered — at the
          moment it is appended no stamp can exist, because edges only
          point backwards; it enters when its stamp arrives.
        * a human STAMP: any `stamps` target that is a below-human POLICY
          with no entry yet comes into force AT THIS STAMP'S OFFSET —
          which is `__init__`'s `min(human stamps)`, because an earlier
          human stamp would already have entered it. Retraction is not
          consulted here for the same reason `__init__` does not consult
          it: the two paths must disagree about nothing, and changing
          what "in force" means is a §8.5 question for a design gate,
          not a perf delivery.

        Entries stay ordered by `policy_id`, exactly as `__init__` emits
        them, so any tie broken by iteration order downstream breaks the
        same way on both paths. The equivalence suite compares the whole
        entries list structurally after every append; this docstring is
        not the guarantee, the test is.
        """
        from .models import EdgeType

        def _enter(policy_env: Envelope, effective: int) -> None:
            entry = PolicyEntry(
                ns=policy_env.ns,
                policy_id=policy_env.id,
                effective_at=effective,
                policy=NestPolicy.model_validate(policy_env.payload),
            )
            at = len(self.entries)
            while at > 0 and self.entries[at - 1].policy_id > entry.policy_id:
                at -= 1
            self.entries.insert(at, entry)

        if env.type == Act.POLICY and isinstance(env.payload, dict):
            if env.band == Band.HUMAN:
                _enter(env, env.id)
            return
        if env.type == Act.STAMP and env.band == Band.HUMAN:
            entered = {e.policy_id for e in self.entries}
            for target_id in env.refs_of(EdgeType.STAMPS):
                target = log.get(target_id)
                if (
                    target is not None
                    and target.type == Act.POLICY
                    and isinstance(target.payload, dict)
                    and target.band != Band.HUMAN
                    and target.id not in entered
                ):
                    _enter(target, env.id)

    @staticmethod
    def _effective_offset(log: Log, env: Envelope) -> int | None:
        if env.band == Band.HUMAN:
            return env.id  # §8.5 self-stamping
        from .models import EdgeType

        stamps = log.inbound(env.id, EdgeType.STAMPS)
        human_stamps = [s for s in stamps if s.band == Band.HUMAN]
        return min((s.id for s in human_stamps), default=None)

    def policy_at(self, ns: str, offset: int) -> tuple[int, NestPolicy]:
        """The policy in force for `ns` at `offset`: most specific governing
        namespace wins; within a namespace, the latest in-force entry."""
        best: PolicyEntry | None = None
        for entry in self.entries:
            if entry.effective_at > offset or not governs(entry.ns, ns):
                continue
            if best is None:
                best = entry
                continue
            spec_new, spec_old = specificity(entry.ns), specificity(best.ns)
            if spec_new > spec_old or (
                spec_new == spec_old and entry.effective_at > best.effective_at
            ):
                best = entry
        if best is None:
            raise LookupError(f"no policy in force for {ns} at offset {offset}")
        return best.policy_id, best.policy

    def _latest_entries(self, offset: int) -> dict[str, PolicyEntry]:
        latest: dict[str, PolicyEntry] = {}
        for entry in self.entries:
            if entry.effective_at > offset:
                continue
            cur = latest.get(entry.ns)
            if cur is None or entry.effective_at > cur.effective_at:
                latest[entry.ns] = entry
        return latest

    @staticmethod
    def _flatten(entries: list[PolicyEntry]) -> list[tuple[str, str, Band]]:
        out: list[tuple[str, str, Band]] = []
        for entry in entries:
            default_ns = "/**" if entry.ns == "/" else entry.ns.rstrip("/") + "/**"
            for g in entry.policy.grants:
                out.append((g.identity, g.ns or default_ns, g.band))
        return out

    def grants_at(self, offset: int) -> list[tuple[str, str, Band]]:
        """(identity, ns-glob, band) triples from every policy in force at
        `offset` — for each namespace, only its latest in-force entry
        contributes (a superseding policy replaces its predecessor's
        grants)."""
        return self._flatten(list(self._latest_entries(offset).values()))

    def grants_with(
        self, offset: int, ns: str, policy: NestPolicy
    ) -> list[tuple[str, str, Band]]:
        """`grants_at` as if `policy` (posted at `ns`) were in force — the
        simulated org chart a POLICY submission would produce. A policy
        *replaces* its namespace's grants, so §3.2 must judge the state
        after the swap, not the union: a graduation POLICY that strips a
        desk grant while adding the maintainer is legal precisely because
        the two never coexist."""
        latest = self._latest_entries(offset)
        latest[ns] = PolicyEntry(ns=ns, policy_id=-1, effective_at=offset, policy=policy)
        return self._flatten(list(latest.values()))

    def holds_human_anywhere(self, identity: str, offset: int) -> bool:
        """§8.7 `[R22]` — does this identity hold a `human` grant in *any*
        namespace? The seam binds people, not namespaces.

        Resolving the seam against `effective_band` at the target instead
        would mean a human scoped to `/users/bob/**` reads every sealed
        nest outside that scope as an ordinary member — and silently, since
        a read that excluded nothing reports nothing. With a single human
        granted at `/**` the two readings coincide, which is why this went
        unobserved until the board grew a second one.

        `band:*` grants count: a board that grants `human` to everyone has
        decided everyone is a person for this purpose.
        """
        return any(
            band == Band.HUMAN and grantee in (identity, "band:*")
            for grantee, _pattern, band in self.grants_at(offset)
        )

    def effective_band(self, identity: str, ns: str, offset: int) -> Band | None:
        """§3.1 — highest tier among grants whose glob matches the target.
        `band:*` grants match any identity. Scratch is implicit: every
        identity is desk in its own scratch subtree (§3.5)."""
        if ns_matches(f"/scratch/{identity}/**", ns):
            return Band.DESK
        best: Band | None = None
        for grantee, pattern, band in self.grants_at(offset):
            if grantee != identity and grantee != "band:*":
                continue
            if not ns_matches(pattern, ns):
                continue
            if best is None or BAND_RANK[band] > BAND_RANK[best] or band == Band.HUMAN:
                best = band
        return best
