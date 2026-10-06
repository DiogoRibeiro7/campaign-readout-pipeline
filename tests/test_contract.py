"""The contract: what it accepts, what it refuses, and how it is identified."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from conftest import CONTRACT_PATH, ROOT, with_updates
from readout.contract import Assignment, Bootstrap, Contract, Covariates, Windows, load_contract


def test_both_shipped_contracts_load():
    v1 = load_contract(CONTRACT_PATH)
    v2 = load_contract(ROOT / "contracts" / "campaign_readout_v2.toml")
    assert (v1.version, v2.version) == (1, 2)
    assert v1.sha256 != v2.sha256
    # Version 2 differs from version 1 in the length of the history and in nothing else.
    assert v2.model_copy(update={"version": 1, "windows": v1.windows}) == v1


def test_the_shipped_contract_follows_the_prototypes_protocol(real_contract, prototype):
    assert (real_contract.windows.outcome_days, real_contract.windows.history_days) == (
        prototype.WINDOW,
        prototype.HISTORY,
    )
    assert real_contract.tolerances.min_treated == prototype.MIN_TREATED
    assert real_contract.bootstrap.replications == prototype.REPS
    assert real_contract.method.name == "weighting"  # the estimator the prototype named as primary
    assert real_contract.covariates.concurrent_campaigns == "through_outcome_window"
    assert not real_contract.assignment.documented


def test_hash_follows_the_content_and_nothing_else(real_contract):
    again = Contract.model_validate(real_contract.model_dump())
    assert again.sha256 == real_contract.sha256
    looser = with_updates(real_contract, tolerances={"placebo_usd": 6.0})
    assert looser.sha256 != real_contract.sha256
    assert real_contract.tag.startswith("campaign_readout@v1:")


def test_contract_is_immutable(real_contract):
    with pytest.raises(ValidationError):
        real_contract.tolerances.placebo_usd = 100.0


def test_unknown_keys_are_rejected(real_contract):
    raw = real_contract.model_dump()
    raw["tolerances"]["bias"] = 1.0
    with pytest.raises(ValidationError):
        Contract.model_validate(raw)


def test_history_must_be_whole_windows():
    with pytest.raises(ValidationError):
        Windows(outcome_days=28, history_days=60)


def test_the_rule_for_other_campaigns_is_a_declared_choice(real_contract):
    raw = real_contract.model_dump()
    raw["covariates"]["concurrent_campaigns"] = "at_launch"
    assert Contract.model_validate(raw).sha256 != real_contract.sha256
    raw["covariates"]["concurrent_campaigns"] = "whenever"
    with pytest.raises(ValidationError):
        Contract.model_validate(raw)


def test_a_documented_rule_names_its_inputs():
    with pytest.raises(ValidationError):
        Assignment(documented=True)
    assert Assignment(documented=True, inputs=("spend",)).documented


def test_a_documented_rule_must_be_adjusted_for(real_contract):
    raw = real_contract.model_dump()
    raw["assignment"] = {"documented": True, "inputs": ["spend"], "note": ""}
    assert Contract.model_validate(raw).assignment.documented
    raw["covariates"]["groups"] = ["behaviour", "history"]
    with pytest.raises(ValidationError, match="does not hold"):
        Contract.model_validate(raw)


def test_dropped_groups():
    assert Covariates().dropped == ()
    assert Covariates(groups=("behaviour",)).dropped == ("spend", "history")
    with pytest.raises(ValidationError):
        Covariates(groups=())


def test_an_interval_needs_at_least_two_replications():
    with pytest.raises(ValidationError):
        Bootstrap(replications=1, seed=0)


def test_shadow_methods_do_not_repeat_the_primary(real_contract):
    names = [method.name for method in real_contract.methods]
    assert names[0] == real_contract.method.name
    assert len(names) == len(set(names))
