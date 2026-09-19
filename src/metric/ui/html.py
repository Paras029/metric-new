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
/* Three voices, and the rule between them is the design.
   - instrument: the system sans. Everything the tool says about itself.
   - source:     a serif, and ONLY ever the policy's own words. Set larger than the
                 interface around it, because the document is the authority and this is
                 the apparatus reading it.
   - record:     mono with tabular figures. Ids, relation names, counts, intervals —
                 anything that has to line up or be copied exactly.
   No font is fetched. An internal network usually cannot reach a font host, and a tool
   that renders unstyled behind the firewall is a tool nobody uses. */
:root {
  --paper:#f7f7f6; --leaf:#ffffff; --ink:#14161a; --slate:#5e646e; --rule:#e4e5e3;
  --seal:#1f4e5f; --met:#22614a; --out:#8c3a2b; --held:#8a5a0b; --idle:#7c828b;
  --wash:rgba(31,78,95,.07); --tint:#eef1f1;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper:#111318; --leaf:#171a20; --ink:#e9e8e5; --slate:#9aa0a8; --rule:#272b33;
    --seal:#79b4c4; --met:#5cbf8a; --out:#e08d78; --held:#d9ab55; --idle:#8b919a;
    --wash:rgba(121,180,196,.10); --tint:#1e232b;
  }
}
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:15px/1.55 var(--sans); font-variant-numeric:tabular-nums;
  -webkit-font-smoothing:antialiased; }
a { color:var(--seal); text-decoration:none; }
a:hover { text-decoration:underline; text-underline-offset:2px; }
:focus-visible { outline:2px solid var(--seal); outline-offset:2px; border-radius:3px; }

/* The docket bar. The build fingerprint sits in it because every number on every page
   below is only true of that build. */
header { border-bottom:1px solid var(--rule); background:var(--leaf);
  position:sticky; top:0; z-index:20; }
header .bar { max-width:1140px; margin:0 auto; padding:0 20px; display:flex;
  align-items:stretch; gap:22px; flex-wrap:wrap; }
header .mark { font-weight:660; letter-spacing:-.02em; align-self:center;
  padding-right:2px; }
header .mark::after { content:""; display:inline-block; width:5px; height:5px;
  margin-left:7px; border-radius:50%; background:var(--seal); vertical-align:middle; }
header nav { display:flex; gap:2px; flex-wrap:wrap; }
header nav a { color:var(--slate); font-size:13.5px; padding:14px 9px 12px;
  border-bottom:2px solid transparent; }
header nav a:hover { color:var(--ink); text-decoration:none; }
header nav a.on { color:var(--ink); font-weight:560; border-bottom-color:var(--seal); }
header .id { margin-left:auto; align-self:center; color:var(--slate); font-size:11.5px;
  font-family:var(--mono); letter-spacing:-.01em; }

main { max-width:1140px; margin:0 auto; padding:30px 20px 90px; }
h1 { font-size:23px; margin:0 0 20px; letter-spacing:-.022em; font-weight:640; }
h2 { font-size:15px; margin:30px 0 10px; letter-spacing:-.01em; }
/* A lede tucks up under its h1; anywhere else it is just a paragraph and needs room. */
p.lede { color:var(--slate); margin:12px 0 0; max-width:66ch; font-size:14px; }
h1 + p.lede { margin:-14px 0 22px; }
.panel > .eyebrow + p.lede { margin-top:0; }

/* A panel title is a field label, not a heading: small, mono, spaced. It names the
   contents rather than competing with them. */
.panel { background:var(--leaf); border:1px solid var(--rule); border-radius:10px;
  padding:15px 18px 17px; margin-bottom:13px; }
.panel > .eyebrow { font-family:var(--mono); font-size:10.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--slate); display:block; margin:0 0 12px; }

/* Figures are grouped by what kind of number they are, not laid out as equal tiles.
   A count of facts and a count of unanswered questions are different things. */
.figures { display:grid; gap:13px; grid-template-columns:repeat(auto-fit,minmax(215px,1fr));
  margin-bottom:13px; }
