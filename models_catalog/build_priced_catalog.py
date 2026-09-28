#!/usr/bin/env python3
"""Build priced catalog for live INTEGRATED_MODELS (Replicate + fal)."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent


def load_integrated_models() -> dict:
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    m = re.search(r"^INTEGRATED_MODELS = \{", src, re.M)
    if not m:
        raise SystemExit("INTEGRATED_MODELS not found")
    i = src.find("{", m.start())
    depth = 0
    end = None
    for j, c in enumerate(src[i:], i):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    ns: dict = {}
    exec("INTEGRATED_MODELS = " + src[i:end], ns)
    return ns["INTEGRATED_MODELS"]


def curl_get(url: str, timeout: int = 45) -> tuple[int, str]:
    cmd = [
        "curl",
        "-sL",
        "--max-time",
        str(timeout),
        "-A",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "-H",
        "Accept: text/html,application/json",
        "-w",
        "\n__HTTP_CODE__:%{http_code}",
        url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    except subprocess.TimeoutExpired:
        return 0, ""
    body = proc.stdout or ""
    code = 0
    if "__HTTP_CODE__:" in body:
        body, _, tail = body.rpartition("__HTTP_CODE__:")
        try:
            code = int(tail.strip().split()[0])
        except Exception:
            code = 0
    return code, body


def extract_json_array_after(page: str, key: str) -> list | None:
    idx = 0
    while True:
        i = page.find(f'"{key}"', idx)
        if i < 0:
            return None
        j = page.find("[", i)
        if j < 0:
            return None
        depth = 0
        for k in range(j, min(j + 8000, len(page))):
            ch = page[k]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    raw = page[j : k + 1]
                    try:
                        arr = json.loads(raw)
                        if isinstance(arr, list) and arr:
                            return arr
                    except json.JSONDecodeError:
                        break
        idx = i + 1


def summarize_replicate_page(page: str) -> dict:
    prices = extract_json_array_after(page, "prices") or []
    parts = []
    for item in prices:
        if not isinstance(item, dict):
            continue
        bit = (item.get("price") or "").strip()
        title = (item.get("title") or item.get("metric_display") or "").strip()
        desc = (item.get("description") or "").strip()
        chunk = " ".join(x for x in [bit, title, f"({desc})" if desc else ""] if x).strip()
        if chunk and chunk not in parts:
            parts.append(chunk)
    p50 = re.search(r'"p50price"\s*:\s*"([^"]+)"', page)
    hw = re.search(r'"price"\s*:\s*"(\$[^"]*per second)"', page)
    if not parts:
        if hw and p50:
            parts.append(f"{hw.group(1)}; typical ~{p50.group(1)}")
        elif hw:
            parts.append(hw.group(1))
        elif p50:
            parts.append(f"typical ~{p50.group(1)}")
    return {
        "price_summary": " · ".join(parts) if parts else "",
        "prices": prices,
        "p50price": p50.group(1) if p50 else "",
        "hardware_price": hw.group(1) if hw else "",
    }


def summarize_fal_markdown(text: str) -> dict:
    """Parse pricing snippets from fal model page markdown / html text."""
    lines = []
    # Common banner: Your request will cost ...
    for m in re.finditer(
        r"Your request will cost[^\n.]{0,200}\.?",
        text,
        re.I,
    ):
        s = " ".join(m.group(0).split())
        if s not in lines:
            lines.append(s)
    # Dollar per unit patterns
    for m in re.finditer(
        r"\$[0-9]+(?:\.[0-9]+)?\s*(?:/\s*(?:s|sec|second|image|video|megapixel|MP|1K characters|minute|min|request|generation)[a-zA-Z0-9 ]*)?",
        text,
        re.I,
    ):
        s = " ".join(m.group(0).split())
        if s not in lines and len(s) < 80:
            lines.append(s)
    # Resolution table rows often like | 1080p | $0.06/s |
    for m in re.finditer(
        r"\|\s*([0-9]{3,4}p(?:\s*\([^)]+\))?)\s*\|\s*(\$[0-9.]+/[a-zA-Z]+)\s*\|",
        text,
        re.I,
    ):
        s = f"{m.group(1)}: {m.group(2)}"
        if s not in lines:
            lines.append(s)
    # Keep first ~6 unique meaningful bits
    filtered = []
    for s in lines:
        if s.startswith("$0") and len(s) < 6:
            continue
        if s not in filtered:
            filtered.append(s)
        if len(filtered) >= 6:
            break
    return {"price_summary": " · ".join(filtered), "raw_hits": filtered}


def group_label(outputs: list, kind: str | None) -> str:
    if kind == "chat" or kind == "llm":
        return "llm"
    outs = set(outputs or [])
    if "video" in outs:
        return "video"
    if "audio" in outs or "music" in outs:
        return "audio"
    if "image" in outs:
        return "image"
    return "text"


def main() -> None:
    models = load_integrated_models()
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = []

    for mid, spec in models.items():
        provider = spec.get("provider")
        name = spec.get("name") or mid
        upstream = (
            spec.get("replicate_model")
            or spec.get("fal_model")
            or spec.get("omniroute_model")
            or ""
        )
        category = group_label(spec.get("outputs") or [], spec.get("kind"))
        inputs = ", ".join(spec.get("inputs") or [])
        outputs = ", ".join(spec.get("outputs") or [])
        row = {
            "id": mid,
            "name": name,
            "provider": provider,
            "upstream": upstream,
            "category": category,
            "inputs": inputs,
            "outputs": outputs,
            "price": "",
            "price_source": "",
            "url": "",
            "notes": "",
        }
        if provider == "omniroute":
            row["price"] = "free-tier / pool (OmniRoute)"
            row["price_source"] = "omniroute"
            row["notes"] = "chat assistant / router; not billed via Replicate/fal"
            rows.append(row)
            continue

        if provider == "replicate" and upstream:
            url = f"https://replicate.com/{upstream}"
            row["url"] = url
            print(f"[replicate] {upstream} ...", flush=True)
            code, page = curl_get(url)
            if code == 200 and page:
                info = summarize_replicate_page(page)
                row["price"] = info["price_summary"] or "see page"
                row["price_source"] = "replicate.com page"
                if info.get("p50price"):
                    row["notes"] = f"p50 {info['p50price']}"
            else:
                row["price"] = "fetch_failed"
                row["notes"] = f"http {code}"
            time.sleep(0.35)

        elif provider == "fal" and upstream:
            # Prefer fal-ai/ prefix in public URLs when missing for some bytedance paths
            path = upstream
            url = f"https://fal.ai/models/{path}"
            row["url"] = url
            # Pricing filled later from fal_prices.json if present; otherwise try page fetch
            fal_cache = OUT / "fal_prices.json"
            cached = {}
            if fal_cache.exists():
                try:
                    cached = json.loads(fal_cache.read_text(encoding="utf-8"))
                except Exception:
                    cached = {}
            if upstream in cached and cached[upstream].get("price_summary"):
                row["price"] = cached[upstream]["price_summary"]
                row["price_source"] = "fal.ai llms.txt / model page"
            else:
                # Prefer llms.txt (lighter than full SPA)
                print(f"[fal] {upstream} (llms.txt)...", flush=True)
                code, page = curl_get(url.rstrip('/') + '/llms.txt', timeout=45)
                if code == 200 and page:
                    info = summarize_fal_markdown(page)
                    # Prefer ## Pricing section body
                    m = re.search(r"## Pricing\s*([\s\S]*?)(?:\n## |\Z)", page)
                    if m:
                        block = " ".join(m.group(1).split())
                        block = re.sub(r"For more details.*", "", block).strip()
                        if block:
                            info["price_summary"] = block[:280]
                    row["price"] = info["price_summary"] or "see page"
                    row["price_source"] = "fal.ai llms.txt"
                else:
                    row["price"] = "pending_fetch"
                    row["notes"] = f"http {code or 'timeout'}"
                time.sleep(0.25)
        else:
            row["price"] = "n/a"

        rows.append(row)

    # Write JSON + CSV + MD
    (OUT / "catalog.json").write_text(
        json.dumps({"fetched_at": fetched_at, "models": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    import csv

    with (OUT / "catalog.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "name",
                "provider",
                "upstream",
                "category",
                "inputs",
                "outputs",
                "price",
                "price_source",
                "url",
                "notes",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    def md_escape(s: str) -> str:
        return (s or "").replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Live models catalog (with prices)",
        "",
        f"Source of truth: `INTEGRATED_MODELS` in `server.py`. Prices fetched {fetched_at}.",
        "",
        "Units differ by model (per image / per second / per token / per megapixel). Compare only within the same unit.",
        "",
        "| Name | Channel | Upstream | Category | In | Out | Price | Source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| "
            + " | ".join(
                md_escape(x)
                for x in [
                    r["name"],
                    r["provider"],
                    r["upstream"],
                    r["category"],
                    r["inputs"],
                    r["outputs"],
                    r["price"] or "—",
                    r["price_source"] or "—",
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## Compare same capability across channels",
        "",
        "Where both Replicate and fal expose related Wan / Seedance models, compare rows with matching category and similar upstream names.",
        "",
        f"Generated by `models_catalog/build_priced_catalog.py`.",
        "",
    ]
    (OUT / "CATALOG.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(rows)} rows → models_catalog/CATALOG.md")


if __name__ == "__main__":
    main()
