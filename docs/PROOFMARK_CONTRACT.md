# Proofmark — Intelligent Contract

Single-file GenLayer intelligent contract:
[`intelligent-contracts/proofmark.py`](../intelligent-contracts/proofmark.py)

**What it is:** non-performance insurance for the AI-agent marketplace. A buyer
pays a premium to insure a job against a specific agent; if the agent never
delivers, or the deliverable fails to meet the agreed spec, the buyer can file a
claim and (if upheld by GenLayer validator consensus) is paid from the
underwriting pool of that agent's tier.

Only one action is ever AI-judged: **claims**. Premium pricing, identity, LP
shares, and the deadline logic are all deterministic.

## The four moving parts

1. **Agent identity & reputation** — one wallet binds to one `agent_id` at
   registration. A tier (`penalty` / `unrated` / `bronze` / `silver` / `gold`) is
   derived from real history (insured jobs, distinct buyers, tenure, breach
   rate) — never requested or self-declared.
2. **Policies** — a buyer pays at least a deterministic premium (coverage × the
   agent's tier rate; overpayment is refunded) to open a `pending` policy on one
   `job_id` against a named agent for a deadline. The named agent must accept it
   (`accept_job`) before it becomes `active`.
3. **LP pools** — LPs deposit native tokens into a tier and earn premiums.
   Per-claim payout is capped at **10% of that tier's pool**.
4. **Claims** — the buyer stakes a claim bond and the claim is judged by GenVM
   validator consensus: validators fetch the spec + the agent's submitted
   deliverable from IPFS, score conformance with an LLM, and vote.

## Public interface

### Write methods

| Method | Payable | Description |
|--------|---------|-------------|
| `register(agent_id)` | no | Bind the caller's wallet to `agent_id` (once). |
| `issue_policy(job_id, agent_id, coverage_atto, spec_url, spec_sha256, deadline_iso, expected_tier="")` | yes | Pay **at least** the premium (excess refunded) to open a `pending` policy on `job_id` against the agent. `spec_url` must be a commit-pinned `raw.githubusercontent.com` link and `spec_sha256` the sha256 of the exact bytes it serves (FIX-22). Reverts if the agent's quoted tier moved (`expected_tier`). |
| `accept_job(job_id)` | yes | The **insured agent** consents to a `pending` policy → `active`, freezing the spec on-chain (FIX-02), and **posts an agent bond of at least the coverage** (FIX-22) — excess is refunded in-call. Refuses a policy whose deadline has already passed (FIX-16) — an agent can never be bound to an impossible delivery and hit by an instant auto-breach. |
| `reject_job(job_id)` | no | The agent declines a `pending` policy → `expired`; exposure released, premium refunded to the buyer. |
| `cancel_pending_policy(job_id)` | no | The buyer withdraws their own `pending` policy → `expired`; exposure released, premium refunded. |
| `expire_pending_policy(job_id)` | no | **Permissionless** (FIX-18): voids a `pending` policy whose deadline **and** 7-day claim window have passed — exposure released, premium refunded. Without it, a policy nobody accepted and nobody cancelled could lock LP capital forever. |
| `submit_deliverable(job_id, deliverable_url, deliverable_sha256)` | no | The **active** insured agent records a deliverable as a commit-pinned GitHub link + the sha256 of its bytes. The contract re-fetches the URL and **refuses the submission unless the served bytes hash to `deliverable_sha256`** (FIX-22) — so a dead or doctored link fails here, on the agent's own transaction, not later on the buyer's claim. Frozen once the deadline passes, and frozen while a claim is pending (evidence stability, FIX-19). |
| `expire_policy(job_id)` | no | Close an expired policy, releasing locked exposure. Buyer may from the deadline; anyone may after the 7-day claim window (FIX-09). |
| `deposit(tier)` | yes | LP adds capital to a tier pool (zero-share deposits are rejected, FIX-11). |
| `withdraw(tier, shares)` | no | LP redeems shares (blocked if it would leave the pool below its locked exposure). |
| `file_claim(job_id)` | yes | **Phase 1 of the two-phase claim (FIX-19/H-02):** buyer escrows `CLAIM_BOND_ATTO` and records the claim as `pending` — *deterministic, no consensus judgement*. Refused once the claim window has closed, while another claim is pending, or if the deliverable is not yet in. |
| `judge_claim(job_id)` | no | **Phase 2:** permissionless, runs the GenLayer consensus judgement (`_judge_breach`). Because it carries no value, a failed/aborted judgement reverts without burning the escrowed bond. Resolution: `upheld` → the agent's forfeited bond pays the buyer the coverage (the tier pool is *not* debited, FIX-22) and the claim bond is refunded; `rejected` → both bonds are forfeited to the pool. |
| `rescind_pending_claim(job_id)` | no | Buyer-only recovery: cancels a `pending` claim before judgement and refunds the escrowed bond, returning the policy to `active`. |

### View methods

| Method | Description |
|--------|-------------|
| `get_profile(agent_id)` | Agent's display name, tier, counters, owner, registration time. |
| `agent_id_for_address(address)` | Reverse lookup of an agent by wallet. |
| `quote_premium(agent_id, coverage_atto)` | Exact premium + tier rate for a policy. |
| `get_policy(job_id)` | Status (`pending`/`active`/`claimed`/`expired`), coverage, deadline, deliverable hash, `agent_accepted`. |
| `get_pool_info(tier)` | Pool balance, total shares, locked exposure. |
| `get_lp_position(tier, address)` | An LP's share count in a tier. |
| `get_claim_status(job_id)` | `unresolved` / `pending` / `upheld` / `rejected` (canonical vocabulary, matches `proofmark.py`). |

## Key parameters

| Constant | Value | Meaning |
|----------|-------|---------|
| `CLAIM_BOND_ATTO` | 2 GEN | Bond a buyer stakes per claim (forfeited if the claim is rejected). |
| `BREACH_THRESHOLD` | 40 | Conformance score below this = breach. |
| `SCORE_TOLERANCE` | 15 | LLM answer is deterministic-confirmed within this tolerance. |
| `MAX_PAYOUT_BPS_OF_POOL` | 1000 | A single claim pays at most 10% of the tier pool. |
| `MAX_COVERAGE_BPS_OF_POOL` | 1000 | One policy's coverage is capped to 10% of the tier pool at issue (same share a single claim can ever pay). |
| `MIN_DEADLINE_HORIZON_SECONDS` | 60 | A deadline must be at least this far in the future at issue. |
| `MAX_DEADLINE_HORIZON_SECONDS` | 90 days | A deadline may be at most this far in the future (FIX-22c) — bounds how long a policy can lock LP exposure. |
| `MIN_COVERAGE_ATTO` | 0.01 GEN | Minimum coverage per policy (cost floor for tier progress). |
| `MAX_OPEN_POLICIES_PER_BUYER` | 10 | Open (pending or active) policies one buyer may hold (FIX-22b). Counted at issue — the buyer's own choice — and released by `_close_policy`. |
| `MAX_OPEN_POLICIES_PER_AGENT` | 10 | Open policies one agent may carry (FIX-22b). Counted only at `accept_job`, so an agent can never be capped out by strangers issuing at them. |
| `RATE_BPS_BY_TIER` | penalty 1200 / unrated 600 / bronze 400 / silver 250 / gold 150 | Annualized premium basis points. |
| `MIN_DISTINCT_BUYERS_BY_TIER` | bronze 2 / silver 5 / gold 10 | Distinct buyer addresses needed to reach a tier. |
| `MIN_TENURE_DAYS_BY_TIER` | bronze 3 / silver 14 / gold 45 | Days since registration needed to reach a tier. |
| `MAX_BREACH_RATE_BY_TIER` | bronze 20% / silver 8% / gold 2% | Upheld-claim rate above this blocks promotion into the tier (FIX-07). |
| `PENALTY_BREACH_RATE` | 34% | Breach rate above this drops an agent into the `penalty` tier (FIX-07). |
| `MAX_UTILIZATION_BPS` | 5000 | Sum of live exposure ≤ 50% of a tier's pool value (aggregate freeze, FIX-03). |
| `CLAIM_WINDOW_SECONDS` | 7 days | After `deadline + window` anyone may expire a policy; `file_claim` is refused (FIX-09). |
| `EVIDENCE_HOST` | `raw.githubusercontent.com` | The **only** host evidence may come from (FIX-22). https only; no query, fragment, or whitespace; shape-checked owner/repo; a full 40-char lowercase commit SHA required; a non-empty file path required. |
| `MAX_EVIDENCE_URL_LEN` / `MAX_EVIDENCE_BYTES` | 320 chars / 128 KiB | Evidence URL length cap and per-evidence size cap (FIX-01/FIX-22). |

## Security hardening (why each is there)

Every hardening here was either required by an earlier review pass or discovered
during a direct-mode security review (2026-09-02) and fixed. Each is covered by a
regression test in `tests/direct/test_proofmark.py`. Items 7, 9 and 10 are the
2026-09-03 "Shape A" pass — the response to the reviewer-facing self-dealing
review. Items 11–18 are the 2026-09-05 "Shape B" pass from the three-pass
adversarial review in `SECURITY-CHECK/`. Shape B supersedes Shape A; the Shape A
deploys are marked DO NOT USE (see PROOFMARK_DEPLOYMENT.md). Item 19 is the GPT
security-audit H-02 fix (two-phase claims); items 20–21 are the 2026-09-07
adversarial re-audit ("Phase-7b") hardening.

1. **Canonical identity keys.** `agent_id` / `job_id` are user-typed strings with
   no external registry. `_normalize_key()` lowercases + strips them before use as
   TreeMap keys, so a case variant can't squat another identity. As-typed text is
   kept separately for display.

2. **No empty-pool first-depositor exploit.** A policy can only be issued against
   a tier that already has real LP capital, and coverage can't exceed that tier's
   current pool value. Previously a premium could accumulate in a zero-share tier
   and the first LP deposit would mint 100% of the shares against pre-existing
   balance.

3. **LPs can't withdraw from under live coverage.** `tier_locked_exposure` tracks
   total live coverage; `withdraw()` refuses to drop a tier's balance below it.

4. **The agent consents to the job and its spec (FIX-02).** `issue_policy`
   creates a `pending` policy; only the insured agent's `accept_job` activates
   it, freezing `spec_url`/`spec_sha256` on-chain. A stranger can't be swept into
   a judged claim against a spec they never saw, and the buyer still can't point a
   claim at content the agent never accepted.

5. **Evidence is a commit-pinned GitHub file, checked twice (FIX-22, was FIX-01).**
   `spec_url` / `deliverable_url` must be an `https://raw.githubusercontent.com/…`
   link that names a **full 40-character lowercase commit SHA** — not a branch, so
   the bytes behind it cannot change after the fact — paired with a `sha256` of
   the exact bytes it serves. The URL is canonicalized (single allowlisted host,
   https only, no query/fragment/whitespace, shape-checked owner/repo, non-empty
   file path, ≤ 320 chars) and the digest shape-checked (64 lowercase hex) at both
   `issue_policy` and `submit_deliverable`. `submit_deliverable` then **re-fetches
   the URL and refuses the submission unless the served bytes hash to the
   committed sha256** — resolving, matching, valid UTF-8, within the 128 KiB /
   16000-character caps. A dead or doctored link therefore fails on the *agent's*
   transaction, not later on the buyer's claim. Validators re-fetch the same frozen
   pair when judging.

6. **Tier promotion can't be bought by one wallet.** Promotion needs a minimum
   real spend per job, a minimum count of **distinct** buyer addresses, and real
   elapsed tenure since registration. This raises the cost of a sybil scheme from
   minutes to weeks (it doesn't make sybil-proof — no on-chain contract can).

7. **Deadlines must be a real window in the future.** A policy issued with an
   already-passed deadline used to let a buyer instantly claim the "no
   deliverable submitted" auto-breach — the agent had no chance to deliver, so a
   ~6% premium could buy a payout of up to 10% of the pool, repeatable with fresh
   `job_id`s to drain a tier or burn an honest agent's reputation in a single
   block. Deadlines are now parsed to epoch seconds (`_iso_to_epoch_seconds`,
   pure positional math, no datetime dependency, fractional seconds ignored) and
   `issue_policy` reverts unless the deadline is at least
   `MIN_DEADLINE_HORIZON_SECONDS` (60 s) in the future. The same epoch compare
   drives `expire_policy` and `file_claim`, so there is no sub-second string
   ordering ambiguity across networks that timestamp differently.

8. **Claims are deterministic before they're AI.** The single-use gate, access
   control, bond, and deadline checks all run before any LLM call; validators
   independently re-derive the score rather than trusting the leader's output.

9. **No self-insurance.** The agent's own owner wallet cannot buy cover on the
   agent's job. This closes the cheapest self-dealing drain — one wallet that
   registers an agent and then buys a policy on it, defaults on its own job, and
   collects a payout it would never have needed. Buyer and agent are separate
   roles, which is how the honest market and the live demo already operate.

10. **Coverage is capped against the pool at issue, and aggregate exposure is
    capped too (FIX-03).** One policy's coverage is capped to
    `MAX_COVERAGE_BPS_OF_POOL` (10%) of the tier pool at issue, and the sum of
    live exposure can never exceed `MAX_UTILIZATION_BPS` (50%) of the pool's
    value — so no buyer can freeze an LP's whole tier with one standing policy.
    The label is the ceiling for the *first* claim; a later payout can be
    smaller if the pool has shrunk.

Items 11+ are the "Shape B" hardening pass (2026-09-05), driven by a
three-pass adversarial review of Shape A. Each maps to a regression test in
`tests/direct/test_proofmark.py`.

11. **Deliverable freeze after the deadline (FIX-01).** `submit_deliverable`
    reverts once the deadline has passed — an agent can't retroactively "find"
    a deliverable to answer a claim.
12. **No silent score clamp (FIX-06).** Out-of-range LLM scores now revert
    instead of clamping to 100, preserving the one divergence signal between
    validators.
13. **Chronic breach is priced, not absorbed (FIX-07).** Tiers carry breach-rate
    gates (bronze ≤ 20%, silver ≤ 8%, gold ≤ 2%); a breach rate above
    `PENALTY_BREACH_RATE` (34%) lands in a dedicated `penalty` tier priced at
    1200 bps — worse than any newcomer. No sequence of honest claims demotes an
    agent, and no sequence of upheld claims keeps a chronic breacher cheap.
14. **Promotion never strands an agent (FIX-08).** Promotion into an unfunded
    pool falls back to the best funded tier at or below the earned tier.
15. **Bounded claim window (FIX-09).** The buyer may file/expire from the
    deadline; after `deadline + CLAIM_WINDOW_SECONDS` (7 days) anyone may expire
    to release exposure and `file_claim` is refused. Exposure can't be locked
    forever by an absent buyer.
16. **Validator error containment (FIX-10).** The validator half of judgement
    catches any leader exception and votes accordingly instead of letting it
    leak.
17. **Prompt-injection hardening (FIX-04).** Evidence is framed as untrusted
    input inside the grading prompt and a separate `injection` signal is read
    from the grader; a truthy signal rejects the evidence rather than grading
    it.
18. **Zero-share deposits rejected (FIX-11)** and **overpayment refunded at
    issue (FIX-14)** — the premium race is gone. **Ungoverned by design
    (FIX-12):** the unused `admin` field and its constructor assignment are
    removed; no keyholder can rotate the gateway, move balances, or change
    verdicts. **Share keys are normalized addresses (FIX-15)** so case variants
    can't fork an LP position, and the spec's own calendar is validated before
    any deadline math.
19. **Judgement can't burn the claim bond (FIX-19 / H-02).** Claiming is two
    phases: the payable `file_claim` is fully deterministic (it only escrows the
    bond and records the claim as `pending`), and the GenLayer consensus
    judgement runs in the separate non-payable `judge_claim`. A reverted,
    aborted, or never-run judgement therefore can never forfeit the buyer's 2 GEN
    bond (on a reverted payable call the value is *not* refunded — it burns into
    the contract ledger). `rescind_pending_claim` is the buyer's recovery route
    to cancel a pending claim and get the bond back.
20. **Evidence custody split — a buyer can't manufacture a breach against an
    agent that delivered (2026-09-07 adversarial re-audit).** The spec and the
    deliverable have *opposite* custody. The deliverable is agent-supplied and
    live-probed at `submit_deliverable`; the spec is buyer-supplied and only
    shape-checked at issue. In `_judge_breach` a 4xx/oversized **deliverable**
    now resolves as a breach (score 0 — the agent's own evidence is gone),
    while a 4xx/oversized **spec** resolves as *rejected* (score 0 but not a
    breach — the buyer's own evidence is gone, so the claim fails and the bond
    is forfeited rather than paying out). Reverting was off the table for both
    (it burns the bond and never resolves the claim); this split makes sure a
    buyer who unpins its own spec can never turn a delivered job into a payout.
21. **No impossible deliveries (FIX-16) and no forever-pending policies
    (FIX-18).** `accept_job` refuses a policy whose deadline has passed — an
    overdue policy is voided (buyer `cancel_pending_policy`, or permissionless
    `expire_pending_policy` past its claim window), never accepted into
    liability. And `expire_pending_policy` releases exposure + refunds the
    premium for a `pending` policy past `deadline + CLAIM_WINDOW_SECONDS`, so a
    policy no agent accepted and no buyer cancelled cannot lock LP capital
    forever.

## Known residual (deliberate, disclosed)

- **Prompt injection raises the cost but doesn't close the class (FIX-04).**
  The structural half of the mitigation is agent acceptance (FIX-02): an agent
  who accepted a specific `spec_url`/`spec_sha256` on-chain consented to those
  exact bytes, so a hostile *deliverable* has to pass the honest agent who wrote
  the spec it answers. A malicious *spec* is a different failure — it prices
  insurance on something the buyer controls — and is out of scope of the mechanism.
- **A two-wallet controller can no longer profit, but can still tie up capital.**
  The FIX-22 agent bond is the change that matters: the agent must post a bond at
  least equal to the coverage, and on an upheld breach that bond — not the tier
  pool — pays the buyer. A buyer/agent pair under one controller therefore ends a
  completed round at **`seed + premium`**, having destroyed `premium` in fees, with
  the pool exactly whole (`tier_balance = pool_value + bond − payout = pool_value`).
  The earlier draft of this document listed this as an accepted residual; it is now
  a closed one, covered by `test_self_dealing_round_is_value_destroying`. What
  remains is *availability*, not theft: the pair can still lock up to 10 open
  policies each (`MAX_OPEN_POLICIES_PER_*`, FIX-22b) worth of exposure, and the
  premium on each, before any cap bites. The self-buy ban (item 9) closes the
  one-wallet case outright.
- **Third-party policy pressure is bounded, not impossible.** Issuance is
  permissionless, so anyone can open (and pay for) a `pending` policy naming an
  agent before the agent rejects it. Acceptance is the agent's veto and a reject
  refunds the premium, but while `pending` the policy locks pool exposure and
  counts toward the agent's `jobs_insured` (counted at issue by design, FIX-02).
  A griefer can therefore spend premiums to briefly lock exposure and inflate
  that one counter. Each attempt costs the attacker a premium, is capped at 10%
  of the pool, is bounded by `MAX_OPEN_POLICIES_PER_BUYER`, can never reach
  judgement without the agent's acceptance, and cannot promote the agent (tiers
  need distinct buyers, tenure, and a breach gate).
- **Evidence rests on one host, but it is a hardening not a widening (FIX-22).**
  `EVIDENCE_HOST` (`raw.githubusercontent.com`) is the one HTTP dependency for
  every spec and deliverable. The trade against the earlier four-gateway IPFS
  design is deliberate: the gateway list was a convenience fallback, not a trust
  anchor (any of the four could serve anything, and the CID digest — not the host
  — was the real check), while a single host makes the allowlist enforceable and
  the user-facing flow something an ordinary person can actually complete. GitHub
  going offline or changing its raw URL scheme would still strand submitted
  evidence; there is no admin to rotate the host (FIX-12 chose Option A).
- **Judged claims have only been proven in direct mode.** The deterministic
  auto-breach path is proven live on StudioNet; the judged path (deliverable
  submitted → validators re-fetch both URL+sha256 pairs and score conformance)
  runs only in direct-mode tests with web + LLM stubbed. It is the documented QA
  gap, targeted by a live judged claim in the FIX-22 evidence pass.

## Testing

- **Direct mode (fast, in-memory):** `python -m pytest tests/direct/test_proofmark.py -v`
  — 55 tests covering every method plus the gaming vectors above (the Shape A/B
  baselines adapted to the current state machine, plus the H-02 two-phase and
  Phase-7b regression tests). Direct
  mode runs the leader half only, so FIX-10's validator containment is verified
  structurally + by lint, not executed here.
- **On-chain smoke:** see [PROOFMARK_DEPLOYMENT.md](PROOFMARK_DEPLOYMENT.md) for the read/write
  verification run against both networks.
