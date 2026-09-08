# Proofmark — Live Network Evidence

Where the **Proofmark** contract (`intelligent-contracts/proofmark.py`,
`class Proofmark`) is proven live on real GenLayer networks, with the tx hashes and
step evidence behind that claim. Historical runs are kept below for context; the
**current canonical** is the Phase-7b hardened artifact at the top of this page.

## Current canonical — Phase-7b hardened artifact (2026-09-08)

The hardened `proofmark.py` — the rebranded artifact plus the GPT-audit H-02
two-phase-claim fix and the 2026-09-07 adversarial pass (evidence custody split,
FIX-16 impossible-acceptance, FIX-18 forever-pending release; see
[PROOFMARK_CONTRACT.md](PROOFMARK_CONTRACT.md) items 19–21) — is re-proven live on
StudioNet by **two fresh deploys of the same working-tree source**:

| Address | Role | On-chain proof |
|---------|------|----------------|
| **`0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`** | **canonical live** — seeded board, the address the frontend/env points at | clean **seed-live** board below (`e2e/results/seed-live-hardened.log`) |
| `0x1FcE880D9fabDEc1Fa883FA3d2CD0685607379f7` | e2e evidence (pool intentionally drained by the run) | **37/37 e2e** (`e2e/results/studionet-e2e-clean.log` + `studionet.json`) |

Both deployed by `node e2e/run.js deploy --network studionet` from the hardened
working tree (2026-09-08). GenVM contracts are consensus-stored (`eth_getCode` is not
applicable on StudioNet), so every finalized write tx in the two logs below — all on
these addresses — is the proof the deployments executed.

### Hardened 37/37 e2e highlights (`0x1FcE88…`)

The full step log is `e2e/results/studionet-e2e-clean.log` (machine JSON
`studionet.json` — every step carries its finalized tx hash). Representative steps
and tx hashes:

| Step | Result | Tx hash |
|------|--------|---------|
| `register(agent)` (agent binds to wallet) | ok | `0x3e94a803541fe0e9ede3d6f566ec1c1a930d25cbf3c967224f3ee6bc2317a582` |
| register(2nd id) reverts (address bound) | revert | `0xea73a7e6f9359bb4c9c7c28d632f2d19559c2269bf61fd967605e495f8cc255e` |
| LP deposit 20 GEN → pool | ok | `0xb2bf7f0b49db834c4a62cb4f1c7002e7438394e7748bec186ce92c75ea95efff` |
| quote = unrated / 600 bps / 0.06 GEN premium | view | — |
| issue job (payable premium) → policy `pending` | ok | `0x6d0ae1aca2c85f083cf06e00eda96960cd379039fe43bb7cb4261563f50e0bef` |
| agent rejects pending → `expired`, premium refunded | ok | `0x643399d75194ed07769cb7450f52263650b2ab58b4c155247a9fbc0755e775da` |
| accept pending → policy `active` | ok | `0x8a7b79f646263c045ba567d15982662e480bbb0b28a2e6c5bec9b357ace029b7` |
| URL-shaped deliverable REVERTS (canonical CID only) | revert | `0x0833fc402099e5def16f0adbab5578a2f47ffd1504b4e52210e0069fc7b7b065` |
| past-deadline issue reverts | revert | `0x886bde53472916deb8f5b71dfb5c750d7fe33b2db7b7a9e6086a6ed28f056848` |
| premature claim reverts (pre-deadline, no deliverable) | revert | `0x0a70c56a402f9ce5495196d3d9480db8a784351e6272a1ba76a18a9b1d329a35` |
| full LP withdraw under locked exposure reverts | revert | `0x4b14dd7d01ef92f8e08bff0fe1f180ee66950108c7cb04ca1f44ac20603ca310` |
| post-deadline submit reverts (deliverable frozen) | revert | `0x52d3b867fca9906e3f2639ef6f1ea00959ba4b767fc7c625f4cb29b290f09ab7` |
| buyer expires job (deadline passed) → `expired` | ok | `0xe9c6912592015f890f7604ac6cb0c26fd3568b3f0b135341c99941b75fab6f6b` |
| `file_claim` after deadline → **auto-breach**, claim `upheld` | ok | `0xdd2db78b0b09200889d8b4249345679587b96a83a4ba96e469e4800b507c1b3c` |
| policy → `claimed`; pool **paid coverage** (20.12 → 19.12 GEN), exposure released | ok | see log |
| agent claim counters `filed=1 upheld=1` | ok | see log |
| LP withdraws everything → pool drained to 0 | ok | `0xd8103f0b1804769c7f059bef348ce969bc5d6026fc201cf571891000432f5ed0` |

