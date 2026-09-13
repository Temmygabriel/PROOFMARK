// Verify the SUBMISSION NOTE's claims against the live canonical contract.
//
// The note tells a reviewer to paste exact URLs and digests, and quotes exact
// board numbers and outcomes. This script re-reads every one of those from the
// chain and prints PASS/FAIL, so a claim can never drift from the deploy.
//
//   node verify-note.mjs
//
// Reads only (view calls) -- spends nothing.
import { createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const ADDRESS = "0x849b576f64ecA308300D278223951E4A88e1B5D4"; // note: canonical FIX-22
const GEN = 10n ** 18n;
const COMMIT = "2208a0be4503ba6beeb41181876e848ca1a6782f";

// ---- exactly what the note tells a reviewer to paste ----------------------
const NOTE = {
  specUrl: `https://raw.githubusercontent.com/Temmygabriel/proofmark/${COMMIT}/e2e/evidence/spec.md`,
  specSha256: "1709a05147f2a78e7c8636be0fa6240c56605dd8361f017e0f509ad4726d9b2b",
  delivUrl: `https://raw.githubusercontent.com/Temmygabriel/proofmark/${COMMIT}/e2e/evidence/deliverable.md`,
  delivSha256: "f3ba9374450e7ba312525018febdc7f7dded8d353c1b7c36258f4344f6501860",
  judgedJob: "verify-job3-studionet-1789320793434", // Step 2, judged: rejected / DELIVERED
  breachJob: "verify-job-studionet-1789320575300", // Step 2, auto-breach: upheld
  board: { unrated: "36.24", bronze: "10", silver: "6", gold: "4" }, // Step 1 "≈"
  unratedLocked: "1", // Step 1 "≈1 GEN locked"
  premiumAtto: GEN * 6n / 100n, // Step 5 "Premium due 0.06 GEN"
};

const client = createClient({ chain: studionet });
const read = async (functionName, args) => {
  try {
    return { ok: true, v: await client.readContract({ address: ADDRESS, functionName, args }) };
  } catch (e) {
    return { ok: false, err: String(e?.message ?? e).slice(0, 160) };
  }
};

let pass = 0, fail = 0;
const check = (label, got, want) => {
  const ok = got === want;
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};
const gen = (atto) => (Number(BigInt(atto)) / 1e18).toFixed(4);
const near = (atto, wantStr) => Math.abs(Number(BigInt(atto)) / 1e18 - Number(wantStr)) < 0.01;

const main = async () => {
  console.log(`contract: ${ADDRESS}\n`);

  // ---- 1. the deploy really is the FIX-22 build ---------------------------
  const rej = await read("get_rejection", ["0x0000000000000000000000000000000000000000", "probe"]);
  check("FIX-21+ surface present (get_rejection answers)", rej.ok, true);
  const acct = await read("get_accounting", ["unrated"]);
  check(
    "FIX-21+ accounting view exposes pool + contract balance",
    acct.ok && "tier_balance_atto" in acct.v && "contract_balance_atto" in acct.v,
    true
  );
  if (acct.ok) {
    console.log(
      `        tier_balance=${gen(acct.v.tier_balance_atto)} GEN  locked=${gen(acct.v.locked_exposure_atto)}` +
        `  pending_claim_bonds=${gen(acct.v.pending_claim_bonds_atto)}  contract_balance=${gen(acct.v.contract_balance_atto)}`
    );
  }

  // ---- 2. Step 1 board numbers -------------------------------------------
  for (const [tier, want] of Object.entries(NOTE.board)) {
    const p = await read("get_pool_info", [tier]);
    check(`Step 1 board: ${tier} ≈ ${want} GEN`, p.ok && near(p.v.balance_atto, want), true);
    if (p.ok) console.log(`        ${tier} balance=${gen(p.v.balance_atto)} locked=${gen(p.v.locked_exposure_atto)}`);
    if (tier === "unrated" && p.ok) {
      check(`Step 1: Unrated locked ≈ ${NOTE.unratedLocked} GEN`, near(p.v.locked_exposure_atto, NOTE.unratedLocked), true);
    }
  }

  // ---- 3. Step 5 premium: unrated 6% of 1 GEN = 0.06 GEN ------------------
  const q = await read("quote_premium", ["agent-that-does-not-exist-yet", GEN]);
  check("Step 5 quote: tier unrated", q.ok && q.v.tier, "unrated");
  check("Step 5 quote: rate 600 bps (6%)", q.ok && String(q.v.rate_bps), "600");
  check("Step 5 quote: premium 0.06 GEN", q.ok && BigInt(q.v.premium_atto) === NOTE.premiumAtto, true);

  // ---- 4. Step 2a: the judged job's pasted values -------------------------
  const j = await read("get_policy", [NOTE.judgedJob]);
  check(`Step 2 job exists (${NOTE.judgedJob})`, j.ok, true);
  if (j.ok) {
    check("  status = claimed", j.v.status, "claimed");
    check("  spec_url matches the note verbatim", j.v.spec_url, NOTE.specUrl);
    check("  spec_sha256 matches the note verbatim", j.v.spec_sha256, NOTE.specSha256);
    check("  deliverable_url matches the note verbatim", j.v.deliverable_url, NOTE.delivUrl);
    check("  deliverable_sha256 matches the note verbatim", j.v.deliverable_sha256, NOTE.delivSha256);
    check("  agent bond was posted (≥ cover)", BigInt(j.v.agent_bond_atto) >= BigInt(j.v.coverage_atto), true);
    console.log(`        coverage=${gen(j.v.coverage_atto)} bond=${gen(j.v.agent_bond_atto)} tier=${j.v.pool_tier}`);
  }
  const jc = await read("get_claim_status", [NOTE.judgedJob]);
  check("  Step 2 claim_status = rejected (deliverable conformed)", jc.ok && jc.v, "rejected");

  // ---- 5. Step 2b: the deterministic auto-breach job ----------------------
  const b = await read("get_policy", [NOTE.breachJob]);
  check(`Step 2 job exists (${NOTE.breachJob})`, b.ok, true);
  if (b.ok) {
    check("  status = claimed", b.v.status, "claimed");
    check("  no deliverable was submitted (breach is deterministic)", b.v.deliverable_url, "");
  }
  const bc = await read("get_claim_status", [NOTE.breachJob]);
  check("  Step 2 claim_status = upheld (buyer paid from the bond)", bc.ok && bc.v, "upheld");

  console.log(`\n${pass} passed, ${fail} failed`);
  if (fail) process.exit(1);
};

main().catch((e) => { console.error("FATAL:", e?.message || e); process.exit(1); });
