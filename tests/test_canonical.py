from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from llm_research_os.canonical import (
    JCS_SHA256_PREFIX,
    LEGACY_SHA256_PREFIX,
    ContentDigest,
    canonical_json,
    content_digest,
    legacy_canonical_json,
    legacy_content_digest,
)

CORPUS_PATH = Path(__file__).resolve().parents[1] / "conformance" / "digest" / "rfc8785-v1.json"
CONTENT_DIGEST = TypeAdapter(ContentDigest)

RFC8785_APPENDIX_B: tuple[tuple[str, str], ...] = (
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
)

LEGACY_GOLDEN_VECTORS: tuple[tuple[Any, str, str], ...] = (
    (
        {},
        "{}",
        "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    ),
    (
        {"z": 1, "a": [True, None, "é"]},
        '{"a":[true,null,"é"],"z":1}',
        "sha256:9622d8e9f6fcc94dd1013e9af622df506351bf2009314dda0ab155ff2bb338ab",
    ),
    (
        {"negativeZero": -0.0, "small": 1e-7, "unicode": "研究"},
        '{"negativeZero":-0.0,"small":1e-07,"unicode":"研究"}',
        "sha256:d2697a905ffb90e76883b377b63aea47bff5992fc72118b3cda53a6de932d8ae",
    ),
)


def _load_corpus() -> dict[str, Any]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def _float_from_bits(ieee754_hex: str) -> float:
    return struct.unpack(">d", bytes.fromhex(ieee754_hex))[0]


def test_committed_corpus_matches_python_jcs() -> None:
    corpus = _load_corpus()
    assert corpus["algorithm"] == "jcs-sha256"
    assert corpus["prefix"] == JCS_SHA256_PREFIX
    vectors = corpus["vectors"]
    assert isinstance(vectors, list)
    assert len(vectors) >= 8
    for vector in vectors:
        assert canonical_json(vector["input"]) == vector["canonicalUtf8"]
        assert content_digest(vector["input"]) == vector["digest"]
        assert vector["digest"].startswith(JCS_SHA256_PREFIX)
        assert not vector["digest"].startswith(LEGACY_SHA256_PREFIX)


def test_rfc8785_primitive_example() -> None:
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27],
        "string": '€$\u000f\nA\'B"\\\\"/',
        "literals": [None, True, False],
    }
    encoded = (
        '{"literals":[null,true,false],'
        '"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )
    assert canonical_json(value) == encoded


@pytest.mark.parametrize(("ieee754_hex", "encoded"), RFC8785_APPENDIX_B)
def test_rfc8785_appendix_b_bit_patterns(ieee754_hex: str, encoded: str) -> None:
    assert canonical_json(_float_from_bits(ieee754_hex)) == encoded


def test_number_boundary_renderings() -> None:
    assert canonical_json(-0.0) == "0"
    assert canonical_json(0.0) == "0"
    assert canonical_json(1e-6) == "0.000001"
    assert canonical_json(1e-7) == "1e-7"
    assert canonical_json(1e20) == "100000000000000000000"
    assert canonical_json(1e21) == "1e+21"


def test_utf16_key_order_matches_rfc8785() -> None:
    value = {
        "\u20ac": "Euro Sign",
        "\r": "Carriage Return",
        "\ufb33": "Hebrew Letter Dalet With Dagesh",
        "1": "One",
        "\U0001f600": "Emoji: Grinning Face",
        "\u0080": "Control",
        "\u00f6": "Latin Small Letter O With Diaeresis",
    }
    assert list(json.loads(canonical_json(value))) == [
        "\r",
        "1",
        "\u0080",
        "\u00f6",
        "\u20ac",
        "\U0001f600",
        "\ufb33",
    ]


def test_astral_keys_sort_before_later_bmp_keys() -> None:
    value = {"\ufffd": "replacement", "\U0001d11e": "g-clef"}
    assert list(json.loads(canonical_json(value))) == ["\U0001d11e", "\ufffd"]
    assert list(json.loads(legacy_canonical_json(value))) == ["\ufffd", "\U0001d11e"]


def test_unicode_is_preserved_without_normalization() -> None:
    nfc = "é"
    nfd = "e\u0301"
    assert nfc != nfd
    assert canonical_json(nfc) == f'"{nfc}"'
    assert canonical_json(nfd) == f'"{nfd}"'
    assert canonical_json({"text": nfc}) != canonical_json({"text": nfd})


def test_control_backslash_and_quote_escapes() -> None:
    encoded = canonical_json('\x00\x01\x07\b\t\n\x0b\f\r\x0e\x0f"\\/')
    assert encoded == '"\\u0000\\u0001\\u0007\\b\\t\\n\\u000b\\f\\r\\u000e\\u000f\\"\\\\/"'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json(value)


def test_lone_surrogates_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unicode scalar"):
        canonical_json("\ud800")
    with pytest.raises(ValueError, match="Unicode scalar"):
        canonical_json({"\ud800": "invalid"})
    with pytest.raises(ValueError, match="Unicode scalar"):
        content_digest({"invalid": "\ud800"})


def test_non_string_keys_tuples_cycles_and_unknown_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="object keys must be strings"):
        canonical_json({1: "one"})
    with pytest.raises(TypeError, match="unsupported type: tuple"):
        canonical_json((1, 2))
    with pytest.raises(TypeError, match="unsupported type: bytes"):
        canonical_json(b"abc")
    with pytest.raises(TypeError, match="unsupported type: set"):
        canonical_json({1})
    with pytest.raises(TypeError, match="unsupported type: complex"):
        canonical_json(1 + 2j)
    with pytest.raises(TypeError, match="unsupported type: object"):
        canonical_json(object())

    cyclic_list: list[Any] = []
    cyclic_list.append(cyclic_list)
    with pytest.raises(ValueError, match="circular reference"):
        canonical_json(cyclic_list)

    cyclic_object: dict[str, Any] = {}
    cyclic_object["self"] = cyclic_object
    with pytest.raises(ValueError, match="circular reference"):
        canonical_json(cyclic_object)


