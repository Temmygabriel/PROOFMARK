# Proofmark — Project Explorer review: punch-list remediation

Reviewer verdict: **conditional pass with a punch list**. This document maps every
item on that list to (a) the root cause, (b) the code that fixes it, and (c) the
test that would fail if the fix regressed. It is written to be checkable, not to
be believed: every claim below names a file, a method, and a test.

Contract under review: `intelligent-contracts/proofmark.py` (`class Proofmark`).
Test suite: `tests/direct/test_proofmark.py` — **67 tests, all passing**
(`python -m pytest tests/direct/ -q`), lint-clean
(`python -m genvm_linter.cli check intelligent-contracts/proofmark.py` →
22 methods: 9 view / 13 write).

The fix series is tagged **FIX-21** in the source, and the batch is referred to
below as *the remediation*.

---

## The one finding that drives most of the rest

> **A reverted payable call on GenLayer does not return the attached value.**

This is the root cause of item 1, and it is not a Proofmark bug — it is a
platform semantic that the contract had been written as though it were false.

Evidence, from the live failure the reviewer cites:

| | |
|---|---|
| tx | `0x429b0177888940543c650593d8d583326f67cfb9cdbafb2097fd611f15ab752f` |
| call | `issue_policy`, funded |
| outcome | finalized **GENVM RESULT: ERROR** (reverted) |
| policy | none created, none readable |
| contract balance | **19.06 → 19.12 GEN** — the 0.06 GEN premium stayed behind |
| ledger entry | **none** — the contract's own accounting never saw the 0.06 |

The value is not refunded and not credited. It is simply retained, invisible to
the contract, visible only as a rising balance on the explorer.

**Therefore:** the only shape that can guarantee non-retention is to *never
revert a payable call on a caller-fixable condition*. Every such condition must
instead **accept the call, refund the full attached value in the same
transaction, return normally, and record the reason on-chain.**

### `_reject_payable` — the structural fix

`intelligent-contracts/proofmark.py:660`

```python
def _reject_payable(self, reason: str, job_key: str = "") -> None:
    paid = int(gl.message.value)
    if paid > 0:
        _EoaPay(gl.message.sender_address).emit_transfer(value=u256(paid))
    sender_key = _normalize_key(str(gl.message.sender_address))
    self.payable_rejections[f"{sender_key}|{job_key[:MAX_ID_LEN]}"] = (
        f"{reason} — rejected and refunded {paid} atto in this transaction; "
        f"the contract retained nothing"
    )
```

Every payable method (`issue_policy`, `deposit`, `file_claim`) routes each
caller-fixable failure through this and returns. The three payable methods have
**no revert path at all** for a condition the caller could fix by retrying with
different arguments.

---

## Item-by-item

### 1. Root-cause analysis + fix for the live failed `issue_policy`

**Root cause.** See above: the call reverted on a caller-fixable condition
(coverage above the single-policy pool cap) and GenLayer retained the premium.

**Fix.** `_reject_payable` (contract:660) + the 18 `issue_policy` rejection
branches converted from `raise gl.vm.UserError` / revert to
`return self._reject_payable(...)` (contract:863–978). The reason is recorded in
the `payable_rejections` TreeMap (contract:648) and remains readable on-chain
after the fact.

**Test.** `test_rejected_payable_never_retains_value` (test:1805) replays the
live failure's exact shape — coverage above the cap — and asserts the pool
ledger is byte-for-byte unchanged after every rejection path.

---

### 2. Demonstrate that a failed payable call cannot retain attached value

**Fix.** Because each rejected call now *returns normally*, the value cannot be
retained: the refund is an `emit_transfer` in the same transaction, on the
external EthSend rail (`_EoaPay`). The call's success is not an assumption —
the reason string itself records the exact amount refunded.

**Read-back surface.** `get_rejection(payer, job_id="")` (contract:687) returns
the recorded reason or `""`.

**Test.** `test_rejected_payable_never_retains_value` (test:1805) drives six
distinct `issue_policy` rejections, a `deposit` rejection and a `file_claim`
rejection, asserting for each that (a) the call returns, (b) the reason names the
refunded amount, (c) the pool balance only ever moved by the one *successful*
issue. `test_successful_payable_clears_stale_rejection` (test:1868) proves a
later success clears the record, so `get_rejection` answers "was *this* call
rejected" rather than "was some earlier call rejected" — the read-back the UI
depends on (item 4).

