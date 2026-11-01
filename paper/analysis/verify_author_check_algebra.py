"""Finite-algebra regression checks for author review items.

This script uses abstract group exponents over small prime fields.  It checks
algebraic identities and integer bounds only; it is neither a formal proof nor
an implementation-level cryptographic verification.

Usage:
    python3 analysis/verify_author_check_algebra.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_PATH: Final = ROOT / "analysis" / "out" / "author_check_algebra.json"
TOY_Q: Final = 11
TOY_H_LOG: Final = 7
BN254_SCALAR_ORDER: Final = (
    21888242871839275222246405745257275088548364400416034343698204186575808495617
)


def inv(value: int, modulus: int) -> int:
    """Return a nonzero field element's inverse."""
    reduced = value % modulus
    if reduced == 0:
        raise ValueError("zero has no multiplicative inverse")
    return pow(reduced, -1, modulus)


def commitment_exponent(message: int, blinding: int, q: int = TOY_Q) -> int:
    """Represent g^message h^blinding by its abstract base-g exponent."""
    return (message + TOY_H_LOG * blinding) % q


@dataclass(frozen=True)
class RelationWitness:
    anchor_message: int
    anchor_blinding: int
    base_message: int
    base_blinding: int
    product_blinding: int


@dataclass(frozen=True)
class FirstMessages:
    alpha: int
    beta: int


@dataclass(frozen=True)
class Responses:
    message: int
    blinding: int
    product_correction: int


@dataclass(frozen=True)
class RelationTranscript:
    anchor_commitment: int
    base_commitment: int
    product_commitment: int
    first: FirstMessages
    responses: Responses
    challenge: int


def first_messages(
    witness: RelationWitness,
    mask_message: int,
    mask_blinding: int,
    mask_product: int,
    q: int = TOY_Q,
) -> FirstMessages:
    base_commitment = commitment_exponent(
        witness.base_message, witness.base_blinding, q
    )
    return FirstMessages(
        alpha=commitment_exponent(mask_message, mask_blinding, q),
        beta=(base_commitment * mask_message + TOY_H_LOG * mask_product) % q,
    )


def responses(
    witness: RelationWitness,
    masks: tuple[int, int, int],
    challenge: int,
    q: int = TOY_Q,
) -> Responses:
    mask_message, mask_blinding, mask_product = masks
    correction = (
        witness.product_blinding
        - witness.base_blinding * witness.anchor_message
    ) % q
    return Responses(
        message=(mask_message + challenge * witness.anchor_message) % q,
        blinding=(mask_blinding + challenge * witness.anchor_blinding) % q,
        product_correction=(mask_product + challenge * correction) % q,
    )


def make_transcript(
    witness: RelationWitness,
    masks: tuple[int, int, int],
    challenge: int,
    q: int = TOY_Q,
) -> RelationTranscript:
    first = first_messages(witness, *masks, q=q)
    return RelationTranscript(
        anchor_commitment=commitment_exponent(
            witness.anchor_message, witness.anchor_blinding, q
        ),
        base_commitment=commitment_exponent(
            witness.base_message, witness.base_blinding, q
        ),
        product_commitment=commitment_exponent(
            witness.anchor_message * witness.base_message,
            witness.product_blinding,
            q,
        ),
        first=first,
        responses=responses(witness, masks, challenge, q),
        challenge=challenge % q,
    )


def verify_transcript(transcript: RelationTranscript, q: int = TOY_Q) -> bool:
    """Check the two Sigma equations in abstract exponent notation."""
    lhs_opening = (
        transcript.responses.message
        + TOY_H_LOG * transcript.responses.blinding
    ) % q
    rhs_opening = (
        transcript.first.alpha
        + transcript.challenge * transcript.anchor_commitment
    ) % q
    lhs_product = (
        transcript.base_commitment * transcript.responses.message
        + TOY_H_LOG * transcript.responses.product_correction
    ) % q
    rhs_product = (
        transcript.first.beta
        + transcript.challenge * transcript.product_commitment
    ) % q
    return lhs_opening == rhs_opening and lhs_product == rhs_product


def extract_fork(
    left: RelationTranscript,
    right: RelationTranscript,
    q: int = TOY_Q,
) -> tuple[int, int, int]:
    """Extract anchor message, anchor blinding, and product correction."""
    if left.first != right.first:
        raise ValueError("forks must share the same first messages")
    delta_challenge = (left.challenge - right.challenge) % q
    inverse_delta = inv(delta_challenge, q)
    return (
        (left.responses.message - right.responses.message) * inverse_delta % q,
        (left.responses.blinding - right.responses.blinding) * inverse_delta % q,
        (
            left.responses.product_correction
            - right.responses.product_correction
        )
        * inverse_delta
        % q,
    )


