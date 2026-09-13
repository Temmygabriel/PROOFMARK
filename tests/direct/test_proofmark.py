"""Direct-mode (in-memory, leader-only) tests for intelligent-contracts/proofmark.py.

Covers every public method plus the gaming/security vectors the contract
documents it defends against. Claim judgement is mocked: web fetches (spec /
deliverable from the IPFS gateway) and the LLM score are stubbed, so the
deterministic gate + payout logic are exercised without real consensus.

Fixture roles used throughout:
  direct_alice  -- LP (underwrites a tier)
  direct_bob    -- the insured agent
  direct_charlie-- the main buyer
  direct_owner  -- a second buyer / extra account

Run:  python -m pytest tests/direct/test_proofmark.py -v
"""

import hashlib
import json
import re

# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------

CLAIM_BOND = 2 * 10**18
MIN_COVERAGE = 10**16

# FIX-22: evidence is now a commit-pinned GitHub raw URL plus the sha256 of the
# exact bytes, both committed on-chain. Tests therefore build REAL (url, sha256)
# pairs from REAL bodies -- a mock that serves different bytes than the digest
# commits to is correctly refused rather than judged. evidence() registers the
# body it hashed so mock_evidence can serve exactly the committed bytes.
EVIDENCE_COMMIT = "a" * 40
EVIDENCE_BASE = (
    f"https://raw.githubusercontent.com/proofmark-test/evidence/{EVIDENCE_COMMIT}/"
)
EVIDENCE_BODIES = {}


def evidence(path: str, body: bytes):
    """A (url, sha256) evidence pair for `body`, pinned to a fake commit."""
    url = EVIDENCE_BASE + path
    EVIDENCE_BODIES[url] = body
    return (url, hashlib.sha256(body).hexdigest())


SPEC_BODY = b"Deliver a report of at least 500 words covering the three risks."
DELIV_OK_BODY = b"Report: risk one, risk two, and risk three, each covered in depth."
DELIV_BAD_BODY = b"TODO: nothing written yet."

SPEC = evidence("spec.txt", SPEC_BODY)
DELIV_OK = evidence("deliverable.txt", DELIV_OK_BODY)
DELIV_BAD = evidence("deliverable-bad.txt", DELIV_BAD_BODY)
# A URL on a host that is NOT the allowlisted evidence host -- must be refused
# by _canonical_evidence_url (FIX-22): the caller does not get to choose what
# every validator fetches (SSRF).
FOREIGN_URL = ("https://gist.github.com/someone/edit", "0" * 64)
# A commit-pinned URL whose commit segment is a BRANCH name: the bytes could be
# moved after the fact, so it must be refused.
BRANCH_URL = (EVIDENCE_BASE.replace(EVIDENCE_COMMIT, "main"), "0" * 64)
# An evidence URL wrapped in whitespace/newlines -- canonicalization must strip.
WHITESPACE_URL = ("   " + DELIV_OK[0] + "\n", DELIV_OK[1])
# An evidence URL past MAX_EVIDENCE_URL_LEN (FIX-22).
LONG_URL = (EVIDENCE_BASE + "x" * 400, "0" * 64)

T0 = "2026-01-01T00:00:00Z"
T_PLUS_4 = "2026-01-05T00:00:00Z"
DEADLINE = "2026-03-01T00:00:00Z"
PAST_DEADLINE = "2025-12-01T00:00:00Z"

# 2026-03-02 = 1 day after DEADLINE (within the 7-day claim window).
AFTER_DEADLINE = "2026-03-02T00:00:00Z"
# 2026-03-10 = 9 days after DEADLINE (past the 7-day claim window, FIX-09).
PAST_WINDOW = "2026-03-10T00:00:00Z"

RATE_BPS = {"unrated": 600, "bronze": 400, "silver": 250, "gold": 150, "penalty": 1200}


def premium_for(coverage_atto: int, tier: str) -> int:
    return (coverage_atto * RATE_BPS[tier]) // 10000


def addr_str(b: bytes) -> str:
    """Canonical lowercase address string (the contract lowercases it anyway
    via _normalize_key before using it as a storage key)."""
    return "0x" + b.hex()


def register(direct_vm, contract, account, agent_id):
    direct_vm.sender = account
    contract.register(agent_id)


def deposit(direct_vm, contract, account, tier, amount_atto):
    direct_vm.sender = account
    direct_vm.value = amount_atto
    contract.deposit(tier)


def issue_policy(direct_vm, contract, buyer, job_id, agent_id, coverage_atto,
                 spec, deadline, premium_atto):
    """`spec` is an (url, sha256) evidence pair -- FIX-22 unpacked here so the
    ~40 call sites keep passing SPEC/DELIV_OK pairs unchanged."""
    spec_url, spec_sha256 = spec
    direct_vm.sender = buyer
    direct_vm.value = premium_atto
    contract.issue_policy(job_id, agent_id, coverage_atto, spec_url, spec_sha256,
                          deadline)


def issue_rejected(direct_vm, contract, buyer, job_id, agent_id, coverage_atto,
                   spec, deadline, premium_atto, fragment):
    """FIX-21: a rejected issue_policy does NOT revert -- it refunds in-call and
    records the precise reason. Assert both, and that no policy was created."""
    issue_policy(direct_vm, contract, buyer, job_id, agent_id, coverage_atto,
                 spec, deadline, premium_atto)
    reason = contract.get_rejection(addr_str(buyer), job_id)
    assert fragment in reason, f"expected {fragment!r} in {reason!r}"
    assert "retained nothing" in reason
    assert f"refunded {premium_atto} atto" in reason
    return reason


def accept(direct_vm, contract, agent_acct, job_id, bond_atto=None):
    """FIX-02: the insured agent must accept a pending policy before any
    submit / claim / expire can happen.

    FIX-22: acceptance is now payable -- the agent posts a bond equal to the
    policy coverage, so the ~50 call sites that just want an active policy get
    the exact required bond read off-chain unless a test overrides it."""
    coverage = int(contract.get_policy(job_id)["coverage_atto"])
    direct_vm.sender = agent_acct
    direct_vm.value = coverage if bond_atto is None else bond_atto
    contract.accept_job(job_id)


def issue_active(direct_vm, contract, buyer, agent_acct, job_id, agent_id,
                 coverage_atto, spec, deadline, premium_atto):
    """Issue a policy AND have the agent accept it, so the test can act on an
    active policy (submit / claim / expire) in one line."""
    issue_policy(direct_vm, contract, buyer, job_id, agent_id, coverage_atto,
                 spec, deadline, premium_atto)
    accept(direct_vm, contract, agent_acct, job_id)


def mock_evidence(direct_vm, evidence_pair, body=None):
    """Register a 200 mock for one evidence URL, serving exactly the bytes that
    the committed sha256 covers unless the caller deliberately overrides them
    (probe at submit + judge fetch at claim both hit the host)."""
    url = evidence_pair[0]
    if body is None:
        body = EVIDENCE_BODIES[url]
    direct_vm.mock_web(re.escape(url), {"status": 200, "body": body})


def mock_judgement(direct_vm, score, injection=False):
    """Mock the LLM conformance grader with the new Shape B output schema."""
    direct_vm.mock_llm(
        r".*material conformance.*",
        json.dumps({"score": score, "injection": injection, "reasoning": "mock"}),
    )


def fund_accounts(direct_vm, *accounts, amount=1000 * 10**18):
    for acc in accounts:
        direct_vm.deal(acc, amount)


