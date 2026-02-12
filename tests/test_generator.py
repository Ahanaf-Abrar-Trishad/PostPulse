from __future__ import annotations

from app.generator.service import ContentGeneratorService


def test_similarity_guard(settings):
    service = ContentGeneratorService(settings)
    source = ["This is a sample ERP transformation post for manufacturers."]
    high = service._max_similarity("This is a sample ERP transformation post for manufacturers.", source)
    low = service._max_similarity("Cloud governance starts with outcome ownership.", source)
    assert high > low
    assert high > 0.9


def test_platform_distribution_respects_ratio(settings):
    settings.config.generation.linkedin_ratio = 0.75
    service = ContentGeneratorService(settings)
    distribution = service._platform_distribution(12, ["linkedin", "facebook"])
    assert distribution["linkedin"] == 9
    assert distribution["facebook"] == 3


def test_platform_distribution_rejects_unsupported_platform(settings):
    service = ContentGeneratorService(settings)
    try:
        service._platform_distribution(10, ["linkedin", "x"])
    except ValueError as exc:
        assert "Unsupported platform" in str(exc)
    else:
        raise AssertionError("ValueError was expected for unsupported platforms")
