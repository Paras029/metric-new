from __future__ import annotations

import threading
from http.client import HTTPConnection
from urllib.parse import urlencode

import pytest

from metric.ui import layout, views
from metric.ui.html import page
from metric.ui.server import _handler


@pytest.fixture()
def client(reviewable):
    """The real server on a real socket — routing and redirects included."""
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(reviewable))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield reviewable, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def get(port: int, path: str) -> tuple[int, str]:
    connection = HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    body = response.read().decode("utf-8")
    connection.close()
    return response.status, body


class TestViewsRender:
    @pytest.mark.parametrize(
        "view",
        [views.overview, views.workflow, views.graph_view, views.scenarios,
         views.evaluations, views.questions],
    )
    def test_a_view_produces_a_whole_page(self, built, view) -> None:
        html = page("t", "/", built.identity, view(built))
        assert html.startswith("<!doctype html>")
        assert "</html>" in html

    def test_the_workflow_draws_every_state_once(self, built) -> None:
        nodes, edges, width, height = layout.layout(built.graph)
        assert len({n.id for n in nodes}) == len(nodes)
        assert width > 0 and height > 0
        assert any(e.back for e in edges), "the retry loop is a back edge"

    def test_a_back_edge_is_routed_clear_of_the_nodes(self, built) -> None:
        nodes, _edges, width, _height = layout.layout(built.graph)
        right = max(n.x + layout.BOX_W for n in nodes)
        svg = layout.render(built.graph)
        assert f"L{right + layout.PAD:.0f}," in svg
        assert width > right, "the lane needs room beyond the widest node"

    def test_evidence_links_back_to_the_source(self, built) -> None:
        assert "/passage/" in views.evaluations(built)

    def test_a_missing_entity_does_not_explode(self, built) -> None:
        assert "Not found" in views.entity_view(built, "Tool:nothing")


class TestServer:
    @pytest.mark.parametrize(
        "path", ["/", "/workflow", "/graph", "/scenarios", "/evaluations", "/questions"]
    )
    def test_every_page_answers(self, client, path) -> None:
        _, port = client
        status, body = get(port, path)
        assert status == 200
        assert "<main>" in body

    def test_an_unknown_path_is_a_404_not_a_traceback(self, client) -> None:
        _, port = client
        assert get(port, "/nowhere")[0] == 404

    def test_a_filter_narrows_the_graph(self, client) -> None:
        _, port = client
        _, body = get(port, "/graph?relation=RETURNS")
        assert "RETURNS" in body
        assert "HAS_NEXT_STEP" not in body.split("<tbody>")[1]

    def test_answering_records_the_decision_and_redirects(self, client) -> None:
        space, port = client
        question = next(
            q for q in space.result.questions if q.kind == "review/unwitnessed"
        )

        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        body = urlencode({"id": question.id, "answer": "approve"})
        connection.request(
            "POST", "/answer", body, {"Content-Type": "application/x-www-form-urlencoded"}
        )
        response = connection.getresponse()
        response.read()
        connection.close()

        assert response.status == 303
        assert response.getheader("Location") == "/questions"
        assert space.decisions[question.id].answer == "approve"
        assert space.questions_path.exists()

    def test_answering_something_that_is_not_open_is_refused(self, client) -> None:
        _, port = client
        connection = HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request(
            "POST",
            "/answer",
            urlencode({"id": "nope", "answer": "approve"}),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 400
