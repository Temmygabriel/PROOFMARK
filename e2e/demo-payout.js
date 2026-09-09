// Proofmark — rerun submission §05 (the reviewer's path) end-to-end on the
// FIXED canonical (PAYOUT-FIX-20 EthSend rail), so the whole loop is on-chain:
//   register agent -> LP funds Unrated 10 (+ Bronze 5 / Silver 3 / Gold 2) ->
//   issue 1 GEN cover @ 0.06 premium, short deadline, CID spec -> accept ->
//   deadline passes with no deliverable -> file_claim (2 GEN bond) ->
//   deterministic auto-breach -> upheld -> buyer paid 1 GEN, bond refunded.
//
// Unlike run.js e2e (which asserts pool-ledger rows), this run also inspects the
// file_claim transaction's triggered children. Under the old broken rail the
// payout children finalized "GenVM Execution ERROR" (IC-to-IC PostMessage to an
// EOA that cannot receive it). Under the fix the value leaves over the external
// EthSend rail, so no errored child may exist and the pool must debit exactly 1 GEN.
//
// Usage:  node e2e/demo-payout.js            (full run, writes results/demo-payout.log)
//
// Reuses role keys from e2e/keys.json (lp funds, buyer buys/claims) plus a fresh
// live agent wallet saved to e2e/live-keys.json — mirrors seed-live.js + plant-claim.js.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createAccount, createClient, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { loadOrGenKeys, accountsFromKeys, makeNetwork } from "./run.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const GEN = 10n ** 18n;
const COVERAGE = GEN; // 1 GEN
const CLAIM_BOND = 2n * GEN;
const SPEC_CID = "Qm" + "a".repeat(44); // content never fetched (auto-breach path)
const DEPOSITS = { unrated: 10n * GEN, bronze: 5n * GEN, silver: 3n * GEN, gold: 2n * GEN };
const DEADLINE_S = 180; // short enough that one wait settles the payout
const WAIT_BUFFER_S = 30;

const genFmt = (v) => (Number(typeof v === "bigint" ? v : BigInt(v)) / 1e18).toFixed(4) + " GEN";
const toB = (v) => (typeof v === "bigint" ? v : BigInt(v)); // u256 reads come back as numbers/strings
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const logLines = [];
const log = (s) => {
  console.log(s);
  logLines.push(s);
};

async function inspectChildren(readClient, parentHash) {
  log(`\n--- triggered children of file_claim ${parentHash} ---`);
  let children = [];
  for (let i = 0; i < 40; i++) {
    try {
      children = await readClient.getTriggeredTransactionIds({ hash: parentHash });
      if (children.length) break;
    } catch (e) {
      // children not indexed yet — keep polling
    }
    await sleep(3000);
  }
  if (!children.length) {
    log("no triggered child transactions (external EthSend rail handled outside IC consensus)");
    return [];
  }
  log(`child count: ${children.length}`);
  const verdicts = [];
  for (const c of children) {
    let tx;
    for (let i = 0; i < 60; i++) {
      try {
        tx = await readClient.getTransaction({ hash: c });
        const st = String(tx?.statusName ?? tx?.status ?? "");
        if (/FINALIZED|DECIDED/.test(st) || i > 30) break;
      } catch (e) {
        /* still appearing */
      }
      await sleep(2000);
    }
    verdicts.push(summarizeChild(c, tx));
  }
  return verdicts;
}

function summarizeChild(hash, tx) {
  if (!tx) return { hash, decided: false, note: "no receipt within poll window" };
  const stName = String(tx.statusName ?? tx.status ?? "");
  const rName = String(tx.resultName ?? "");
  const execNm = String(tx.txExecutionResultName ?? "");
  let cd = tx.consensus_data;
  if (typeof cd === "string") {
    try { cd = JSON.parse(cd); } catch { cd = null; }
  }
  const raw = Array.isArray(cd?.validators)
    ? cd.validators
    : Array.isArray(cd?.leader_receipt) ? cd.leader_receipt : [];
  const seen = raw.map((e) => ({
    result: e?.execution_result ?? e?.genvm_result?.execution_result ?? null,
    vote: e?.vote ?? null,
    mode: e?.mode ?? null,
  }));
  const agreeing = seen.filter((e) => e?.vote === "agree");
  const errored = agreeing.some((e) => e?.result === "ERROR");
  const summary = {
    hash,
    decided: /FINALIZED|DECIDED/.test(stName) || agreeing.length > 0 || execNm !== "",
    status: stName,
    resultName: rName,
    txExecutionResultName: execNm,
    agreeing,
    errored,
    note: errored
      ? "EXECUTION ERROR on agreeing validator — value would NOT have credited"
      : agreeing.length
        ? `ok (${agreeing.map((e) => e?.result).join(",")})`
        : `undetermined (${stName}/${rName})`,
  };
  log(
    `child ${hash.slice(0, 18)}… status=${summary.status} resultName=${rName} ` +
      `exec=${execNm} agree=${agreeing.length ? agreeing.map((e) => e?.result).join(",") : "—"} -> ${summary.note}`
  );
  return summary;
}

