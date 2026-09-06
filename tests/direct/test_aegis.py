"""Direct-mode (in-memory, leader-only) tests for intelligent-contracts/aegis.py.

Covers every public method plus the gaming/security vectors the contract
documents it defends against. Claim judgement is mocked: web fetches (spec /
deliverable from the IPFS gateway) and the LLM score are stubbed, so the
deterministic gate + payout logic are exercised without real consensus.

Fixture roles used throughout:
  direct_alice  -- LP (underwrites a tier)
  direct_bob    -- the insured agent
  direct_charlie-- the main buyer
  direct_owner  -- a second buyer / extra account

Run:  python -m pytest tests/direct/test_aegis.py -v
"""

import json

# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------

CLAIM_BOND = 2 * 10**18
MIN_COVERAGE = 10**16

# Content-addressed CIDs (valid CIDv0 shape: 46 chars, base58, starts "Qm").
SPEC = "Qm" + "a" * 44
DELIV_OK = "Qm" + "b" * 44
DELIV_BAD = "Qm" + "c" * 44
# A mutable URL -- must be rejected by _canonical_content_hash (FIX-01).
MUTABLE_URL = "https://gist.github.com/someone/edit"
# A CID wrapped in whitespace/newlines -- canonicalization must strip (FIX-01 v2).
WHITESPACE_CID = "   " + DELIV_OK + "\n"
# A syntactically-valid CIDv1 that exceeds MAX_CID_LEN (FIX-01 v3).
LONG_CID = "b" + "y" * 80

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
    direct_vm.sender = buyer
    direct_vm.value = premium_atto
    contract.issue_policy(job_id, agent_id, coverage_atto, spec, deadline)


def accept(direct_vm, contract, agent_acct, job_id):
    """FIX-02: the insured agent must accept a pending policy before any
    submit / claim / expire can happen."""
    direct_vm.sender = agent_acct
    contract.accept_job(job_id)


def issue_active(direct_vm, contract, buyer, agent_acct, job_id, agent_id,
                 coverage_atto, spec, deadline, premium_atto):
    """Issue a policy AND have the agent accept it, so the test can act on an
    active policy (submit / claim / expire) in one line."""
    issue_policy(direct_vm, contract, buyer, job_id, agent_id, coverage_atto,
                 spec, deadline, premium_atto)
    accept(direct_vm, contract, agent_acct, job_id)


def mock_cid(direct_vm, cid, body="untrusted spec/deliverable bytes"):
    """Register a 200 mock for one evidence CID (probe at submit + judge fetch
    at claim both hit the gateway)."""
    direct_vm.mock_web(r".*" + cid + r".*", {"status": 200, "body": body})


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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
    register(direct_vm, contract, direct_bob, "agent-a")

    with direct_vm.expect_revert("already registered"):
        register(direct_vm, contract, direct_charlie, "agent-a")

    with direct_vm.expect_revert("address already bound"):
        register(direct_vm, contract, direct_bob, "agent-b")


def test_register_case_variant_is_same_identity(
    direct_vm, direct_deploy, direct_bob
):
    """Case-variant squatting must be closed: 'Agent-A' == 'agent-a'."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    register(direct_vm, contract, direct_bob, "Agent-A")
    with direct_vm.expect_revert("already registered"):
        register(direct_vm, contract, direct_bob, "agent-a")


def test_register_empty_id_rejected(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    with direct_vm.expect_revert("cannot be empty"):
        register(direct_vm, contract, direct_bob, "   ")


# ---------------------------------------------------------------------------
# LP pools
# ---------------------------------------------------------------------------

def test_deposit_bootstrap_and_proportional_shares(
    direct_vm, direct_deploy, direct_alice, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
    with direct_vm.expect_revert("unknown tier"):
        deposit(direct_vm, contract, direct_alice, "platinum", 5 * 10**18)

    direct_vm.sender = direct_alice
    direct_vm.value = 0
    with direct_vm.expect_revert("deposit must be > 0"):
        contract.deposit("unrated")


def test_withdraw_blocks_under_locked_exposure(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """LP cannot pull capital out from under live coverage."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    """Empty-pool first-depositor exploit must be closed: no capital, no policy."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    direct_vm.warp(T0)  # so DEADLINE reads as future; the pool check is the target
    fund_accounts(direct_vm, direct_bob, direct_charlie)
    register(direct_vm, contract, direct_bob, "agent-a")

    direct_vm.sender = direct_charlie
    direct_vm.value = premium_for(10**18, "unrated")
    with direct_vm.expect_revert("no underwriting capital"):
        contract.issue_policy("job-1", "agent-a", 10**18, SPEC, DEADLINE)


