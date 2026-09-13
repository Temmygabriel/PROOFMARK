# Proofmark — Deployment Guide

Where the contract is deployed, how to deploy it again, and how to verify a
deployment actually succeeded.

## Live deployments

| Network | Chain ID | Contract address | Deployed | E2E verified |
|---------|----------|------------------|----------|--------------|
| **StudioNet** | 61999 | **`0x849b576f64ecA308300D278223951E4A88e1B5D4`** | 2026-09-12 | ✅ **FIX-22** — deploy tx `0x1ea533ada62af64d5e85a4a06033bf481fa9a0b25ef25e9a04ac4529f37e6c69`, validators AGREE; CLI 0.37.1; **74/74** direct tests + `genvm-lint` clean. Live e2e + demo logs in `e2e/results/` — see [PROOFMARK_LIVE_EVIDENCE.md](PROOFMARK_LIVE_EVIDENCE.md) |
| Testnet Bradbury | 4221 | **`0xE76AF22aea26A84dB11e87FB946060B02F490217`** | 2026-09-08 | **superseded for the FIX-22 model** — still the PAYOUT-FIX-20 minified build; a FIX-22 minified redeploy is outstanding |

> The **canonical** StudioNet address above is **FIX-22**: GitHub URL+sha256
> evidence (no IPFS), a paywalled `accept_job` that requires an agent bond of at
> least the coverage, per-buyer/per-agent open-policy caps, a 90-day deadline
> ceiling, and a penalty tier that sticks when no LP funds the penalty pool.
> Deployed 2026-09-12 from `intelligent-contracts/proofmark.py` (`class Proofmark`)
> with **CLI 0.37.1** — StudioNet requires that version; the global RC CLI
> (0.40.0-rc.3) can neither deploy nor read there.
>
> **Superseded canonical (2026-09-08):** `0x65319a2787BE8a57ee570fD0eB61A69887D91099`
> (PAYOUT-FIX-20 rail, CID evidence, unbonded `accept_job`). Its pool could be
> drained by a two-wallet buyer/agent pair, and its evidence model required an IPFS
> pin — both fixed in FIX-22.
>
> **Superseded canonical (2026-09-08, earlier):** `0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6`
> ran the **pre-fix** code — its "settled payout" moved the pool ledger but never
> EOA-credited the buyer. Replaced by `0x65319a27…`.
>
> **Bradbury note (resolved 2026-09-08, needs refresh):** the canonical `proofmark.py`
> exceeds Bradbury's per-transaction pubdata cap (`BlockPubdataLimitReached`; largest
> known-good ~39,869 B), which long blocked a fresh deploy. The live Bradbury
> deployment is a **minified build** — `intelligent-contracts/proofmark-bradbury.py`
> (strips only full-line comments / trailing comments / blank lines / docstrings,
> never any code or string-literal byte). Equivalence is machine-checked by
> `e2e/minify_contract.py` (code-token identity + ast.parse + fixed-point gates).
> The address above still carries the **PAYOUT-FIX-20** build; regenerating and
> deploying the FIX-22 minified build is outstanding.
>
> **Rebrand outcome (2026-09-06, historical):** the rename to `proofmark.py` /
> `class Proofmark` was a new deploy artifact. The pre-rename Shape B deploy
> (`0x589472da571Db60151100b153D65a7170367E17D`, StudioNet e2e **37/37** PASS on
> 2026-09-06) is kept as the historical pre-rename validation.

- Deploy account (`deployer`): `0xa881365a99d77be904e414ae610e22938bb0466d`
- The FIX-22 run exercises register, LP deposit, quoting, payable issuance,
  **agent accept + coverage bond**, deliverable submit (commit-pinned GitHub
  URL+sha256 only), foreign-host and tampered-evidence refusals, all negative/gate
  reverts (past **and** sub-60 s deadlines), expire, auto-breach claim + payout
  **drawn from the agent bond with the pool unchanged**, counters, and LP withdraw.
- Historical runs (not canonical, kept for provenance): PAYOUT-FIX-20 56/56 on
  `0x65319a27…` (2026-09-08); pre-hardening rebranded `0x1c91f37F…` 37/37 + 10/10
  (2026-09-06); Shape A 28/28 on `0x605e5BE4…` (2026-09-03); pre-rename Shape B
  37/37 on `0x589472da…` (2026-09-06). Do **not** use the 2026-09-02 generation
  (`0xED90…` StudioNet, `0xcBF4…` Bradbury) — it runs the unpatched source.

### Explorer links

- StudioNet: `https://explorer-studio.genlayer.com/address/0x849b576f64ecA308300D278223951E4A88e1B5D4`
- Bradbury:
  `https://explorer-bradbury.genlayer.com/address/0xE76AF22aea26A84dB11e87FB946060B02F490217`

## Frontend environment variables

The Next.js frontend reads these at build time (set them in Vercel). The live
Vercel deployment points at **StudioNet** (gasless) — set the **FIX-22** canonical
address:

```env
NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS=0x849b576f64ecA308300D278223951E4A88e1B5D4
NEXT_PUBLIC_PROOFMARK_NETWORK=studionet
```

If you'd rather run the frontend against **Bradbury** (no rate limits), you can swap in its
deployment — it now runs the **fixed Proofmark** (minified build, see the note above):

```env
NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS=0xE76AF22aea26A84dB11e87FB946060B02F490217
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
#    StudioNet: the canonical source
genlayer deploy --contract intelligent-contracts/proofmark.py
#    Bradbury:  the minified build (canonical source exceeds the pubdata cap)
genlayer deploy --contract intelligent-contracts/proofmark-bradbury.py

# 3. Record the returned Contract Address + Transaction Hash
```

StudioNet is gasless (0 GEN balance is fine). Bradbury needs GEN — claim from
the faucet if the account is empty: https://testnet-faucet.genlayer.foundation/

To rebuild the minified Bradbury artifact from the canonical source:
`python e2e/minify_contract.py intelligent-contracts/proofmark.py intelligent-contracts/proofmark-bradbury.py`
(the script enforces code-token equivalence; re-run `genvm-lint check` + the
direct suite against the build before any re-deploy).

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
