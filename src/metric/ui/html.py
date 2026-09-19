"""HTML building blocks.

Everything is inline and served from this process: no CDN, no font host, no build
step. That is not minimalism for its own sake — an internal network usually cannot
reach a CDN, and a tool that renders unstyled behind the firewall is a tool nobody
uses.
"""

from __future__ import annotations

from collections.abc import Iterable
from html import escape
from typing import Any

NAV = (
    ("/", "Overview"),
    ("/workflow", "Workflow"),
    ("/graph", "Graph"),
    ("/bases", "Bases"),
    ("/evaluations", "Evaluations"),
    ("/quarantine", "Quarantine"),
    ("/questions", "Review"),
)

STYLE = """
:root {
  --bg:#fbfbfa; --panel:#fff; --line:#e3e1dd; --ink:#1a1a18; --muted:#6c6a66;
  --accent:#2b5c8a; --pass:#2e7d55; --fail:#b3432f; --warn:#9a6b14; --idle:#6c6a66;
  --chip:#f1efeb;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#14151a; --panel:#1b1d24; --line:#2c2f39; --ink:#e8e6e3; --muted:#9a9790;
    --accent:#6fa8dc; --pass:#5cbf8a; --fail:#e8785f; --warn:#d6a441; --idle:#8a877f;
    --chip:#252831;
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 ui-sans-serif,
  system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
a { color:var(--accent); text-decoration:none; }
a:hover { text-decoration:underline; }
header { border-bottom:1px solid var(--line); background:var(--panel);
  position:sticky; top:0; z-index:20; }
header .bar { max-width:1180px; margin:0 auto; padding:12px 20px; display:flex;
  align-items:baseline; gap:20px; flex-wrap:wrap; }
header .mark { font-weight:650; letter-spacing:-.01em; }
header nav { display:flex; gap:16px; flex-wrap:wrap; }
header nav a { color:var(--muted); font-size:14px; }
header nav a.on { color:var(--ink); font-weight:600; }
header .id { margin-left:auto; color:var(--muted); font-size:12px;
  font-family:ui-monospace,Menlo,monospace; }
main { max-width:1180px; margin:0 auto; padding:26px 20px 80px; }
h1 { font-size:21px; margin:0 0 4px; letter-spacing:-.01em; }
h2 { font-size:15px; margin:30px 0 10px; letter-spacing:-.005em; }
p.lede { color:var(--muted); margin:0 0 22px; max-width:70ch; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:9px;
  padding:16px 18px; margin-bottom:14px; }
.grid { display:grid; gap:12px; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); }
.stat { background:var(--panel); border:1px solid var(--line); border-radius:9px;
  padding:13px 15px; }
.stat b { display:block; font-size:25px; font-weight:620; letter-spacing:-.02em; }
.stat span { color:var(--muted); font-size:12.5px; }
table { width:100%; border-collapse:collapse; font-size:14px; }
th { text-align:left; font-weight:600; color:var(--muted); font-size:12px;
  text-transform:uppercase; letter-spacing:.04em; padding:6px 10px 6px 0;
  border-bottom:1px solid var(--line); }
td { padding:8px 10px 8px 0; border-bottom:1px solid var(--line); vertical-align:top; }
tr:last-child td { border-bottom:0; }
code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; }
.chip { display:inline-block; padding:1px 8px; border-radius:999px; background:var(--chip);
  color:var(--muted); font-size:11.5px; white-space:nowrap; }
.chip.pass { color:var(--pass); } .chip.fail { color:var(--fail); }
.chip.warn { color:var(--warn); } .chip.idle { color:var(--idle); }
.quote { border-left:2px solid var(--line); padding:2px 0 2px 11px; margin:6px 0;
  color:var(--muted); font-size:13px; }
form.inline { display:inline; }
button { font:inherit; font-size:13px; padding:4px 11px; border-radius:6px;
  border:1px solid var(--line); background:var(--panel); color:var(--ink); cursor:pointer; }
button:hover { border-color:var(--accent); color:var(--accent); }
button.primary { border-color:var(--pass); color:var(--pass); }
.empty { color:var(--muted); font-style:italic; }
mark { background:rgba(214,164,65,.32); color:inherit; padding:1px 0; border-radius:2px; }
details summary { cursor:pointer; color:var(--muted); font-size:13px; }
.scroll { overflow-x:auto; }
"""


def page(title: str, active: str, identity: str, body: str) -> str:
    nav = "".join(
        f"<a href='{href}' class='{'on' if href == active else ''}'>{escape(label)}</a>"
        for href, label in NAV
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(title)} · metric</title><style>{STYLE}</style></head><body>"
        f"<header><div class='bar'><span class='mark'>metric</span>"
        f"<nav>{nav}</nav><span class='id'>build {escape(identity)}</span></div></header>"
        f"<main>{body}</main></body></html>"
    )


def stats(items: Iterable[tuple[str, Any]]) -> str:
    cells = "".join(
        f"<div class='stat'><b>{escape(str(value))}</b><span>{escape(label)}</span></div>"
        for label, value in items
    )
    return f"<div class='grid'>{cells}</div>"


def table(
    headers: Iterable[str], rows: Iterable[Iterable[str]], *, empty: str = "Nothing here."
) -> str:
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    if not body:
        return f"<p class='empty'>{escape(empty)}</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    return (
        f"<div class='scroll'><table><thead><tr>{head}</tr></thead>"
        f"<tbody>{body}</tbody></table></div>"
    )


def chip(text: str, tone: str = "") -> str:
    return f"<span class='chip {tone}'>{escape(text)}</span>"


def quote(text: str, *, source: str = "") -> str:
    tail = f" <span class='mono'>{escape(source)}</span>" if source else ""
    return f"<div class='quote'>{escape(text)}{tail}</div>"


def panel(title: str, body: str) -> str:
    heading = f"<h2 style='margin-top:0'>{escape(title)}</h2>" if title else ""
    return f"<div class='panel'>{heading}{body}</div>"


TONES = {
    "pass": "pass",
    "fail": "fail",
    "undecided": "warn",
    "not_applicable": "idle",
    "blocker": "fail",
    "error": "fail",
    "warning": "warn",
    "info": "idle",
    "advisory": "idle",
    "admitted": "pass",
    "review": "warn",
    "rejected": "idle",
    "conflicted": "fail",
    "superseded": "idle",
}


def tone(value: str) -> str:
    return TONES.get(value, "")
