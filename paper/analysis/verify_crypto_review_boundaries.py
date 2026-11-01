"""Regression checks for cryptographic-review boundary cases.

This script checks finite algebraic and combinatorial claims used to delimit the
paper's arguments.  It is not a security proof, a cryptographic implementation,
or a performance experiment.

Usage:
    python3 -I analysis/verify_crypto_review_boundaries.py
"""

from __future__ import annotations

import itertools
import json
import math
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "analysis" / "out" / "crypto_review_boundaries.json"
BN254_SCALAR_FIELD = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)


def fraction_text(value: Fraction) -> str:
    """Return a stable exact representation of a rational number."""

    return f"{value.numerator}/{value.denominator}"


def decimal_text(value: Fraction, digits: int = 50) -> str:
    """Return a deterministic decimal rendering without losing the exact value."""

    with localcontext() as context:
        context.prec = digits
        return str(Decimal(value.numerator) / Decimal(value.denominator))


def subsets(size: int, count: int) -> tuple[frozenset[int], ...]:
    """Enumerate all count-element subsets of range(size)."""

    return tuple(frozenset(items) for items in itertools.combinations(range(size), count))


def theoretical_miss_probability(size: int, samples: int, bad: int) -> Fraction:
    """Compute C(size-bad, samples) / C(size, samples), with empty cases handled."""

    numerator = math.comb(size - bad, samples) if samples <= size - bad else 0
    return Fraction(numerator, math.comb(size, samples))


def enumerate_subset_boundaries(max_size: int = 6) -> dict[str, object]:
    """Exhaustively compare subset counts with the hypergeometric expression."""

    parameter_cases = 0
    bad_set_instances = 0
    full_sample_instances = 0
    for size in range(1, max_size + 1):
        for samples in range(size + 1):
            sample_sets = subsets(size, samples)
            for bad in range(size + 1):
                parameter_cases += 1
                expected = theoretical_miss_probability(size, samples, bad)
                for bad_set in subsets(size, bad):
                    bad_set_instances += 1
                    misses = sum(sample_set.isdisjoint(bad_set) for sample_set in sample_sets)
                    observed = Fraction(misses, len(sample_sets))
                    assert observed == expected
                    if samples == size and bad > 0:
                        full_sample_instances += 1
                        assert observed == 0

    example = theoretical_miss_probability(size=4, samples=2, bad=1)
    return {
        "sizes_enumerated": [1, max_size],
        "parameter_cases_checked": parameter_cases,
        "bad_set_instances_checked": bad_set_instances,
        "all_exact_hypergeometric_checks_passed": True,
        "full_sample_positive_bad_set_instances_checked": full_sample_instances,
        "full_sample_miss_probability_is_zero": True,
        "example_N4_t2_w1": fraction_text(example),
    }


def adaptive_bad_set(
    size: int,
    bad: int,
    history: tuple[frozenset[int], ...],
) -> frozenset[int]:
    """Choose W from prior samples only, never from the current fresh sample."""

    offset = len(history)
    for index, previous_sample in enumerate(history, start=1):
        offset += index * sum(previous_sample)
    start = offset % size
    return frozenset((start + step) % size for step in range(bad))


def adaptive_history_probability(
    size: int,
    samples: int,
    bad: int,
    attempts: int,
) -> dict[str, object]:
    """Enumerate adaptive histories and verify the constant conditional miss rate."""

    sample_space = subsets(size, samples)
    expected_single = theoretical_miss_probability(size, samples, bad)
    conditional_probabilities: list[Fraction] = []
    failure_frontier: tuple[tuple[frozenset[int], ...], ...] = ((),)

    for _ in range(attempts):
        next_failure_frontier: list[tuple[frozenset[int], ...]] = []
        for history in failure_frontier:
            bad_set = adaptive_bad_set(size, bad, history)
            success_count = sum(current.isdisjoint(bad_set) for current in sample_space)
            conditional = Fraction(success_count, len(sample_space))
            conditional_probabilities.append(conditional)
            assert conditional == expected_single
            next_failure_frontier.extend(
                history + (current,)
                for current in sample_space
                if not current.isdisjoint(bad_set)
            )
        failure_frontier = tuple(next_failure_frontier)

    total_paths = len(sample_space) ** attempts
    no_success_paths = len(failure_frontier)
    enumerated_success = Fraction(total_paths - no_success_paths, total_paths)
    expected_success = 1 - (1 - expected_single) ** attempts
    assert enumerated_success == expected_success

    return {
        "attempts": attempts,
        "adaptive_policy_uses_only_prior_sample_history": True,
        "conditional_history_nodes_checked": len(conditional_probabilities),
        "all_conditional_miss_probabilities_equal_single_attempt_value": True,
        "single_attempt_miss_probability": fraction_text(expected_single),
        "at_least_one_miss_enumerated": fraction_text(enumerated_success),
        "at_least_one_miss_formula": fraction_text(expected_success),
    }


