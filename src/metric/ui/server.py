"""The server: stdlib only.

No framework and no Node. An evaluation tool that needs a package manager, a build
step and a CDN to render is a tool that will not be installed on the machine where the
policies live. `python -m metric.cli ui` and a browser is the whole deployment.

Answering a question is a POST followed by a redirect, so a refresh cannot re-answer
it, and the rebuild happens inline — the effect of approving something is visible on
the next page rather than the next run.
"""

from __future__ import annotations

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from metric.ui import views
from metric.ui.html import page
from metric.workspace import Workspace

Route = Callable[[Workspace, dict[str, str], list[str]], tuple[str, str]]


def _overview(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Overview", views.overview(space)


def _workflow(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Workflow", views.workflow(space)


def _graph(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Graph", views.graph_view(
        space, relation=query.get("relation", ""), status=query.get("status", "")
    )


def _entity(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Entity", views.entity_view(space, unquote(rest[0]) if rest else "")


def _scenarios(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Scenarios", views.scenarios(space)


def _scenario(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Scenario", views.scenario_view(space, unquote(rest[0]) if rest else "")


def _evaluations(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Evaluations", views.evaluations(space)


def _trace(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Trace", views.trace_view(space, _int(rest[0] if rest else "0"))


def _quarantine(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Quarantine", views.quarantine(space)


def _questions(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Review", views.questions(space)


def _passage(space: Workspace, query: dict[str, str], rest: list[str]) -> tuple[str, str]:
    return "Source", views.passage_view(
        space,
        unquote(rest[0]) if rest else "",
        start=_int(query.get("start", "0")),
        end=_int(query.get("end", "0")),
    )


ROUTES: dict[str, Route] = {
    "": _overview,
    "workflow": _workflow,
    "graph": _graph,
    "entity": _entity,
    "scenarios": _scenarios,
    "scenario": _scenario,
    "evaluations": _evaluations,
    "trace": _trace,
    "quarantine": _quarantine,
    "questions": _questions,
    "passage": _passage,
}

_ACTIVE = {
    "": "/",
    "workflow": "/workflow",
    "graph": "/graph",
    "entity": "/graph",
    "scenarios": "/scenarios",
    "scenario": "/scenarios",
    "evaluations": "/evaluations",
    "trace": "/evaluations",
    "quarantine": "/quarantine",
    "questions": "/questions",
    "passage": "/graph",
}


def serve(space: Workspace, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), _handler(space))
    print(f"metric ui on http://{host}:{port}  (ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


def _handler(space: Workspace) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "metric"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            head = parts[0] if parts else ""
            route = ROUTES.get(head)

            if route is None:
                self._send(404, page("Not found", "/", space.identity, "<h1>Not found</h1>"))
                return

            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            title, body = route(space, query, parts[1:])
            self._send(200, page(title, _ACTIVE[head], space.identity, body))

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/answer":
                self._send(404, page("Not found", "/", space.identity, "<h1>Not found</h1>"))
                return

            length = int(self.headers.get("Content-Length", "0"))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            question = form.get("id", [""])[0]
            answer = form.get("answer", [""])[0]

            try:
                space.answer(question, answer)
            except (KeyError, ValueError) as exc:
                body = f"<h1>Could not record that</h1><p class='lede'>{exc}</p>"
                self._send(400, page("Review", "/questions", space.identity, body))
                return

            self.send_response(303)
            self.send_header("Location", "/questions")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def _int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