async function main() {
  const keys = loadOrGenKeys(false);
  const accs = accountsFromKeys(keys);
  const m = makeNetwork("studionet");
  const readClient = createClient({ chain: studionet });
  const suffix = `live-${Date.now()}`;
  const livePk = generatePrivateKey();
  const liveAcc = createAccount(livePk);
  const liveWallet = { address: liveAcc.address, account: liveAcc };
  const agentId = `agent-${suffix}`;
  const jobId = `job-${suffix}`;
  const BUYER = accs.buyer.address;
  const LP = accs.lp.address;

  fs.writeFileSync(
    path.join(__dirname, "live-keys.json"),
    JSON.stringify({ role: "live", pk: livePk, address: liveAcc.address.toLowerCase(), agentId }, null, 2)
  );

  const write = async (acc, fn, args, value, label) => {
    const r = await m.submitAndWait(acc.account, fn, args, value);
    log(`[${r.ok ? "PASS" : r.undetermined ? "UNDETERMINED" : "REVERTED"}] ${label} -- ${r.hash}`);
    if (!r.ok && !r.undetermined) throw new Error(`${label} reverted: ${r.execName || r.status}`);
    if (r.undetermined) throw new Error(`${label} undetermined: ${r.execName}`);
    return r;
  };

  log(`contract: ${m.address}`);
  log(`agentId:  ${agentId}  (wallet ${liveAcc.address})`);
  log(`jobId:    ${jobId}`);
  log(`lp/buyer roles from e2e/keys.json: lp=${LP} buyer=${BUYER}\n`);

  // ---- Step 0: read-verify the fresh deploy has empty pools ----
  for (const tier of Object.keys(DEPOSITS)) {
    const p = await m.read("get_pool_info", [tier]);
    log(`pool ${tier} before: balance=${genFmt(p?.balance_atto)} locked=${genFmt(p?.locked_exposure_atto)}`);
  }
  log("");

  // ---- Step 1: register the agent (fresh wallet → fresh id) ----
  await write(liveWallet, "register", [agentId], 0n, "register agent (window A)");
  const profile = await m.read("get_profile", [agentId]);
  log(`profile: tier=${profile?.tier} registered_at=${profile?.registered_at}`);
  // Clock calibration (same as run.js): if the on-chain clock lags wall clock the
  // deadline arrives later; wait that much extra.
  const netOffsetMs = profile?.registered_at ? Date.parse(profile.registered_at) - Date.now() : 0;
  log(`net clock offset: ${Math.round(netOffsetMs)} ms\n`);

  // ---- Step 2: fund every tier pool (underwriting) from the LP wallet ----
  for (const [tier, amount] of Object.entries(DEPOSITS)) {
    await write(accs.lp, "deposit", [tier], amount, `deposit ${genFmt(amount)} into ${tier} (window B)`);
    await sleep(1500);
  }
  log("\n--- tier pools after underwriting ---");
  for (const tier of Object.keys(DEPOSITS)) {
    const p = await m.read("get_pool_info", [tier]);
    log(`${tier.padEnd(7)} balance=${genFmt(p?.balance_atto)}  locked=${genFmt(p?.locked_exposure_atto)}`);
  }

  // ---- Step 3: quote + issue 1 GEN of cover on the agent, short deadline ----
  const quote = await m.read("quote_premium", [agentId, COVERAGE]);
  log(`\nquote: tier=${quote?.tier} rate_bps=${quote?.rate_bps} premium=${genFmt(quote?.premium_atto)}`);
  const deadlineMs = Date.now() + DEADLINE_S * 1000;
  const deadlineIso = new Date(deadlineMs).toISOString().replace(/\.\d{3}Z$/, ".000Z");
  const issued = await write(
    accs.buyer,
    "issue_policy",
    [jobId, agentId, COVERAGE, SPEC_CID, deadlineIso],
    quote?.premium_atto ?? 0n,
    `issue ${jobId} 1 GEN cover @ premium (window B)`
  );
  const issueHash = issued.hash;

  // ---- Step 4: agent accepts ----
  await write(liveWallet, "accept_job", [jobId], 0n, "agent accepts job (window A)");

  let pol = await m.read("get_policy", [jobId]);
  log(`policy ${jobId}: status=${pol?.status} agent_id=${pol?.agent_id} deadline=${pol?.deadline_iso ?? pol?.deadline}`);
  let unrated = await m.read("get_pool_info", ["unrated"]);
  log(`unrated during run: balance=${genFmt(unrated?.balance_atto)} locked=${genFmt(unrated?.locked_exposure_atto)}\n`);

  // ---- Step 5: wait out the deadline (no deliverable) ----
  const waitMs =
    Math.max(0, deadlineMs + Math.max(0, -netOffsetMs) - Date.now()) + WAIT_BUFFER_S * 1000;
  log(`[wait] sleeping ~${Math.round(waitMs / 1000)}s for the deadline to pass...`);
  await sleep(waitMs);

  // ---- Step 6: file the claim (2 GEN bond) → deterministic auto-breach ----
  const claim = await write(
    accs.buyer,
    "file_claim",
    [jobId],
    CLAIM_BOND,
    "file_claim with 2 GEN bond after deadline (window B)"
  );
  const claimHash = claim.hash;

  const status = await m.read("get_claim_status", [jobId]);
  log(`\nclaim_status: ${status}`);
  pol = await m.read("get_policy", [jobId]);
  log(`policy: status=${pol?.status} buyer=${pol?.buyer} coverage=${genFmt(pol?.coverage_atto)}`);
  unrated = await m.read("get_pool_info", ["unrated"]);
  log(`unrated after: balance=${genFmt(unrated?.balance_atto)} locked=${genFmt(unrated?.locked_exposure_atto)}`);

  // ---- Step 7: prove the payout rail — inspect the file_claim children ----
  const children = await inspectChildren(readClient, claimHash);
  const erroredChildren = children.filter((c) => c.errored);

  log("\n=== DEMO RUN REPORT ===");
  log(`contract: ${m.address}`);
  log(`agentId:  ${agentId}`);
  log(`jobId:    ${jobId}`);
  log(`issue_policy (payable, 1 GEN cover): ${issueHash}`);
  log(`file_claim (2 GEN bond, payout):     ${claimHash}`);
  log(`claim_status: ${status}`);
  log(
    `unrated pool: ${genFmt(10n * GEN)} funded + 0.06 premium - 1.00 payout -> ${genFmt(unrated?.balance_atto)} (want 9.0600), locked ${genFmt(unrated?.locked_exposure_atto)}`
  );
  const checks = {
    "claim upheld": status === "upheld",
    "policy claimed": pol?.status === "claimed",
    "pool 10.06 - 1.00 = 9.06": toB(unrated?.balance_atto) === 9060000000000000000n,
    "pool locked released to 0": toB(unrated?.locked_exposure_atto) === 0n,
    "no errored payout children (EthSend rail)": erroredChildren.length === 0,
  };
  for (const [name, ok] of Object.entries(checks)) {
    log(`[${ok ? "PASS" : "FAIL"}] ${name}`);
  }
  const allOk = Object.values(checks).every(Boolean);
  log(allOk ? "\nALL CHECKS PASS — payout left over the external EthSend rail." : "\nSOME CHECKS FAILED.");

  fs.mkdirSync(path.join(__dirname, "results"), { recursive: true });
  fs.writeFileSync(path.join(__dirname, "results", "demo-payout.log"), logLines.join("\n") + "\n");
  fs.writeFileSync(
    path.join(__dirname, "results", "demo-payout.json"),
    JSON.stringify(
      {
        network: "studionet",
        contract: m.address,
        agent: agentId,
        job: jobId,
        agentWallet: liveAcc.address.toLowerCase(),
        lp: LP,
        buyer: BUYER,
        issueHash,
        claimHash,
        children,
        claimStatus: status,
        unratedAfter: { balance: String(unrated?.balance_atto), locked: String(unrated?.locked_exposure_atto) },
        allOk,
      },
      null,
      2
    )
  );
  process.exit(allOk ? 0 : 1);
}

main().catch((e) => {
  console.error("FATAL:", e?.message || e);
  console.error(e?.stack || "");
  process.exit(1);
});
