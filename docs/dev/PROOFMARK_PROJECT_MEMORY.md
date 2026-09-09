# Proofmark — Project Memory

Local working notes. This file holds facts that are easy to lose between
sessions: deployed addresses, network quirks, tooling gotchas, and the
reasoning behind decisions. Update it whenever something notable changes.

## PAYOUT-FIX-20 banner — EOA payouts now over the external EthSend rail (2026-09-08)

**A real money bug was found + fixed + re-proven live (commit `349e071`).** Every
payee is a plain EOA wallet, but money-out sites used `gl.get_contract_at(payee)
.emit_transfer(...)` — the **IC-to-IC `PostMessage`** rail, which an empty/EOA address
cannot receive → each transfer child finalized with a "GenVM Execution ERROR": value
left the contract, wallet never credited. Fix: all **six** money-out sites pay through
an external **`@gl.evm.contract_interface` `_EoaPay`** handle → runtime gl_call
**`EthSend`** (credits the EOA; executes on finality, preserving `on="finalized"`
reentrancy semantics). See `genlayer-eoa-payout-path.md` (project root) for the generic
explanation to reuse in other GenLayer projects. **NEW addresses supersede everything
below that says `0x850F…`/`0xA2aA…`:** StudioNet canonical **`0x65319a2787BE8a57ee570fD0eB61A69887D91099`**
(§05 demo loop on-chain, `file_claim` children = FINALIZED EthSend credits to the buyer
EOA, 1 + 2 GEN, no Execution ERROR — `e2e/results/demo-payout.log`) and Bradbury
**`0xE76AF22aea26A84dB11e87FB946060B02F490217`** (deploy-only). The pre-fix `0x850F…`
"settled payout" moved only the pool ledger; the EOA credit never happened — corrected
in `docs/PROOFMARK_LIVE_EVIDENCE.md`.

## Rebrand banner — Proofmark (2026-09-06)

Product rebranded to **Proofmark** across everything
(`proofmark-rebrand-spec.md`, project root). Contract lives at
`intelligent-contracts/proofmark.py` (`class Proofmark`); tests renamed
`tests/direct/test_proofmark*.py`; e2e package → `proofmark-e2e`; **frontend fully
rebranded (Phase 3 done):** Geist fonts, graphite + proof-blue design
system (spec §2, copper/shield/navy/ALL-CAPS removed), `ProofmarkLogo`
hexagon-check, ConformanceStamp NOT DELIVERED/DELIVERED, proof-pill, feed keys
`proofmark.activity.v1`/`proofmark:feed`, identity key
`proofmark.identity.pk.v1` + legacy migration, `proofmarkClient.ts` +
`VERDICT_BOND_ATTO` + `penalty` tier. In-repo docs renamed to `PROOFMARK_*` and
project-root deliverables brand-swept to grep-zero (Phases 4–5 done).
**No ABI change** — the rename
made a new deploy artifact, and **Phase 6 is done**: StudioNet redeployed + re-proven
on the fresh **Proofmark** contract `0x1c91f37F…D85f0c3` (37/37 e2e + 10/10
verify-payments + seeded live board, 2026-09-06); the **Bradbury fresh deploy is
blocked** (`BlockPubdataLimitReached` on the 62,351-byte source) and recorded as an
honest residual — the Bradbury canonical address remains the pre-rename Shape A
`0x79C1…`. The StudioNet
e2e **37/37** run on `0x589472da571Db60151100b153D65a7170367E17D` (2026-09-06) is
the **historical pre-rename validation**. GitHub repo was renamed to `proofmark`
by the user (origin URL untouched; GitHub redirects). Full current addresses are in
the "Deployed contract addresses" section below (old `0x605e…`/`0x5894…` Shape
A/B runs are historical).
**Phase 7 (evidence + close-out) is DONE (2026-09-07):** canonical live evidence + re-verify command
in `docs/PROOFMARK_LIVE_EVIDENCE.md`; the submission note + demo run-sheet/captions reconciled to the
verified rebranded UI copy; `genlayer-project-explorer-submission.md` (a Rigor worked example) and
`SECURITY-CHECK/e2e-deploy-spec.md` (historical Shape B runbook) kept verbatim on purpose. All rebrand
commits were **pushed to GitHub 2026-09-07** (`origin/main` → `9a02783`); the Vercel env rename
(`NEXT_PUBLIC_PROOFMARK_*` = StudioNet `0x1c91…`) was the last manual step.
**Phase 7b (adversarial hardening) is DONE + LIVE-PROVEN (2026-09-08):** GPT-audit H-02
two-phase claims + the adversarial pass (evidence custody split, FIX-16, FIX-18) closed the
last reviewer-pickable flaws (contract items 19–21 in PROOFMARK_CONTRACT.md); **55/55** direct
tests green. Re-proven live on StudioNet with fresh deploys of the hardened working tree — e2e
**37/37** on `0x1FcE880D9fabDEc1Fa883FA3d2CD0685607379f7`, clean **seeded live board** on
`0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`; `page.tsx` seed rebaked, docs re-pointed. The
pre-hardening `0x1c91…` package is superseded (historical). **Manual:** flip Vercel env to
`NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS = 0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`.