def test_issue_policy_rejects_url_and_min_coverage(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    # spec_hash must be a CID, not a mutable URL.
    with direct_vm.expect_revert("must be a content-addressed"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                     10**18, MUTABLE_URL, DEADLINE, premium_for(10**18, "unrated"))

    # Coverage below MIN_COVERAGE_ATTO.
    with direct_vm.expect_revert("at least"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                     MIN_COVERAGE - 1, SPEC, DEADLINE, 1)


def test_issue_policy_premium_min_and_overpay_refunded(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """FIX-14: exact-premium enforcement was a front-runnable race (a concurrent
    issue could flip the agent's tier between quote and payment and revert the
    buyer for one atto). issue_policy now accepts value >= premium, crediting
    exactly the premium and refunding the excess."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    exact = premium_for(coverage, "unrated")

    # Underpaying still reverts.
    with direct_vm.expect_revert("premium must be at least"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                     coverage, SPEC, DEADLINE, exact - 1)

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
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    with direct_vm.expect_revert("seconds in the future"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                     10**18, SPEC, PAST_DEADLINE, premium_for(10**18, "unrated"))

    # 30 s out is real (past) but under the 60 s floor -> rejected too.
    with direct_vm.expect_revert("seconds in the future"):
        issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                     10**18, SPEC, "2026-01-01T00:00:30Z", premium_for(10**18, "unrated"))

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
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_bob)

    with direct_vm.expect_revert("cannot insure the agent's own job"):
        issue_policy(direct_vm, contract, direct_bob, "job-1", "agent-a",
                     10**18, SPEC, DEADLINE, premium_for(10**18, "unrated"))


def test_issue_policy_coverage_capped_to_single_claim_share(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """MAX_COVERAGE_BPS_OF_POOL: one policy's coverage is capped to what one
    claim can ever pay (10% of the tier pool), so no buyer holds a policy
    labeled more than a single claim could collect."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    # 20% of the 20 GEN pool is above the 10% cap -> rejected.
    with direct_vm.expect_revert("single-claim pool cap"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                     4 * 10**18, SPEC, DEADLINE, premium_for(4 * 10**18, "unrated"))

    # Exactly 10% (2 GEN) is allowed.
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 2 * 10**18, SPEC, DEADLINE, premium_for(2 * 10**18, "unrated"))
    accept(direct_vm, contract, direct_bob, "job-2")
    assert contract.get_policy("job-2")["status"] == "active"


def test_issue_policy_locks_exposure_and_counts_buyer_once(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Same buyer across multiple jobs counts as ONE distinct buyer, and
    exposure locks pool capital behind live coverage."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    p = contract.get_profile("agent-a")
    assert p["jobs_insured"] == 2
    assert p["distinct_buyers"] == 1  # same address counted once
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 2 * coverage


def test_policy_idempotency_and_unknown_agent(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    with direct_vm.expect_revert("unknown agent_id"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "ghost",
                     10**18, SPEC, DEADLINE, premium_for(10**18, "unrated"))

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    with direct_vm.expect_revert("already exists"):
        issue_policy(direct_vm, contract, direct_charlie, "Job-1", "agent-a",
                     coverage, SPEC, DEADLINE, prem)  # case variant = same key


# ---------------------------------------------------------------------------
# Deliverable submission
# ---------------------------------------------------------------------------

def test_submit_deliverable_access_and_shape(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Only the insured agent may submit.
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert("only the insured agent"):
        contract.submit_deliverable("job-1", DELIV_OK)

    # Must be a CID, not a URL (rejected before any probe).
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("must be a content-addressed"):
        contract.submit_deliverable("job-1", MUTABLE_URL)

    # Agent submits, and can overwrite before the claim is judged. Each submit
    # live-probes the CID (FIX-01), so both CIDs must resolve before submit.
    mock_cid(direct_vm, DELIV_BAD, "a genuinely bad deliverable")
    mock_cid(direct_vm, DELIV_OK, "the real deliverable")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", DELIV_BAD)
    contract.submit_deliverable("job-1", DELIV_OK)
    assert contract.get_policy("job-1")["deliverable_hash"] == DELIV_OK


def test_submit_deliverable_unknown_job(direct_vm, direct_deploy, direct_bob):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    register(direct_vm, contract, direct_bob, "agent-a")
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("unknown job_id"):
        contract.submit_deliverable("job-nope", DELIV_OK)


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

def test_claim_premature_without_deliverable(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Before the deadline and no deliverable -> premature.
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("deadline has not passed"):
        contract.file_claim("job-1")


def test_claim_auto_breach_when_no_deliverable_after_deadline(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Agent never submitted anything + deadline passed = deterministic breach,
    full payout up to the pool cap, bond refunded, exposure released."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
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

    # Payout = full coverage (20e18 pool, 10% cap = 2e18 >= 1e18 coverage).
    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 20 * 10**18 + prem - coverage


def test_claim_judged_upheld(direct_vm, direct_deploy, direct_alice, direct_bob,
                             direct_charlie):
    """Judged path: agent submitted a deliverable that DOES NOT meet spec ->
    LLM score below threshold -> breach upheld, payout + bond refund."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # submit_deliverable live-probes the CID (FIX-01): mock it before submit.
    mock_cid(direct_vm, DELIV_BAD, "It's a static cat picture.")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", DELIV_BAD)

    # Mock the spec fetch + the LLM judgement (Shape B output schema).
    mock_cid(direct_vm, SPEC, "Build a React dashboard with 5 pages.")
    mock_judgement(direct_vm, 5)  # score below threshold -> breach

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")

    assert contract.get_claim_status("job-1") == "upheld"
    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    assert info["balance_atto"] == 20 * 10**18 + prem - coverage


def test_claim_judged_rejected_bond_forfeited(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """Deliverable conforms -> score high -> rejected; buyer's bond goes to
    the pool (compensates LPs for consensus), exposure released."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_cid(direct_vm, DELIV_OK, "React dashboard with 5 pages delivered.")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", DELIV_OK)

    mock_cid(direct_vm, SPEC, "Build a React dashboard with 5 pages.")
    mock_judgement(direct_vm, 95)  # score above threshold -> conforms

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")

    assert contract.get_claim_status("job-1") == "rejected"
    info = contract.get_pool_info("unrated")
    assert info["locked_exposure_atto"] == 0
    # Premium stays, bond added to pool, coverage not paid out.
    assert info["balance_atto"] == 20 * 10**18 + prem + CLAIM_BOND


def test_claim_gate_access_and_bond(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadline
    # Wrong bond.
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND - 1
    with direct_vm.expect_revert("claim bond must be exactly"):
        contract.file_claim("job-1")

    # Not the buyer.
    direct_vm.sender = direct_owner
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("only the policy buyer"):
        contract.file_claim("job-1")

    # Legit claim then double-claim is blocked.
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("already resolved"):
        contract.file_claim("job-1")


def test_claim_payout_capped_at_10pct_pool(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    """MAX_PAYOUT_BPS_OF_POOL: a single claim can pay at most 10% of the tier
    pool at claim time. Coverage is now itself capped to 10% of the pool at
    issue, so the payout cap binds when an earlier payout has already shrunk
    the pool below the coverage amount: two 2 GEN policies on a 20 GEN pool --
    the first pays its full 2 GEN, the second finds the pool at 18.24 GEN and
    can only pay 1.824 GEN."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    cov = 2 * 10**18  # exactly 10% of the 20 GEN pool -- allowed at issue
    prem = premium_for(cov, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 cov, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 cov, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")
    accept(direct_vm, contract, direct_bob, "job-2")

    direct_vm.warp("2026-03-02T00:00:00Z")  # after deadlines, no deliverable

    # Claim 1 pays its full 2 GEN: pool 20.24 GEN -> 18.24 GEN.
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "upheld"

    # Claim 2's cap = 10% of the now-shrunken 18.24 GEN pool = 1.824 GEN,
    # so the payout binds below the 2 GEN coverage.
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-2")
    assert contract.get_claim_status("job-2") == "upheld"

    info = contract.get_pool_info("unrated")
    assert info["balance_atto"] == 16416000000000000000  # 18.24 - 1.824 GEN
    assert info["locked_exposure_atto"] == 0  # both exposures released


# ---------------------------------------------------------------------------
# Reputation / tier
# ---------------------------------------------------------------------------

def test_tier_promotion_bronze_requires_real_buyers_and_tenure(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """Bronze: >=3 insured jobs, >=2 distinct buyers, >=3 days tenure.
    FIX-08: promotion only sticks when the earned tier is actually funded, so
    the test backs 'bronze' with real LP capital too."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    deposit(direct_vm, contract, direct_alice, "bronze", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")

    # Buyer 1 buys 2 jobs at T0.
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_profile("agent-a")["tier"] == "unrated"

    # Same address buying a 3rd job must NOT push to bronze (needs 2 distinct).
    issue_policy(direct_vm, contract, direct_charlie, "job-3", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_profile("agent-a")["tier"] == "unrated"

    # Distinct buyer 2, but still within tenure window (2 days < 3).
    direct_vm.warp("2026-01-03T00:00:00Z")
    issue_policy(direct_vm, contract, direct_owner, "job-4", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_profile("agent-a")["tier"] == "unrated"

    # After >=3 days tenure, the next action promotes.
    direct_vm.warp(T_PLUS_4)
    issue_policy(direct_vm, contract, direct_owner, "job-5", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_profile("agent-a")["tier"] == "bronze"
    assert contract.get_profile("agent-a")["distinct_buyers"] == 2


def test_tier_pricing_changes_after_promotion(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, direct_owner
):
    """After promotion the premium is priced off the new tier's rate."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    fund_accounts(direct_vm, direct_alice, direct_bob, direct_charlie, direct_owner)
    direct_vm.warp(T0)
    deposit(direct_vm, contract, direct_alice, "unrated", 50 * 10**18)
    deposit(direct_vm, contract, direct_alice, "bronze", 50 * 10**18)
    register(direct_vm, contract, direct_bob, "agent-a")

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_charlie, "job-2", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    issue_policy(direct_vm, contract, direct_owner, "job-3", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    direct_vm.warp(T_PLUS_4)
    issue_policy(direct_vm, contract, direct_owner, "job-4", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    assert contract.get_profile("agent-a")["tier"] == "bronze"

    quote = contract.quote_premium("agent-a", coverage)
    assert quote["tier"] == "bronze"
    assert quote["rate_bps"] == 400

    # A new policy on a bronze agent is priced off the bronze rate. Paying less
    # (gold's 150 bps) reverts; the bronze premium is accepted (FIX-14).
    with direct_vm.expect_revert("premium must be at least"):
        issue_policy(direct_vm, contract, direct_charlie, "job-5", "agent-a",
                     coverage, SPEC, DEADLINE, premium_for(coverage, "gold"))
    issue_policy(direct_vm, contract, direct_charlie, "job-5", "agent-a",
                 coverage, SPEC, DEADLINE, premium_for(coverage, "bronze"))
    assert contract.get_policy("job-5")["status"] == "pending"


# ---------------------------------------------------------------------------
# Claim against an agent drags their reputation down
# ---------------------------------------------------------------------------

def test_claim_history_updates_profile(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    contract = direct_deploy("intelligent-contracts/aegis.py")
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

def test_unresolvable_cid_submit_reverts(direct_vm, direct_deploy, direct_alice,
                                         direct_bob, direct_charlie):
    """C-1 veto: a deliverable CID that does not resolve must fail on the
    AGENT's submit transaction (live probe, FIX-01) -- never brick the buyer's
    later claim with an unjudgeable CID."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Deterministic 404 for an unpinned CID.
    direct_vm.mock_web(r".*" + DELIV_BAD + r".*",
                       {"status": 404, "body": ""})
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("not retrievable"):
        contract.submit_deliverable("job-1", DELIV_BAD)
    # The policy is left untouched -- the buyer can still claim the no-breach
    # path or a later good submission.
    assert contract.get_policy("job-1")["deliverable_hash"] == ""


def test_post_probe_unpin_is_breach_not_revert(direct_vm, direct_deploy,
                                               direct_alice, direct_bob,
                                               direct_charlie):
    """C-1 veto: a CID that was retrievable at submit but 404s at claim time
    is adjudicated as a BREACH (score 0), not an unjudgeable revert -- so an
    agent cannot unpin after the fact to neutralise a pending claim."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    # Submit passes the probe (CID resolves at submit time).
    mock_cid(direct_vm, DELIV_OK, "deliverable that gets unpinned later")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", DELIV_OK)

    # Between submit and claim the content is unpinned -> now 404 at judge.
    direct_vm.clear_mocks()
    mock_cid(direct_vm, SPEC, "spec for a real job")
    direct_vm.mock_web(r".*" + DELIV_OK + r".*", {"status": 404, "body": ""})

    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    contract.file_claim("job-1")  # must NOT revert

    assert contract.get_claim_status("job-1") == "upheld"
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 0
    # Breach paid out: pool lost the coverage amount.
    assert contract.get_pool_info("unrated")["balance_atto"] == 20 * 10**18 + prem - coverage


def test_deliverable_frozen_after_deadline(direct_vm, direct_deploy,
                                           direct_alice, direct_bob,
                                           direct_charlie):
    """C-1: evidence is frozen at the deadline -- the agent cannot swap in an
    unretrievable CID once a claim looks likely (FIX-01 Step 3)."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp(AFTER_DEADLINE)  # 1 day past the deadline
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("deadline passed -- deliverable is frozen"):
        contract.submit_deliverable("job-1", DELIV_OK)


def test_whitespace_cid_is_canonicalized(direct_vm, direct_deploy,
                                         direct_alice, direct_bob,
                                         direct_charlie):
    """C-1 variant 2: the fix CANONICALIZES rather than rejecting, so a CID
    padded with whitespace/newlines is stored stripped -- validating .strip()
    while storing the raw argument would have corrupted the gateway URL."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_cid(direct_vm, DELIV_OK, "canonical deliverable")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", WHITESPACE_CID)  # "   Qm...\n"
    assert contract.get_policy("job-1")["deliverable_hash"] == DELIV_OK


def test_oversized_cid_rejected(direct_vm, direct_deploy, direct_alice,
                                direct_bob, direct_charlie):
    """C-1 variant 3: an unbounded CIDv1 that would 414 the gateway is rejected
    by the MAX_CID_LEN cap before any fetch."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("CID too long"):
        contract.submit_deliverable("job-1", LONG_CID)


def test_unaccepted_policy_cannot_submit_or_claim(direct_vm, direct_deploy,
                                                  direct_alice, direct_bob,
                                                  direct_charlie):
    """C-2 consent: a PENDING policy (issued but not yet accepted by the agent)
    carries no submit or claim rights -- a stranger cannot bind an agent and
    then let the deadline auto-breach."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    assert contract.get_policy("job-1")["status"] == "pending"

    # Agent cannot submit against a policy it has not accepted.
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("policy not active"):
        contract.submit_deliverable("job-1", DELIV_OK)

    # Buyer cannot claim against an unaccepted policy either.
    direct_vm.warp(AFTER_DEADLINE)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("policy not active"):
        contract.file_claim("job-1")

    accept(direct_vm, contract, direct_bob, "job-1")
    assert contract.get_policy("job-1")["status"] == "active"


def test_reject_job_releases_and_refunds(direct_vm, direct_deploy, direct_alice,
                                         direct_bob, direct_charlie):
    """C-2: an agent rejecting a pending policy releases its locked exposure
    and refunds the buyer's premium (no grief-lock, no value lost)."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    cov = 2 * 10**18  # exactly the 10%-of-20-GEN single-policy cap
    prem = premium_for(cov, "unrated")
    for i in range(5):
        issue_policy(direct_vm, contract, direct_charlie, f"job-{i}", "agent-a",
                     cov, SPEC, DEADLINE, prem)
    assert contract.get_pool_info("unrated")["locked_exposure_atto"] == 5 * cov

    # A 6th policy would push exposure past the 50% utilization cap.
    with direct_vm.expect_revert("at capacity"):
        issue_policy(direct_vm, contract, direct_charlie, "job-overflow", "agent-a",
                     cov, SPEC, DEADLINE, prem)


def test_bronze_requires_breach_rate(direct_vm, direct_deploy, direct_alice,
                                     direct_bob, direct_charlie, direct_owner):
    """FIX-07: bronze is gated on an actual breach-rate record, not monotonic
    counts. An agent meeting the job/buyer/tenure thresholds but carrying a
    1-in-3 breach rate stays unrated -- it must NOT be promoted to bronze."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
        mock_cid(direct_vm, DELIV_OK, f"{jid} conforms")
        direct_vm.sender = direct_bob
        contract.submit_deliverable(jid, DELIV_OK)
        mock_cid(direct_vm, SPEC, "spec for " + jid)
        mock_judgement(direct_vm, 95)
        direct_vm.sender = buyer
        direct_vm.value = CLAIM_BOND
        contract.file_claim(jid)
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
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
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    direct_vm.warp(PAST_WINDOW)
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("claim window has closed"):
        contract.file_claim("job-1")


def test_out_of_range_score_rejected(direct_vm, direct_deploy, direct_alice,
                                     direct_bob, direct_charlie):
    """FIX-06: an out-of-range LLM score reverts the claim instead of being
    silently clamped -- clamping would destroy the divergence signal the
    validator comparison depends on."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_cid(direct_vm, DELIV_BAD, "some deliverable")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", DELIV_BAD)

    mock_cid(direct_vm, SPEC, "some spec")
    mock_judgement(direct_vm, 250)  # adversarial echo, not a real grade
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("score out of range"):
        contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "unresolved"


def test_zero_share_deposit_rejected(direct_vm, direct_deploy, direct_alice,
                                     direct_bob, direct_charlie):
    """FIX-11: a deposit too small to mint any LP shares reverts instead of
    silently burning the depositor's value."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    # Inflate pool balance above total shares by issuing (premium is credited
    # to the pool with no matching share mint), so 1 atto mints 0 shares.
    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)

    direct_vm.sender = direct_charlie
    direct_vm.value = 1  # 1 atto
    with direct_vm.expect_revert("deposit too small"):
        contract.deposit("unrated")


def test_invalid_calendar_date_rejected(direct_vm, direct_deploy, direct_alice,
                                        direct_bob, direct_charlie):
    """FIX-15c: an impossible calendar date (2026-02-30) must not silently roll
    over in epoch math -- it is rejected at issuance."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    with direct_vm.expect_revert("must be an ISO-8601"):
        issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                     10**18, SPEC, "2026-02-30T00:00:00Z",
                     premium_for(10**18, "unrated"))


def test_rate_limit_maps_to_transient(direct_vm, direct_deploy, direct_alice,
                                      direct_bob, direct_charlie):
    """FIX-13: a per-validator 429 on the evidence gateway routes to a
    transient error (revert + consensus rotation) -- never to a permanent
    verdict, and never with status codes embedded in the [EXTERNAL] message."""
    contract = direct_deploy("intelligent-contracts/aegis.py")
    setUpPoolAndAgent(direct_vm, contract, direct_alice, direct_bob, direct_charlie)

    coverage = 10**18
    prem = premium_for(coverage, "unrated")
    issue_policy(direct_vm, contract, direct_charlie, "job-1", "agent-a",
                 coverage, SPEC, DEADLINE, prem)
    accept(direct_vm, contract, direct_bob, "job-1")

    mock_cid(direct_vm, DELIV_OK, "deliverable")
    direct_vm.sender = direct_bob
    contract.submit_deliverable("job-1", DELIV_OK)

    # Gateway rate-limits the claim-time fetch of the spec.
    direct_vm.mock_web(r".*" + SPEC + r".*", {"status": 429, "body": ""})
    direct_vm.sender = direct_charlie
    direct_vm.value = CLAIM_BOND
    with direct_vm.expect_revert("rate-limited"):
        contract.file_claim("job-1")
    assert contract.get_claim_status("job-1") == "unresolved"
