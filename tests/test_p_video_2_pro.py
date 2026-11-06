"""P-Video 2 Pro: payload, цена по умолчанию и второй кадр."""
import server


def test_payload_defaults_and_frames():
    spec = server.INTEGRATED_MODELS["p-video-2-pro"]
    assert spec["replicate_model"] == "prunaai/p-video-2-pro"
    bare = server._build_provider_input(spec, "кот", None, None, None)
    assert bare == {
        "prompt": "кот",
        "mode": "speed",
        "resolution": "768p",
        "duration": 5,
        "aspect_ratio": "16:9",
        "prompt_upsampler": "turbo",
    }
    framed = server._build_provider_input(
        spec, "кот", "data:image/png;base64,AA==", None, None,
        last_image_data_url="data:image/png;base64,BB==",
    )
    assert framed["image"] == "data:image/png;base64,AA=="
    assert framed["last_frame_image"] == "data:image/png;base64,BB=="
    assert "aspect_ratio" not in framed
    assert framed["mode"] == "speed" and framed["resolution"] == "768p"


def test_assist_params_cannot_raise_the_billed_tier():
    payload = {
        "prompt": "кот",
        "mode": "speed",
        "resolution": "768p",
        "duration": 5,
        "aspect_ratio": "16:9",
        "prompt_upsampler": "turbo",
    }
    out = server._apply_assist_params(
        payload,
        {"mode": "quality", "resolution": "4k", "duration": 99, "aspect_ratio": "9:16"},
        model_id="p-video-2-pro",
    )
    assert out["mode"] == "speed"
    assert out["resolution"] == "768p"
    assert out["duration"] == 15
    assert out["aspect_ratio"] == "9:16"
    assert out["prompt_upsampler"] == "turbo"
