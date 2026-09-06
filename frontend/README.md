# Proofmark Frontend

Next.js dashboard for the single-file `intelligent-contracts/proofmark.py`
intelligent contract: register agents, back jobs with coverage, underwrite
tier pools as an LP, submit deliverables, request verdicts, and watch
conformance verdicts resolve as ink stamps — all read/write calls go straight
from the browser to the configured GenLayer network via `genlayer-js`
(StudioNet by default, Testnet Bradbury with
`NEXT_PUBLIC_PROOFMARK_NETWORK=testnet-bradbury`).

Transactions are signed by a **browser identity** — a genlayer-js keypair
stored in this browser's localStorage (key `proofmark.identity.pk.v1`), not by
MetaMask (which cannot sign GenLayer transactions). The identity menu
(`IdentityBadge`) shows/copies the private key, recovers a wallet from a key,
and can generate a fresh identity.

## Local development

```bash
npm install
cp .env.example .env.local
# edit .env.local -> paste your deployed contract address
npm run dev
```

Open `http://localhost:3000`. There's no local `next build`/`tsc` on this
machine (8 GB RAM, no node_modules) — the parse gate is `esbuild` over the
`app/` + `components/` + `lib/` sources into the gitignored `.esbuild-check/`
directory before pushes.

## Deploying: GitHub → Vercel

1. **Push this repo** (the whole `aegis-repo`, not just this folder) to GitHub.

2. **Import it in Vercel:**
   - vercel.com → *Add New* → *Project* → import the GitHub repo.
   - Framework preset: Vercel auto-detects Next.js, no changes needed.

3. **Add the contract address + network as environment variables:**
   - Vercel project → *Settings* → *Environment Variables*:
     - `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS` — the address from
       `genlayer deploy --contract intelligent-contracts/proofmark.py`.
     - `NEXT_PUBLIC_PROOFMARK_NETWORK` — `studionet` or `testnet-bradbury`
       (live addresses are recorded in `docs/PROOFMARK_DEPLOYMENT.md`).
   - Apply to Production (and Preview if you want preview deploys against the
     same contract).
   - **Redeploy** after adding them — Next.js inlines `NEXT_PUBLIC_*` vars at
     build time, so a running deployment won't pick up a newly-added one until
     it rebuilds.

4. Every subsequent `git push` to `main` triggers a new Vercel deployment
   automatically.

## If you redeploy the contract later

Contract addresses are per-deployment and per-network. If you redeploy
`proofmark.py` (fresh state, new address), update the Vercel env vars and
redeploy the frontend — nothing else in this app needs to change, since the
address and network are the only environment-specific things.

## Honesty notes in the UI

- **Conformance is not fabricated.** The contract stores no 0–100 score, so the
  job-record card shows an honest breach/conforming track (40-threshold tick,
  no fill) and explains the scoring rule in words. The verdict stamp only
  renders for a **real resolved** claim read from `get_claim_status`.
- **"X GEN backing active jobs"** is the contract's locked-exposure figure —
  the contract exposes no live policy count, so the hero states what the chain
  can actually prove.
- **Recent activity** is a local log of this browser's confirmed writes (plus a
  one-time replay of the genuine seed transactions on the canonical StudioNet
  deploy, so a first-time reviewer sees a funded board). It is not a chain-wide
  event feed.
- Empty-pool quoting surfaces the "fund the pool" gate; a live quote re-quotes
  at payment time so a stale tier rate can never fire a wrong-amount revert.
