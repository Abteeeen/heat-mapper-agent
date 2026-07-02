import pytest

from shadescout.clients import vision
from shadescout.errors import VisionAnalysisError


def test_extract_json_object_plain():
    obj = vision._extract_json_object('{"has_patio": true, "already_covered": false, "estimated_sun_hours": 8}')
    assert obj == {"has_patio": True, "already_covered": False, "estimated_sun_hours": 8}


def test_extract_json_object_markdown_fenced():
    text = (
        "Here is the analysis:\n```json\n"
        '{"has_patio": true, "already_covered": false, "estimated_sun_hours": 9}\n```'
    )
    obj = vision._extract_json_object(text)
    assert obj["estimated_sun_hours"] == 9


def test_extract_json_object_none_found_raises():
    with pytest.raises(VisionAnalysisError):
        vision._extract_json_object("no json here")


def test_coerce_analysis_missing_field_raises():
    with pytest.raises(VisionAnalysisError):
        vision._coerce_analysis({"has_patio": True})


def test_analyze_property_success(monkeypatch):
    captured = {}

    def fake_request_json(method, url, *, error_cls, error_context, timeout, headers, json):
        captured["headers"] = headers
        captured["payload"] = json
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"has_patio": true, "already_covered": false, "estimated_sun_hours": 10}'
                    }
                }
            ]
        }

    monkeypatch.setattr(vision, "request_json", fake_request_json)
    client = vision.VisionClient(api_key="fake-key", model="test-model")
    analysis = client.analyze_property("sat_b64", "street_b64")

    assert analysis.has_patio is True
    assert analysis.already_covered is False
    assert analysis.estimated_sun_hours == 10
    assert captured["headers"]["Authorization"] == "Bearer fake-key"
    assert captured["payload"]["model"] == "test-model"
    images = [c for c in captured["payload"]["messages"][0]["content"] if c["type"] == "image_url"]
    assert len(images) == 2
    assert "sat_b64" in images[0]["image_url"]["url"]
    assert "street_b64" in images[1]["image_url"]["url"]


def test_analyze_property_bad_response_shape_raises(monkeypatch):
    monkeypatch.setattr(vision, "request_json", lambda *a, **k: {"choices": []})
    client = vision.VisionClient(api_key="fake-key")
    with pytest.raises(VisionAnalysisError):
        client.analyze_property("a", "b")
