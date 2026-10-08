"""Ассистент называет прикреплённые файлы по имени: при подборе, в сводке, в предупреждениях."""
from assistant.files import clean_attachments, describe
from assistant.flask_adapter import clean_context

SID = "u1:files"
PHOTO = [{"kind": "image", "name": "cat.png"}]
PHOTO_AUDIO = [{"kind": "image", "name": "cat.png"}, {"kind": "audio", "name": "voice.wav"}]
INPUTS = {"p-video": ["text", "image", "audio"], "veo-3-1": ["text", "image"], "seedream-5-pro": ["text", "image"],
          "elevenlabs-music": ["text"], "gen4-turbo": ["image", "text"]}


def block(r, typ):
    return next((bl for bl in r["blocks"] if bl["type"] == typ), None)


def _a(make_assistant):
    return make_assistant(inputs_fn=lambda mid: INPUTS.get(mid, ["text"]))


# ───────────── чистка того, что прислал фронт ─────────────

def test_clean_attachments_keeps_kind_and_safe_name_only():
    raw = [
        {"kind": "image", "name": "old.png", "id": "upl_x", "size": 5},
        {"kind": "image", "name": "C:\\Users\\me\\cat <script>.png"},     # несколько фото одного типа — ок
        {"kind": "audio", "name": "«voice».wav"},
        {"kind": "exe", "name": "virus.exe"},
        "junk",
        {"kind": "video", "name": "x" * 200 + ".mp4"},
    ]
    files = clean_attachments(raw)
    assert [f["kind"] for f in files] == ["image", "image", "audio", "video"]
    assert files[0] == {"kind": "image", "name": "old.png"}
    assert files[1] == {"kind": "image", "name": "C:Usersmecat script.png"}
    assert files[2]["name"] == "voice.wav"
    assert len(files[3]["name"]) <= 60 and files[3]["name"].endswith(".mp4")
    assert clean_attachments("nope") == [] and clean_attachments(None) == []


def test_describe_joins_names():
    assert describe(PHOTO_AUDIO, "ru") == "фото «cat.png» и аудио «voice.wav»"
    assert describe(PHOTO, "en") == "photo “cat.png”"


def test_adapter_context_passes_attachments_and_drops_junk():
    ctx = clean_context({"attachments": PHOTO_AUDIO + [{"kind": "pdf", "name": "a.pdf"}], "has_image": False,
                         "_account": {"authed": True}})
    assert ctx["attachments"] == PHOTO_AUDIO
    assert "_account" not in ctx
    assert "attachments" not in clean_context({"attachments": "x"})


# ───────────── подбор моделей ─────────────

def test_models_reply_names_the_photo_once(make_assistant):
    a = _a(make_assistant)
    r = a.handle("сделай видео: кот прыгает", {"attachments": PHOTO}, SID)
    assert "«cat.png»" in r["reply"] and r["reply"].lstrip().startswith("Вижу фото «cat.png»")
    r2 = a.handle("", {"attachments": PHOTO}, SID, action={"type": "more"})
    assert "cat.png" not in r2["reply"].splitlines()[0]          # повторно не твердит
    r3 = a.handle("", {"attachments": PHOTO_AUDIO}, SID, action={"type": "more"})
    if block(r3, "models"):
        assert "«voice.wav»" in r3["reply"]                        # набор файлов поменялся — сказала снова


def test_attached_photo_counts_as_has_image(make_assistant):
    a = _a(make_assistant)
    a.handle("видео из фото: кот прыгает", {"attachments": PHOTO}, SID)
    r = a.handle("", {"attachments": PHOTO}, SID, action={"type": "pick_model", "value": "gen4-turbo"})
    assert "нужно фото" not in r["reply"]                          # фото уже есть — не просим
    r = a.handle("", {}, "u1:nophoto", action={"type": "pick_model", "value": "gen4-turbo"})
    assert r["generate_model"] == "gen4-turbo"


# ───────────── сводка перед запуском ─────────────

