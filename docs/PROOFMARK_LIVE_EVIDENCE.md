# Proofmark — Live Network Evidence

Where the **Proofmark** contract (`intelligent-contracts/proofmark.py`,
`class Proofmark`) is proven live on real GenLayer networks, with the tx hashes and
step evidence behind that claim. Historical runs are kept below for context; the
**current canonical** is FIX-22 at the top of this page.

## Current canonical — FIX-22 (2026-09-12)

The current `proofmark.py` — **commit-pinned GitHub URL + sha256 evidence**, the
**agent bond** that closes the self-dealing drain, per-buyer/per-agent
throughput caps, a 90-day deadline ceiling, and FIX-22d penalty-tier stickiness
(see [PROOFMARK_REVIEW_REMEDIATION.md](PROOFMARK_REVIEW_REMEDIATION.md) §13–16)
— is proven live on StudioNet:

| Address | Role | On-chain proof |
|---------|------|----------------|
| **`0x849b576f64ecA308300D278223951E4A88e1B5D4`** | **canonical live** — the address the frontend/env points at | deploy tx `0x1ea533ada62af64d5e85a4a06033bf481fa9a0b25ef25e9a04ac4529f37e6c69`, validators **AGREE**; **44/44** live e2e steps (`e2e/results/e2e-fix22.log`) |

Deployed 2026-09-12 with **CLI 0.37.1** (StudioNet requires that version — the
global 0.40.0-rc.3 RC can neither deploy nor read there). StudioNet is gasless,
so the run costs nothing but time.

### Live e2e — 44/44 steps (`0x849b576f…`)

`node e2e/run.js e2e --network studionet` walks the whole contract: register,
address-binding revert, LP deposit, quoting, payable issuance (including a
rejected and a past-deadline issuance that must **refund in-call**), agent
accept + bond, deliverable submission, foreign-host refusal, the open-policy
caps, premature-claim refusal, expiry, the auto-breach payout, and LP
withdrawal. Final line:

```
=== STUDIONET E2E on 0x849b576f64ecA308300D278223951E4A88e1B5D4: 44/44 steps passed ===
```

The load-bearing assertions for the FIX-22 economics are:

```
[PASS] agent bond escrowed == coverage -- bond=1.0000 GEN
[PASS] foreign-host 'deliverable' REVERTS (allowlisted evidence host only)
[PASS] past-deadline issue refunded: pool unchanged, no policy
[PASS] premature claim refunded: bond back, policy untouched
[PASS] pool made whole by the bond (keeps both premiums, pays no LP capital)
       -- balance=20.1200 GEN (want 20.1200 GEN) locked=0.0000 GEN
[PASS] all agent bonds returned (escrow 0) -- escrow=0.0000 GEN
```

That fifth line is the whole point of FIX-22: an upheld breach paid the buyer
**out of the agent's forfeited bond**, and the Unrated pool closed the round at
exactly `20 + 2 premiums` — **zero LP capital spent**. The sixth confirms the
escrow ledger nets to zero: every bond went to a payout or back to its agent,
none is stranded.

Direct-mode suite on this source: `python -m pytest tests/direct/ -q` →
**74 passed**; `genvm-lint check` clean (22 methods: 9 view, 13 write).

### §05 demo loop on the FIX-22 canonical

Written by `node e2e/demo-payout.js` — the reviewer's exact path (submission note
§05): register agent → LP funds Unrated 10 (+ Bronze 5 / Silver 3 / Gold 2) →
issue 1 GEN cover @ 0.06 premium, short deadline, **commit-pinned GitHub spec** →
agent accepts (posting the 1 GEN bond) → deadline passes with nothing delivered →
`file_claim` (2 GEN bond) → deterministic auto-breach, no AI call.

All five checks pass (`e2e/results/demo-payout.log`):

```
[PASS] claim upheld
[PASS] policy claimed
[PASS] pool keeps its capital (bond funded the payout)
[PASS] this run's lock released; nothing else left locked
[PASS] no errored payout children (EthSend rail)
```

This is the FIX-22 money claim, stated as arithmetic. The run began with Unrated
at 10.0600 GEN and ended at **20.1200 GEN** — exactly `baseline + 10 GEN deposit +
0.06 GEN premium`. The 1 GEN paid to the buyer on the upheld claim came **out of
the agent's forfeited bond**, not out of the pool: had the payout debited LP
capital the pool would have closed at 19.12, not 20.12. (The harness asserts
these as deltas rather than absolute figures, so it is re-runnable on a board
that already carries activity.)