def fork_extraction_regression() -> dict[str, object]:
    cases = 0
    transcripts_verified = 0
    product_openings_verified = 0
    cross_relation_anchor_checks = 0

    for enrollment in range(TOY_Q):
        for probe in range(TOY_Q):
            for variant in range(TOY_Q):
                enrollment_blinding = (2 * variant + enrollment + 1) % TOY_Q
                probe_blinding = (3 * variant + probe + 2) % TOY_Q
                product_blindings = {
                    "ee": (5 * variant + enrollment + 3) % TOY_Q,
                    "pp": (7 * variant + probe + 4) % TOY_Q,
                    "ep": (variant + enrollment + probe + 5) % TOY_Q,
                }
                relation_witnesses = {
                    "ee": RelationWitness(
                        enrollment,
                        enrollment_blinding,
                        enrollment,
                        enrollment_blinding,
                        product_blindings["ee"],
                    ),
                    "pp": RelationWitness(
                        probe,
                        probe_blinding,
                        probe,
                        probe_blinding,
                        product_blindings["pp"],
                    ),
                    "ep": RelationWitness(
                        probe,
                        probe_blinding,
                        enrollment,
                        enrollment_blinding,
                        product_blindings["ep"],
                    ),
                }
                challenge_left = (variant + 1) % TOY_Q
                challenge_right = (variant + 4) % TOY_Q
                extracted: dict[str, tuple[int, int, int]] = {}

                for label_index, (label, witness) in enumerate(
                    relation_witnesses.items()
                ):
                    masks = (
                        (variant + 2 * label_index + 1) % TOY_Q,
                        (enrollment + 3 * label_index + 2) % TOY_Q,
                        (probe + 5 * label_index + 3) % TOY_Q,
                    )
                    left = make_transcript(
                        witness, masks, challenge_left, TOY_Q
                    )
                    right = make_transcript(
                        witness, masks, challenge_right, TOY_Q
                    )
                    assert verify_transcript(left, TOY_Q)
                    assert verify_transcript(right, TOY_Q)
                    transcripts_verified += 2

                    anchor_message, anchor_blinding, correction = extract_fork(
                        left, right, TOY_Q
                    )
                    assert anchor_message == witness.anchor_message
                    assert anchor_blinding == witness.anchor_blinding
                    assert left.anchor_commitment == commitment_exponent(
                        anchor_message, anchor_blinding, TOY_Q
                    )
                    reconstructed_product = commitment_exponent(
                        anchor_message * witness.base_message,
                        witness.base_blinding * anchor_message + correction,
                        TOY_Q,
                    )
                    assert reconstructed_product == left.product_commitment
                    product_openings_verified += 1
                    extracted[label] = (
                        anchor_message,
                        anchor_blinding,
                        correction,
                    )

                assert extracted["ee"][:2] == (
                    enrollment,
                    enrollment_blinding,
                )
                assert extracted["pp"][:2] == extracted["ep"][:2]
                assert extracted["pp"][:2] == (probe, probe_blinding)
                cross_relation_anchor_checks += 2
                cases += 1

    return {
        "field_order": TOY_Q,
        "cases": cases,
        "relation_labels": ["ee", "pp", "ep"],
        "shared_challenge_pairs_per_case": 1,
        "transcripts_verified": transcripts_verified,
        "product_openings_verified": product_openings_verified,
        "cross_relation_anchor_checks": cross_relation_anchor_checks,
        "passed": True,
    }


def joint_uniformity_regression() -> dict[str, object]:
    inverse_two = inv(2, TOY_Q)
    triple_counts: dict[tuple[int, int, int], int] = {}
    target_to_last_bijections = 0
    reconstruction_checks = 0

    for commitment_ee in range(TOY_Q):
        for commitment_pp in range(TOY_Q):
            last_values: set[int] = set()
            for target_distance in range(TOY_Q):
                commitment_ep = (
                    (commitment_ee + commitment_pp - target_distance)
                    * inverse_two
                ) % TOY_Q
                reconstructed_distance = (
                    commitment_ee + commitment_pp - 2 * commitment_ep
                ) % TOY_Q
                assert reconstructed_distance == target_distance
                reconstruction_checks += 1
                last_values.add(commitment_ep)
                triple = (commitment_ee, commitment_pp, commitment_ep)
                triple_counts[triple] = triple_counts.get(triple, 0) + 1
            assert last_values == set(range(TOY_Q))
            target_to_last_bijections += 1

    assert len(triple_counts) == TOY_Q**3
    assert set(triple_counts.values()) == {1}
    return {
        "field_order": TOY_Q,
        "enumerated_input_tuples": TOY_Q**3,
        "distinct_product_triples": len(triple_counts),
        "multiplicity_per_product_triple": 1,
        "target_to_last_bijections": target_to_last_bijections,
        "reconstruction_checks": reconstruction_checks,
        "derived_distance_is_deterministic_from_product_triple": True,
        "derived_distance_treated_as_independent": False,
        "passed": True,
    }