def test_summary_says_what_each_file_becomes(make_assistant):
    a = _a(make_assistant)
    a.handle("видео: кот прыгает в снег", {"attachments": PHOTO_AUDIO}, SID)
    r = a.handle("", {"attachments": PHOTO_AUDIO}, SID, action={"type": "pick_model", "value": "p-video"})
    assert "Фото «cat.png» — первый кадр видео." in r["reply"]
    assert "Аудио «voice.wav» — звук для видео." in r["reply"]
    s = block(r, "summary")
    assert s["files_title"] == "Файлы"
    assert s["files"] == ["фото «cat.png» — первый кадр видео", "аудио «voice.wav» — звук для видео"]
    assert r["generate_files"] == PHOTO_AUDIO


def test_model_that_ignores_a_file_is_honest_by_name(make_assistant):
    a = _a(make_assistant)
    a.handle("видео: кот прыгает в снег", {"attachments": PHOTO_AUDIO}, SID)
    r = a.handle("", {"attachments": PHOTO_AUDIO}, SID, action={"type": "pick_model", "value": "veo-3-1"})
    assert "Аудио «voice.wav» Veo" in r["reply"] and "не примет" in r["reply"]
    assert block(r, "summary")["files"][1].endswith("— не используется")
    assert r["generate_files"] == PHOTO                            # уйдёт только фото


def test_image_model_calls_photo_a_reference(make_assistant):
    a = _a(make_assistant)
    a.handle("картинка: кот в космосе", {"attachments": PHOTO}, SID)
    r = a.handle("", {"attachments": PHOTO}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    assert "Фото «cat.png» — референс для картинки." in r["reply"]


def test_english_reply_names_files(make_assistant):
    a = _a(make_assistant)
    a.handle("make a video: a cat jumps into snow", {"attachments": PHOTO_AUDIO, "lang": "en"}, "en:files")
    r = a.handle("", {"attachments": PHOTO_AUDIO, "lang": "en"}, "en:files",
                 action={"type": "pick_model", "value": "veo-3-1"})
    assert "Photo “cat.png” — first frame of the video." in r["reply"]
    assert "can't use the audio “voice.wav”" in r["reply"]


def test_without_files_nothing_changes(make_assistant):
    a = _a(make_assistant)
    a.handle("видео: кот прыгает", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "veo-3-1"})
    assert block(r, "summary")["files"] == [] and r["generate_files"] == []
    assert "«" not in r["reply"].split("\n")[0] or "cat.png" not in r["reply"]


def test_card_modes_fallback_without_inputs_fn(make_assistant):
    a = make_assistant()                                           # inputs_fn не передан
    a.handle("видео: кот прыгает", {"attachments": PHOTO_AUDIO}, SID)
    r = a.handle("", {"attachments": PHOTO_AUDIO}, SID, action={"type": "pick_model", "value": "veo-3-1"})
    assert r["generate_files"] == PHOTO                            # фото — по режиму i2v, аудио — нет


def test_models_reply_says_who_takes_the_audio(make_assistant):
    a = _a(make_assistant)
    r = a.handle("сделай видео: кот прыгает в снег", {"attachments": PHOTO_AUDIO}, "u1:audio")
    lines = r["reply"].splitlines()
    assert lines[0] == "Вижу фото «cat.png» и аудио «voice.wav» — показываю модели, которые умеют работать с фото."
    shown = [m["id"] for m in block(r, "models")["items"]]
    takers = [m for m in shown if "audio" in INPUTS.get(m, [])]
    audio_line = lines[1]
    if takers and len(takers) < len(shown):
        assert audio_line.startswith("Аудио «voice.wav» из них примет только ")
    elif not takers:
        assert audio_line == "Аудио «voice.wav» эти модели не примут — уйдёт только текст."
    else:
        assert audio_line == "Аудио «voice.wav» примут все эти модели."


def test_audio_only_attachment(make_assistant):
    a = _a(make_assistant)
    r = a.handle("сделай видео: кот прыгает в снег", {"attachments": [{"kind": "audio", "name": "beat.mp3"}]}, "u1:a2")
    assert r["reply"].splitlines()[0] == "Вижу аудио «beat.mp3»."