def test_safe_integer_bounds() -> None:
    assert canonical_json(9007199254740991) == "9007199254740991"
    assert canonical_json(-9007199254740991) == "-9007199254740991"
    with pytest.raises(ValueError, match="IEEE 754 binary64"):
        canonical_json(9007199254740992)
    with pytest.raises(ValueError, match="IEEE 754 binary64"):
        canonical_json(-9007199254740992)
    assert canonical_json(9007199254740992.0) == "9007199254740992"


def test_legacy_functions_keep_python_encoding_and_sha256_digests() -> None:
    for value, encoded, digest in LEGACY_GOLDEN_VECTORS:
        assert legacy_canonical_json(value) == encoded
        assert legacy_content_digest(value) == digest
        assert digest.startswith(LEGACY_SHA256_PREFIX)
        assert not digest.startswith(JCS_SHA256_PREFIX)

    legacy = {"negativeZero": -0.0, "small": 1e-7, "unicode": "研究"}
    assert canonical_json(legacy) == '{"negativeZero":0,"small":1e-7,"unicode":"研究"}'
    assert content_digest(legacy) != legacy_content_digest(legacy)


def test_content_digest_only_emits_jcs_sha256() -> None:
    digest = content_digest({"z": 1, "a": True})
    assert digest.startswith(JCS_SHA256_PREFIX)
    assert digest == f"{JCS_SHA256_PREFIX}{digest.removeprefix(JCS_SHA256_PREFIX)}"
    assert len(digest.removeprefix(JCS_SHA256_PREFIX)) == 64
    assert digest.removeprefix(JCS_SHA256_PREFIX).islower()
    assert not digest.startswith(LEGACY_SHA256_PREFIX)
    assert "sha256:" not in digest.removeprefix(JCS_SHA256_PREFIX)


def test_content_digest_type_accepts_new_and_legacy_forms() -> None:
    payload = "a" * 64
    assert CONTENT_DIGEST.validate_python(f"{JCS_SHA256_PREFIX}{payload}") == (
        f"{JCS_SHA256_PREFIX}{payload}"
    )
    assert CONTENT_DIGEST.validate_python(f"{LEGACY_SHA256_PREFIX}{payload}") == (
        f"{LEGACY_SHA256_PREFIX}{payload}"
    )


@pytest.mark.parametrize(
    "value",
    [
        f"JCS-SHA256:{'a' * 64}",
        f"jcs-SHA256:{'a' * 64}",
        f"SHA256:{'a' * 64}",
        f"sha256:{'A' * 64}",
        f"jcs-sha256:{'A' * 64}",
        f"sha256:{'a' * 63}",
        f"sha256:{'a' * 65}",
        f"jcs-sha256:{'a' * 63}",
        f"sha512:{'a' * 64}",
        f"md5:{'a' * 32}",
        "sha256:",
        "not-a-digest",
    ],
)
def test_content_digest_type_rejects_other_algorithms_case_and_length(value: str) -> None:
    with pytest.raises(ValidationError):
        CONTENT_DIGEST.validate_python(value)


def test_content_digest_strips_surrounding_whitespace() -> None:
    payload = "a" * 64
    current = f"{JCS_SHA256_PREFIX}{payload}"
    legacy = f"{LEGACY_SHA256_PREFIX}{payload}"
    assert CONTENT_DIGEST.validate_python(f"  {current}  ") == current
    assert CONTENT_DIGEST.validate_python(f"\n{legacy}\t") == legacy


def test_legacy_and_jcs_digests_are_not_interchangeable_by_hex() -> None:
    value = {"z": 1, "a": True}
    current = content_digest(value)
    legacy = legacy_content_digest(value)
    assert current.startswith(JCS_SHA256_PREFIX)
    assert legacy.startswith(LEGACY_SHA256_PREFIX)
    assert current != legacy
    relabeled = f"{LEGACY_SHA256_PREFIX}{current.removeprefix(JCS_SHA256_PREFIX)}"
    assert relabeled != current
    assert CONTENT_DIGEST.validate_python(relabeled) == relabeled


def test_out_of_range_integers_must_be_json_strings() -> None:
    with pytest.raises(ValueError, match="IEEE 754 binary64"):
        content_digest({"maxIterations": 10**100})
    with pytest.raises(ValueError, match="IEEE 754 binary64"):
        canonical_json(10**100)
    digest = content_digest({"amount": "1" + "0" * 100})
    assert digest.startswith(JCS_SHA256_PREFIX)
    assert digest == content_digest({"amount": "1" + "0" * 100})