def zero_challenge_negative_control() -> dict[str, object]:
    witness = RelationWitness(
        anchor_message=3,
        anchor_blinding=4,
        base_message=5,
        base_blinding=6,
        product_blinding=8,
    )
    honest = make_transcript(witness, (2, 7, 9), challenge=0, q=TOY_Q)
    assert verify_transcript(honest, TOY_Q)
    modified = RelationTranscript(
        anchor_commitment=honest.anchor_commitment,
        base_commitment=honest.base_commitment,
        product_commitment=honest.product_commitment,
        first=honest.first,
        responses=Responses(
            message=(honest.responses.message + 1) % TOY_Q,
            blinding=honest.responses.blinding,
            product_correction=honest.responses.product_correction,
        ),
        challenge=0,
    )
    assert not verify_transcript(modified, TOY_Q)

    zero_inverse_rejected = False
    try:
        inv(0, TOY_Q)
    except ValueError:
        zero_inverse_rejected = True
    assert zero_inverse_rejected
    return {
        "field_order": TOY_Q,
        "honest_zero_challenge_transcript_verified": True,
        "deliberately_modified_response_rejected": True,
        "zero_challenge_inverse_rejected": True,
        "passed": True,
    }


def bn254_integer_bounds() -> dict[str, object]:
    coordinate_bits = 16
    coordinates_per_block = 15
    packed_bits = coordinate_bits * coordinates_per_block
    max_packed_block = (1 << packed_bits) - 1
    dimension = 512
    max_coordinate = (1 << coordinate_bits) - 1
    max_distance = dimension * max_coordinate * max_coordinate

    assert packed_bits == 240
    assert max_packed_block < BN254_SCALAR_ORDER
    assert max_distance < (1 << 48)
    return {
        "bn254_scalar_order": str(BN254_SCALAR_ORDER),
        "bn254_scalar_order_bits": BN254_SCALAR_ORDER.bit_length(),
        "coordinate_bits": coordinate_bits,
        "coordinates_per_block": coordinates_per_block,
        "packed_bits": packed_bits,
        "max_packed_block": str(max_packed_block),
        "max_packed_block_below_scalar_order": True,
        "dimension": dimension,
        "max_coordinate": max_coordinate,
        "max_squared_distance": max_distance,
        "two_to_48": 1 << 48,
        "max_squared_distance_below_two_to_48": True,
        "passed": True,
    }


def main() -> None:
    results = {
        "script": "analysis/verify_author_check_algebra.py",
        "script_version": 1,
        "scope": (
            "Deterministic finite-algebra regression for selected author checks; "
            "not a formal proof or actual cryptographic implementation verification."
        ),
        "checks": {
            "shared_ee_pp_ep_fork_extraction": fork_extraction_regression(),
            "n1_product_triple_joint_uniformity": joint_uniformity_regression(),
            "zero_challenge_negative_control": zero_challenge_negative_control(),
            "bn254_packing_and_distance_bounds": bn254_integer_bounds(),
        },
        "verification_counts": {
            "top_level_checks": 4,
            "top_level_checks_passed": 4,
        },
        "limitations": [
            "The toy group stores abstract exponents and does not model elliptic-curve encodings, pairings, or discrete-log hardness.",
            "The small-field enumerations are algebra regressions, not asymptotic or machine-checked proofs.",
            "The checks do not implement Groth16, Poseidon, Fiat--Shamir, a random oracle, Circom, or Solidity.",
            "The q=11 joint-uniformity check treats the reconstructed distance as a deterministic function of the product triple, not as an independent variable.",
            "The BN254 checks verify integer inequalities only and do not compile or audit the circuit.",
        ],
        "passed": True,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS: 4 finite-algebra checks; "
        f"wrote {OUTPUT_PATH.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
