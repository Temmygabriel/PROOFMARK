# Proofmark — Live Network Evidence

Where the **Proofmark** contract (`intelligent-contracts/proofmark.py`,
`class Proofmark`) is proven live on real GenLayer networks, with the tx hashes and
step evidence behind that claim. Historical runs are kept below for context; the
**current canonical** is the Phase-7b hardened artifact at the top of this page.

## Current canonical — fixed Proofmark, PAYOUT-FIX-20 (2026-09-08)

The fixed `proofmark.py` — the **PAYOUT-FIX-20 external-EthSend-rail fix** plus the
Phase-7b hardening (GPT-audit H-02 two-phase-claim fix, evidence custody split,
FIX-16 impossible-acceptance, FIX-18 forever-pending release; see
[PROOFMARK_CONTRACT.md](PROOFMARK_CONTRACT.md)) — is proven live on StudioNet by
**one fresh deploy that carries the full §05 demo loop AND a settled payout whose
EthSend children are verified**:

| Address | Role | On-chain proof |
|---------|------|----------------|
| **`0x65319a2787BE8a57ee570fD0eB61A69887D91099`** | **canonical live** — the address the frontend/env points at; funded board + a settled payout paid over the external rail | **§05 demo run** (`e2e/results/demo-payout.log` + `demo-payout.json`), 2026-09-08 |

> **Why a new canonical (PAYOUT-FIX-20).** The prior canonical `0x850F773B…` ran
> **pre-fix** code: its planted payout settled the *pool ledger* (Unrated 10.06 →
> 9.06) but paid the buyer through an IC-to-IC `PostMessage` — and because the buyer
> is a plain EOA (no intelligent contract deployed), each transfer child finalized
> with a **"GenVM Execution ERROR"**: value left the contract but never reached the
> wallet. That is exactly the bug PAYOUT-FIX-20 fixes (six money-out sites converted
> to the external `@gl.evm.contract_interface` `_EoaPay` → **EthSend** rail; see the
> module docstring / [PROOFMARK_CONTRACT.md](PROOFMARK_CONTRACT.md) item 22).
> `0x850F…` is superseded — do not point the frontend at it.

Deployed by `node e2e/run.js deploy --network studionet` from the fixed working
tree (2026-09-08). GenVM contracts are consensus-stored (`eth_getCode` is not
applicable on StudioNet), so every finalized write tx below — all on this address —
is the proof the deployment executed.

### §05 demo loop + EthSend payout proof (`0x65319a27…`)

Written by `node e2e/demo-payout.js` — the reviewer's exact path (submission note
§05): register agent → LP funds Unrated 10 (+ Bronze 5 / Silver 3 / Gold 2) → issue
1 GEN cover @ 0.06 premium, short deadline, CID spec → accept → deadline passes with
nothing delivered → `file_claim` (2 GEN bond) → deterministic auto-breach. Every
write finalized success; board re-read live from the contract. Agent
`agent-live-1788895030112` (wallet in `e2e/live-keys.json`), job
`job-live-1788895030112`.

After the deadline passed with no deliverable, the claim resolved **upheld**: policy
`claimed`, buyer paid **exactly 1.000000 GEN** from the Unrated pool, the 2 GEN bond
refunded. Board re-read directly from the contract after settlement:

| Tier | Pool | Locked | Jobs |
|------|------|--------|-----------|
| unrated | 9.0600 GEN | 0.0000 GEN | 1 settled payout: `job-live-1788895030112` (1 GEN covered, NOT DELIVERED) |
| bronze | 5.0000 GEN | — | — |
| silver | 3.0000 GEN | — | — |
| gold | 2.0000 GEN | — | — |
| penalty | 0 | — | — |

**The wallet-credit proof (StudioNet's best).** The `file_claim` tx
`0xdeec2cf17c598a770ee272d5f9405dd84e2e4f11498272acd1b30f00da1aed00` triggered **two
child transactions, both FINALIZED, both from the contract `0x65319a27…` → the buyer
EOA `0xd7d4dcab3cc4bab91f7c77df38a50c98461dd1f7`**, carrying **1.000000 GEN** (the
payout) and **2.000000 GEN** (the bond refund) — **no Execution ERROR** on either.
This is the exact mechanism that failed on the pre-fix contract, where the same
children finalized with a "GenVM Execution ERROR". The external **EthSend** rail is
independently pinned by the direct-mode regression test
`test_payouts_leave_over_external_ethsend_rail` (the run's traces show `EthSend`,
never `PostMessage`).

Demo txs (all `[PASS]`, `e2e/results/demo-payout.log`): register
`0xdbea899cebadb59e8b9ab42697ea1f55c0ad152a86cd7ea2f43bdfd6a8ca1a6d`, deposits
`0x22e25f1583264e876115de35ccbf23cac175901bc7501688af1ada67b3e56b84` (unrated 10) /
`0x0a24075581505bcee11282259e5fac7f28cf64e5ca7033688644801fcc9f02fa` (bronze 5) /
`0x1ad4315736e19101dcd26f631ec63ee6eda2045fd713cb5dae0a7086a9e9d10a` (silver 3) /
`0x4d6df5c43a5a0b34b91f2d9c5f827dc33447471e9749c98a5a65343049eeeba4` (gold 2), issue
`0x26ab2637c1f6cabdd1827ee833cbf87ab789207a8afc4f2ded64b8fdf11b53b8`, accept
`0xd574fa1127ede36c3640f500d948d00f79c42e4f113b52f3deaff865edb8107a`,
file_claim `0xdeec2cf17c598a770ee272d5f9405dd84e2e4f11498272acd1b30f00da1aed00`.

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

### Direct-mode suite (2026-09-08)

`python -m pytest tests/direct/ -q` → **56 passed** (the current suite, including the
H-02 two-phase and Phase-7b regression tests and the PAYOUT-FIX-20
`test_payouts_leave_over_external_ethsend_rail`). `genvm-lint check` clean.

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
2. **(Resolved 2026-09-08, updated for the fix)** Bradbury Proofmark — the pre-fix
   minified deploy (`0xA2aA…`) is superseded by the **fixed** minified build
   `intelligent-contracts/proofmark-bradbury.py` (**36,811 B**) deployed to
   `0xE76AF22aea26A84dB11e87FB946060B02F490217`. See the Bradbury section above.
3. **(Honest correction, 2026-09-08)** the superseded pre-fix canonical `0x850F…`
   (and Bradbury `0xA2aA…`) reported a "settled payout" that only moved the **pool
   ledger** — the buyer EOA was never credited, because the IC-to-IC rail cannot
   deliver to an empty address (children finalized "GenVM Execution ERROR"). That is
   the very bug PAYOUT-FIX-20 fixes; the current canonical's payout children are clean
   EthSend credits. Prior docs' "buyer paid 1 GEN" phrasing on `0x850F…` referred to
   the ledger move only and is corrected here.
4. **Live judged (V3) claim** — skipped: the evidence gateway `https://w3s.link/ipfs/`
   does not resolve the pinned CIDs from this network (gateway migration: 403/429/504;
   alternate gateways unreachable). The judged bond path (incl. the H-02 two-phase
   split) is proven in direct-mode tests (**56/56** in `tests/direct/`) and the live
   deterministic auto-breach payout (the §05 loop above).

## Re-verify in one command

```bash
# Reproduce the fixed proof from scratch (StudioNet, gasless): deploy a fresh
# contract from the working tree, then run the full §05 demo loop against it
# (register -> fund -> issue -> accept -> deadline -> file_claim payout, incl.
# the child-transfer check) automatically.
cd e2e && node run.js deploy --network studionet && node demo-payout.js
```
