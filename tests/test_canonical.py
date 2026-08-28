from pathlib import Path

import pytest

from llm_research_os.blocks.registry import build_registry
from llm_research_os.canonical import canonical_json, content_digest
from llm_research_os.execution import TrustedKernel
from llm_research_os.spec.io import load_spec

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_reference_digest_golden_vectors() -> None:
    vectors = [
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
    ]
    for value, encoded, digest in vectors:
        assert canonical_json(value) == encoded
        assert content_digest(value) == digest


def test_m0_protocol_digest_golden_vectors() -> None:
    registry = build_registry()
    manifest = registry.blocks()[0]
    assert manifest.digest == (
        "sha256:6edd4922cd9dd0e574d35040d4a9a7cdd71c196b961a16557dcb14bf668c1fc4"
    )
    assert registry.digest() == (
        "sha256:e01025755a6d814de2b78096fc9c0fe961a936a8c76701d19f4cb087470fc6da"
    )

    spec = load_spec(EXAMPLES / "valid/minimal.yaml")
    report = TrustedKernel(registry).dry_run(spec)
    assert report.digests.spec == (
        "sha256:16d0739a84f6ec928d3b2002dbf8a9f58e816ee3951a34a95fe670387ae97b29"
    )
    assert report.digests.plan == (
        "sha256:a175c8473fed497560b3300c44cf30b4c7db6d1ad05a473bcca3e0668ba15118"
    )


def test_reference_digest_rejects_lone_unicode_surrogates() -> None:
    with pytest.raises(ValueError, match="Unicode scalar"):
        content_digest({"invalid": "\ud800"})