---

### 3. Reconcile the explorer balance with the pool's internal accounting

**Fix.** `get_accounting(tier)` (contract:696) returns, for a tier:

```
tier                          the tier name
tier_balance_atto             the tier pool per the internal ledger
pending_claim_bonds_atto      escrowed bonds not yet credited to the pool
locked_exposure_atto          coverage reserved against unsettled policies
total_shares                  LP shares outstanding
contract_balance_atto         self.balance — the contract's own GEN, as the chain sees it
attributed_atto               tier_balance + pending bonds
```

For a correctly operating contract, `sum(ledger over all tiers) ==
contract_balance`. Any surplus is value a **pre-FIX-21** rejected call retained;
FIX-21's refund-in-call shape exists so the surplus cannot grow.

**Test.** `test_accounting_reconciles_with_contract_balance` (test:837).

---

### 4. Surface the precise revert reason and transaction link in the UI

The subtlety: a rejected payable call now **succeeds on-chain**, so there is no
revert message in the receipt to display. The reason has to be read back.

**Fix.**
- `frontend/lib/proofmarkClient.ts`: `getRejection(payer, jobId)` reads
  `get_rejection`; `assertNotRejected` runs after every payable write
  (`deposit`, `issuePolicy`, `fileClaim`) and throws a typed
  `ContractRejectionError` carrying `reason`, `hash` and `explorerUrl`.
- `explorerTxUrl()` / `explorerAddressUrl()` build links against the correct
  explorer for the selected network (`explorer-studio` / `explorer-bradbury`).
- `frontend/app/page.tsx`: `errNotice()` renders a rejection as
  *"Deposit: not accepted, refunded in full"* + the precise on-chain reason +
  a **"Verify the refund on the explorer"** link; `txNotice()` links every
  successful write to its transaction; the hero contract address links to the
  explorer.

**Test.** `test_successful_payable_clears_stale_rejection` (test:1868) covers the
contract side of the read-back. The UI side is typechecked
(`npx tsc --noEmit` clean) and parsed by the esbuild TSX gate.

---

### 5. New successful production test of the full paid lifecycle

**Test.** `test_full_paid_lifecycle_quote_to_payout` (test:2176) drives
quote → issuance → agent acceptance → deliverable submission → claim filing →
`judge_claim` → and asserts the final policy state, the verdict, and the payout
(`claimed` + `upheld` + the buyer credited `coverage_atto`).

**Live.** The live production equivalent is the §05 demo loop recorded in
[PROOFMARK_LIVE_EVIDENCE.md](PROOFMARK_LIVE_EVIDENCE.md). The version on the
current canonical address is the **deterministic auto-breach** path (no
deliverable → breach), which settles and pays over the external rail. A live
**judged** claim (deliverable present → GenLayer consensus verdict) is the
remaining live item — see *Live status* at the end of this document.

---

### 6. `coverage_atto` cannot exceed actual settlement-time payout

**Root cause.** The payout used to be `min(coverage_atto, 10% of the pool *at
settlement time*)`. An LP withdrawal between issue and settlement could
therefore shrink the real payout below the advertised cover — the label was not
the ceiling it claimed to be.

**Fix.** `_resolve_claim` (contract:1520) pays `payout = int(policy.coverage_atto)`
**in full**. This is always solvent by three invariants the contract enforces,
written out in the source at contract:1540–1558:

1. `issue_policy` requires `coverage_atto <= 10%` of the tier pool **and** total
   locked exposure `<= 50%` of it — so right after any issue,
   `tier_balance >= 2 × locked_exposure`.
2. `withdraw` refuses any amount that would take `tier_balance` below
   `tier_locked_exposure`; every other debit (`_refund_premium`) is `<=` the
   coverage it un-locks. So `tier_balance >= tier_locked_exposure` is preserved.
3. This claim's coverage is part of `locked_exposure`, so
   `tier_balance >= coverage_atto` at settlement.

`get_accounting` exposes the figures, so the invariant is externally checkable
rather than merely asserted.

**Test.** `test_claim_pays_full_coverage_even_after_pool_shrinks` (test:771).

---

### 7. Voided / rejected / expired policies must not inflate reputation