.figures .set { background:var(--leaf); border:1px solid var(--rule); border-radius:10px;
  padding:14px 17px 15px; }
.figures .set > .eyebrow { font-family:var(--mono); font-size:10.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--slate); display:block; margin-bottom:11px; }
.figures .row { display:flex; align-items:baseline; gap:8px; margin-top:7px; }
.figures .row:first-of-type { margin-top:0; }
.figures b { font-size:26px; font-weight:620; letter-spacing:-.035em; line-height:1;
  min-width:1.6em; }
.figures .row.minor b { font-size:17px; font-weight:600; color:var(--slate); }
.figures span { color:var(--slate); font-size:12.5px; }
.figures .set.attention { border-color:color-mix(in srgb,var(--held) 42%,var(--rule)); }
.figures .set.attention b { color:var(--held); }

table { width:100%; border-collapse:collapse; font-size:13.5px; }
/* The evidence column is the point of the table, so it gets room rather than the
   scraps left over by everything else. */
table th:last-child, table td:last-child { min-width:19ch; }
th { text-align:left; font-weight:600; color:var(--slate); font-family:var(--mono);
  font-size:10.5px; text-transform:uppercase; letter-spacing:.09em;
  padding:0 12px 8px 0; border-bottom:1px solid var(--rule); }
td { padding:9px 12px 9px 0; border-bottom:1px solid var(--rule); vertical-align:top; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:var(--wash); }
/* The standing rail: one vertical line a reviewer can scan for anything not settled. */
tbody tr[data-rail] td:first-child { border-left:3px solid transparent; padding-left:11px; }
tbody tr[data-rail="held"] td:first-child { border-left-color:var(--held); }
tbody tr[data-rail="out"] td:first-child { border-left-color:var(--out); }
tbody tr[data-rail="met"] td:first-child { border-left-color:var(--met); }
tbody tr[data-rail="idle"] td:first-child { border-left-color:var(--rule); }

code, .mono { font-family:var(--mono); font-size:12px; letter-spacing:-.01em; }

.chip { display:inline-block; padding:2px 9px 3px; border-radius:5px; background:var(--tint);
  color:var(--slate); font-size:11px; font-weight:520; white-space:nowrap;
  letter-spacing:.005em; }
.chip.pass { color:var(--met); background:color-mix(in srgb,var(--met) 11%,transparent); }
.chip.fail { color:var(--out); background:color-mix(in srgb,var(--out) 11%,transparent); }
.chip.warn { color:var(--held); background:color-mix(in srgb,var(--held) 12%,transparent); }
.chip.idle { color:var(--idle); }

/* THE SIGNATURE. Source text is the only serif on the page and it is set larger than
   the interface around it. Every other tool shrinks evidence to grey 12px; this one
   exists to put a claim next to the sentence that supports it, so the sentence wins. */
.quote { font-family:var(--serif); font-size:15.5px; line-height:1.5; color:var(--ink);
  border-left:2px solid var(--seal); background:var(--wash);
  padding:9px 14px 10px 15px; margin:9px 0; border-radius:0 6px 6px 0; }
.quote .locator { font-family:var(--mono); font-size:10.5px; letter-spacing:.06em;
  text-transform:uppercase; color:var(--slate); display:block; margin-bottom:4px; }

form.inline { display:inline; }
select, input[type=text] { font:inherit; font-size:12.5px; color:var(--ink);
  background:var(--leaf); border:1px solid var(--rule); border-radius:6px;
  padding:5px 9px; appearance:none; cursor:pointer;
  background-image:linear-gradient(45deg,transparent 50%,var(--slate) 50%),
    linear-gradient(135deg,var(--slate) 50%,transparent 50%);
  background-position:calc(100% - 15px) 52%,calc(100% - 11px) 52%;
  background-size:4px 4px,4px 4px; background-repeat:no-repeat; padding-right:28px; }
select:hover { border-color:var(--seal); }
button { font:inherit; font-size:12.5px; font-weight:520; padding:5px 12px;
  border-radius:6px; border:1px solid var(--rule); background:var(--leaf);
  color:var(--slate); cursor:pointer; transition:border-color .12s,color .12s; }