**Independently audited.** `node e2e/audit-receipts.mjs <txhash>…` re-reads any
transaction's receipt and prints each validator's `mode` / `vote` /
`execution_result`, because `FINALIZED` alone proves nothing — a reverted call
finalizes too. For the load-bearing txs of this run the agreeing validators
report execution **SUCCESS**:

| tx | agreeing validators |
|---|---|
| `issue_policy` (`0x90c7007a…`) | 2 agree **SUCCESS**, 2 idle ERROR (ignored) |
| `accept_job` + 1 GEN bond (`0x00e50ea4…`) | 3 agree **SUCCESS**, 1 idle ERROR (ignored) |
| `file_claim` auto-breach (`0xb04b85f9…`) | 2 agree **SUCCESS**, 2 idle ERROR (ignored) |

Note the `idle ERROR` entries: idle validators routinely report ERROR because they
timed out and never ran the contract. Only validators that voted **agree** decide
the committed outcome — a repo-wide rule documented at `e2e/run.js:150-163`. The
same audit run against the two *negative* txs in the full e2e (foreign-host
`submit_deliverable`, LP withdraw under locked exposure) shows the contrasting
signature — **3/3 agreeing validators report ERROR** — so the harness demonstrably
tells a real revert apart from an idle no-show rather than treating both as failure.

### Superseded — fixed Proofmark, PAYOUT-FIX-20 (2026-09-08)

| Address | Role | On-chain proof |
|---------|------|----------------|
| `0x65319a2787BE8a57ee570fD0eB61A69887D91099` | **superseded** — PAYOUT-FIX-20 rail, CID evidence, **unbonded** `accept_job` | §05 demo (`e2e/results/demo-payout.log` + `demo-payout.json`), 2026-09-08 |

> **Why FIX-22 replaced it.** Its `accept_job` was free, so a buyer/agent pair
> under one controller could issue a policy, let it lapse, collect the
> auto-breach payout from the LP pool, and repeat — draining LPs with no AI
> judgment involved. The agent bond (§13 of the remediation doc) makes that loop
> value-destroying. Its evidence model also required an IPFS pin.

> **Why PAYOUT-FIX-20 replaced `0x850F773B…`.** The earlier canonical ran
> **pre-fix** code: its planted payout settled the *pool ledger* (Unrated 10.06 →
> 9.06) but paid the buyer through an IC-to-IC `PostMessage` — and because the
> buyer is a plain EOA (no intelligent contract deployed), each transfer child
> finalized with a **"GenVM Execution ERROR"**: value left the contract but never
> reached the wallet. PAYOUT-FIX-20 converted six money-out sites to the external
> `@gl.evm.contract_interface` `_EoaPay` → **EthSend** rail — still the rail
> FIX-22 pays over today (see [PROOFMARK_CONTRACT.md](PROOFMARK_CONTRACT.md)).

The PAYOUT-FIX-20 run's durable contribution is the **wallet-credit proof**: the
`file_claim` tx `0xdeec2cf17c598a770ee272d5f9405dd84e2e4f11498272acd1b30f00da1aed00`
triggered **two child transactions, both FINALIZED, both from the contract → the
buyer EOA `0xd7d4dcab3cc4bab91f7c77df38a50c98461dd1f7`**, carrying **1.000000 GEN**
(the payout) and **2.000000 GEN** (the bond refund) — **no Execution ERROR** on
either. This is the exact mechanism that failed on the pre-fix contract, where the
same children finalized with a "GenVM Execution ERROR". The external **EthSend**
rail is independently pinned by the direct-mode regression test
`test_payouts_leave_over_external_ethsend_rail` (the run's traces show `EthSend`,
never `PostMessage`).

### Superseded pre-fix evidence (kept for context)

The 2026-09-08 **hardened (pre-fix)** deploys `0x850F773B…` (seeded board + planted
claim, `e2e/results/seed-live-hardened.log` + `plant-payout.log`) and `0x1FcE88…`
(37/37 e2e, `e2e/results/studionet-e2e-clean.log`) ran code **before PAYOUT-FIX-20**.
Their pool-ledger money movement (deposit credits, an upheld claim debiting **exactly
1.000000 GEN**, withdraw to 0) is genuine and still demonstrates the ledger half of
the conservation — but their payouts went over the IC-to-IC rail and therefore did
**not** credit the EOA buyer wallets (children finalized "GenVM Execution ERROR").
They are superseded by `0x65319a27…`, whose payout children are clean EthSend
credits (above).

