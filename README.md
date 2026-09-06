# Proofmark — Trust Infrastructure for AI Agent Transactions

Every AI agent job, verified on-chain. A buyer backs a job commitment from a
registered AI agent; if the agent fails to deliver to spec, GenLayer validator
consensus confirms the breach and the buyer is covered from the underwriting
pool. LPs fund tier pools and earn deterministic premiums; the one thing
GenLayer genuinely judges is whether a delivered job matches its agreed spec.

This repo holds the single-file intelligent contract plus the Next.js
frontend that talks to it.

```
.
├── intelligent-contracts/
│   └── proofmark.py      — the one contract; deploy to studio.genlayer.com
├── frontend/              — Next.js dashboard (deploy to Vercel)
├── tests/direct/          — fast in-memory direct-mode tests (no server)
├── e2e/                   — real-network end-to-end harness (genlayer-js)
└── docs/
    ├── PROOFMARK_CONTRACT.md      — contract overview, interface, security hardening
    ├── PROOFMARK_DEPLOYMENT.md    — per-network addresses + redeploy/verify steps
    └── PROOFMARK_UX_FLOW.md       — the three user flows (agent / buyer / LP)
```

## Order of operations

1. Deploy `intelligent-contracts/proofmark.py` to StudioNet (gasless) or
   Bradbury Testnet — see `docs/PROOFMARK_DEPLOYMENT.md` and the contract's
   own README.
2. Put the deployed address + network into the frontend's environment as
   `NEXT_PUBLIC_PROOFMARK_CONTRACT_ADDRESS` / `NEXT_PUBLIC_PROOFMARK_NETWORK` —
   see `frontend/README.md` for local-dev and Vercel steps.
3. Run the frontend, act as your browser identity, use it.

## What this is, briefly

Premium pricing and pool accounting are deterministic — no AI call, no
judgment involved. The one thing GenLayer actually judges is whether a
delivered job matches its agreed spec when a buyer requests a verdict;
validators independently re-fetch the evidence (content-addressed CIDs, so
every validator judges identical bytes) and re-derive a conformance score
rather than trusting a single leader's answer. An upheld claim stamps the job
**NOT DELIVERED** and the buyer is covered from the pool; a rejected claim
stamps it **DELIVERED** and the claim bond is forfeited to the pool. See the
contract's own docstring and inline comments for the full reasoning behind
each design choice (single-use claim gates, content-hashed evidence, exact
premiums, why forfeited bonds return to the pool).

## Validation

- Direct-mode suite (fast, in-memory): `python -m pytest tests/direct/ -v`
  → 47 passing on `class Proofmark`.
- Real-network e2e harness in `e2e/` (Node + genlayer-js, because the CLI
  cannot attach `value` to payable writes): full scenario + verify-payments.
  Live results and addresses are recorded in `docs/PROOFMARK_DEPLOYMENT.md`
  and `docs/dev/PROOFMARK_E2E_REPORT.md`.
- `genvm-lint check intelligent-contracts/proofmark.py` is clean.
