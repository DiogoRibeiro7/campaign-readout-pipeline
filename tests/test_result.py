"""A refusal is not an estimate with a flag on it: it has no estimate."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from readout.result import PROGRAMME_RESULT, RESULT, ProgrammeRefused, Published, Refused, json_schemas


def _mean_effect(results) -> float:
    """What a careless consumer would write."""
    return sum(result.effect.estimate for result in results) / len(results)


def test_a_refusal_has_nowhere_to_put_an_effect(replayed):
    results = replayed.readouts()
    refused = [result for result in results if isinstance(result, Refused)]
    assert refused
    assert "effect" not in Refused.model_fields and "effect" not in ProgrammeRefused.model_fields
    with pytest.raises(AttributeError):
        _mean_effect(results)
    for result in refused:
        assert result.reasons and all(not reason.passed and reason.code for reason in result.reasons)
        assert all(reason in result.gates for reason in result.reasons)


def test_a_refusal_cannot_be_given_an_effect(replayed):
    record = RESULT.dump_python(next(r for r in replayed.readouts() if isinstance(r, Refused)), mode="json")
    record["effect"] = {"estimate": 12.0, "low": 1.0, "high": 23.0, "se": 5.0}
    with pytest.raises(ValidationError):
        RESULT.validate_python(record)


def test_a_refusal_says_what_each_gate_measured(replayed):
    """What a refusal does carry: the placebos it failed on, so that the reason can be checked."""
    refused = next(r for r in replayed.readouts() if any(g.gate == "assignment" for g in r.gates))
    gate = next(g for g in refused.gates if g.gate == "assignment")
    assert {"placebo", "placebo_low", "placebo_high", "record", "state", "documented"} <= set(gate.measurements)
    assert gate.thresholds["placebo_usd"] == 5.0


def test_results_round_trip_through_json(replayed, replayed_lenient):
    for result in [*replayed.readouts(), *replayed_lenient.readouts()]:
        again = RESULT.validate_json(json.dumps(RESULT.dump_python(result, mode="json"), allow_nan=False))
        assert again == result


def test_results_are_immutable(replayed):
    result = replayed.readouts()[0]
    with pytest.raises(ValidationError):
        result.method = "regression"


def test_the_kind_decides_the_type():
    schemas = json_schemas()
    assert set(schemas) == {"readout", "programme"}
    assert set(schemas["readout"]["discriminator"]["mapping"]) == {"published", "refused"}
    required = schemas["readout"]["$defs"]["Published"]["required"]
    for field in (
        "effect",
        "prehistory_placebo",
        "shifted_placebo",
        "prehistory_evidence",
        "assignment_evidence",
        "gates",
        "provenance",
    ):
        assert field in required
    assert "effect" not in schemas["readout"]["$defs"]["Refused"]["properties"]
    assert set(PROGRAMME_RESULT.json_schema()["discriminator"]["mapping"]) == {
        "programme_published",
        "programme_refused",
    }


def test_a_published_result_names_its_evidence_and_its_origin(replayed_lenient, plain_snapshot, lenient):
    """With a tolerance nothing can exceed, every readout that reaches the placebo gates is published."""
    results = replayed_lenient.readouts()
    published = [result for result in results if isinstance(result, Published)]
    assert len(published) == len(results) == 6
    for result in published:
        assert all(gate.passed for gate in result.gates)
        assert [gate.gate for gate in result.gates] == ["data", "timing", "overlap", "prehistory_placebo", "assignment"]
        assert result.prehistory_evidence == "own_placebo" and result.assignment_evidence == "own_placebo"
        assert result.provenance.contract_sha256 == lenient.sha256
        assert result.provenance.snapshot_id == plain_snapshot.snapshot_id
        assert result.provenance.view_id == f"{plain_snapshot.snapshot_id}@{result.as_of}"
        assert result.effect.low <= result.effect.estimate <= result.effect.high
        assert result.households_treated + result.households_compared <= plain_snapshot.manifest["households"]
