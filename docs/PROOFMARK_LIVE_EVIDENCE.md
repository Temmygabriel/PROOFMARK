# Proofmark — Live Network Evidence

Where the rebranded **Proofmark** contract (`intelligent-contracts/proofmark.py`,
`class Proofmark`) is proven live on real GenLayer networks, with the tx hashes and
step evidence behind that claim. Historical pre-rename runs are kept below for
context; the **canonical** Proofmark proof is the StudioNet deployment at the top
of this page.

## Canonical Proofmark deployment (rebranded artifact)

| Network | Chain ID | Contract address | Deployed | On-chain proof |
|---------|----------|------------------|----------|----------------|
| **StudioNet** | 61999 | **`0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3`** | 2026-09-06 | ✅ **37/37 e2e** + **10/10 verify-payments** + seeded live board (below) |
| Testnet Bradbury | 4221 | `0x79C15889D5070321176994373C440778a9eC47c1` | 2026-09-03 | deploy-only read-verified — but **pre-rename Shape A artifact** (Proofmark redeploy blocked, see [Bradbury status](#bradbury-status-deploy-only-blocked)) |

Deploy account (`default`): `0xa881365a99d77be904e414ae610e22938bb0466d`
StudioNet deploy tx: `0x42d1f3c5149c202e89e612ac1678b6115e3745bec82c87df1ae878aa6a621279`
(receipt finalized; every step tx below references the same contract and proves the
deployment executed — GenVM contracts are consensus-stored, so `eth_getCode` is not
applicable on StudioNet; live view/write calls are the proof.)

### Evidence files (all committed under `e2e/results/`)

| File | Verdict | What it proves |
|------|---------|----------------|
| `studionet-proofmark-e2e.log` + `studionet.json` | **37/37 PASS** | Full lifecycle on the Proofmark contract (see highlights below) |
| `studionet-proofmark-verify-payments.log` | **10/10 PASS** | Value actually moves: LP deposit/withdraw round-trip; auto-breach claim pays out + debits the pool exactly 1.000000 GEN |
| `studionet-seed-live.log` | seeded board | Live underwriting board written to the canonical contract |
| fresh read-verify (2026-09-07) | persisted | Independent reads of the seeded state taken after the run (this page's source of the board numbers) |

### 37/37 e2e highlights (contract `0x1c91f37F…D85f0c3`, StudioNet)

The full step log lives in `e2e/results/studionet-proofmark-e2e.log` (machine JSON in
`e2e/results/studionet.json` — every step carries its finalized tx hash). Representative
steps and their tx hashes:

| Step | Result | Tx hash |
|------|--------|---------|
| `register(agent)` (agent binds to wallet) | ok | `0x386f107b045b68ac66f8937046288255bfb90d1d3ce0a97b11175d6de05fe73c` |
| register(2nd id) reverts (address bound) | revert | `0x78c7f1591c3286526ab13b7018dcea69f60e78810a2f5a6ca41b7a023c2eb8a6` |
| LP deposit 20 GEN → pool | ok | `0x1dfca47f0f6e270f81557e0723a8a960d6c371b1d4be3cfdf73649d72f137fe0` |
| quote = unrated / 600 bps / 0.06 GEN premium | view | — |
| issue job (payable premium) → policy `pending` | ok | `0x68b81acf4e2fb3de7806cc868e21c675df3d8bd99fb3f64872443463f74f6753` |
| agent rejects pending → policy `expired`, premium refunded | ok | `0x3deccdf54e45778beef0f7b81f7c89cfb8d0fb911f681efdf4481f21a3fefb2b` |
| accept pending → policy `active` | ok | `0x50dc925550a645ab8181f38370df21d391d1b9f6454404c2ed7d967dd7234e51` |
| URL-shaped deliverable REVERTS (canonical CID only) | revert | `0xf44995234d15ad059c76ad80c4a3eaed5f8b62f62b23fc9a1b313be1c9b670d1` |
| past deadline issue reverts | revert | `0xb65b6f47e69ca29ad23ba1ab536925da50b02cdd5057e53a350eebd3a688f89a` |
| premature claim reverts (pre-deadline, no deliverable) | revert | `0x230902a805408abe16640d1624da2b3694d2d4de0f5b3ff8fd5c9cb08755d2d5` |
| full LP withdraw under locked exposure reverts | revert | `0x2db0e9ee1e7363b4e8a15df03491e1ef60c06f076bdfddd50ccd2e3d45627288` |
| post-deadline submit reverts (deliverable frozen) | revert | `0xa0dcd4a53298206be50e453904f66d5be8d478a07483ab8c53c4914d33215181` |
| buyer expires job (deadline passed) → `expired` | ok | `0xe3bf9f6e8b9089e7ee73331329fe09401fab1412b8962ffdf07a97c14de0a120` |
| `file_claim` after deadline → **auto-breach**, claim `upheld` | ok | `0x163aa4e831c86df96182c87268939095a3225a8013ac75f16f0e11a057da12f8` |
| policy → `claimed`; pool paid coverage; exposure released | ok | see log |
| LP withdraws everything → pool drained to 0 | ok | `0x42c16f3bba2c69cb759dc2277e68bebdd05fadeeb59a2f734244f4a6966a1278` |

### 10/10 verify-payments (value-movement proof)

`e2e/results/studionet-proofmark-verify-payments.log`:
- **V1** — LP deposit → withdraw round-trip: pool `0 → 5 → 0` GEN, shares credited and
  released, both txs finalize success.
- **V2** — auto-breach claim payout: 12.06 GEN pool, claim finalized `AGREE[SUCCESS…]`
  (`0xcc25add35e4bc3335eb7730da920ca83220d8d711590528af85771b70a1407c5`), contract state
  `upheld`, pool debited exactly **1.000000 GEN** (12.060000 → 11.060000), bond refund path
  intact.
- **V3 (judged claim)** — skipped on live: the evidence gateway (`https://w3s.link/ipfs/`)
  no longer resolves the pinned CIDs (see [Residuals](#residuals)). Judged-path behaviour is
  covered in direct-mode tests (47 in `tests/direct/test_proofmark.py`) and in the live
  auto-breach path above.

### Seeded live board (canonical StudioNet Proofmark)

Written by `node e2e/seed-live.js` after the 37/37 run so the demo dashboard reads real
data from the Proofmark contract (agent id `agent-live-1788715641710`, job
`job-live-1788715641710`). Re-read independently on 2026-09-07 — **state persisted**:

| Tier | Pool | Locked | Live jobs |
|------|------|--------|-----------|
| unrated | 10.0600 GEN | 1.0000 GEN | 1 active job (payable premium 0.06 GEN paid) |
| bronze | 5.0000 GEN | — | — |
| silver | 3.0000 GEN | — | — |
| gold | 2.0000 GEN | — | — |
| penalty | 0 | — | — |

Live agent profile on-chain: `jobs_insured=1`, `distinct_buyers=1`, tier `unrated`,
owner `0xdab51271357fC198f2507F4e1D639a9d2CEabeDb`. Key seed txs:
register `0x1debfb0f80bc9b8f3ddfbf302a5057aa2912a8816fd1f245e6b20807e298d488`,
issue `0x39801272aa8992238765b522fd5ec011a84f7b4b98aa63e8a62c4621f75d183c`,
accept `0x5abcdf3d97f185ec8db3d779863c8a35f3cd883ab55e24f8fb7b05dbd74dc647`,
deposits `0x658b5bd6…` / `0x8b05c162…` / `0x763ea176…` / `0x80b21fb8…`.

## Bradbury status: deploy-only (blocked)

Scope for Bradbury was deploy-only (no e2e — StudioNet carries the full scenario). A fresh
Proofmark address on Bradbury **could not be produced**: the rebranded source
(`intelligent-contracts/proofmark.py`, 62,351 bytes) is rejected by the Bradbury RPC with
`invalid transaction: BlockPubdataLimitReached`. Details recorded honestly:

- Largest source ever deployed to Bradbury from this repo: the **Shape A** artifact
  (~39,869 B → canonical `0x79C1…`, 2026-09-03). The Shape B + rebrand contract is ~62 KB —
  it exceeds Bradbury's per-transaction pubdata cap. (StudioNet, gasless, accepts it; the
  Shape B pre-rename 37/37 and the Proofmark 37/37 both ran there.)
- The single blocked deploy attempt included + reverted, spending ~0.0014 GEN
  (30.495286 → 30.493878). No further attempts were made per the account-funds constraint.
- Byte-exact provenance is a hard constraint (`deployed source == audited repo file`), so a
  comment/whitespace-trimmed variant was **not** used to force the deploy.

**Canonical Bradbury address therefore remains `0x79C15889D5070321176994373C440778a9eC47c1`**
— the pre-rename Shape A artifact (2026-09-03, read-verified, `eth_getCode` returns a live
proxy). It is *not* the rebranded Proofmark bytecode. A Proofmark Bradbury deploy is a
known residual pending either a smaller artifact or a raised network limit.

## Historical runs (pre-rename, kept for context)

| Network | Address | Artifact | When | Proof |
|---------|---------|----------|------|-------|
| StudioNet | `0x605e5BE4a8013B2B6c70c4BECa3CEbB7BD7918e4` | Shape A hardened | 2026-09-03 | **28/28** e2e (`studionet-e2e.log`) |
| StudioNet | `0x589472da571Db60151100b153D65a7170367E17D` | **Shape B (pre-rename source)** | 2026-09-06 | **37/37** e2e (`studionet-shapeb-e2e.log`) — the pre-rebrand validation the Proofmark run supersedes |
| Bradbury | `0x79C15889D5070321176994373C440778a9eC47c1` | Shape A hardened | 2026-09-03 | deploy-only reads + earlier-generation roundtrip (`bradbury-roundtrip.log`: deposit 1 GEN → pool → withdraw → 0) |

Do **not** use the 2026-09-02 generation (`0xED90…` StudioNet, `0xcBF4…` Bradbury) — it runs
the unpatched source.

## Residuals

1. **Bradbury Proofmark fresh deploy** — blocked by `BlockPubdataLimitReached` on the
   62,351-byte source; canonical Bradbury is the pre-rename Shape A artifact. See above.
2. **Live judged (V3) claim** — skipped: the evidence gateway `https://w3s.link/ipfs/`
   does not resolve the pinned CIDs from this network (gateway migration: 403/429/504;
   alternate gateways unreachable). The judged bond path is proven in direct-mode tests
   (47/47 in `tests/direct/test_proofmark.py`) and the live auto-breach payout (V2).

## Re-verify in one command

```bash
# Full lifecycle against the canonical Proofmark contract (StudioNet, gasless):
cd e2e && node run.js e2e --network studionet --address 0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3
```