The money-relevant rows (deposit credits the pool, an upheld claim debits it
**exactly 1.000000 GEN**, the full withdrawal releases the rest) are the pool-ledger
half of "GEN actually moved". The wallet-credit half (Mode B) is only enforceable on
a balance-mirroring network — see [Residuals](#residuals).

### Hardened seeded live board (`0x850F773B…`)

Written by `node e2e/seed-live.js`; every write finalized success, board re-read back
live from the contract. Agent `agent-live-1788864539810` (wallet in
`e2e/live-keys.json`), job `job-live-1788864539810` (1 GEN cover, deadline ~1 h out):

| Tier | Pool | Locked | Live jobs |
|------|------|--------|-----------|
| unrated | 10.0600 GEN | 1.0000 GEN | 1 active job (payable premium 0.06 GEN paid) |
| bronze | 5.0000 GEN | — | — |
| silver | 3.0000 GEN | — | — |
| gold | 2.0000 GEN | — | — |
| penalty | 0 | — | — |

Seed txs (all `[PASS]`, `e2e/results/seed-live-hardened.log`): register
`0x95646645…98e3aba`, deposits `0x0718b1ec…2a0d0ed` (unrated 10) /
`0xe4671e06…2b2e562` (bronze 5) / `0x18100fc9…459f1f2a` (silver 3) /
`0x15a5672c…39d6c569c` (gold 2), issue `0xac5297d9…3950b244`, accept
`0x261e5ae7…4bd2a728`.

### Direct-mode suite (2026-09-08)

`python -m pytest tests/direct/ -q` → **55 passed** (the current suite, including the
H-02 two-phase and Phase-7b regression tests). `genvm-lint check` clean.

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

## Bradbury status: deploy-only (blocked)

Scope for Bradbury was deploy-only (no e2e — StudioNet carries the full scenario). A fresh
Proofmark address on Bradbury **could not be produced**: the source
(`intelligent-contracts/proofmark.py`, 62,351 bytes) is rejected by the Bradbury RPC with
`invalid transaction: BlockPubdataLimitReached`. Details recorded honestly:

- Largest source ever deployed to Bradbury from this repo: the **Shape A** artifact
  (~39,869 B → canonical `0x79C1…`, 2026-09-03). The hardened contract is ~62 KB — it
  exceeds Bradbury's per-transaction pubdata cap. (StudioNet, gasless, accepts it; both
  hardened 37/37 and the seed ran there.)
- The single blocked deploy attempt included + reverted, spending ~0.0014 GEN
  (30.495286 → 30.493878). No further attempts were made per the account-funds constraint.
- Byte-exact provenance is a hard constraint (`deployed source == audited repo file`), so a
  comment/whitespace-trimmed variant was **not** used to force the deploy.

**Canonical Bradbury address therefore remains `0x79C15889D5070321176994373C440778a9eC47c1`**
— the pre-rename Shape A artifact (2026-09-03, read-verified). It is *not* the hardened
Proofmark bytecode. A Proofmark Bradbury deploy is a known residual pending either a
smaller artifact or a raised network limit.

## Historical runs (pre-hardening, kept for context)

| Network | Address | Artifact | When | Proof |
|---------|---------|----------|------|-------|
| StudioNet | `0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4` | Shape A hardened | 2026-09-03 | **28/28** e2e (`studionet-e2e.log`) |
| StudioNet | `0x589472da571Db60151100b153D65a7170367E17D` | **Shape B (pre-rename source)** | 2026-09-06 | **37/37** e2e (`studionet-shapeb-e2e.log`) — the pre-rebrand validation |
| StudioNet | `0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3` | rebranded, pre-H-02/Phase-7b | 2026-09-06 | **37/37** + **10/10** + seeded board (section above) |
| Bradbury | `0x79C15889D5070321176994373C440778a9eC47c1` | Shape A hardened | 2026-09-03 | deploy-only reads + earlier-generation roundtrip (`bradbury-roundtrip.log`: deposit 1 GEN → pool → withdraw → 0) |

Do **not** use the 2026-09-02 generation (`0xED90…` StudioNet, `0xcBF4…` Bradbury) — it runs
the unpatched source.

## Residuals

1. **Wallet-credit (Mode B) proof is unprovable on StudioNet** — StudioNet does not
   mirror account balances (`getBalance` reads 0.000000 for every wallet), so the
   "recipient wallet actually rose" assertion can only be a wallet-credit check on a
   balance-enforcing network. The pool-ledger conservation half — deposit credits,
   payout debits **exactly** the coverage, exposure releases — is proven live by the
   37/37 table above. A Bradbury value run would close Mode B, but Bradbury cannot
   host the hardened 62 KB artifact (`BlockPubdataLimitReached`, above) and carries
   scarce testnet funds; it stays a documented residual.
2. **Bradbury Proofmark fresh deploy** — blocked by `BlockPubdataLimitReached` on the
   62,351-byte source; canonical Bradbury is the pre-rename Shape A artifact. See above.
3. **Live judged (V3) claim** — skipped: the evidence gateway `https://w3s.link/ipfs/`
   does not resolve the pinned CIDs from this network (gateway migration: 403/429/504;
   alternate gateways unreachable). The judged bond path (incl. the H-02 two-phase
   split) is proven in direct-mode tests (**55/55** in `tests/direct/`) and the live
   deterministic auto-breach payout (37/37 above).

## Re-verify in one command

```bash
# Reproduce the hardened proof from scratch (StudioNet, gasless): deploy a fresh
# contract from the working tree, then run the full e2e against it automatically.
cd e2e && node run.js deploy --network studionet && node run.js e2e --network studionet
# Then seed a fresh live board on a second fresh deploy:
node run.js deploy --network studionet && node seed-live.js
```