### Direct-mode suite (2026-09-08, PAYOUT-FIX-20 generation)

`python -m pytest tests/direct/ -q` → **56 passed** at that generation. The
current FIX-22 source runs **74 passing** (see the canonical section above).

## Pre-hardening canonical — rebranded artifact (2026-09-06, superseded)

The rebranded `proofmark.py` **before** the H-02 / Phase-7b hardening. Its 37/37 +
10/10 + seeded-board proof was the canonical evidence until the 2026-09-08 hardened
re-proof above; it is kept as the historical validation of the rename.

| Network | Chain ID | Contract address | Deployed | On-chain proof |
|---------|----------|------------------|----------|----------------|
| StudioNet | 61999 | `0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3` | 2026-09-06 | ✅ **37/37 e2e** + **10/10 verify-payments** + seeded live board |

Deploy account (`default`): `0xa881365a99d77be904e414ae610e22938bb0466d`
StudioNet deploy tx: `0x42d1f3c5149c202e89e612ac1678b6115e3745bec82c87df1ae878aa6a621279`

Evidence files: `studionet-proofmark-e2e.log` + `studionet.json` (**37/37**),
`studionet-proofmark-verify-payments.log` (**10/10**: LP deposit/withdraw round-trip;
auto-breach claim pays out + debits the pool exactly 1.000000 GEN), and the seeded
board (`studionet-seed-live.log`, agent `agent-live-1788715641710`, job
`job-live-1788715641710`) re-read independently on 2026-09-07. The 10/10 value log
predates the hardening; the hardened contract's pool-ledger money movement is
re-proven by the 37/37 table above.

## Bradbury: fixed Proofmark deployed (2026-09-08)

Scope for Bradbury is deploy-only (no e2e — StudioNet carries the full scenario). The
fixed Proofmark (PAYOUT-FIX-20) is live on Bradbury from a **minified build** that fits
the pubdata cap while preserving behavior exactly:

- **Deploy tx:** `0xfd0b7d926bf57914193aab7b07bc56a2d7a679e3ee1b0a0771127e6c8962b02b` — status
  `ACCEPTED` / result `AGREE`, CLI `✔ Contract deployed successfully` (exit 0).
- **Contract:** `0xE76AF22aea26A84dB11e87FB946060B02F490217` — **read-verified** 2026-09-08:
  `get_pool_info` across `unrated`/`bronze`/`silver`/`gold`/`penalty` all return fresh pools
  (`balance_atto:0`, `total_shares:0`), confirming the class + ABI decoded and executed.
- **Artifact:** `intelligent-contracts/proofmark-bradbury.py`, **36,811 B** — produced by
  `e2e/minify_contract.py` from the canonical `intelligent-contracts/proofmark.py`
  (72,965 B, sha256 `1b7b1cba2223ff42f5d9628dbc38c9079366807ebe0c6224d3f4201b3eb6356f`). The minifier removes only full-line/trailing
  comments, blank lines and standalone-string (docstring) expressions and enforces, per
  run: `ast.parse` clean + **code-token identity** with the source + fixed-point. The build
  is `genvm-lint` clean (`Proofmark`, 20 methods) and the **56/56 direct tests pass against
  it** — so it is behaviorally identical to the canonical StudioNet artifact, unlike the
  old comment-trim-only idea this section previously rejected (a 57.9 KB trim was still over
  the cap; the docstring-stripping minifier is what fits).
- **Why the canonical source can't deploy to Bradbury:** the 72,965 B source exceeds
  Bradbury's per-tx pubdata cap (`BlockPubdataLimitReached`; largest known-good ~39,869 B).
  This is a **size** limit, not the v0.6/fee migration — per the consensus-v0.6 doc,
  Bradbury is not yet on the v0.6 stack.
- **Historical superseded:** `0xA2aA845152CC493D9EfD48E967d8d1789DDa1ccd` (pre-fix minified,
  2026-09-08, tx `0x88a465…`) and `0x79C15889D5070321176994373C440778a9eC47c1` (Shape A,
  2026-09-03) and the earlier blocked attempts (incl. one ~0.0014 GEN revert). The 2026-09-08
  deploy spent ~0.0049 GEN (30.485816809 → 30.480955856); prior run spend ~0.0081 GEN.

## Historical runs (pre-hardening, kept for context)