button:hover { border-color:var(--seal); color:var(--seal); }
button.primary { border-color:color-mix(in srgb,var(--met) 45%,var(--rule));
  color:var(--met); }
button.primary:hover { border-color:var(--met); }
.empty { color:var(--slate); }
/* A question's detail may carry a list. It is written as plain text because it also
   goes to questions.yaml and to the terminal, so the line breaks have to survive here
   rather than be re-encoded as markup for one of the three. */
.detail { white-space:pre-line; }
mark { background:color-mix(in srgb,var(--held) 26%,transparent); color:inherit;
  padding:1px 1px; border-radius:2px; }
details summary { cursor:pointer; color:var(--slate); font-size:13px; }
.scroll { overflow-x:auto; }
svg { max-width:100%; height:auto; display:block; margin:0 auto; }

/* One short settling motion on load, and nothing else. */
.panel, .figures .set { animation:rise .34s cubic-bezier(.2,.7,.3,1) both; }
.figures .set:nth-child(2) { animation-delay:.04s; }
.figures .set:nth-child(3) { animation-delay:.08s; }
@keyframes rise { from { opacity:0; transform:translateY(5px); } }
@media (prefers-reduced-motion: reduce) {
  * { animation:none !important; transition:none !important; }
}
@media (max-width:640px) {
  main { padding:22px 16px 60px; }
  header .bar { padding:0 16px; }
  header .id { display:none; }
  h1 { font-size:20px; }
  /* Let a table scroll rather than squeeze. A column of one word per line is not a
     narrower table, it is an unreadable one. */
  .scroll table { min-width:560px; }
  .quote { font-size:15px; }
}
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


def figures(groups: Iterable[tuple[str, Iterable[tuple[str, Any]]]]) -> str:
    """Counts grouped by what kind of number they are.

    Six equal tiles say every figure carries the same weight. They do not: how many
    facts the graph holds, how many of them nobody has confirmed, and how big the test
    space is are three different questions, and only one of them is a call to act. A
    group whose name starts with `!` is that one, and is marked.
    """
    sets = []
    for name, items in groups:
        attention = name.startswith("!")
        rows = [
            f"<div class='row{'' if index == 0 else ' minor'}'>"
            f"<b>{escape(str(value))}</b><span>{escape(label)}</span></div>"
            for index, (label, value) in enumerate(items)
        ]
        sets.append(
            f"<div class='set{' attention' if attention else ''}'>"
            f"<span class='eyebrow'>{escape(name.lstrip('!'))}</span>"
            + "".join(rows)
            + "</div>"
        )
    return f"<div class='figures'>{''.join(sets)}</div>"


def stats(items: Iterable[tuple[str, Any]]) -> str:
    """One ungrouped set, for pages where the figures are all of a kind."""
    return figures([("", items)])


def table(
    headers: Iterable[str],
    rows: Iterable[Iterable[str]],
    *,
    empty: str = "Nothing here.",
    rails: Iterable[str] | None = None,
) -> str:
    """A table, optionally with a standing rail down its left edge.

    `rails` gives one tone per row — `met`, `held`, `out`, `idle`. It puts everything
    not yet settled on a single vertical line, which is what a reviewer is scanning
    for and what a row of coloured chips scattered across six columns is not.
    """
    marks = list(rails or ())
    body = "".join(
        f"<tr{f' data-rail={marks[index]}' if index < len(marks) and marks[index] else ''}>"
        + "".join(f"<td>{cell}</td>" for cell in row)
        + "</tr>"
        for index, row in enumerate(rows)
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
    """The source's own words, and where they came from.

    The only serif on the page, and set larger than the interface around it. The whole
    product exists to put a claim next to the sentence that supports it, so the
    sentence is what should be easy to read.
    """
    locator = f"<span class='locator'>{escape(source)}</span>" if source else ""
    return f"<div class='quote'>{locator}{escape(text)}</div>"


def panel(title: str, body: str) -> str:
    heading = f"<span class='eyebrow'>{escape(title)}</span>" if title else ""
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