## What the project is

Proofmark = non-performance coverage for the AI-agent marketplace, on GenLayer.

- `intelligent-contracts/proofmark.py` — single GenLayer intelligent contract.
- `frontend/` — Next.js dashboard (deploy to Vercel).
- `docs/PROOFMARK_UX_FLOW.md` — the three user flows (agent / buyer / LP).

Four moving parts in the contract:
1. **Agent identity & reputation** — one wallet binds to one `agent_id` at
   registration; tier (`unrated/bronze/silver/gold`) is derived from real
   history, never requested.
2. **Policies** — buyer pays an exact, deterministic premium (coverage × tier
   rate) to insure a job against a specific agent.
3. **LP pools** — LPs fund a tier and earn premiums; per-claim payout is capped
   at 10% of the tier pool.
4. **Claims** — the only AI-judged action. GenLayer validators fetch the spec
   + the agent-submitted deliverable from IPFS and score conformance.

## Networks

| Alias | CLI network | genlayer-js chain | Gas |
|-------|-------------|-------------------|-----|
| StudioNet | `studionet` | `studionet` | gasless (0 GEN fine) |
| Bradbury | `testnet-bradbury` | `testnetBradbury` | needs GEN (faucet) |
| Asimov | `testnet-asimov` | `testnetAsimov` | needs GEN |

- studio.genlayer.com rate limits: **60 req/min, 1000 req/hr, 10000 req/day**.
  Pending-queue cap ~32 in-flight txs per sender. Throttle + wait for receipts.
- `gltest` networks are named with underscores: `studionet`, `testnet_bradbury`.

### Consensus v0.6 migration — forward-looking only, no action at submission

Recorded 2026-09-08 per the user. Before any FUTURE deploy study
https://docs.genlayer.com/developers/consensus-v06-migration ("Test on Studio-dev
first"): the v0.6 RC stack is on **studio-dev** (`studio-dev.genlayer.com`, RPC
`https://studio-dev.genlayer.com/api`, chain 61997) and **may reset**; the stable
**studionet** chain object (61999 — where canonical `0x850F…` lives) must NOT be
pointed at the preview RPC — chain identity and consensus contract addresses move
together. On fee-charging networks every deploy/write must carry a quoted
`FeesDistribution` estimated from a measured `fee-profile.json`; a tx counts as
success only when status `ACCEPTED`/`FINALIZED` **and** the execution result is
`FINISHED_WITH_RETURN` (the same accepted-but-error rule this repo hardened for).
A Studio deployment can be gasless — detect that from the fee estimate, not the
network name. The user's earlier py-genlayer v0.3.0 / `Depends`-hash header note
is superseded by this doc for deploy decisions.

## Deployed contract addresses

**Canonical — Proofmark, FIXED artifact, PAYOUT-FIX-20 (`proofmark.py`, `class Proofmark`):**
- **StudioNet (canonical LIVE — §05 demo loop + settled payout over the external EthSend rail; `page.tsx` + Vercel env point at this):**
  `0x65319a2787BE8a57ee570fD0eB61A69887D91099` (deployed 2026-09-08 via `run.js deploy`).
  - **§05 loop on it** (`e2e/results/demo-payout.log` + `demo-payout.json`): agent
    `agent-live-1788895030112`, job `job-live-1788895030112` (1 GEN cover @ 0.06) —
    register → fund 10/5/3/2 → issue → accept → deadline passed (nothing delivered) →
    `file_claim` (2 GEN bond) resolved **upheld**; buyer paid **exactly 1.000000 GEN**
    from the Unrated pool, the 2 GEN bond refunded. Board re-read after settlement:
    Unrated **9.0600 / locked 0.0000**, Bronze 5, Silver 3, Gold 2. **Wallet-credit
    proof:** the `file_claim` tx `0xdeec2cf1…1aed00` triggered **two children, both
    FINALIZED, contract → buyer EOA `0xd7d4dcab…` (1 + 2 GEN), NO Execution ERROR** —
    the external rail. Live wallet in `e2e/live-keys.json`.
- **StudioNet (superseded pre-fix canonical, 2026-09-08):** `0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`
  — ran the **pre-fix** code; its "settled payout" (seed-live + plant-payout logs)
  moved only the pool ledger, the buyer EOA was **never credited** (children errored).
  Do not point the frontend at it.