def fs_input_without_responses() -> dict[str, object]:
    """Show structurally that response-only edits leave the specified FS input unchanged."""

    statement_and_first_messages = {
        "context": "BioZero/hom/v1",
        "identity": 7,
        "nonce": 11,
        "commitments": {
            "ce": [[1, 2]],
            "cp": [[3, 4]],
            "cee": [[5, 6]],
            "cpp": [[7, 8]],
            "cep": [[9, 10]],
        },
        "first_messages": {
            "alpha": [[12, 13], [14, 15], [16, 17]],
            "beta": [[18, 19], [20, 21], [22, 23]],
        },
    }
    responses_before = [24, 25, 26]
    responses_after = list(responses_before)
    responses_after[1] += 1

    encoded_before = json.dumps(
        statement_and_first_messages,
        sort_keys=True,
        separators=(",", ":"),
    )
    encoded_after = json.dumps(
        statement_and_first_messages,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert responses_before != responses_after
    assert encoded_before == encoded_after

    return {
        "responses_changed": True,
        "specified_fiat_shamir_input_unchanged": True,
        "cryptographic_hash_simulated": False,
        "scope": (
            "This is a structural check of the specified input fields. It does not show "
            "that commitment-changing distance attacks avoid the challenge/sample cycle."
        ),
    }


def modulo_distribution(modulus: int) -> dict[str, object]:
    """Compute the exact distributional bias of a 256-bit word reduced modulo modulus."""

    domain_size = 1 << 256
    quotient, remainder = divmod(domain_size, modulus)
    high_probability = Fraction(quotient + 1, domain_size)
    low_probability = Fraction(quotient, domain_size)
    uniform_probability = Fraction(1, modulus)
    total_variation = Fraction(1, 2) * (
        remainder * abs(high_probability - uniform_probability)
        + (modulus - remainder) * abs(low_probability - uniform_probability)
    )
    maximum_relative_to_uniform = high_probability / uniform_probability

    assert quotient == 5
    assert total_variation > Fraction(3, 100)
    assert maximum_relative_to_uniform > 1

    return {
        "source_domain_size": str(domain_size),
        "modulus": str(modulus),
        "quotient": quotient,
        "remainder": str(remainder),
        "residues_with_quotient_plus_one_preimages": str(remainder),
        "residues_with_quotient_preimages": str(modulus - remainder),
        "maximum_point_probability_exact": fraction_text(high_probability),
        "maximum_point_probability_decimal": decimal_text(high_probability),
        "uniform_point_probability_exact": fraction_text(uniform_probability),
        "uniform_point_probability_decimal": decimal_text(uniform_probability),
        "maximum_point_probability_relative_to_uniform_exact": fraction_text(
            maximum_relative_to_uniform
        ),
        "maximum_point_probability_relative_to_uniform_decimal": decimal_text(
            maximum_relative_to_uniform
        ),
        "total_variation_distance_exact": fraction_text(total_variation),
        "total_variation_distance_decimal": decimal_text(total_variation),
        "total_variation_exceeds_three_percent": True,
        "interpretation": (
            "Simple reduction of one uniform 256-bit word modulo the BN254 scalar field "
            "is measurably non-uniform at this fixed instantiation. This calculation alone "
            "does not constitute a cryptographic break."
        ),
    }


def bn254_zero_modular_distance_example() -> dict[str, object]:
    """Construct an out-of-range BN254 vector with squared distance zero modulo q."""

    modulus = BN254_SCALAR_FIELD
    assert modulus % 4 == 1

    nonresidue = 2
    while pow(nonresidue, (modulus - 1) // 2, modulus) != modulus - 1:
        nonresidue += 1

    sqrt_minus_one = pow(nonresidue, (modulus - 1) // 4, modulus)
    assert pow(sqrt_minus_one, 2, modulus) == modulus - 1

    difference = (1, sqrt_minus_one)
    enrollment = (0, 0)
    probe = tuple((-coordinate) % modulus for coordinate in difference)
    integer_representative_distance = sum(
        (left - right) ** 2 for left, right in zip(enrollment, probe)
    )
    modular_distance = integer_representative_distance % modulus
    coordinate_limit = 1 << 16

    assert probe[0] == modulus - 1
    assert probe[0] >= coordinate_limit
    assert any(coordinate >= coordinate_limit for coordinate in probe)
    assert modular_distance == 0

    return {
        "q": str(modulus),
        "q_mod_4": modulus % 4,
        "smallest_quadratic_nonresidue_found": nonresidue,
        "sqrt_minus_one": str(sqrt_minus_one),
        "sqrt_minus_one_squared_mod_q": str(pow(sqrt_minus_one, 2, modulus)),
        "difference_vector": [str(coordinate) for coordinate in difference],
        "enrollment_vector": list(enrollment),
        "probe_vector": [str(coordinate) for coordinate in probe],
        "probe_first_coordinate_is_q_minus_one": True,
        "all_coordinates_are_16_bit": False,
        "integer_representative_distance": str(integer_representative_distance),
        "squared_distance_mod_q": modular_distance,
        "conclusion": (
            "For N=2 over the BN254 scalar field, an out-of-range probe can have "
            "zero modular squared distance from the zero enrollment vector."
        ),
    }


def finite_fresh_grinding(
    size: int,
    samples: int,
    bad: int,
    trial_counts: Iterable[int],
) -> dict[str, object]:
    """Evaluate 1-(1-P)^K for finitely many independently refreshed first messages."""

    single = theoretical_miss_probability(size, samples, bad)
    probabilities: dict[str, dict[str, str | int]] = {}
    previous = Fraction(-1, 1)
    for trials in trial_counts:
        success = 1 - (1 - single) ** trials
        assert success > previous
        previous = success
        probabilities[str(trials)] = {
            "trials": trials,
            "success_probability_exact": fraction_text(success),
            "success_probability_decimal": decimal_text(success),
        }

    return {
        "N": size,
        "t": samples,
        "w": bad,
        "single_trial_miss_probability_exact": fraction_text(single),
        "single_trial_miss_probability_decimal": decimal_text(single),
        "finite_trials": probabilities,
        "scope": (
            "The formula assumes each refreshed first-message trial induces an independent "
            "ideal sample. It is finite grinding, not a claim of certain success."
        ),
    }


def build_results() -> dict[str, object]:
    """Build and assert all requested regression results."""

    q = 11
    enrollment = 0
    probe = 10
    threshold = 1
    integer_distance = (enrollment - probe) ** 2
    modular_distance = integer_distance % q
    assert integer_distance > threshold
    assert modular_distance <= threshold

    return {
        "metadata": {
            "purpose": "Finite regression checks for cryptographic-review boundary cases.",
            "is_security_proof": False,
            "is_performance_experiment": False,
            "uses_network_or_external_data": False,
        },
        "integer_far_modular_near_counterexample": {
            "q": q,
            "N": 1,
            "enrollment": enrollment,
            "probe": probe,
            "threshold": threshold,
            "integer_distance": integer_distance,
            "modular_distance": modular_distance,
            "integer_distance_exceeds_threshold": True,
            "modular_distance_is_within_threshold": True,
            "conclusion": (
                "An integer-far premise alone does not imply failure of a modular-distance relation."
            ),
        },
        "bn254_out_of_range_zero_modular_distance": bn254_zero_modular_distance_example(),
        "uniform_subset_enumeration": enumerate_subset_boundaries(),
        "conditional_history_enumeration": {
            "N": 4,
            "t": 2,
            "w": 1,
            "two_attempts": adaptive_history_probability(4, 2, 1, 2),
            "three_attempts": adaptive_history_probability(4, 2, 1, 3),
        },
        "response_only_fiat_shamir_boundary": fs_input_without_responses(),
        "bn254_256_bit_modulo_distribution": modulo_distribution(BN254_SCALAR_FIELD),
        "finite_fresh_first_message_grinding": finite_fresh_grinding(
            size=128,
            samples=56,
            bad=1,
            trial_counts=(1, 2, 5, 10),
        ),
    }


def main() -> None:
    """Write deterministic results after all assertions pass."""

    results = build_results()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"PASS: wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