**Root cause.** `jobs_insured` and distinct-buyer counts were credited at
`issue_policy`. Any third party could inflate an unwilling agent's reputation —
and therefore its tier and pricing — for free, and the counts stayed inflated
forever when the agent rejected or the policy expired without ever being
accepted.

**Fix.** Reputation now credits **only on the agent's own `accept_job`**
(contract:1020). `issue_policy` reserves exposure but credits nothing
(contract:1005–1012).

**Tests.**
- `test_reputation_uninflatable_without_agent_consent` (test:1917) — three
  policies from two distinct buyers, none accepted → counters stay 0, tier stays
  `unrated`; only the accepted one counts; the rejected and cancelled ones
  contribute nothing.
- `test_voided_policies_never_inflate_reputation` (test:1963).
- `test_tier_promotion_bronze_requires_real_buyers_and_tenure` (test:883) —
  the Bronze gate requires ≥3 insured, ≥2 distinct buyers, ≥3 days tenure, so
  none of these can be reached by issuing policies alone.

---

### 8. Verify fetched evidence bytes against the committed CID

**Root cause.** Evidence was fetched and judged as text with no check that the
bytes returned actually hashed to the CID the policy committed to, and no
defined behaviour for long, binary, malformed, or gateway-unavailable content —
a gateway could return a truncated body and it would be judged as if complete.

**Fix.** `_fetch_verified` / `_probe_evidence` (contract:1148) are
consensus-checked and return exactly one explicit state, never a guess:

| state | meaning |
|---|---|
| `ok` | bytes hash to the CID, decode as strict UTF-8, within size bounds |
| `integrity` | bytes fetched but `sha256(body) != CID digest` |
| `not_found` | gateway answered 4xx |
| `oversized` | body > `MAX_EVIDENCE_BYTES` (128 KiB), or text > `MAX_EVIDENCE_CHARS` (16 000) |
| `non_text` | bytes are not valid UTF-8 (strict decode — never `errors="replace"`) |
| `unavailable` | every gateway 5xx / rate-limited / errored |

`_judge_breach` maps each state to a defined verdict: a non-`ok` **deliverable**
is a breach; a non-`ok` **buyer spec** rejects the claim (`score 0, breach
False`); a **transient** (`unavailable`) on either side raises
`ERROR_TRANSIENT` so the call reverts with no attached value at risk
(`judge_claim` is deliberately non-payable) and can simply be retried.

**Tests.** `test_cid_integrity_mismatch_is_refused_not_judged` (test:2061),
`test_cid_integrity_mismatch_on_buyer_spec_rejects_claim` (test:2108),
`test_non_text_evidence_refused_at_submit` (test:1998),
`test_non_text_deliverable_at_judge_is_breach` (test:2024),
`test_spec_unavailable_at_judge_is_rejected_not_breach` (test:1531),
`test_spec_oversized_at_judge_is_rejected` (test:1567),
`test_rate_limit_maps_to_transient` (test:1487),
`test_oversized_cid_rejected` (test:1117).

---

### 9. Evidence-source redundancy

**Fix.** `EVIDENCE_GATEWAYS` (contract:288) — four independent public IPFS
gateways, tried in a **fixed order** (deterministic across validators, no
shuffling):

```
https://w3s.link/ipfs/
https://dweb.link/ipfs/
https://ipfs.io/ipfs/
https://cloudflare-ipfs.com/ipfs/
```

A 429 or 5xx moves to the next gateway; a 4xx is remembered as `not_found`; an
integrity mismatch is remembered as `integrity`. Only if *every* gateway fails
does the probe report `unavailable` → transient → retryable, never a silent
breach or a silent dismissal.

**Test.** `test_rate_limit_maps_to_transient` (test:1487),
`test_post_probe_unpin_is_breach_not_revert` (test:1040).

---

### 10. Replace raw private-key storage with safer key custody

**Root cause.** Earlier builds wrote the raw private key to `localStorage`
(`proofmark.identity.pk.v1`, and before the rename `aegis.identity.pk.v1` /
`specmark.identity.pk.v1`). Any script on the origin — including a compromised
dependency — could read it and drain the address.

**Fix.** `frontend/lib/identity.ts` now stores an **encrypted keystore**:

