from __future__ import annotations

from app.generator.service import ContentGeneratorService


def test_similarity_guard(settings):
    service = ContentGeneratorService(settings)
    source = ["This is a sample ERP transformation post for manufacturers."]
    high = service._max_similarity("This is a sample ERP transformation post for manufacturers.", source)
    low = service._max_similarity("Cloud governance starts with outcome ownership.", source)
    assert high > low
    assert high > 0.9
