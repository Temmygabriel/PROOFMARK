# intelligent-contracts / `proofmark.py`

**`proofmark.py` is the one and only contract source.** GenLayer intelligent-contract
code is **network-agnostic** — the same file is deployed to each network; there is
no separate "StudioNet contract" vs "Bradbury contract" to maintain. Keeping one
source (instead of two byte-identical copies) is what prevents the two from ever
drifting apart.

## Canonical live deployments

| Network | Address | Verified |
|---|---|---|
| **StudioNet** (61999) | `0x850F773BF5Bb2bddB788896152C0a3C7C1C212B6` | ✅ **37/37** e2e (on `0x1FcE88…`, same hardened artifact) + **seeded live board** (2026-09-08) |
| **Testnet Bradbury** (4221) | `0x79C15889D5070321176994373C440778a9eC47c1` | deploy-only reads — **pre-rename Shape A artifact** (Proofmark redeploy blocked; see below) |

> **Current artifact (2026-09-08):** the contract source is `proofmark.py` (`class
> Proofmark`) with the **Phase-7b hardening** — the GPT-audit H-02 two-phase-claim fix
> plus the 2026-09-07 adversarial pass (evidence custody split, FIX-16 impossible
> acceptance, FIX-18 forever-pending release). Two fresh StudioNet deploys of the same
> working-tree source carry the live proof: a **37/37 full e2e** on
> `0x1FcE880D9fabDEc1Fa883FA3d2CD0685607379f7` and the **seeded live board** on
> `0x850F773B…` (agent `agent-live-1788864539810` / job `job-live-1788864539810`).
>
> **Rebrand outcome (2026-09-06, superseded):** the rename to `proofmark.py` /
> `class Proofmark` was a new deploy artifact; the pre-hardening rebranded contract
> (`0x1c91…`, 37/37 + 10/10 + seeded board) stood as canonical until the hardened
> re-proof above. The prior Shape B deploy (`0x589472da571Db60151100b153D65a7170367E17D`,
> StudioNet e2e **37/37** PASS on 2026-09-06) is the **historical pre-rename validation**.
>
> **Bradbury:** a fresh Proofmark deploy is **blocked** — the 62,351-byte source exceeds
> Bradbury's per-transaction pubdata cap (`BlockPubdataLimitReached`; largest known-good
> deploy was the ~39,869-byte Shape A artifact). The Bradbury address above therefore still
> runs the pre-rename Shape A bytecode (2026-09-03) and is kept as canonical for Bradbury
> only for that reason.

Full evidence, prior deployments, and re-deploy steps live in
[`docs/PROOFMARK_LIVE_EVIDENCE.md`](../docs/PROOFMARK_LIVE_EVIDENCE.md),
[`docs/PROOFMARK_DEPLOYMENT.md`](../docs/PROOFMARK_DEPLOYMENT.md) and
[`docs/dev/PROOFMARK_E2E_REPORT.md`](../docs/dev/PROOFMARK_E2E_REPORT.md).

## If you deploy a new version

1. Edit `proofmark.py`.
2. Re-run the direct test suite: `pytest tests/direct/test_proofmark.py` and
   `genvm-lint check intelligent-contracts/proofmark.py`.
3. Deploy + value-test on StudioNet, then on Bradbury (see
   `e2e/run.js` / `e2e/verify-payments.js`).
4. Record the new addresses in `docs/PROOFMARK_DEPLOYMENT.md` and point the frontend
   `.env` at them.