```
localStorage["proofmark.identity.keystore.v1"] = {
  v, kdf: "PBKDF2-SHA256", iterations, salt, iv, ct, address
}
```

`ct` is the AES-GCM-256 ciphertext of the private key under a key derived from
the user's passphrase — PBKDF2-SHA256, **310 000 iterations**, random 16-byte
salt, random 12-byte IV. The key exists in cleartext only in memory, only after
an unlock, only for the tab's lifetime. A plaintext key is **never** written to
disk by this module.

Two usable states only: encrypted keystore + passphrase (persists), or an
explicitly-labelled session-only identity in `sessionStorage` (dies with the
tab). A legacy plaintext key found on disk is offered for adoption (encrypt it)
or discard — and is deleted the moment the user chooses. `providers.tsx` and
`components/IdentityBadge.tsx` expose create / adopt / unlock / lock / forget.

**UI consequence (item 4 adjacency).** Because an identity can now be *locked*,
`page.tsx`'s `ensureWallet()` reports *why* signing is unavailable
("Your identity is locked…", "Set up an identity first…") rather than failing
opaquely at the SDK.

---

### 11. Pinned Python test dependencies + reproducible setup

**Fix.**
- `requirements-dev.txt` — pinned `genlayer-test==0.29.2`,
  `genvm-linter==0.10.0`, `pytest==9.1.1`, verified on CPython 3.14.3 / Windows
  11, with the two loader gotchas documented (one contract per module per test;
  `mock_web` keeps the *first* registration, so `clear_mocks()` first).
- `gltest.config.yaml` — networks / paths / environment, so `pytest tests/direct/`
  picks up the contract and artifacts directories with no per-machine setup.

---

### 12. Tests covering each remediation

67 tests, listed by remediation:

| Remediation | Test(s) |
|---|---|
| failed payable execution / value recovery | `test_rejected_payable_never_retains_value` (1805), `test_successful_payable_clears_stale_rejection` (1868) |
| coverage conservation | `test_claim_pays_full_coverage_even_after_pool_shrinks` (771), `test_accounting_reconciles_with_contract_balance` (837) |
| reputation rollback | `test_reputation_uninflatable_without_agent_consent` (1917), `test_voided_policies_never_inflate_reputation` (1963) |
| CID-integrity mismatch | `test_cid_integrity_mismatch_is_refused_not_judged` (2061), `test_cid_integrity_mismatch_on_buyer_spec_rejects_claim` (2108) |
| oversized / non-text evidence | `test_non_text_evidence_refused_at_submit` (1998), `test_non_text_deliverable_at_judge_is_breach` (2024), `test_spec_oversized_at_judge_is_rejected` (1567), `test_oversized_cid_rejected` (1117) |
| gateway failure | `test_rate_limit_maps_to_transient` (1487), `test_spec_unavailable_at_judge_is_rejected_not_breach` (1531) |
| validator disagreement | `test_validator_rejects_divergent_leader` (2141) |
| full paid lifecycle | `test_full_paid_lifecycle_quote_to_payout` (2176) |

Plus the pre-existing suite covering the deterministic core: identity
registration, pool bootstrap/proportional shares, withdrawal under locked
exposure, policy issuance gates, deadline/calendar validation, claim windows,
auto-breach, judged upheld/rejected, bond accounting, tier promotion and
demotion, and permissionless expiry.

---

## Live status (honest)

Direct-mode tests exercise leader logic only — they do not prove consensus or
settlement on a live network. What is proven live and what is not:

| Claim | Status |
|---|---|
| Deterministic core, 67 tests, lint-clean | **proven locally** |
| ETH-rail payout to a buyer EOA (EthSend children FINALIZED) | **proven live** on canonical `0x65319a27…` — see [PROOFMARK_LIVE_EVIDENCE.md](PROOFMARK_LIVE_EVIDENCE.md) |
| Reject-and-refund payable shape (FIX-21) on a live network | **pending** — the canonical address predates FIX-21; a fresh deploy of the current source is required and is the last open item |
| Live **judged** claim (deliverable present → consensus verdict → payout) | **pending** — same fresh deploy |

The current canonical addresses were deployed from a **pre-FIX-21** source, so
they do not carry this remediation. A fresh deploy of the reviewed source, with
the §05 demo loop and a live judged claim re-run against it, is the closing
step; until it lands, the live column above says exactly that.