- **StudioNet (e2e evidence — pre-fix, pool intentionally drained by the run):**
  `0x1FcE880D9fabDEc1Fa883FA3d2CD0685607379f7` (deployed 2026-09-08, same **pre-fix**
  hardened working-tree source). **Full e2e 37/37 PASS** (`studionet.json` +
  `studionet-e2e-clean.log`): deposit credits pool 20; upheld auto-breach claim debits
  pool 20.12→19.12 **exactly 1 GEN**; full LP withdraw drains to 0.
  - Hardened deltas over the pre-hardening artifact: **evidence custody split** in
    `_judge_breach` (a 4xx/oversized deliverable → breach; a 4xx/oversized spec →
    rejected — a buyer can't manufacture a breach against an agent that delivered),
    **FIX-16** (`accept_job` refuses post-deadline acceptance), **FIX-18**
    (permissionless `expire_pending_policy` past deadline+7d), and the GPT-audit
    **H-02** two-phase claims (FIX-19): payable `file_claim` is deterministic + escrows
    the bond, the nondet judgement runs in the non-payable `judge_claim`,
    `rescind_pending_claim` recovers the bond. **56/56 direct tests green** (incl. the
    `external_ethsend_rail` regression); `genvm-lint` clean. Frontend H-04 (positive
    success check) / M-01 (pending lifecycle) fixes are in the same batch.
- **StudioNet (superseded first hardened deploy):** `0x9fac0b43D5fcE76E6115dB91E0a7105D16218a82`
  (2026-09-07, tx `0x5b1a50…`; the first FIX-16/18 deploy — its e2e hit StudioNet RPC
  flakiness at 26/37; superseded by the 2026-09-08 fresh deploys above).
- **StudioNet (superseded pre-hardening canonical):** `0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3`
  (deployed 2026-09-06, tx `0x42d1f3c5…`). 37/37 e2e + 10/10 verify-payments + seeded
  board (agent `agent-live-1788715641710`); superseded by the hardened re-proof.
  - StudioNet quirks (unchanged): no `genlayer schema` ("not supported on this network");
    RPC is flaky (ECONNRESET / SSL session-id) — retry and it succeeds; `registered_at`
    includes fractional seconds — the deadline guard (epoch-compare) parses ISO to
    integer epoch seconds, slices the fractional tail, requires a 60 s minimum horizon.
- **Bradbury (canonical but pre-rename Shape A):** `0x79C15889D5070321176994373C440778a9eC47c1`
  (deployed 2026-09-03, tx `0x14222a14…3832350a`; read-verified live).
  - **Proofmark fresh deploy BLOCKED (honest residual):** the 62,351-byte
    `proofmark.py` is rejected by Bradbury with `invalid transaction:
    BlockPubdataLimitReached` (largest known-good deploy ~39,869 B Shape A artifact).
    One blocked attempt spent ~0.0014 GEN (30.495286 → 30.493878). No further
    attempts per account-funds constraint. Canonical Bradbury address stays the
    pre-rename Shape A bytecode until either the artifact shrinks or the limit
    rises. `e2e/run.js` bradbury default carries this note.
  - **1 GEN deposit→withdraw roundtrip 7/7 PASS** (`e2e/results/bradbury-roundtrip.log`)
    was proven on a prior generation; value semantics unchanged.
  - Bradbury `registered_at` is whole seconds (`2026-09-02T04:26:37Z`, no fraction).
  - Bradbury receipts have NO `consensus_data` — outcome is numeric
    `txExecutionResult` (1=return/ok, 2=error/revert, 0=NOT_VOTED); a
    `LEADER_TIMEOUT`/`IDLE` tx is undetermined, never ok.
- **Historical Proofmark-era runs (pre-rename source):** StudioNet Shape B
  `0x589472da571Db60151100b153D65a7170367E17D` (37/37 e2e, 2026-09-06 — the pre-rebrand
  validation; `studionet-shapeb-e2e.log`); StudioNet Shape A `0x605e5BE4…` (28/28 e2e,
  2026-09-03; `studionet-e2e.log`). Recorded as context in LIVE_EVIDENCE.
- **Superseded (do not use):** 2026-09-02 unpatched generation — StudioNet
  `0xED90a97A77cd959bB278cBDfA0f2981dF5b5B843`, Bradbury
  `0xcBF48A444242919EEA65Ff5bB6BD9d2CB82506e2`; older still StudioNet `0x4870…`,
  Bradbury `0x1ad8…` (first) and `0xcE82…` (holds orphaned 20.06 GEN from a
  LEADER_TIMEOUT deposit burn; no recovery path — see PROOFMARK_PROGRESS.md).

The frontend needs the address via `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS` (and
`NEXT_PUBLIC_PROOFMARK_NETWORK` for which network) — see `frontend/.env.example`.

## Tooling gotchas (this machine)

- `genvm-lint` exe lives at
  `%APPDATA%\Python\Python314\Scripts\genvm-lint.exe` (not on PATH). Must set
  `PYTHONIOENCODING=utf-8` on Windows or it crashes printing `✓`.
- `genvm-lint validate` currently fails: it tries to fetch GenVM SDK
  `v0.3.0-rc7` which 404s. Cached: v0.2.12 / v0.2.16. Lint (AST) still passes;
  real deployment is the authoritative validation.
- `genlayer-test` 0.29.2 has a Windows bug in `gltest/direct/loader.py`: it
  tries to `os.unlink` a temp file still open as stdin. Patched in-place to
  swallow `PermissionError`. If genlayer-test is upgraded, re-apply the patch.
- Node builds are NOT run locally (8GB RAM). Vercel does the cloud build.
- `gh` CLI not installed — GitHub repo creation/check must be done in the
  browser or via API with a token.

## Contract design decisions worth remembering

- `_normalize_key()` lowercases+strips every user-typed id before touching a
  TreeMap key (prevents case-variant squatting). As-typed text kept for display.
- `issue_policy` only allows a policy against a tier with real LP capital, and
  coverage ≤ current pool value (closes empty-pool first-depositor exploit).
- `withdraw()` refuses to drop a tier's balance below `tier_locked_exposure`.
- The deliverable being judged is submitted by the **agent** only — a buyer can
  never supply their own "evidence."
- `spec_hash` / `deliverable_hash` must look like an IPFS CID (CIDv0/v1 shape),
  not a mutable URL — so every validator fetches identical bytes.
- Tier promotion needs a minimum real spend + distinct buyers + elapsed tenure
  (sybil mitigation; documented as raising cost, not making it impossible).
- Premiums must match exactly (no rounding slack).
- `issue_policy` requires the deadline to be strictly in the future. Without
  that, a buyer could issue with an already-passed deadline and instantly
  claim the no-deliverable auto-breach (drain pool / burn agent reputation in
  one block). Guard added 2026-09-02; regression test
  `test_issue_policy_rejects_past_deadline`.

## GenLayer signing model (frontend, learned the hard way)

- MetaMask **cannot sign** GenLayer tx. The app signs with a genlayer-js
  keypair created/stored in the browser (localStorage; key + legacy migration
  live in `lib/identity.ts`) and labels it honestly as a "browser identity." Modeled on the Rigor
  frontend (`identity.ts` / `IdentityBadge.tsx` / `providers.tsx` on disk).
- **viem private-key trap:** `createAccount(pk)` returns an Account object
  whose `.privateKey` is `undefined`. Persist YOUR OWN copy of the key
  (from `generatePrivateKey()`) and rebuild with `createAccount(key)`.
- Write client = `createClient({ chain, account })` with the Account object —
  no provider, no `.connect()`. MetaMask-style `{ account: address, provider,
  connect() }` is the WRONG model here.
- **genlayer-js `writeContract` types require `value: bigint`** (always present).
  Its implementation defaults to `0n` and signs value-0 transactions normally
  on the local-account path (verified in genlayer-js 1.2.0 `dist/index.js`,
  `_sendTransaction`). The older Rigor note "never send an explicit value:0 —
  GenLayer's RPC rejects it" applies to the MetaMask/`eth_sendTransaction`
  provider path, NOT to local-account signing. This app uses local accounts, so it
  passes `value` unconditionally (0n when nothing moves).
- Identity hydration must run in a client-only `useEffect` (never during SSR),
  or the page server-renders a fresh random key every request.

## Frontend design (user is opinionated about the UI — Proofmark tokens govern)

- **Superseded (pre-rebrand):** the "bold modern" dark-navy `#0a0e19` console with
  a copper `#d98e45` glow was the pre-rebrand look. The Proofmark rebrand (spec §2)
  **retired it** — true graphite-black `#09090b/#0e0e11/#141417`, proof blue
  `#3b8eff` (primary), settled green `#22c97a` (delivered), breach amber
  `#e8a020` (NOT DELIVERED), muted-red `#c96161` (penalty tier), infra-grid body,
  Geist/Geist_Mono, sentence-case mono labels (no ALL-CAPS eyebrows), hexagon-check
  `ProofmarkLogo` (no shield, no watermark glyph beyond a faint hexagon).
- Keep the Vercel deployment pointed at **StudioNet**; Bradbury stays in docs.
- Do not surprise the user with a light theme again without asking.

## Related

- `docs/dev/PROOFMARK_PROGRESS.md` — running log of work, status, and next steps.