| Network | Address | Artifact | When | Proof |
|---------|---------|----------|------|-------|
| StudioNet | `0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4` | Shape A hardened | 2026-09-03 | **28/28** e2e (`studionet-e2e.log`) |
| StudioNet | `0x589472da571Db60151100b153D65a7170367E17D` | **Shape B (pre-rename source)** | 2026-09-06 | **37/37** e2e (`studionet-shapeb-e2e.log`) — the pre-rebrand validation |
| StudioNet | `0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3` | rebranded, pre-H-02/Phase-7b | 2026-09-06 | **37/37** + **10/10** + seeded board (section above) |
| Bradbury | `0x79C15889D5070321176994373C440778a9eC47c1` | Shape A hardened (superseded by `0xA2aA…`, 2026-09-08) | 2026-09-03 | deploy-only reads + earlier-generation roundtrip (`bradbury-roundtrip.log`: deposit 1 GEN → pool → withdraw → 0) |

Do **not** use the 2026-09-02 generation (`0xED90…` StudioNet, `0xcBF4…` Bradbury) — it runs
the unpatched source.

## Residuals

1. **EOA balance-credit is not directly readable on StudioNet** — StudioNet does not
   mirror account balances (`getBalance` reads 0.000000 for every wallet), so a literal
   "recipient wallet rose" read is impossible there. What the current canonical
   **does** prove is one layer deeper than the old pool-ledger-only evidence: the
   payout/refund children of `file_claim`
   (`0xdeec2cf1…1aed00`) are **FINALIZED transfers from the contract to the buyer EOA
   over the external EthSend rail — exact amounts, no Execution ERROR** (see above),
   the identical mechanism that failed on the pre-fix rail. A wallet-balance assertion
   still needs a balance-enforcing network: the fixed Proofmark is deployed on Bradbury
   (`0xE76AF22a…`, minified build) which *would* host a value run, but Bradbury carries
   scarce testnet funds and a value run needs funding ~43 GEN across roles; it stays a
   documented residual unless the user opts to fund it.
2. **(Updated for FIX-22)** Bradbury Proofmark — the pre-fix minified deploy
   (`0xA2aA…`) was superseded by the **PAYOUT-FIX-20** minified build
   (`intelligent-contracts/proofmark-bradbury.py`) deployed to
   `0xE76AF22aea26A84dB11e87FB946060B02F490217`. That build **predates FIX-22**,
   so it still has the unbonded `accept_job` and the CID evidence model; a FIX-22
   minified rebuild + redeploy is outstanding (`node e2e/minify_contract.py`,
   then deploy-only — Bradbury carries scarce testnet funds). StudioNet is the
   canonical live proof of the FIX-22 model. See the Bradbury section above.
3. **(Honest correction, 2026-09-08)** the superseded pre-fix canonical `0x850F…`
   (and Bradbury `0xA2aA…`) reported a "settled payout" that only moved the **pool
   ledger** — the buyer EOA was never credited, because the IC-to-IC rail cannot
   deliver to an empty address (children finalized "GenVM Execution ERROR"). That is
   the very bug PAYOUT-FIX-20 fixes; the current canonical's payout children are clean
   EthSend credits. Prior docs' "buyer paid 1 GEN" phrasing on `0x850F…` referred to
   the ledger move only and is corrected here.
4. **Live judged (V3) claim** — the IPFS-gateway skip that blocked this is
   **resolved by FIX-22**: evidence is now a commit-pinned GitHub URL, and
   `raw.githubusercontent.com` is reachable from the validator set. What remains
   is sourcing a *real* public spec + deliverable pair to judge against (the V3
   path in `e2e/verify-payments.js` takes them as `REAL_SPEC_URL` /
   `REAL_SPEC_SHA256` / `REAL_DELIV_URL` / `REAL_DELIV_SHA256`). Until that run
   lands, the judged bond path is proven in direct-mode tests (74/74) and the
   live deterministic auto-breach payout is proven live on the canonical
   (above). The auto-breach path needs no AI call, so it proves the bond-funded
   payout end to end without exercising validator judgment.

## Re-verify in one command

```bash
# Reproduce the fixed proof from scratch (StudioNet, gasless): deploy a fresh
# contract from the working tree, then run the full §05 demo loop against it
# (register -> fund -> issue -> accept -> deadline -> file_claim payout, incl.
# the child-transfer check) automatically.
cd e2e && node run.js deploy --network studionet && node demo-payout.js
```
