"""Движения камеры для видео: превью из assets/camera/ + фраза в промпт (aicameramovements.com).

Файлы качаются: bash download_camera_examples.sh → assets/camera/*.mp4 (в .gitignore).
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

# id → файл превью, подписи, готовая английская инструкция для промпта
MOVES: list[dict[str, str]] = [
    {"id": "static", "file": "01-static-shot-hq.mp4",
     "title_ru": "Статика", "title_en": "Static shot",
     "prompt": "locked-off static shot. Movement: hold one fixed camera position for the full clip. Speed: still and steady. Framing: keep the same angle, height, lens distance and composition. End: finish with the same framing and camera position."},
    {"id": "pan-right", "file": "02-pan-right-hq.mp4",
     "title_ru": "Пан вправо", "title_en": "Pan right",
     "prompt": "pan right. Movement: rotate the camera horizontally from left to right from one fixed point. Speed: smooth constant rotation. Framing: keep the horizon level while new space enters from the right side of the frame. End: settle on a clear final composition."},
    {"id": "pan-left", "file": "2b-pan-left-hq.mp4",
     "title_ru": "Пан влево", "title_en": "Pan left",
     "prompt": "pan left. Movement: rotate the camera horizontally from right to left from one fixed point. Speed: smooth constant rotation. Framing: keep the horizon level while new space enters from the left side of the frame. End: settle on a clear final composition."},
    {"id": "whip-pan-right", "file": "03-whip-pan-right-hq.mp4",
     "title_ru": "Whip pan вправо", "title_en": "Whip pan right",
     "prompt": "whip pan right. Movement: rotate rapidly from the starting direction toward a new target on the right. Speed: fast snap with brief motion blur during the rotation. Framing: begin on one readable composition and land on a second readable target. End: settle into a sharp final frame."},
    {"id": "whip-pan-left", "file": "3b-whip-pan-left-hq.mp4",
     "title_ru": "Whip pan влево", "title_en": "Whip pan left",
     "prompt": "whip pan left. Movement: rotate rapidly from the starting direction toward a new target on the left. Speed: fast snap with brief motion blur during the rotation. Framing: begin on one readable composition and land on a second readable target. End: settle into a sharp final frame."},
    {"id": "tilt-up", "file": "04-tilt-up-hq.mp4",
     "title_ru": "Наклон вверх", "title_en": "Tilt up",
     "prompt": "tilt up. Movement: rotate the camera upward from one fixed point. Speed: smooth constant tilt. Framing: keep the vertical subject or architecture centered as the frame travels upward. End: land on the upper target."},
    {"id": "tilt-down", "file": "4b-tilt-down-hq.mp4",
     "title_ru": "Наклон вниз", "title_en": "Tilt down",
     "prompt": "tilt down. Movement: rotate the camera downward from one fixed point. Speed: smooth constant tilt. Framing: keep the vertical subject or architecture centered as the frame travels downward. End: land on the lower target."},
    {"id": "slow-zoom-in", "file": "05-slow-zoom-in-hq.mp4",
     "title_ru": "Медленный зум in", "title_en": "Slow zoom in",
     "prompt": "slow zoom in. Movement: slowly increase lens focal length toward a tighter frame. Speed: gradual and even. Framing: keep the main visual target readable as it becomes larger in frame. End: finish on a stable tighter composition."},
    {"id": "slow-zoom-out", "file": "5b-slow-zoom-out-hq.mp4",
     "title_ru": "Медленный зум out", "title_en": "Slow zoom out",
     "prompt": "slow zoom out. Movement: slowly decrease lens focal length toward a wider frame. Speed: gradual and even. Framing: keep the main visual target readable as more surrounding space appears. End: finish on a stable wider composition."},
    {"id": "fast-zoom-in", "file": "06-fast-zoom-in-v2-hq.mp4",
     "title_ru": "Быстрый зум in", "title_en": "Fast zoom in",
     "prompt": "fast zoom in. Movement: quickly increase lens focal length toward the main visual target. Speed: quick decisive zoom. Framing: keep the target centered or clearly readable during the scale change. End: finish on a stable tighter composition."},
    {"id": "fast-zoom-out", "file": "06b-fast-zoom-out-v2-hq.mp4",
     "title_ru": "Быстрый зум out", "title_en": "Fast zoom out",
     "prompt": "fast zoom out. Movement: quickly decrease lens focal length away from the main visual target. Speed: quick decisive zoom. Framing: keep the target readable as the surrounding space appears. End: finish on a stable wider composition."},
    {"id": "crash-zoom-in", "file": "07a-crash-zoom-in-v2-hq.mp4",
     "title_ru": "Crash zoom in", "title_en": "Crash zoom in",
     "prompt": "crash zoom in. Movement: snap the lens rapidly toward the main visual target. Speed: very fast and punchy. Framing: keep the target readable through the sudden scale change. End: land on a bold tighter composition."},
    {"id": "crash-zoom-out", "file": "07b-crash-zoom-out-v2-hq.mp4",
     "title_ru": "Crash zoom out", "title_en": "Crash zoom out",
     "prompt": "crash zoom out. Movement: snap the lens rapidly away from the main visual target. Speed: very fast and punchy. Framing: keep the target readable as the surrounding space appears. End: land on a bold wider composition."},
    {"id": "dolly-in", "file": "08-dolly-in-hq.mp4",
     "title_ru": "Dolly in", "title_en": "Dolly in",
     "prompt": "dolly in. Movement: move the camera physically forward in a straight line toward the main subject. Speed: smooth controlled push. Framing: keep camera height, lens direction and subject position consistent while distance closes. End: finish in a tighter composition."},
    {"id": "dolly-out", "file": "09-dolly-out-hq.mp4",
     "title_ru": "Dolly out", "title_en": "Dolly out",
     "prompt": "dolly out. Movement: move the camera physically backward in a straight line away from the main subject. Speed: smooth controlled retreat. Framing: keep lens direction and camera height consistent while more environment enters frame. End: finish in a wider composition."},
    {"id": "truck-right", "file": "10-truck-right-hq.mp4",
     "title_ru": "Truck вправо", "title_en": "Truck right",
     "prompt": "truck right. Movement: move the camera physically to the right on a straight horizontal path. Speed: smooth constant lateral travel. Framing: keep the lens facing the same direction while the scene slides across frame. End: finish on a clean lateral composition."},
    {"id": "truck-left", "file": "10b-truck-left-hq.mp4",
     "title_ru": "Truck влево", "title_en": "Truck left",
     "prompt": "truck left. Movement: move the camera physically to the left on a straight horizontal path. Speed: smooth constant lateral travel. Framing: keep the lens facing the same direction while the scene slides across frame. End: finish on a clean lateral composition."},
    {"id": "pedestal-up", "file": "11a-pedestal-up-hq.mp4",
     "title_ru": "Pedestal вверх", "title_en": "Pedestal up",
     "prompt": "pedestal up. Movement: move the entire camera vertically upward in a straight line. Speed: smooth constant lift. Framing: keep the lens level and pointed in the same direction during the vertical move. End: finish with the higher framing clearly readable."},
    {"id": "pedestal-down", "file": "11b-pedestal-down-hq.mp4",
     "title_ru": "Pedestal вниз", "title_en": "Pedestal down",
     "prompt": "pedestal down. Movement: move the entire camera vertically downward in a straight line. Speed: smooth constant descent. Framing: keep the lens level and pointed in the same direction during the vertical move. End: finish with the lower framing clearly readable."},
    {"id": "slider-right", "file": "12-slider-right-hq.mp4",
     "title_ru": "Слайдер вправо", "title_en": "Slider right",
     "prompt": "slider right. Movement: slide the camera a small distance to the right. Speed: slow controlled constant motion. Framing: keep foreground, subject and background layers readable as parallax shifts. End: finish on a refined composition with the new right-side angle visible."},
    {"id": "slider-left", "file": "12b-slider-left-hq.mp4",
     "title_ru": "Слайдер влево", "title_en": "Slider left",
     "prompt": "slider left. Movement: slide the camera a small distance to the left. Speed: slow controlled constant motion. Framing: keep foreground, subject and background layers readable as parallax shifts. End: finish on a refined composition with the new left-side angle visible."},
    {"id": "push-past", "file": "13-push-past-pass-by-shot-hq.mp4",
     "title_ru": "Push past", "title_en": "Push past",
     "prompt": "push past. Movement: move forward past a visible foreground object, edge or opening. Speed: smooth forward glide. Framing: let the foreground pass close to the lens while the space beyond becomes clearer. End: arrive inside or beyond the foreground layer."},
    {"id": "arc-right", "file": "14-arc-right-hq.mp4",
     "title_ru": "Дуга вправо", "title_en": "Arc right",
     "prompt": "arc right. Movement: move on a shallow curved path around the main subject toward the right side. Speed: smooth measured curve. Framing: keep distance, height and subject readability consistent while the angle changes. End: finish from a new right-side angle."},
    {"id": "arc-left", "file": "14b-arc-left-hq.mp4",
     "title_ru": "Дуга влево", "title_en": "Arc left",
     "prompt": "arc left. Movement: move on a shallow curved path around the main subject toward the left side. Speed: smooth measured curve. Framing: keep distance, height and subject readability consistent while the angle changes. End: finish from a new left-side angle."},
    {"id": "orbit-cw", "file": "15-orbit-clockwise-hq.mp4",
     "title_ru": "Орбита по часовой", "title_en": "Orbit clockwise",
     "prompt": "clockwise orbit. Movement: circle clockwise around the main subject at a consistent radius. Speed: smooth controlled orbit. Framing: keep the subject centered while the background rotates around them. End: complete the intended arc or full circle with stable framing."},
    {"id": "orbit-ccw", "file": "15b-orbit-counterclockwise-hq.mp4",
     "title_ru": "Орбита против часовой", "title_en": "Orbit counterclockwise",
     "prompt": "counterclockwise orbit. Movement: circle counterclockwise around the main subject at a consistent radius. Speed: smooth controlled orbit. Framing: keep the subject centered while the background rotates around them. End: complete the intended arc or full circle with stable framing."},
    {"id": "tracking", "file": "16-tracking-shot-hq.mp4",
     "title_ru": "Трекинг", "title_en": "Tracking shot",
     "prompt": "tracking shot. Movement: move through the scene with the main subject. Speed: match the subject's pace. Framing: keep the subject consistently readable while the environment moves around them. End: maintain a clear moving composition."},
    {"id": "follow-ots", "file": "17-follow-shot-over-the-shoulder-hq.mp4",
     "title_ru": "Следом / через плечо", "title_en": "Follow / OTS",
     "prompt": "follow shot from behind. Movement: move behind the subject along their route at shoulder height. Speed: match the subject's pace. Framing: keep the back, shoulder or head as the foreground guide while the route ahead stays readable. End: continue following with the subject leading the frame."},
    {"id": "reverse-tracking", "file": "18-reverse-tracking-walk-and-talk-hq.mp4",
     "title_ru": "Обратный трекинг", "title_en": "Reverse tracking",
     "prompt": "reverse tracking shot. Movement: move backward in front of the walking subject. Speed: match the subject's forward pace. Framing: keep front-facing face and body framing stable as the background moves behind them. End: hold a clear front-facing moving composition."},
    {"id": "side-tracking", "file": "19-side-tracking-hq.mp4",
     "title_ru": "Боковой трекинг", "title_en": "Side tracking",
     "prompt": "side tracking shot. Movement: move parallel beside the subject along their direction of travel. Speed: match the subject's motion. Framing: keep the subject in side profile or three-quarter profile at a stable distance. End: continue the parallel movement with clear horizontal motion."},
    {"id": "low-tracking", "file": "20-low-tracking-v2-hq.mp4",
     "title_ru": "Низкий трекинг", "title_en": "Low tracking",
     "prompt": "low tracking shot. Movement: move at ground or below-waist height alongside the subject's movement path. Speed: match the subject, footsteps or wheels. Framing: keep the low detail readable while the ground plane moves through frame. End: finish with the low perspective clearly maintained."},
    {"id": "vehicle-tracking", "file": "21-vehicle-tracking-hq.mp4",
     "title_ru": "С машины", "title_en": "Vehicle tracking",
     "prompt": "vehicle tracking shot. Movement: move with the vehicle along its route. Speed: match the vehicle's pace. Framing: keep the vehicle stable in frame while the road or environment moves past. End: maintain a clear moving vehicle composition."},
    {"id": "chase", "file": "22-chase-shot-hq.mp4",
     "title_ru": "Погоня", "title_en": "Chase shot",
     "prompt": "chase shot. Movement: follow a moving subject quickly along the action route. Speed: fast, reactive and physically close. Framing: keep the subject visible while allowing energetic reframing. End: stay connected to the subject in motion."},
    {"id": "handheld", "file": "23-handheld-shot-hq.mp4",
     "title_ru": "Handheld", "title_en": "Handheld",
     "prompt": "handheld shot. Movement: hold the camera at human operator height with natural body movement. Speed: responsive and organic. Framing: keep the subject readable while the frame has subtle sway and micro-adjustments. End: finish with a natural handheld composition."},
    {"id": "snorricam", "file": "24-snorricam-v2-hq.mp4",
     "title_ru": "Snorricam", "title_en": "Snorricam",
     "prompt": "body-mounted Snorricam. Movement: keep the camera fixed relative to the subject's torso or face while the subject moves. Speed: match the subject's body motion. Framing: keep the subject close, centered and facing the camera as the background moves around them. End: finish with the subject still locked in frame."},
    {"id": "crane-up", "file": "25-crane-up-hq.mp4",
     "title_ru": "Кран вверх", "title_en": "Crane up",
     "prompt": "crane up. Movement: travel smoothly upward through open space. Speed: slow controlled vertical lift. Framing: keep the subject or location readable as the camera rises. End: finish with the higher scale clearly visible."},
    {"id": "crane-down", "file": "25b-crane-down-hq.mp4",
     "title_ru": "Кран вниз", "title_en": "Crane down",
     "prompt": "crane down. Movement: travel smoothly downward through open space. Speed: slow controlled vertical descent. Framing: keep the subject or location readable as the camera descends. End: finish with the lower subject or destination clearly visible."},
    {"id": "drone-push", "file": "26-drone-push-in-hq.mp4",
     "title_ru": "Дрон к объекту", "title_en": "Drone push in",
     "prompt": "drone push in. Movement: fly smoothly forward through open space toward the subject or destination. Speed: controlled aerial glide. Framing: keep the route and destination readable as the camera approaches. End: arrive at a closer aerial composition."},
    {"id": "drone-pull", "file": "26b-drone-pull-back-hq.mp4",
     "title_ru": "Дрон отлет", "title_en": "Drone pull back",
     "prompt": "drone pull back. Movement: fly smoothly backward away from the subject or destination. Speed: controlled aerial retreat. Framing: keep the subject readable as more landscape appears. End: finish on a wider aerial composition."},
    {"id": "helicopter", "file": "27-helicopter-shot-hq.mp4",
     "title_ru": "Вертолёт", "title_en": "Helicopter shot",
     "prompt": "helicopter-style aerial shot. Movement: move from high altitude along a broad gradual flight path. Speed: steady controlled aerial motion. Framing: keep the landscape or distant moving subject readable at wide scale. End: finish on a stable high-altitude composition."},
    {"id": "fpv", "file": "s1-first-person-view-hq.mp4",
     "title_ru": "От 1-го лица", "title_en": "First-person view",
     "prompt": "first-person view. Movement: move forward at human eye height from the character's perspective. Speed: natural walking or reaching pace. Framing: use visible hands, arms or body edges as the viewer's physical reference. End: arrive at the next point of action from the same point of view."},
    {"id": "tilt-shift", "file": "s2-tilt-shift-hq.mp4",
     "title_ru": "Tilt-shift", "title_en": "Tilt-shift",
     "prompt": "tilt-shift miniature view. Movement: hold or glide from a high angled view over the scene. Speed: small precise movement. Framing: keep a narrow band of sharp focus across the key subject area with soft blur above and below. End: finish with the miniature-scale view intact."},
    {"id": "infinite-zoom", "file": "s3-infinite-zoom-hq.mp4",
     "title_ru": "Бесконечный зум", "title_en": "Infinite zoom",
     "prompt": "infinite zoom. Movement: zoom continuously inward toward the exact center target. Speed: smooth accelerating zoom. Framing: keep the circular target centered as it expands. End: finish when the next visual world fills the frame."},
    {"id": "earth-zoom-out", "file": "s4-earth-zoom-out-hq.mp4",
     "title_ru": "Зум от Земли", "title_en": "Earth zoom out",
     "prompt": "earth zoom out. Movement: pull upward from the starting point through street, city, landscape and planet scale. Speed: rapid expanding zoom out. Framing: keep the original location centered as scale grows. End: finish on a planet-scale view with the starting point still implied at center."},
    {"id": "time-lapse", "file": "s5-time-lapse-hq.mp4",
     "title_ru": "Таймлапс", "title_en": "Time-lapse",
     "prompt": "locked-camera time-lapse. Movement: hold one fixed camera position while time moves rapidly forward. Speed: fast time compression with a stable camera. Framing: keep the same composition and horizon as motion passes through the frame. End: finish from the same camera angle with visible passage of time."},
    {"id": "pass-through", "file": "s6-pass-through-objects-hq.mp4",
     "title_ru": "Сквозь объекты", "title_en": "Pass-through",
     "prompt": "pass-through movement. Movement: move forward toward a visible object, surface or barrier and continue into the space beyond. Speed: smooth centered glide. Framing: keep the opening or surface centered as the transition point. End: arrive inside the revealed space beyond."},
]


# Группы как на aicameramovements.com (фильтр в флоу и на витрине)
_FILE_GROUP = {
    "01-static-shot-hq.mp4": "Pan/Tilt",
    "02-pan-right-hq.mp4": "Pan/Tilt",
    "03-whip-pan-right-hq.mp4": "Pan/Tilt",
    "04-tilt-up-hq.mp4": "Pan/Tilt",
    "05-slow-zoom-in-hq.mp4": "Zoom/Lens",
    "06-fast-zoom-in-v2-hq.mp4": "Zoom/Lens",
    "06b-fast-zoom-out-v2-hq.mp4": "Zoom/Lens",
    "07a-crash-zoom-in-v2-hq.mp4": "Zoom/Lens",
    "07b-crash-zoom-out-v2-hq.mp4": "Zoom/Lens",
    "08-dolly-in-hq.mp4": "Dolly/Track",
    "09-dolly-out-hq.mp4": "Dolly/Track",
    "10-truck-right-hq.mp4": "Physical Moves",
    "10b-truck-left-hq.mp4": "Physical Moves",
    "11a-pedestal-up-hq.mp4": "Physical Moves",
    "11b-pedestal-down-hq.mp4": "Physical Moves",
    "12-slider-right-hq.mp4": "Physical Moves",
    "12b-slider-left-hq.mp4": "Physical Moves",
    "13-push-past-pass-by-shot-hq.mp4": "Physical Moves",
    "14-arc-right-hq.mp4": "Physical Moves",
    "14b-arc-left-hq.mp4": "Physical Moves",
    "15-orbit-clockwise-hq.mp4": "Physical Moves",
    "15b-orbit-counterclockwise-hq.mp4": "Physical Moves",
    "16-tracking-shot-hq.mp4": "Dolly/Track",
    "17-follow-shot-over-the-shoulder-hq.mp4": "Dolly/Track",
    "18-reverse-tracking-walk-and-talk-hq.mp4": "Dolly/Track",
    "19-side-tracking-hq.mp4": "Dolly/Track",
    "20-low-tracking-v2-hq.mp4": "Dolly/Track",
    "21-vehicle-tracking-hq.mp4": "Dolly/Track",
    "22-chase-shot-hq.mp4": "Dolly/Track",
    "23-handheld-shot-hq.mp4": "Human Camera",
    "24-snorricam-v2-hq.mp4": "Human Camera",
    "25-crane-up-hq.mp4": "Drone/Crane",
    "25b-crane-down-hq.mp4": "Drone/Crane",
    "26-drone-push-in-hq.mp4": "Drone/Crane",
    "26b-drone-pull-back-hq.mp4": "Drone/Crane",
    "27-helicopter-shot-hq.mp4": "Drone/Crane",
    "2b-pan-left-hq.mp4": "Pan/Tilt",
    "3b-whip-pan-left-hq.mp4": "Pan/Tilt",
    "4b-tilt-down-hq.mp4": "Pan/Tilt",
    "5b-slow-zoom-out-hq.mp4": "Zoom/Lens",
    "s1-first-person-view-hq.mp4": "Specials",
    "s2-tilt-shift-hq.mp4": "Specials",
    "s3-infinite-zoom-hq.mp4": "Specials",
    "s4-earth-zoom-out-hq.mp4": "Specials",
    "s5-time-lapse-hq.mp4": "Specials",
    "s6-pass-through-objects-hq.mp4": "Specials"
}
for _m in MOVES:
    _m["group"] = _FILE_GROUP.get(_m["file"], "Specials")

DEFAULT_ID = None  # по умолчанию без движения (раньше была статика)

GROUP_ORDER = [
    ("Pan/Tilt", "Пан / наклон", "Pan / Tilt"),
    ("Zoom/Lens", "Зум / объектив", "Zoom / Lens"),
    ("Dolly/Track", "Долли / трекинг", "Dolly / Track"),
    ("Physical Moves", "Физические", "Physical moves"),
    ("Human Camera", "С рук / тело", "Human camera"),
    ("Drone/Crane", "Дрон / кран", "Drone / Crane"),
    ("Specials", "Спецприёмы", "Specials"),
]

_BY_ID = {m["id"]: m for m in MOVES}


def get(move_id: str | None) -> dict[str, str] | None:
    return _BY_ID.get(move_id or "")


def title(move: dict[str, str], lang: str) -> str:
    return move["title_en"] if lang == "en" else move["title_ru"]


def labeled_prompt(move: dict[str, str]) -> str:
    """Текст движения для вставки в промпт: явно помечен как camera movement (как на витрине)."""
    raw = (move.get("prompt") or "").strip()
    if not raw:
        return ""
    if re.match(r"(?i)^camera(\s+movement)?\s*:", raw):
        return raw
    # «Camera movement — Whip pan right: whip pan right. Movement: …»
    name = (move.get("title_en") or move.get("id") or "").strip()
    head = f"Camera movement — {name}" if name else "Camera movement"
    return f"{head}: {raw}"


_PROMPTS = tuple(dict.fromkeys(
    [labeled_prompt(m) for m in MOVES] + [m["prompt"] for m in MOVES]
))


def ensure_default(ses: dict) -> None:
    """По умолчанию без движения — ничего не подставляем в сессию."""
    return


def strip(prompt: str) -> str:
    """Убрать ранее вставленную инструкцию камеры из конца промпта."""
    text = (prompt or "").rstrip()
    if not text:
        return ""
    lower = text.lower()
    for frag in sorted(_PROMPTS, key=len, reverse=True):
        f = frag.lower()
        for sep in (". " + f, " " + f, f):
            if lower.endswith(sep):
                return text[: len(text) - len(sep)].rstrip(" .")
            idx = lower.rfind(f)
            if idx > 0 and lower[idx:].strip() == f:
                return text[:idx].rstrip(" .")
    return text


def compose(base: str, move_id: str | None) -> str:
    move = get(move_id)
    base = (base or "").strip()
    if not move:
        return base
    frag = labeled_prompt(move)
    raw = (move.get("prompt") or "").strip()
    # уже вставлено (с подписью или без)
    if frag.lower() in base.lower() or (raw and raw.lower() in base.lower()):
        return base
    if not base:
        return frag
    return base.rstrip(" .") + ". " + frag


def apply(ses: dict, prompt: str | None = None) -> str:
    """Записать prompt_base / camera → итоговый prompt в сессии, вернуть его."""
    ensure_default(ses)
    if prompt is not None:
        base = strip(prompt)
    else:
        stored = ses.get("prompt_base")
        base = strip(stored) if stored else strip(ses.get("prompt") or "")
    ses["prompt_base"] = base
    out = compose(base, ses.get("camera"))
    ses["prompt"] = out
    return out


def work_id(move: dict[str, str]) -> str:
    """id работы на витрине (vitrina-camera-moves.js): cam-01-static-shot."""
    stem = (move.get("file") or "").removesuffix(".mp4")
    if stem.endswith("-hq"):
        stem = stem[:-3]
    return f"cam-{stem}"


def vitrina_href(move: dict[str, str] | None = None, group: str | None = None) -> str:
    url = "/explore?f=Camera"
    g = group or (move.get("group") if move else None)
    if g:
        url += "&cam=" + quote(g)
    if move:
        url += "&work=" + quote(work_id(move))
    return url


def block(selected: str | None, lang: str) -> dict[str, Any]:
    L = "en" if lang == "en" else "ru"
    items = []
    for m in MOVES:
        poster = m["file"].replace(".mp4", ".jpg")
        items.append({
            "id": m["id"],
            "title": title(m, L),
            "preview": f"/assets/camera/{m['file']}",
            "poster": f"/assets/camera/{poster}",
            "group": m.get("group") or "Specials",
            "work_id": work_id(m),
            "vitrina": vitrina_href(m),
            "selected": m["id"] == selected,
        })
    groups = []
    for gid, ru, en in GROUP_ORDER:
        groups.append({"id": gid, "label": en if L == "en" else ru})
    label = "Добавим движение камеры?" if L == "ru" else "Add a camera move?"
    hint = ("Сначала тип (пан / зум / трекинг…), затем конкретное движение. По умолчанию — без движения"
            if L == "ru" else
            "First pick a type (pan / zoom / tracking…), then a specific move. No move by default")
    sel_move = get(selected)
    return {
        "type": "camera",
        "label": label,
        "hint": hint,
        "groups": groups,
        "items": items,
        "vitrina_url": vitrina_href(sel_move) if sel_move else "/explore?f=Camera",
    }
