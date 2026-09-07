# Proofmark — Deployment Guide

Where the contract is deployed, how to deploy it again, and how to verify a
deployment actually succeeded.

## Live deployments

| Network | Chain ID | Contract address | Deployed | E2E verified |
|---------|----------|------------------|----------|--------------|
| **StudioNet** | 61999 | **`0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3`** | 2026-09-06 | ✅ **37/37 steps** + **10/10 verify-payments** + seeded live board (`e2e/results/studionet-proofmark-e2e.log`) — see [PROOFMARK_LIVE_EVIDENCE.md](PROOFMARK_LIVE_EVIDENCE.md) |
| Testnet Bradbury | 4221 | `0x79C15889D5070321176994373C440778a9eC47c1` | 2026-09-03 | deploy-only read-verified — **pre-rename Shape A artifact** (see note) |

> The **canonical** StudioNet address above is the rebranded **Proofmark** contract —
> deployed 2026-09-06 from `intelligent-contracts/proofmark.py` (`class Proofmark`,
> Shape B + rebrand), re-proven live at 37/37 + 10/10 + seeded board. Full evidence in
> [PROOFMARK_LIVE_EVIDENCE.md](PROOFMARK_LIVE_EVIDENCE.md).
>
> **Bradbury note:** a fresh Proofmark deploy to Bradbury is **blocked** — the 62,351-byte
> source exceeds Bradbury's per-transaction pubdata cap (`BlockPubdataLimitReached`; largest
> known-good deploy was the ~39,869-byte Shape A artifact). The address above therefore still
> runs the pre-rename Shape A bytecode from 2026-09-03 and is kept as the canonical Bradbury
> address only for that reason. See the evidence doc for the full honest residual.

- Deploy account (`default`): `0xa881365a99d77be904e414ae610e22938bb0466d`
- StudioNet deploy tx (Proofmark, canonical):
  `0x42d1f3c5149c202e89e612ac1678b6115e3745bec82c87df1ae878aa6a621279`.
- The full 37-step run exercised register, LP deposit, quoting, 3× payable policy
  issuance, deliverable submit (canonical CID only), all negative/gate reverts
  (past **and** sub-60 s deadlines), expire, auto-breach claim + payout, counters,
  and LP withdraw to pool 0.
- verify-payments proved value movement: LP deposit/withdraw round-trip (pool
  0→5→0) and an upheld auto-breach claim that debited the pool exactly 1.000000 GEN.
- Historical runs (not canonical, kept for provenance): Shape A 28/28 on
  `0x605e5BE4…` (2026-09-03); pre-rename Shape B 37/37 on `0x589472da…` (2026-09-06).
  Do **not** use the 2026-09-02 generation (`0xED90…` StudioNet, `0xcBF4…`
  Bradbury) — it runs the unpatched source.

### Explorer links

- StudioNet: `https://explorer-studio.genlayer.com/address/0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3`
- Bradbury:
  `https://explorer-bradbury.genlayer.com/address/0x79C15889D5070321176994373C440778a9eC47c1`

## Frontend environment variables

The Next.js frontend reads these at build time (set them in Vercel). The live
Vercel deployment points at **StudioNet** (gasless):

```env
NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS=0x1c91f37F3ec428EcBf4B0A5698bFFf0c9D85f0c3
NEXT_PUBLIC_PROOFMARK_NETWORK=studionet
```

If you'd rather run the frontend against **Bradbury** (no rate limits), you can swap in its
deployment — but note the Bradbury address currently runs the pre-rename Shape A artifact,
not the rebranded Proofmark bytecode (see the note above):

```env
NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS=0x79C15889D5070321176994373C440778a9eC47c1
NEXT_PUBLIC_PROOFMARK_NETWORK=testnet-bradbury
```

Network values follow the `genlayer-js/chains` names: `studionet`,
`testnetBradbury`, `testnetAsimov`. Note StudioNet is rate-limited (60 req/min
per IP) — fine for a demo dashboard, but batch scripts should use Bradbury.

## How to deploy again

Prerequisite: `genlayer` CLI installed and `genlayer account unlock` run for the
deploying account.

```bash
# 1. Pick the network
genlayer network set studionet            # gasless, but rate-limited
genlayer network set testnet-bradbury     # needs GEN in the account

# 2. Deploy from the repo root
genlayer deploy --contract intelligent-contracts/proofmark.py

# 3. Record the returned Contract Address + Transaction Hash
```

StudioNet is gasless (0 GEN balance is fine). Bradbury needs GEN — claim from
the faucet if the account is empty: https://testnet-faucet.genlayer.foundation/

## How to verify a deployment (do not skip)

`ACCEPTED` / `FINALIZED` transaction status does **not** mean the contract code
executed. A failed execution still finalizes, but no contract is created. Verify
with reads and a write, not just the deploy banner:

```bash
# Read: should return a fresh pool
genlayer call <ADDRESS> get_pool_info --args "unrated"

# Write: should be accepted by consensus
genlayer write <ADDRESS> register --args "agent-smoke"

# Read back: profile should exist with your account as owner
genlayer call <ADDRESS> get_profile --args "agent-smoke"
```

On StudioNet, `genlayer schema` and `genlayer code` are **not supported** — the
network rejects those RPCs. The receipt plus working view/write calls are the
proof. The receipt can be checked with:

```bash
genlayer receipt <TX_HASH> --stdout --stderr
```

## Network quirks learned on this machine

- **StudioNet RPC is flaky.** Reads/writes sometimes fail with `ECONNRESET` or
  an SSL `invalid session id` error. Retry — they succeed on the next attempt.
- **StudioNet rate limits:** 60 req/min, 1000 req/hr per IP. Throttle batch
  scripts and wait for receipts between writes.
- **Bradbury receipt polling** can take a while to reach `FINALIZED`; reads and
  writes work immediately after deployment anyway.