def setUpPoolAndAgent(direct_vm, contract, lp, agent_acct, buyer_acct):
    """Common happy-path setup: LP funds 'unrated', agent registers."""
    fund_accounts(direct_vm, lp, agent_acct, buyer_acct)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, lp, "unrated", 20 * 10**18)
    register(direct_vm, contract, agent_acct, "agent-a")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_and_get_profile(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    direct_vm.warp(T0)
    register(direct_vm, contract, direct_bob, "Agent-Bob")

    p = contract.get_profile("agent-bob")  # normalized lookup works
    assert p["display_name"] == "Agent-Bob"  # as-typed kept for display
    assert p["tier"] == "unrated"
    assert p["jobs_insured"] == 0
    assert p["registered_at"] == T0

    # agent_id_for_address round-trips (uses the checksummed form from owner)
    assert contract.agent_id_for_address(p["owner"]) == "agent-bob"


def test_register_rejects_duplicate_and_bound_address(
    direct_vm, direct_deploy, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    register(direct_vm, contract, direct_bob, "agent-a")

    with direct_vm.expect_revert("already registered"):
        register(direct_vm, contract, direct_charlie, "agent-a")

    with direct_vm.expect_revert("address already bound"):
        register(direct_vm, contract, direct_bob, "agent-b")


def test_register_case_variant_is_same_identity(
    direct_vm, direct_deploy, direct_bob
):
    """Case-variant squatting must be closed: 'Agent-A' == 'agent-a'."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    register(direct_vm, contract, direct_bob, "Agent-A")
    with direct_vm.expect_revert("already registered"):
        register(direct_vm, contract, direct_bob, "agent-a")


def test_register_empty_id_rejected(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    with direct_vm.expect_revert("cannot be empty"):
        register(direct_vm, contract, direct_bob, "   ")


# ---------------------------------------------------------------------------
# LP pools
# ---------------------------------------------------------------------------

def test_deposit_bootstrap_and_proportional_shares(
    direct_vm, direct_deploy, direct_alice, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_charlie)

    deposit(direct_vm, contract, direct_alice, "unrated", 5 * 10**18)
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 5 * 10**18
    assert info["total_shares"] == 5 * 10**18  # 1:1 bootstrap
    assert contract.get_lp_position("unrated", addr_str(direct_alice)) == 5 * 10**18

    # Second LP buys in; shares mint proportionally.
    deposit(direct_vm, contract, direct_charlie, "unrated", 5 * 10**18)
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 10 * 10**18
    assert info["total_shares"] == 10 * 10**18


def test_deposit_invalid_tier_and_zero_value(
    direct_vm, direct_deploy, direct_alice
):
    """FIX-21: deposit is PAYABLE, so a bad argument is rejected-and-refunded
    rather than reverted -- a revert would retain the attached value."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    deposit(direct_vm, contract, direct_alice, "platinum", 5 * 10**18)
    reason = contract.get_rejection(addr_str(direct_alice))
    assert "unknown tier" in reason
    assert "refunded 5000000000000000000 atto" in reason
    assert "retained nothing" in reason

    direct_vm.sender = direct_alice
    direct_vm.value = 0
    contract.deposit("unrated")
    assert "deposit must be > 0" in contract.get_rejection(addr_str(direct_alice))
    assert contract.get_pool_info("unrated")["balance_atto"] == 0


def test_withdraw_blocks_under_locked_exposure(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """LP cannot pull capital out from under live coverage."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18  # 1 GEN
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == coverage
    assert info["balance_atto"] == 20 * 10**18 + prem

    # Withdrawing the full 20e18 shares would drop balance to 0 < locked.
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("withdrawal blocked"):
        contract.withdraw("unrated", 20 * 10**18)

    # Partial withdraw that keeps balance >= locked is fine.
    direct_vm.sender = direct_alice
    contract.withdraw("unrated", 5 * 10**18)
    info = contract.get_pool_info("unrated")
    assert info["total_shares"] == 15 * 10**18


def test_withdraw_release_after_policy_expires(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Once the buyer expires the policy (deadline passed), exposure is
    released and the LP can fully withdraw."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadline
    direct_vm.sender = direct_charlie
    contract.expire_policy("job-1")

    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    assert contract.get_policy("job-1")["status"] == "expired"

    # Now the LP can take everything out.
    direct_vm.sender = direct_alice
    contract.withdraw("unrated", 20 * 10**18)
    info = contract.get_pool_info("unrated")
    assert info["total_shares"] == 0


def test_expire_policy_requires_buyer_and_passed_deadline(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Before the deadline -> not allowed.
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("deadline has not passed"):
        contract.expire_policy("job-1")

    # After the deadline but from a non-buyer, before the claim window closes
    # -> still not allowed (FIX-09: only the buyer may expire while a claim
    # could still race in; anyone may once the 7-day window closes).
    direct_vm.warp("2026-03-02T00:00:00Z")
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("claim window still open"):
        contract.expire_policy("job-1")


# ---------------------------------------------------------------------------
# Policy issuance
# ---------------------------------------------------------------------------

def test_issue_policy_requires_pool_capital(
    direct_vm, direct_deploy, direct_bob, direct_charlie
):
    """Empty-pool first-depositor exploit must be closed: no capital, no policy.
    FIX-21: rejected-and-refunded, not reverted."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    direct_vm.warp(T0)  # so DEADLINE reads as future; the pool check is the target
    fund_accounts(direct_vm, direct_bob, direct_charlie)
    register(direct_vm, contract, direct_bob, "agent-a")

    premium = premium_for(10**18, "unrated")
    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   10**18, SPEC, DEADLINE, premium, "no underwriting capital")
    assert contract.get_claim_status("job-1") == "unresolved"


def test_issue_policy_rejects_foreign_host_and_min_coverage(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    # FIX-22: the evidence URL must be on the single allowlisted host, so a
    # caller cannot make every validator fetch an arbitrary address (SSRF).
    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   10**18, FOREIGN_URL, DEADLINE, premium_for(10**18, "unrated"),
                   "evidence URL must be https://raw.githubusercontent.com/")

    # A branch/tag in the commit slot is mutable -- refused, because the whole
    # immutability argument rests on that segment being a commit SHA.
    issue_rejected(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                   10**18, BRANCH_URL, DEADLINE, premium_for(10**18, "unrated"),
                   "commit SHA")
    # ...as is a sha256 that is not 64 hex characters.
    issue_rejected(direct_vm, contract, direct_charlie, "job-3", "agent-a",
                   10**18, (SPEC[0], "deadbeef"), DEADLINE,
                   premium_for(10**18, "unrated"), "sha256 must be 64 hex")

    # Coverage below MIN_COVERAGE_ATTO.
    issue_rejected(direct_vm, contract, direct_charlie, "job-4", "agent-a",
                   MIN_COVERAGE - 1, SPEC, DEADLINE, 1, "at least")


def test_issue_policy_premium_min_and_overpay_refunded(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """FIX-14: exact-premium enforcement was a front-runnable race (a concurrent
    issue could flip the agent's tier between quote and payment and revert the
    buyer for one atto). issue_policy now accepts value >= premium, crediting
    exactly the premium and refunding the excess. FIX-21: an underpayment is
    rejected-and-refunded, so the buyer's GEN is never retained."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    exact = premium_for(coverage, "unrated")

    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   coverage, SPEC, DEADLINE, exact - 1, "premium must be at least")
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18

    # Overpaying is accepted; only the premium is credited to the pool.
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, exact + 10**18)
    assert contract.get_policy("job-2")["status"] == "pending"
    # Pool gained exactly `exact`, not the overpaid amount (excess refunded).
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + exact


def test_issue_policy_rejects_past_and_too_soon_deadlines(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Gaming fix: an already-passed deadline must be rejected at issuance so
    a buyer can't instantly trigger the no-deliverable auto-breach. The same
    guard now also floors the horizon (MIN_DEADLINE_HORIZON_SECONDS = 60 s) so
    a manufactured round can't run on a ~1-second deadline."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   10**18, SPEC, PAST_DEADLINE, premium_for(10**18, "unrated"),
                   "seconds in the future")

    # 30 s out is real (past) but under the 60 s floor -> rejected too.
    issue_rejected(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                   10**18, SPEC, "2026-01-01T00:00:30Z",
                   premium_for(10**18, "unrated"), "seconds in the future")

    # 90 s out clears the floor (this is the boundary the demo relies on).
    issue_policy(direct_vm, contract, direct_charlie, "job-3", "agent-a",
                 10**18, SPEC, "2026-01-01T00:01:30Z", premium_for(10**18, "unrated"))
    # FIX-02: freshly issued policy is PENDING until the agent accepts.
    assert contract.get_policy("job-3")["status"] == "pending"
    accept(direct_vm, contract, direct_bob, "job-3")
    assert contract.get_policy("job-3")["status"] == "active"
    assert contract.get_policy("job-3")["agent_accepted"] is True


def test_issue_policy_rejects_self_buy(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Self-dealing hardening: the agent's own owner wallet cannot buy cover
    on it (closes the one-wallet drain -- register an agent, self-buy, collect
    a payout on a default you control). The buyer must be a separate role."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_bob)

    issue_rejected(direct_vm, contract, direct_bob, "job-1", "agent-a",
                   10**18, SPEC, DEADLINE, premium_for(10**18, "unrated"),
                   "cannot insure the agent's own job")


def test_issue_policy_coverage_capped_to_single_claim_share(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """MAX_COVERAGE_BPS_OF_POOL: one policy's coverage is capped at issue to
    10% of the tier pool -- the same share a single claim can move. Paired with
    the 50% aggregate utilization cap and withdraw's locked-exposure floor, this
    is what lets _resolve_claim pay coverage_atto IN FULL at settlement."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    # 20% of the 20 GEN pool is above the 10% cap -> rejected.
    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   4 * 10**18, SPEC, DEADLINE, premium_for(4 * 10**18, "unrated"),
                   "single-claim pool cap")

    # Exactly 10% (2 GEN) is allowed.
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 2 * 10**18, SPEC, DEADLINE, premium_for(2 * 10**18, "unrated"))
    accept(direct_vm, contract, direct_bob, "job-2")
    assert contract.get_policy("job-2")["status"] == "active"


def test_issue_policy_locks_exposure_and_counts_buyer_once(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Same buyer across multiple jobs counts as ONE distinct buyer, and
    exposure locks pool capital behind live coverage. FIX-21: the reputation
    counters are credited at ACCEPTANCE, not at issue."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    # Exposure is reserved the moment cover is issued...
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 2 * coverage
    # ...but nothing is credited to the agent's record yet.
    p = contract.get_profile("agent-a")
    assert p["jobs_insured"] == 0
    assert p["distinct_buyers"] == 0

    accept(direct_vm, contract, direct_bob, "job-1")
    accept(direct_vm, contract, direct_bob, "job-2")
    p = contract.get_profile("agent-a")
    assert p["jobs_insured"] == 2
    assert p["distinct_buyers"] == 1  # same address counted once


def test_policy_idempotency_and_unknown_agent(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "ghost",
                   10**18, SPEC, DEADLINE, premium_for(10**18, "unrated"),
                   "unknown agent_id")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    # Case variant = same key, so the second issue is rejected-and-refunded.
    issue_rejected(direct_vm, contract, direct_charlie, "Job-1", "agent-a",
                   coverage, SPEC, DEADLINE, prem, "already exists")


# ---------------------------------------------------------------------------
# Deliverable submission
# ---------------------------------------------------------------------------

def test_submit_deliverable_access_and_shape(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Only the insured agent may submit.
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("only the insured agent"):
        contract.submit_deliverable("job-1", *DELIV_OK)

    # Must be a commit-pinned URL on the allowlisted evidence host -- a foreign
    # host is refused before any probe (FIX-22: the caller does not choose what
    # every validator fetches).
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("no other host is fetchable"):
        contract.submit_deliverable("job-1", *FOREIGN_URL)

    # Agent submits, and can overwrite before the claim is judged. Each submit
    # live-probes the URL (FIX-01), so both must resolve before submit.
    mock_evidence(direct_vm, DELIV_BAD)
    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_BAD)
    contract.submit_deliverable("job-1", *DELIV_OK)
    assert contract.get_policy("job-1")["deliverable_url"] == DELIV_OK[0]


def test_submit_deliverable_unknown_job(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    register(direct_vm, contract, direct_bob, "agent-a")
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("unknown job_id"):
        contract.submit_deliverable("job-nope", *DELIV_OK)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def test_claim_premature_without_deliverable(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Before the deadline and no deliverable -> premature. file_claim is
    # PAYABLE, so the bond is refunded in-call rather than retained (FIX-21).
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    reason = contract.get_rejection(addr_str(direct_charlie), "job-1")
    assert "deadline has not passed" in reason
    assert f"refunded {CLAIM_BOND} atto" in reason
    assert contract.get_claim_status("job-1") == "unresolved"


def test_claim_auto_breach_when_no_deliverable_after_deadline(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Agent never submitted anything + deadline passed = deterministic breach,
    full coverage paid, bond refunded, exposure released."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadline, no deliverable
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")

    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_policy("job-1")["status"] == "claimed"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0

    # FIX-21: payout is exactly coverage_atto -- never a shrunken pool-share cap.
    # FIX-22: it is funded by the agent's bond, so the pool keeps its capital.
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 20 * 10**18 + prem
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0


def test_payouts_leave_over_external_ethsend_rail(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """PAYOUT-FIX-20 regression: every payee is a plain EOA wallet, so value
    must leave over the EXTERNAL (EthSend) rail -- never an IC-to-IC
    PostMessage to an address with no intelligent contract deployed (the bug
    that made each payout transfer finalize with a GenVM Execution ERROR and
    never credit the wallet). The direct VM records the gl_call request type
    of each emit in its trace: assert a payout emits EthSend and no value
    transfer routes as PostMessage."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadline, no deliverable
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # auto-breach: payout + bond refund

    assert contract.get_claim_status("job-1") == "upheld"
    traces = list(direct_vm._traces)
    assert any("EthSend" in t for t in traces), (
        f"payout did not use the external EthSend rail -- {traces}"
    )
    assert not any("PostMessage" in t for t in traces), (
        f"value routed as IC-to-IC PostMessage to an EOA (bug) -- {traces}"
    )


def test_claim_judged_upheld(direct_vm, direct_deploy, direct_alice, direct_bob,
                             direct_charlie):
    """Judged path: agent submitted a deliverable that DOES NOT meet spec ->
    LLM score below threshold -> breach upheld, payout + bond refund."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # submit_deliverable live-probes the URL (FIX-01): mock it before submit.
    mock_evidence(direct_vm, DELIV_BAD)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_BAD)

    # Mock the spec fetch + the LLM judgement (Shape B output schema).
    mock_evidence(direct_vm, SPEC)
    mock_judgement(direct_vm, 5)  # score below threshold -> breach

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # two-phase (FIX-19/H-02): escrows the bond
    assert contract.get_claim_status("job-1") == "pending"
    contract.judge_claim("job-1")  # non-payable verdict settles the claim

    assert contract.get_claim_status("job-1") == "upheld"
    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    # FIX-22: the agent's bond equals the coverage, so an upheld breach pays the
    # buyer the full coverage OUT OF THE BOND and the pool is made whole --
    # balance is exactly "premium earned", never "premium minus a payout".
    assert info["balance_atto"] == 20 * 10**18 + prem
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0


def test_claim_judged_rejected_bond_forfeited(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Deliverable conforms -> score high -> rejected; buyer's claim bond goes to
    the pool (compensates LPs for consensus), the AGENT's bond is returned, and
    exposure is released (FIX-22: a conforming agent keeps its skin)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == coverage

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    mock_evidence(direct_vm, SPEC)
    mock_judgement(direct_vm, 95)  # score above threshold -> conforms

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    contract.judge_claim("job-1")

    assert contract.get_claim_status("job-1") == "rejected"
    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    # Premium stays, the claim bond is added to the pool, coverage not paid out,
    # and the agent's bond left escrow (returned, not forfeited).
    assert info["balance_atto"] == 20 * 10**18 + prem + CLAIM_BOND
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0


def test_claim_gate_access_and_bond(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadline
    # Wrong bond -- rejected-and-refunded, not reverted (FIX-21).
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND - 1
    contract.file_claim("job-1")
    assert "claim bond must be exactly" in contract.get_rejection(
        addr_str(direct_charlie), "job-1"
    )

    # Not the buyer -> also refunded in-call.
    direct_vm.sender = direct_owner
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert "only the policy buyer" in contract.get_rejection(
        addr_str(direct_owner), "job-1"
    )

    # Legit claim then double-claim is rejected-and-refunded.
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert "claim already resolved" in contract.get_rejection(
        addr_str(direct_charlie), "job-1"
    )


def test_claim_pays_full_coverage_even_after_pool_shrinks(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """FIX-21 (review item 5) -- the coverage-conservation guarantee.

    Before this fix the payout was min(coverage_atto, 10% of the CURRENT pool),
    so an LP withdrawal between issue and settlement silently shrank what a
    policy actually paid: cover 2 GEN, receive less. Now coverage_atto is paid
    IN FULL at settlement, and the ledger is guaranteed to be able to fund it
    because withdraw refuses to take the pool below locked exposure.

    This test drives exactly the adversarial case: two 2 GEN policies on a
    20 GEN pool, then the LP withdraws almost everything still permitted. The
    pool is left at 4.048 GEN, so the OLD cap would have paid 0.4048 GEN on a
    2 GEN policy. The claim must still pay the full 2 GEN."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    cov = 2 * 10**18  # exactly 10% of the 20 GEN pool -- allowed at issue
    prem = premium_for(cov, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 cov, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 cov, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    accept(direct_vm, contract, direct_bob, "job-2")

    pool_before_wd = contract.get_pool_info("unrated")["balance_atto"]
    assert pool_before_wd == 20 * 10**18 + 2 * prem

    # LP pulls out as much as the locked-exposure floor allows. 16e18 shares of
    # the 20e18 total leaves the pool at 4.048 GEN against 4 GEN of locked
    # exposure -- just barely solvent, and far below the old 10% payout cap.
    direct_vm.sender = direct_alice
    contract.withdraw("unrated", 16 * 10**18)
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 4048000000000000000
    assert info["locked_exposure_atto"] == 2 * cov
    # The invariant that makes full-coverage payout safe.
    assert info["balance_atto"] >= info["locked_exposure_atto"]

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadlines, no deliverable

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"

    # Paid exactly coverage_atto (2 GEN), not the 0.4048 GEN the old cap gave.
    # FIX-22: that 2 GEN comes out of the agent's 2 GEN bond, so the pool's own
    # balance is UNCHANGED by the settlement -- the LP capital is never spent.
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 4048000000000000000
    assert info["locked_exposure_atto"] == cov
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == cov

    # The second policy settles at its own full coverage too.
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-2")
    assert contract.get_claim_status("job-2") == "upheld"
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 4048000000000000000
    assert info["locked_exposure_atto"] == 0
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0


# ---------------------------------------------------------------------------
# Accounting reconciliation (FIX-21 review item 3)
# ---------------------------------------------------------------------------

def test_accounting_reconciles_with_contract_balance(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """get_accounting exposes the numbers a reviewer needs to reconcile the
    explorer balance against the contract's internal ledger: the tier pool, the
    escrowed claim bonds held outside it, and the contract's own balance."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    acc = contract.get_accounting("unrated")
    assert acc["tier"] == "unrated"
    assert acc["tier_balance_atto"] == 20 * 10**18 + prem
    assert acc["locked_exposure_atto"] == coverage
    assert acc["pending_claim_bonds_atto"] == 0
    # FIX-22: the agent's bond is held OUTSIDE the pool but is still contract-
    # attributed value -- so attributed = pool + bonds, not pool alone.
    assert acc["agent_bond_escrow_atto"] == coverage
    assert acc["attributed_atto"] == acc["tier_balance_atto"] + coverage

    # A pending claim's bond is held but not yet credited to any pool, so it
    # must show up as an attributed-but-unpooled amount.
    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")

    acc = contract.get_accounting("unrated")
    assert acc["pending_claim_bonds_atto"] == CLAIM_BOND
    assert acc["attributed_atto"] == (
        acc["tier_balance_atto"] + CLAIM_BOND + coverage
    )
    # `contract_balance_atto` is only meaningful on-chain: direct mode does not
    # model native value at the VM level, so self.balance reads 0 here. On the
    # live network it is the explorer-visible balance and the whole point of the
    # view -- surplus over `attributed_atto` is exactly the value an old
    # reverted payable call would have retained.
    assert isinstance(acc["contract_balance_atto"], int)


# ---------------------------------------------------------------------------
# Reputation / tier
# ---------------------------------------------------------------------------

def test_tier_promotion_bronze_requires_real_buyers_and_tenure(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """Bronze: >=3 insured jobs, >=2 distinct buyers, >=3 days tenure.
    FIX-08: promotion only sticks when the earned tier is actually funded, so
    the test backs 'bronze' with real LP capital too."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    deposit(direct_vm, contract, direct_alice, "bronze", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")

    # FIX-21 (review item 7): reputation is credited on the agent's ACCEPTANCE,
    # not at issuance -- a third party can no longer inflate an unwilling
    # agent's counts. So every job here must be accepted to count.

    # Buyer 1 buys 2 jobs at T0; the agent accepts both.
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-2")
    profile = contract.get_profile("agent-a")
    assert profile["jobs_insured"] == 2
    assert profile["distinct_buyers"] == 1
    assert profile["tier"] == "unrated"

    # Same address buying a 3rd job must NOT push to bronze (needs 2 distinct).
    issue_policy(direct_vm, contract, direct_charlie, "job-3", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-3")
    assert contract.get_profile("agent-a")["tier"] == "unrated"
    assert contract.get_profile("agent-a")["distinct_buyers"] == 1

    # Distinct buyer 2, but still within tenure window (2 days < 3).
    direct_vm.warp("2026-01-03T00:00:00Z")
    issue_policy(direct_vm, contract, direct_owner, "job-4", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-4")
    assert contract.get_profile("agent-a")["distinct_buyers"] == 2
    assert contract.get_profile("agent-a")["tier"] == "unrated"

    # After >=3 days tenure, the acceptance promotes.
    direct_vm.warp(T_PLUS_4)
    issue_policy(direct_vm, contract, direct_owner, "job-5", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-5")
    assert contract.get_profile("agent-a")["tier"] == "bronze"
    assert contract.get_profile("agent-a")["distinct_buyers"] == 2


def test_tier_pricing_changes_after_promotion(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """After promotion the premium is priced off the new tier's rate."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    deposit(direct_vm, contract, direct_alice, "bronze", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    # FIX-21: reputation accrues on acceptance, so each job must be accepted.
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-2")
    issue_policy(direct_vm, contract, direct_owner, "job-3", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-3")
    direct_vm.warp(T_PLUS_4)
    issue_policy(direct_vm, contract, direct_owner, "job-4", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-4")

    assert contract.get_profile("agent-a")["tier"] == "bronze"

    quote = contract.quote_premium("agent-a", coverage)
    assert quote["tier"] == "bronze"
    assert quote["rate_bps"] == 400

    # A new policy on a bronze agent is priced off the bronze rate. Paying less
    # (gold's 150 bps) is rejected-and-refunded (FIX-21 -- issue_policy is
    # payable, so an underpayment must never revert and retain the value); the
    # bronze premium is accepted (FIX-14).
    issue_rejected(direct_vm, contract, direct_charlie, "job-5", "agent-a",
                   coverage, SPEC, DEADLINE, premium_for(coverage, "gold"),
                   "premium must be at least")
    issue_policy(direct_vm, contract, direct_charlie, "job-5", "agent-a",
                 coverage, SPEC, DEADLINE, premium_for(coverage, "bronze"))
    assert contract.get_policy("job-5")["status"] == "pending"


# ---------------------------------------------------------------------------
# Claim against an agent drags their reputation down
# ---------------------------------------------------------------------------

def test_claim_history_updates_profile(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadline, no deliverable
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")

    p = contract.get_profile("agent-a")
    assert p["claims_filed_against"] == 1
    assert p["claims_upheld_against"] == 1


# ---------------------------------------------------------------------------
# Shape B regression tests (SECURITY-CHECK/security-fixes.md)
# ---------------------------------------------------------------------------

def test_unresolvable_url_submit_reverts(direct_vm, direct_deploy, direct_alice,
                                         direct_bob, direct_charlie):
    """C-1 veto: a deliverable URL that does not resolve must fail on the
    AGENT's submit transaction (live probe, FIX-01) -- never brick the buyer's
    later claim with unjudgeable evidence."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Deterministic 404 for a URL that is not retrievable.
    direct_vm.mock_web(re.escape(DELIV_BAD[0]),
                       {"status": 404, "body": ""})
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("not retrievable"):
        contract.submit_deliverable("job-1", *DELIV_BAD)
    # The policy is left untouched -- the buyer can still claim the no-breach
    # path or a later good submission.
    assert contract.get_policy("job-1")["deliverable_url"] == ""


def test_post_probe_unpin_is_breach_not_revert(direct_vm, direct_deploy,
                                               direct_alice, direct_bob,
                                               direct_charlie):
    """C-1 veto: a URL that was retrievable at submit but 404s at claim time
    is adjudicated as a BREACH (score 0), not an unjudgeable revert -- so an
    agent cannot unpin after the fact to neutralise a pending claim."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Submit passes the probe (the URL resolves at submit time).
    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    # Between submit and claim the content is unpinned -> now 404 at judge.
    direct_vm.clear_mocks()
    mock_evidence(direct_vm, SPEC)
    direct_vm.mock_web(re.escape(DELIV_OK[0]), {"status": 404, "body": ""})

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # must NOT revert
    contract.judge_claim("job-1")  # judge decides the unpinned deliverable = breach

    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    # Breach paid out of the agent's bond: the pool keeps its capital (FIX-22).
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + prem


def test_deliverable_frozen_after_deadline(direct_vm, direct_deploy,
                                           direct_alice, direct_bob,
                                           direct_charlie):
    """C-1: evidence is frozen at the deadline -- the agent cannot swap in an
    unretrievable URL once a claim looks likely (FIX-01 Step 3)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp(AFTER_DEADLINE)  # 1 day past the deadline
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("deadline passed -- deliverable is frozen"):
        contract.submit_deliverable("job-1", *DELIV_OK)


def test_whitespace_url_is_canonicalized(direct_vm, direct_deploy,
                                         direct_alice, direct_bob,
                                         direct_charlie):
    """C-1 variant 2 (FIX-22): the fix CANONICALIZES rather than rejecting, so a
    commit-pinned URL padded with whitespace/newlines is stored stripped --
    validating .strip() while storing the raw argument would have corrupted the
    fetched URL (a guaranteed 404, and historically an agent's cheapest veto)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *WHITESPACE_URL)  # "   https://...\n"
    assert contract.get_policy("job-1")["deliverable_url"] == DELIV_OK[0]


def test_oversized_url_rejected(direct_vm, direct_deploy, direct_alice,
                                direct_bob, direct_charlie):
    """C-1 variant 3 (FIX-22): an unbounded URL that would 414 the host is
    rejected by the MAX_EVIDENCE_URL_LEN cap before any fetch."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("evidence URL too long"):
        contract.submit_deliverable("job-1", *LONG_URL)


def test_unaccepted_policy_cannot_submit_or_claim(direct_vm, direct_deploy,
                                                  direct_alice, direct_bob,
                                                  direct_charlie):
    """C-2 consent: a PENDING policy (issued but not yet accepted by the agent)
    carries no submit or claim rights -- a stranger cannot bind an agent and
    then let the deadline auto-breach."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_policy("job-1")["status"] == "pending"

    # Agent cannot submit against a policy it has not accepted.
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("policy not active"):
        contract.submit_deliverable("job-1", *DELIV_OK)

    # Buyer cannot claim against an unaccepted policy either. file_claim is
    # payable, so this is a reject-and-refund (FIX-21), not a revert -- and the
    # bond is returned rather than retained.
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    reason = contract.get_rejection(addr_str(direct_charlie), "job-1")
    assert "policy not active" in reason
    assert f"refunded {CLAIM_BOND} atto" in reason
    assert "retained nothing" in reason

    # FIX-16: accepting after the deadline is refused -- an overdue policy
    # can no longer be bound into an instant "no deliverable" auto-breach.
    # accept_job is PAYABLE (FIX-22), so this is a reject-and-refund of the
    # posted bond (FIX-21), not a revert that would retain it.
    direct_vm.sender = direct_bob
    direct_vm.value = coverage
    contract.accept_job("job-1")
    reason = contract.get_rejection(addr_str(direct_bob), "job-1")
    assert "deadline has passed" in reason
    assert f"refunded {coverage} atto" in reason
    assert "retained nothing" in reason
    assert contract.get_policy("job-1")["status"] == "pending"


def test_reject_job_releases_and_refunds(direct_vm, direct_deploy, direct_alice,
                                         direct_bob, direct_charlie):
    """C-2: an agent rejecting a pending policy releases its locked exposure
    and refunds the buyer's premium (no grief-lock, no value lost)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == coverage
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + prem

    direct_vm.sender = direct_bob
    contract.reject_job("job-1")

    assert contract.get_policy("job-1")["status"] == "expired"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    # Premium refunded -> pool back to its pre-issue balance.
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18


def test_cancel_pending_policy_releases_and_refunds(direct_vm, direct_deploy,
                                                    direct_alice, direct_bob,
                                                    direct_charlie, direct_owner):
    """C-2: the buyer can cancel a pending policy the agent never accepted;
    exposure is released and the premium refunded. Only the buyer may cancel."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    # Non-buyer cannot cancel.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("only the buyer may cancel"):
        contract.cancel_pending_policy("job-1")

    direct_vm.sender = direct_charlie
    contract.cancel_pending_policy("job-1")
    assert contract.get_policy("job-1")["status"] == "expired"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18


def test_aggregate_exposure_capped(direct_vm, direct_deploy, direct_alice,
                                   direct_bob, direct_charlie):
    """FIX-03: aggregate live coverage per tier is capped at 50% of the pool,
    so enough 10%-sized policies can no longer freeze LP capital forever."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    cov = 2 * 10**18  # exactly the 10%-of-20-GEN single-policy cap
    prem = premium_for(cov, "unrated")
    for i in range(5):
        issue_policy(direct_vm, contract, direct_charlie, f"job-{i}", "agent-a",
                     cov, SPEC, DEADLINE, prem)
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 5 * cov

    # A 6th policy would push exposure past the 50% utilization cap. FIX-21:
    # issue_policy is payable, so the over-cap issue is rejected and the premium
    # refunded in-call rather than reverting with the value retained.
    issue_rejected(direct_vm, contract, direct_charlie, "job-overflow", "agent-a",
                   cov, SPEC, DEADLINE, prem, "at capacity")
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 5 * cov


def test_bronze_requires_breach_rate(direct_vm, direct_deploy, direct_alice,
                                     direct_bob, direct_charlie, direct_owner):
    """FIX-07: bronze is gated on an actual breach-rate record, not monotonic
    counts. An agent meeting the job/buyer/tenure thresholds but carrying a
    1-in-3 breach rate stays unrated -- it must NOT be promoted to bronze."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 100 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    # 3 jobs, 2 distinct buyers (charlie x2, owner x1).
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-2")
    issue_policy(direct_vm, contract, direct_owner, "job-3", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-3")

    # job-2 (charlie) and job-3 (owner) conform -> rejected claims (no breach).
    for jid, buyer in (("job-2", direct_charlie), ("job-3", direct_owner)):
        mock_evidence(direct_vm, DELIV_OK)
        direct_vm.sender = direct_bob
        contract.submit_deliverable(jid, *DELIV_OK)
        mock_evidence(direct_vm, SPEC)
        mock_judgement(direct_vm, 95)
        direct_vm.sender = buyer
        direct_vm.value = CLAIM_BOND
        contract.file_claim(jid)
        contract.judge_claim(jid)  # two-phase (FIX-19/H-02)
        assert contract.get_claim_status(jid) == "rejected"

    # job-1 never received a deliverable -> deterministic auto-breach (upheld).
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"

    # Now: 3 jobs, 2 distinct buyers, tenure elapsed -- but breach_rate is
    # 1/3, above bronze's 0.20 ceiling and below penalty's 0.34 -> unrated.
    p = contract.get_profile("agent-a")
    assert p["claims_filed_against"] == 3
    assert p["claims_upheld_against"] == 1
    assert p["tier"] == "unrated"


def test_penalty_tier_after_high_breach(direct_vm, direct_deploy, direct_alice,
                                        direct_bob, direct_charlie, direct_owner):
    """FIX-07: a chronic breacher (breach rate above PENALTY_BREACH_RATE) is
    demoted to the penalty tier, priced WORSE than any newcomer (1200 bps).
    The penalty pool must be funded for the tier to stick (FIX-08 fallback)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    deposit(direct_vm, contract, direct_alice, "penalty", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    for jid, buyer in (("job-1", direct_charlie), ("job-2", direct_owner)):
        issue_policy(direct_vm, contract, buyer, jid, "agent-a",
                     coverage, SPEC, DEADLINE, prem)
        accept(direct_vm, contract, direct_bob, jid)

    # Both jobs breach (no deliverable, deadline passed).
    direct_vm.warp(AFTER_DEADLINE)
    for jid, buyer in (("job-1", direct_charlie), ("job-2", direct_owner)):
        direct_vm.sender = buyer
        direct_vm.value = CLAIM_BOND
        contract.file_claim(jid)
        assert contract.get_claim_status(jid) == "upheld"

    p = contract.get_profile("agent-a")
    assert p["tier"] == "penalty"
    quote = contract.quote_premium("agent-a", coverage)
    assert quote["tier"] == "penalty"
    assert quote["rate_bps"] == 1200


def test_promotion_into_unfunded_falls_back(direct_vm, direct_deploy,
                                            direct_alice, direct_bob,
                                            direct_charlie, direct_owner):
    """FIX-08: promotion into an unfunded tier falls back to the best funded
    tier at or below -- an honest agent can never be stranded in a tier with no
    underwriting capital (which would make them uninsurable)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)  # no bronze pool
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    direct_vm.warp(T_PLUS_4)  # tenure >= 3 days
    # 3rd job + 2nd distinct buyer -> earns bronze, but bronze is unfunded.
    issue_policy(direct_vm, contract, direct_owner, "job-3", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    p = contract.get_profile("agent-a")
    assert p["tier"] == "unrated"  # fell back instead of being stranded
    assert contract.quote_premium("agent-a", coverage)["rate_bps"] == 600


def test_permissionless_expiry_after_window(direct_vm, direct_deploy,
                                            direct_alice, direct_bob,
                                            direct_charlie, direct_owner):
    """FIX-09: after the 7-day claim window closes, ANYONE can expire an
    abandoned active policy and release its locked exposure."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp(PAST_WINDOW)  # 9 days after DEADLINE
    direct_vm.sender = direct_owner  # not the buyer
    contract.expire_policy("job-1")

    assert contract.get_policy("job-1")["status"] == "expired"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0


def test_file_claim_refused_after_window(direct_vm, direct_deploy, direct_alice,
                                         direct_bob, direct_charlie):
    """FIX-09: once the 7-day claim window has closed no claim may be filed --
    this is what makes the permissionless expiry race-free."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp(PAST_WINDOW)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    reason = contract.get_rejection(addr_str(direct_charlie), "job-1")
    assert "claim window has closed" in reason
    assert f"refunded {CLAIM_BOND} atto" in reason
    assert contract.get_claim_status("job-1") == "unresolved"


def test_out_of_range_score_rejected(direct_vm, direct_deploy, direct_alice,
                                     direct_bob, direct_charlie):
    """FIX-06: an out-of-range LLM score reverts the claim instead of being
    silently clamped -- clamping would destroy the divergence signal the
    validator comparison depends on."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_evidence(direct_vm, DELIV_BAD)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_BAD)

    mock_evidence(direct_vm, SPEC)
    mock_judgement(direct_vm, 250)  # adversarial echo, not a real grade
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # deterministic file -- escrows bond, succeeds
    assert contract.get_claim_status("job-1") == "pending"

    # The out-of-range score makes the NON-payable verdict call revert. No value
    # is attached, so the bond is never burned and the claim stays pending
    # (FIX-19 / H-02).
    with direct_vm.expect_revert("score out of range"):
        contract.judge_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"

    # Retry with a sane grade settles the same pending claim. (mock_llm keeps
    # the first registration, so clear + re-register everything.)
    direct_vm.clear_mocks()
    mock_evidence(direct_vm, SPEC)
    mock_evidence(direct_vm, DELIV_BAD)
    mock_judgement(direct_vm, 5)
    contract.judge_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"


def test_zero_share_deposit_rejected(direct_vm, direct_deploy, direct_alice,
                                     direct_bob, direct_charlie):
    """FIX-11: a deposit too small to mint any LP shares is rejected-and-
    refunded (FIX-21: deposit is payable, so rejecting must not revert) instead
    of silently burning the depositor's value."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    # Inflate pool balance above total shares by issuing (premium is credited
    # to the pool with no matching share mint), so 1 atto mints 0 shares.
    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    pool_before = contract.get_pool_info("unrated")["balance_atto"]

    direct_vm.sender = direct_charlie
    direct_vm.value = 1  # 1 atto
    contract.deposit("unrated")
    reason = contract.get_rejection(addr_str(direct_charlie))
    assert "deposit too small to mint any LP shares" in reason
    assert "refunded 1 atto" in reason
    assert "retained nothing" in reason
    # Nothing was credited and nothing was retained.
    assert contract.get_pool_info("unrated")["balance_atto"] == pool_before


def test_invalid_calendar_date_rejected(direct_vm, direct_deploy, direct_alice,
                                        direct_bob, direct_charlie):
    """FIX-15c: an impossible calendar date (2026-02-30) must not silently roll
    over in epoch math -- it is rejected-and-refunded at issuance (FIX-21)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    prem = premium_for(10**18, "unrated")
    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   10**18, SPEC, "2026-02-30T00:00:00Z", prem, "must be an ISO-8601")
    # No policy was created by the rejected call.
    with direct_vm.expect_revert("unknown job_id"):
        contract.get_policy("job-1")


def test_rate_limit_maps_to_transient(direct_vm, direct_deploy, direct_alice,
                                      direct_bob, direct_charlie):
    """FIX-13: a per-validator 429 on the evidence gateway routes to a
    transient error (revert + consensus rotation) -- never to a permanent
    verdict, and never with status codes embedded in the [EXTERNAL] message."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    # Gateway rate-limits the claim-time fetch of the spec.
    direct_vm.mock_web(re.escape(SPEC[0]), {"status": 429, "body": ""})
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # deterministic file -- succeeds, escrows bond
    assert contract.get_claim_status("job-1") == "pending"

    # The verdict call (non-payable) reverts on the transient 429 -- NO value is
    # attached to judge_claim, so the bond is NOT burned (FIX-19 / H-02). The
    # claim stays pending and is retryable. FIX-21: four gateways are tried, so
    # "every gateway failed" is an outage, not a 404 -- hence the generic
    # "gateway unavailable" transient rather than a gateway-specific status.
    with direct_vm.expect_revert("evidence host unavailable"):
        contract.judge_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"

    # Gateway recovers: the same pending claim settles normally. (mock_llm keeps
    # the first registration, so clear + re-register everything.)
    direct_vm.clear_mocks()
    mock_evidence(direct_vm, SPEC)
    mock_evidence(direct_vm, DELIV_OK)
    mock_judgement(direct_vm, 95)  # deliverable conforms
    contract.judge_claim("job-1")
    assert contract.get_claim_status("job-1") == "rejected"


def test_spec_unavailable_at_judge_is_rejected_not_breach(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Custody split (FIX-01): the SPEC is buyer-supplied and only shape-checked
    at issue, so a spec that 404s at judge time means the BUYER's own evidence is
    gone -- the claim is REJECTED (bond forfeited, agent not demoted), never a
    manufactured breach against an agent that delivered conforming work."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    # The buyer unpins its own spec after the agent already delivered.
    direct_vm.mock_web(re.escape(SPEC[0]), {"status": 404, "body": ""})

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    contract.judge_claim("job-1")

    assert contract.get_claim_status("job-1") == "rejected"
    assert contract.get_profile("agent-a")["claims_upheld_against"] == 0
    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    # Premium stays, bond forfeited to the pool, coverage never paid out.
    assert info["balance_atto"] == 20 * 10**18 + prem + CLAIM_BOND


def test_spec_oversized_at_judge_is_rejected(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """FIX-05 custody split: a spec that grew past MAX_EVIDENCE_BYTES at judge
    time is the buyer's own evidence failing -- rejected, not a breach."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    direct_vm.mock_web(re.escape(SPEC[0]),
                       {"status": 200, "body": b"x" * (128 * 1024 + 1)})

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    contract.judge_claim("job-1")

    assert contract.get_claim_status("job-1") == "rejected"
    assert contract.get_profile("agent-a")["claims_upheld_against"] == 0
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + prem + CLAIM_BOND


def test_expire_pending_policy_releases_after_window(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """FIX-18: a PENDING policy the agent never accepted and the buyer never
    cancelled can be expired by ANYONE once its deadline + claim window have
    passed -- locked exposure released, premium refunded to the buyer."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_policy("job-1")["status"] == "pending"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == coverage

    # Within the deadline + claim window, expiry is refused.
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("still within its deadline"):
        contract.expire_pending_policy("job-1")

    # Past the boundary: anyone can void it; the premium returns to the buyer.
    direct_vm.warp(PAST_WINDOW)
    contract.expire_pending_policy("job-1")
    assert contract.get_policy("job-1")["status"] == "expired"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18


# ---------------------------------------------------------------------------
# Two-phase claims (FIX-19 / H-02) -- failed judgements must never burn the bond
# ---------------------------------------------------------------------------

def _judged_policy(direct_vm, contract, buyer, agent_acct, job_id, score=95):
    """Issue + accept + deliver a conforming deliverable so file_claim takes the
    judged (non-deterministic) path, then mock the spec + LLM for judgement."""
    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, buyer, job_id, "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, agent_acct, job_id)
    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = agent_acct
    contract.submit_deliverable(job_id, *DELIV_OK)
    mock_evidence(direct_vm, SPEC)
    mock_judgement(direct_vm, score)
    direct_vm.sender = buyer
    direct_vm.value = CLAIM_BOND


def test_judge_claim_requires_a_pending_claim(direct_vm, direct_deploy,
                                              direct_alice, direct_bob,
                                              direct_charlie, direct_owner):
    """judge_claim is only valid for a claim file_claim escrowed -- an
    unclaimed policy, a non-active policy, or an already-resolved claim all
    revert, so nobody can settle (or double-settle) a claim out of thin air."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # No claim filed -> no pending claim to judge.
    with direct_vm.expect_revert("no pending claim"):
        contract.judge_claim("job-1")

    # Auto-breach resolves inside file_claim itself -> never a pending claim.
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"
    with direct_vm.expect_revert("no pending claim"):
        contract.judge_claim("job-1")


def test_pending_claim_freezes_deliverable_and_expiry(direct_vm, direct_deploy,
                                                      direct_alice, direct_bob,
                                                      direct_charlie, direct_owner):
    """While a judgement is pending: the agent cannot swap the deliverable
    (evidence must be stable until resolution) and nobody can expire the policy
    (exposure must stay locked until the claim settles or is rescinded)."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    _judged_policy(direct_vm, contract, direct_charlie, direct_bob, "job-1")
    contract.file_claim("job-1")  # judged path -> pending
    assert contract.get_claim_status("job-1") == "pending"
    assert contract.get_policy("job-1")["status"] == "active"

    # Deliverable frozen while pending (even pre-deadline -- a claim is live).
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("frozen while a claim is pending"):
        contract.submit_deliverable("job-1", *DELIV_OK)

    # Expiry blocked while pending -- exposure stays locked for the verdict.
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("verdict pending"):
        contract.expire_policy("job-1")
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("verdict pending"):
        contract.expire_policy("job-1")
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 10**18


def test_permissionless_judge_claim_refunds_bond_to_buyer(direct_vm, direct_deploy,
                                                          direct_alice, direct_bob,
                                                          direct_charlie, direct_owner):
    """judge_claim is permissionless: a third party can settle a pending claim
    to its correct outcome, and the escrowed bond refund goes to the POLICY
    BUYER who paid it -- never to the caller."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    _judged_policy(direct_vm, contract, direct_charlie, direct_bob, "job-1", score=5)
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"

    # A stranger runs the consensus judgement; the payout still goes to the buyer.
    direct_vm.sender = direct_owner
    contract.judge_claim("job-1")

    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_profile("agent-a")["claims_upheld_against"] == 1
    # FIX-22: coverage is paid out of the forfeited agent bond, so the pool's
    # balance is the premium and nothing more; the escrowed claim bond is
    # refunded to the buyer (never to the permissionless caller).
    assert contract.get_pool_info("unrated")["balance_atto"] == (
        20 * 10**18 + premium_for(10**18, "unrated")
    )
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0


def test_rescind_pending_claim_returns_policy_to_active(direct_vm, direct_deploy,
                                                        direct_alice, direct_bob,
                                                        direct_charlie, direct_owner):
    """If the evidence is unjudgeable (e.g. gateway outage) the buyer can walk
    away: rescind releases the escrowed bond, the policy returns to active with
    exposure still locked, and a fresh claim can be filed later."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    _judged_policy(direct_vm, contract, direct_charlie, direct_bob, "job-1")
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"

    # Only the buyer can rescind their own escrowed bond.
    direct_vm.sender = direct_owner
    with direct_vm.expect_revert("only the policy buyer"):
        contract.rescind_pending_claim("job-1")

    direct_vm.sender = direct_charlie
    contract.rescind_pending_claim("job-1")
    assert contract.get_claim_status("job-1") == "unresolved"
    assert contract.get_policy("job-1")["status"] == "active"
    # Exposure stays locked (not released by rescind) -- expiry still works.
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 10**18

    # The buyer can file again -- the escrow slot is free (bond was returned).
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"
    contract.judge_claim("job-1")  # mocks still score 95 -> conforming -> rejected
    assert contract.get_claim_status("job-1") == "rejected"


def test_double_file_claim_blocked_while_pending(direct_vm, direct_deploy,
                                                 direct_alice, direct_bob,
                                                 direct_charlie):
    """A second file_claim while the first judgement is pending is rejected-and-
    refunded (FIX-21) -- one escrow slot per policy, and the second bond is
    handed straight back rather than retained."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    _judged_policy(direct_vm, contract, direct_charlie, direct_bob, "job-1")
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"

    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    reason = contract.get_rejection(addr_str(direct_charlie), "job-1")
    assert "claim already pending" in reason
    assert f"refunded {CLAIM_BOND} atto" in reason
    assert "retained nothing" in reason
    assert contract.get_claim_status("job-1") == "pending"
    # The escrow is exactly one bond -- the rejected second call credited nothing.
    acc = contract.get_accounting("unrated")
    assert acc["pending_claim_bonds_atto"] == CLAIM_BOND


# ---------------------------------------------------------------------------
# FIX-21 remediation coverage (review items 5, 7, 8, 9, 12)
#
# One test per remediation the review asked to see demonstrated:
#   * failed payable execution + value recovery  -> test_rejected_payable_never_retains_value
#   * coverage conservation                      -> test_claim_pays_full_coverage_even_after_pool_shrinks
#   * reputation rollback                        -> test_voided_policies_never_inflate_reputation
#   * evidence-integrity mismatch                     -> test_evidence_integrity_mismatch_is_refused_not_judged
#   * oversized / non-text evidence              -> test_non_text_evidence_refused_at_submit
#   * gateway failure                            -> test_rate_limit_maps_to_transient
#   * validator disagreement                     -> test_validator_rejects_divergent_leader
#   * full paid lifecycle                        -> test_full_paid_lifecycle_quote_to_payout
# ---------------------------------------------------------------------------

def test_rejected_payable_never_retains_value(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review items 1-2: the live failure was a FUNDED issue_policy that
    finalized GENVM RESULT: ERROR, created no policy, and still moved the
    contract's balance up (19.06 -> 19.12 GEN) -- GenLayer does not refund the
    attached value of a reverted payable call.

    The remediation is structural: no buyer-fixable condition may revert. Every
    payable rejection must SUCCEED, refund the full attached value in the same
    transaction, and record the reason on-chain. This test drives every payable
    rejection path and asserts the properties that make retention impossible:
    (a) the call returns normally, (b) the recorded reason names the exact
    amount refunded, (c) the pool's ledger is byte-for-byte unchanged."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")

    # --- issue_policy rejections (the exact live failure's method) ----------
    pool0 = contract.get_pool_info("unrated")["balance_atto"]
    # (i) the live failure's shape: coverage above the single-claim pool cap.
    issue_rejected(direct_vm, contract, direct_charlie, "job-cap", "agent-a",
                   2 * 10**18 + 1, SPEC, DEADLINE, prem, "coverage exceeds")
    # (ii) unknown agent, (iii) foreign-host spec URL, (iv) premium below
    #      quote, (v) self-buy, (vi) impossible calendar date.
    issue_rejected(direct_vm, contract, direct_charlie, "job-unk", "ghost",
                   coverage, SPEC, DEADLINE, prem, "unknown agent")
    issue_rejected(direct_vm, contract, direct_charlie, "job-url", "agent-a",
                   coverage, FOREIGN_URL, DEADLINE, prem,
                   "evidence URL must be https")
    issue_rejected(direct_vm, contract, direct_charlie, "job-cheap", "agent-a",
                   coverage, SPEC, DEADLINE, prem - 1, "premium must be at least")
    direct_vm.sender = direct_bob
    direct_vm.value = prem
    contract.issue_policy("job-self", "agent-a", coverage, SPEC[0], SPEC[1], DEADLINE)
    assert "cannot insure the agent's own job" in contract.get_rejection(
        addr_str(direct_bob), "job-self"
    )
    issue_rejected(direct_vm, contract, direct_charlie, "job-cal", "agent-a",
                   coverage, SPEC, "2026-02-30T00:00:00Z", prem, "must be an ISO-8601")

    # --- deposit and file_claim rejections ---------------------------------
    direct_vm.sender = direct_charlie
    direct_vm.value = 5 * 10**18
    contract.deposit("platinum")
    assert "unknown tier" in contract.get_rejection(addr_str(direct_charlie))

    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")  # active, so the bond is the gate
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND - 1
    contract.file_claim("job-1")  # active policy, but the bond is wrong
    assert "claim bond must be exactly" in contract.get_rejection(
        addr_str(direct_charlie), "job-1"
    )

    # Every rejected call above returned normally, so the pool only ever saw
    # the one successful issue: 20 GEN + its premium.
    assert contract.get_pool_info("unrated")["balance_atto"] == pool0 + prem


def test_successful_payable_clears_stale_rejection(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 4: the UI reads get_rejection(payer, job_id) after a payable
    write to learn whether THAT call was rejected (a rejection legitimately
    SUCCEEDS on-chain and refunds, so there is no revert message to read). For
    that read-back to be truthful, a successful call must clear any rejection
    recorded earlier for the same key -- otherwise a single past rejection would
    make every later success look rejected."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")

    # --- deposit: reject, then succeed, and the rejection must be gone ------
    direct_vm.sender = direct_charlie
    direct_vm.value = 5 * 10**18
    contract.deposit("platinum")  # unknown tier -> rejected + refunded
    assert "unknown tier" in contract.get_rejection(addr_str(direct_charlie))

    deposit(direct_vm, contract, direct_charlie, "unrated", 5 * 10**18)
    assert contract.get_rejection(addr_str(direct_charlie)) == ""

    # --- issue_policy: reject, then succeed --------------------------------
    issue_rejected(direct_vm, contract, direct_charlie, "job-x", "ghost",
                   coverage, SPEC, DEADLINE, prem, "unknown agent")
    assert contract.get_rejection(addr_str(direct_charlie), "job-x") != ""

    issue_policy(direct_vm, contract, direct_charlie, "job-x", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_rejection(addr_str(direct_charlie), "job-x") == ""

    # --- file_claim: reject, then succeed (auto-breach path) ---------------
    accept(direct_vm, contract, direct_bob, "job-x")
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND - 1
    contract.file_claim("job-x")  # wrong bond -> rejected + refunded
    assert "claim bond must be exactly" in contract.get_rejection(
        addr_str(direct_charlie), "job-x"
    )

    direct_vm.warp(AFTER_DEADLINE)  # no deliverable -> deterministic auto-breach
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-x")
    assert contract.get_rejection(addr_str(direct_charlie), "job-x") == ""
    assert contract.get_claim_status("job-x") == "upheld"


def test_reputation_uninflatable_without_agent_consent(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """Review item 7: before FIX-21 a THIRD PARTY could inflate an unwilling
    agent's jobs_insured / distinct_buyers -- and therefore its tier -- just by
    issuing policies, and those counts stayed inflated forever when the agent
    rejected or the policy expired. Reputation now credits only on the agent's
    own accept_job."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")

    # Three policies from two distinct buyers, none accepted by the agent.
    for i, buyer in enumerate((direct_charlie, direct_owner, direct_charlie)):
        issue_policy(direct_vm, contract, buyer, f"job-{i}", "agent-a",
                     coverage, SPEC, DEADLINE, prem)

    profile = contract.get_profile("agent-a")
    assert profile["jobs_insured"] == 0
    assert profile["distinct_buyers"] == 0
    assert profile["tier"] == "unrated"

    # Only the job the agent actually accepts counts.
    accept(direct_vm, contract, direct_bob, "job-0")
    assert contract.get_profile("agent-a")["jobs_insured"] == 1

    # Void the other two the two ways available: agent reject, buyer cancel.
    direct_vm.sender = direct_bob
    contract.reject_job("job-1")
    direct_vm.sender = direct_charlie
    contract.cancel_pending_policy("job-2")
    assert contract.get_policy("job-1")["status"] == "expired"
    assert contract.get_policy("job-2")["status"] == "expired"

    # The rejected and cancelled policies contributed nothing.
    profile = contract.get_profile("agent-a")
    assert profile["jobs_insured"] == 1
    assert profile["distinct_buyers"] == 1
    assert profile["tier"] == "unrated"


def test_voided_policies_never_inflate_reputation(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """Review item 7, expiry path: a PENDING policy that times out without ever
    being accepted must leave no reputation trace -- neither jobs_insured nor
    distinct_buyers -- so the counts a tier gate reads are always a record of
    jobs the agent actually bound itself to."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_owner, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    # Past deadline + claim window: anyone may void the unaccepted policies.
    direct_vm.warp(PAST_WINDOW)
    direct_vm.sender = direct_owner
    contract.expire_pending_policy("job-1")
    contract.expire_pending_policy("job-2")

    profile = contract.get_profile("agent-a")
    assert profile["jobs_insured"] == 0
    assert profile["distinct_buyers"] == 0
    assert profile["tier"] == "unrated"
    # Exposure fully released and premiums returned to their buyers.
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    assert contract.get_pool_info("unrated")["balance_atto"] == 50 * 10**18


def test_non_text_evidence_refused_at_submit(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 8: binary evidence must be REFUSED explicitly, never
    silently decoded with a lossy error handler and judged as truncated UTF-8.
    The agent's own submit transaction is where that refusal belongs."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    binary = b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01\x80\x81"
    # A hash-matching but non-UTF-8 body: the sha256 commits to these exact
    # bytes, so the failure is "not text", not "wrong bytes".
    binary_evidence = evidence("deliverable.bin", binary)
    mock_evidence(direct_vm, binary_evidence)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("not valid UTF-8 text"):
        contract.submit_deliverable("job-1", *binary_evidence)
    # Refused here, on the agent's own transaction -- not judged as text later.
    assert contract.get_policy("job-1")["deliverable_url"] == ""


def test_tampered_deliverable_at_judge_is_breach(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 8, custody split under FIX-22: the submit commits the sha256
    of the exact bytes, so a host that later serves something else (repinned,
    tampered upstream, or a re-pointed URL) is caught by the digest rather than
    judged as if it were the deliverable. That is the AGENT's evidence failing
    -- a breach, not a claim rejection. FIX-22 also makes the judge-side
    non_text branch unreachable in practice (the bytes are pinned), but it is
    kept as defence in depth."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    # The URL now serves bytes that no longer hash to the committed sha256.
    direct_vm.clear_mocks()
    mock_evidence(direct_vm, SPEC)
    direct_vm.mock_web(re.escape(DELIV_OK[0]),
                       {"status": 200, "body": b"swapped after submission"})

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    contract.judge_claim("job-1")

    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_profile("agent-a")["claims_upheld_against"] == 1
    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    assert info["balance_atto"] == 20 * 10**18 + prem


def test_evidence_integrity_mismatch_is_refused_not_judged(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 8 (the core of it): a gateway serving HTTP 200 does NOT mean
    the bytes are the evidence. Every fetch is hashed and compared against the
    sha256 committed on-chain. At submit a mismatch is refused; at judge
    time a mismatched DELIVERABLE is the agent's breach and a mismatched SPEC
    fails the buyer's own claim -- so neither party can substitute content
    behind a sha256 already committed on-chain."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # --- submit-side: 200 OK but the body does not hash to the committed sha256 ----------
    mock_evidence(direct_vm, DELIV_OK, body=b"totally different bytes")
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("bytes do not match the sha256 committed"):
        contract.submit_deliverable("job-1", *DELIV_OK)
    assert contract.get_policy("job-1")["deliverable_url"] == ""

    # --- judge-side: deliverable matched at submit, tampered by judge time --
    # (mock_web keeps the FIRST registration for a URL, so clear before
    # re-registering the same URL with its correct bytes.)
    direct_vm.clear_mocks()
    mock_evidence(direct_vm, DELIV_OK)  # correct bytes now
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)

    direct_vm.clear_mocks()
    mock_evidence(direct_vm, SPEC)
    direct_vm.mock_web(re.escape(DELIV_OK[0]),
                       {"status": 200, "body": b"tampered after submission"})

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    contract.judge_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_profile("agent-a")["claims_upheld_against"] == 1
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + prem


def test_evidence_integrity_mismatch_on_buyer_spec_rejects_claim(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 8, the buyer's half of the custody split: a SPEC whose bytes
    no longer hash to the sha256 committed at issue is the BUYER's own evidence
    failing, so the claim is rejected -- never a manufactured breach against an
    agent whose deliverable resolved and verified cleanly."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-s", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-s")

    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-s", *DELIV_OK)

    direct_vm.clear_mocks()
    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.mock_web(re.escape(SPEC[0]), {"status": 200, "body": b"swapped spec"})
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-s")
    contract.judge_claim("job-s")

    assert contract.get_claim_status("job-s") == "rejected"
    assert contract.get_profile("agent-a")["claims_upheld_against"] == 0
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0


def test_validator_rejects_divergent_leader(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 12: the non-deterministic evidence probe must be CONSENSUS
    checked, not leader-trusted. The validator independently re-fetches and
    compares the evidence STATE (never the payload) -- so it agrees with an
    honest leader, and disagrees the moment the leader's claimed state differs
    from what the validator can re-derive, and whenever the leader errored."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.clear_validators()
    mock_evidence(direct_vm, DELIV_OK)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_OK)  # captures the probe validator

    # Honest leader -> the validator re-derives the same state and agrees.
    assert direct_vm.run_validator(leader_result={"state": "ok"}) is True

    # Leader claims "ok" but the bytes the validator can fetch have changed
    # underneath it -> disagree (forces rotation instead of accepting a lie).
    direct_vm.clear_mocks()
    mock_evidence(direct_vm, DELIV_OK, body=b"swapped after the leader looked")
    assert direct_vm.run_validator(leader_result={"state": "ok"}) is False

    # A leader that ERRORED is never agreed with.
    assert direct_vm.run_validator(leader_error=RuntimeError("leader died")) is False


def test_full_paid_lifecycle_quote_to_payout(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Review item 5: the complete production lifecycle in one test --
    quote -> issue -> agent acceptance -> deliverable submission -> claim
    filing -> judge_claim -> final policy / verdict / payout state -- ending in
    a real EthSend payout to the buyer and a pool balance that reconciles
    exactly with the premium in and the coverage out."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 2 * 10**18  # exactly the 10%-of-20-GEN single-policy cap

    # 1. Quote: the premium is contract-derived, not client-guessed.
    quote = contract.quote_premium("agent-a", coverage)
    assert quote["tier"] == "unrated"
    assert quote["rate_bps"] == 600
    prem = quote["premium_atto"]
    assert prem == premium_for(coverage, "unrated")

    # 2. Issue (payable) -> pending, exposure locked.
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_policy("job-1")["status"] == "pending"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == coverage

    # 3. Agent acceptance -> active, reputation credited.
    accept(direct_vm, contract, direct_bob, "job-1")
    assert contract.get_policy("job-1")["status"] == "active"
    profile = contract.get_profile("agent-a")
    assert profile["jobs_insured"] == 1
    assert profile["distinct_buyers"] == 1

    # 4. Deliverable submission (commit-pinned URL probed + digest-verified live).
    mock_evidence(direct_vm, DELIV_BAD)
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", *DELIV_BAD)
    assert contract.get_policy("job-1")["deliverable_url"] == DELIV_BAD[0]

    # 5. Claim filed -- deterministic phase escrows the bond.
    mock_evidence(direct_vm, SPEC)
    mock_judgement(direct_vm, 5)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "pending"
    assert contract.get_accounting("unrated")["pending_claim_bonds_atto"] == CLAIM_BOND

    # 6. Verdict -- consensus adjudication settles the claim.
    contract.judge_claim("job-1")

    # 7. Final state: verdict, policy, reputation, payout, reconciliation.
    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_policy("job-1")["status"] == "claimed"
    assert contract.get_policy("job-1")["agent_accepted"] is True

    profile = contract.get_profile("agent-a")
    assert profile["claims_filed_against"] == 1
    assert profile["claims_upheld_against"] == 1

    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    # pool = seed + premium: the coverage payout came out of the agent's
    # forfeited bond, and the claim bond was refunded to the buyer (never to the
    # pool), so neither is a term in the pool balance (FIX-22).
    assert info["balance_atto"] == 20 * 10**18 + prem

    acc = contract.get_accounting("unrated")
    assert acc["pending_claim_bonds_atto"] == 0
    assert acc["agent_bond_escrow_atto"] == 0
    assert acc["attributed_atto"] == acc["tier_balance_atto"]

    traces = list(direct_vm._traces)
    assert any("EthSend" in t for t in traces), (
        f"payout did not use the external EthSend rail -- {traces}"
    )
    assert not any("PostMessage" in t for t in traces)


# ---------------------------------------------------------------------------
# FIX-22: agent bond + throughput caps (the self-dealing closure)
# ---------------------------------------------------------------------------

def test_accept_requires_agent_bond(direct_vm, direct_deploy, direct_alice,
                                    direct_bob, direct_charlie):
    """accept_job is payable and the agent must post at least the coverage.
    FIX-21: an underpayment is rejected-and-refunded, never reverted -- a revert
    would retain the attached value with no ledger entry."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    # Under-funded: rejected, the attached value refunded, policy still pending.
    direct_vm.sender = direct_bob
    direct_vm.value = coverage - 1
    contract.accept_job("job-1")
    reason = contract.get_rejection(addr_str(direct_bob), "job-1")
    assert "agent bond must be at least" in reason
    assert f"refunded {coverage - 1} atto" in reason
    assert contract.get_policy("job-1")["status"] == "pending"
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0

    # Over-funded: accepted, exactly the coverage escrowed, the excess refunded.
    direct_vm.sender = direct_bob
    direct_vm.value = coverage + 12345
    contract.accept_job("job-1")
    assert contract.get_policy("job-1")["status"] == "active"
    assert int(contract.get_policy("job-1")["agent_bond_atto"]) == coverage
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == coverage


def test_self_dealing_round_is_value_destroying(direct_vm, direct_deploy,
                                                direct_alice, direct_bob,
                                                direct_charlie):
    """The exploit FIX-22 exists for. One controller runs BOTH sides: it issues a
    policy to its own agent, never delivers, files the deterministic auto-breach
    and collects the FULL coverage.

    Before the bond the pool paid that coverage and the claim bond came straight
    back, so the round netted +0.94 x coverage with no rate limit anywhere -- the
    pool drained geometrically. Now the payout is drawn from the agent's own
    forfeited bond: the pool ends EXACTLY whole (seed + premium, LP capital never
    touched). Collusion is still possible, but it is now value-DESTROYING rather
    than profitable, which is the honest guarantee -- not that it is impossible."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    seed = 20 * 10**18
    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    # direct_charlie (buyer) and direct_bob (owner of agent-a) are the same
    # attacker in the real exploit; the contract cannot tell, and need not.
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # deterministic no-deliverable auto-breach
    assert contract.get_claim_status("job-1") == "upheld"

    info = contract.get_pool_info("unrated")
    acc = contract.get_accounting("unrated")
    # 1. The pool is made whole: it keeps the premium and NOT ONE ATTO of LP
    #    capital funds the payout, because the coverage came out of the bond.
    assert info["balance_atto"] == seed + prem
    assert info["locked_exposure_atto"] == 0
    # 2. The bond left escrow entirely -- the attacker cannot get it back.
    assert acc["agent_bond_escrow_atto"] == 0
    # 3. Nothing is left attributed-but-unpooled: the round is fully settled.
    assert acc["attributed_atto"] == acc["tier_balance_atto"]
    # The attacker's own ledger, for the record: -premium (paid at issue),
    # -coverage (bond posted), +coverage (payout), +CLAIM_BOND (refund) =
    # -premium. Repeating the round now loses money every time.


def test_agent_bond_refunded_on_expiry(direct_vm, direct_deploy, direct_alice,
                                       direct_bob, direct_charlie):
    """An ACTIVE policy that lapses -- deadline and claim window both passed with
    no claim -- releases the agent's bond back to the agent. An honest agent must
    never lose collateral for a job nobody claimed."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == coverage

    direct_vm.warp(PAST_WINDOW)
    direct_vm.sender = direct_charlie  # the buyer lapses its own policy
    contract.expire_policy("job-1")

    assert contract.get_policy("job-1")["status"] == "expired"
    assert contract.get_accounting("unrated")["agent_bond_escrow_atto"] == 0
    # The premium stays with the pool; the bond is a ledger move, not a pool move.
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + prem


def test_buyer_open_policy_cap(direct_vm, direct_deploy, direct_alice,
                               direct_bob, direct_charlie):
    """FIX-22b: a buyer may hold at most MAX_OPEN_POLICIES_PER_BUYER open
    policies. Neither the per-policy coverage cap nor the aggregate utilization
    cap ever bounded the NUMBER of rounds -- which is what the drain needed."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 40 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    for i in range(10):
        issue_policy(direct_vm, contract, direct_charlie, f"job-{i}", "agent-a",
                     coverage, SPEC, DEADLINE, prem)

    issue_rejected(direct_vm, contract, direct_charlie, "job-over", "agent-a",
                   coverage, SPEC, DEADLINE, prem, "max 10")


def test_agent_open_policy_cap(direct_vm, direct_deploy, direct_alice,
                               direct_bob, direct_charlie, direct_owner):
    """FIX-22b: an agent may ACCEPT at most MAX_OPEN_POLICIES_PER_AGENT open
    policies. The counter moves only on the agent's own consent, so a third party
    cannot fill an unwilling agent's slots -- and a would-be drainer needs a
    fresh agent identity per 10 rounds, which is the throughput bound that makes
    the (now loss-making) round rate-limited too."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 40 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    for i in range(10):
        issue_policy(direct_vm, contract, direct_charlie, f"job-{i}", "agent-a",
                     coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_owner, "job-extra", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    for i in range(10):
        accept(direct_vm, contract, direct_bob, f"job-{i}")

    # The 11th acceptance is refused -- and, being payable, refunded in-call.
    direct_vm.sender = direct_bob
    direct_vm.value = coverage
    contract.accept_job("job-extra")
    reason = contract.get_rejection(addr_str(direct_bob), "job-extra")
    assert "max 10" in reason
    assert f"refunded {coverage} atto" in reason
    assert contract.get_policy("job-extra")["status"] == "pending"


def test_deadline_ceiling_rejected(direct_vm, direct_deploy, direct_alice,
                                   direct_bob, direct_charlie):
    """FIX-22c: a deadline has a ceiling as well as a floor. Without one a buyer
    locks up to the 50% utilization cap of a tier for ~0.06% of the pool in
    premium, capping every LP's exit and consuming issuance capacity forever."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    # 2026-01-01 + 94 days = past the 90-day horizon.
    issue_rejected(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                   coverage, SPEC, "2026-04-05T00:00:00Z",
                   premium_for(coverage, "unrated"), "90 days in the future")


def test_penalty_tier_sticks_without_funded_pool(direct_vm, direct_deploy,
                                                 direct_alice, direct_bob,
                                                 direct_charlie, direct_owner):
    """FIX-22d: a demotion must not silently become a promotion. With NO LP
    capital in the penalty pool, a chronic breacher now STAYS in penalty --
    issue_policy's pool_value > 0 gate then refuses them outright -- instead of
    falling through to TIER_UNRATED at exactly the newcomer rate the demotion
    exists to beat."""
    contract = direct_deploy("intelligent-contracts/proofmark.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    for jid, buyer in (("job-1", direct_charlie), ("job-2", direct_owner)):
        issue_policy(direct_vm, contract, buyer, jid, "agent-a",
                     coverage, SPEC, DEADLINE, prem)
        accept(direct_vm, contract, direct_bob, jid)

    direct_vm.warp(AFTER_DEADLINE)
    for jid, buyer in (("job-1", direct_charlie), ("job-2", direct_owner)):
        direct_vm.sender = buyer
        direct_vm.value = CLAIM_BOND
        contract.file_claim(jid)
        assert contract.get_claim_status(jid) == "upheld"

    # The penalty pool was never funded, yet the demotion sticks.
    assert contract.get_pool_info("penalty")["balance_atto"] == 0
    assert contract.get_profile("agent-a")["tier"] == "penalty"
    assert contract.quote_premium("agent-a", coverage)["tier"] == "penalty"
