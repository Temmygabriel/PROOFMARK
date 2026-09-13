// Independent receipt audit: for each tx hash, print the committed status AND
// the per-validator execution results, so "ACCEPTED" is never confused with
// "executed successfully". A reverted call ALSO finalizes as ACCEPTED on
// GenLayer -- only the agreeing validators' execution_result tells the truth.
import { createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const client = createClient({ chain: studionet });

const HASHES = process.argv.slice(2);

for (const h of HASHES) {
  let tx;
  for (let i = 0; i < 6; i++) {
    try {
      tx = await client.getTransaction({ hash: h });
      if (tx) break;
    } catch (e) {
      if (i === 5) throw e;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  if (!tx) {
    console.log(`${h.slice(0, 18)}… NO RECEIPT`);
    continue;
  }
  let cd = tx.consensus_data;
  if (typeof cd === "string") {
    try { cd = JSON.parse(cd); } catch { cd = null; }
  }
  const raw = Array.isArray(cd?.validators)
    ? cd.validators
    : Array.isArray(cd?.leader_receipt) ? cd.leader_receipt : [];
  const vals = raw.map((e) => ({
    mode: e?.mode ?? "?",
    result: e?.execution_result ?? e?.genvm_result?.execution_result ?? null,
    vote: e?.vote ?? null,
  }));
  const agreeing = vals.filter((v) => v.vote === "agree");
  const agreeResults = agreeing.map((v) => v.result);
  const anyAgreeErr = agreeResults.includes("ERROR");
  const anyAgreeOk = agreeResults.includes("SUCCESS") || agreeResults.includes("RETURN");
  const verdict = agreeing.length === 0
    ? "NO AGREEING VALIDATOR READ"
    : anyAgreeErr
      ? "**EXECUTION ERROR**"
      : anyAgreeOk
        ? "SUCCESS"
        : `other (${agreeResults.join(",")})`;
  console.log(`\n${h}`);
  console.log(`  statusName=${tx.statusName}  resultName=${tx.resultName}  txExecutionResult=${tx.txExecutionResult} (${tx.txExecutionResultName})`);
  console.log(`  validators seen: ${vals.length}  agreeing: ${agreeing.length}  -> ${verdict}`);
  for (const v of vals) console.log(`    [${v.mode}/${v.vote}] ${v.result}`);
}
