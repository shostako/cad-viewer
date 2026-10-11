"""The app's requests to its engine, for the E2E scripts, on both versions.

Over HTTP (the checkout's version: the backend) a script holds, answers or
breaks a request with page.route, and watches them with page.on("request").
The Web version has no HTTP for them: its engine is a Worker in the page
(frontend/src/local/client.ts). These helpers do the same on both, by the
request's URL as page.route takes it (the same glob patterns):

    net = engine_net.Net(page)
    net.route("**/mesh.bin", lambda r: r.fulfill(status=500, body="no"))
    net.unroute("**/mesh.bin")
    net.on_request(lambda r: seen.append(r.url))
    with net.expect_response(lambda r: r.url.endswith("/api/models")):
        ...

and the API itself, as page.request takes it (a script's own request, not
the app's: not routed):

    engine_net.api(page, "GET", f"/api/models/{id}/sidecar").json()
    engine_net.upload(page, path).json()

Which version the page is: CAD_VIEWER_ENGINE=local (CI's e2e (web) job), else http.

On the Web version: the page's engine asks window.__cadEngineNet, which these
helpers put there; a request a handler holds (decides later) waits in the
page until the script decides it.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

# Playwright's own glob -> regex (not a public API: playwright is pinned to 1.58.0
# in CLAUDE.md and CI; on an upgrade, check it is still there)
from playwright._impl._glob import glob_to_regex_pattern

LOCAL = os.environ.get("CAD_VIEWER_ENGINE", "http") == "local"

_HOOK = r"""
(() => {
  if (window.__cadEngineNet) return
  const st = { routes: [], decisions: {}, observing: false }
  window.__cadEngineNetState = st
  // the routes a script set before this page loaded (page.goto after net.route);
  // a request waits for them (one made at the page's start would slip past otherwise)
  st.ready = window.__cadEngineRoutesCall().then((r) => {
    st.routes = r.routes
    st.observing = r.observing
  })
  window.__cadEngineNet = {
    async route(req) {
      await st.ready
      if (!st.routes.some((re) => new RegExp(re).test(req.url))) return { action: 'continue' }
      let r = await window.__cadEngineRouteCall(req)
      while (r.pending) {
        await new Promise((ok) => setTimeout(ok, 20))
        const d = st.decisions[r.token]
        if (d) {
          delete st.decisions[r.token]
          r = d
        }
      }
      return r
    },
    observe(ev) {
      if (st.observing) window.__cadEngineObserveCall(ev)
    },
  }
})()
"""


class Request:
    def __init__(self, url: str, method: str, post_data: str | None = None) -> None:
        self.url = url
        self.method = method
        self.post_data = post_data

    @property
    def post_data_json(self):
        return json.loads(self.post_data) if self.post_data else None


class Response:
    def __init__(self, url: str, method: str, status: int) -> None:
        self.url = url
        self.status = status
        self.request = Request(url, method)
        self.ok = 200 <= status < 300


class Route:
    """a request held for a script (page.route's Route, as far as the scripts use it)"""

    def __init__(self, net: "Net", token: int, request: Request) -> None:
        self._net = net
        self._token = token
        self.request = request
        self.decision: dict | None = None

    def _decide(self, d: dict) -> None:
        if self.decision is not None:
            raise RuntimeError("route already handled")
        self.decision = d
        if not self._net._in_call:
            self._net.page.evaluate("([t, d]) => { window.__cadEngineNetState.decisions[t] = d }", [self._token, d])

    def continue_(self, **_kw) -> None:
        self._decide({"action": "continue"})

    fallback = continue_

    def abort(self, *_a, **_kw) -> None:
        self._decide({"action": "abort"})

    def fulfill(self, status: int = 200, body: str | bytes | None = None, json: object = None,
                content_type: str | None = None, **_kw) -> None:
        if json is not None:
            body, content_type = __import__("json").dumps(json), content_type or "application/json"
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        self._decide({"action": "fulfill", "status": status, "body": body or "", "contentType": content_type or "text/plain"})


class Net:
    """one per page (Net.of(page)): the page's bindings are made once"""

    @staticmethod
    def of(page) -> "Net":
        net = getattr(page, "_cad_engine_net", None)
        if net is None:
            net = Net(page)
            page._cad_engine_net = net
        return net

    def __init__(self, page) -> None:
        self.page = page
        self._routes: list[tuple[str, str, object]] = []  # (pattern, regex, handler), the last one first
        self._observers: list = []
        self._responses: list = []
        self._ends: list = []  # (event, the requests seen) for expect_event
        self._token = 0
        self._in_call = False
        if LOCAL:
            page.expose_binding("__cadEngineRouteCall", lambda _src, req: self._route_call(req))
            page.expose_binding("__cadEngineObserveCall", lambda _src, ev: self._observe_call(ev))
            page.expose_binding("__cadEngineRoutesCall", lambda _src: self._state())
            page.add_init_script(_HOOK)
            page.evaluate(_HOOK)

    # ---- routes --------------------------------------------------------------

    def route(self, pattern, handler) -> None:
        """pattern: a glob or a compiled regex, as page.route takes them"""
        if not LOCAL:
            self.page.route(pattern, handler)
            return
        regex = pattern.pattern if isinstance(pattern, re.Pattern) else glob_to_regex_pattern(pattern)
        self._routes.insert(0, (pattern, regex, handler))
        self._sync()

    def unroute(self, pattern: str) -> None:
        if not LOCAL:
            self.page.unroute(pattern)
            return
        self._routes = [r for r in self._routes if r[0] != pattern]
        self._sync()

    def _state(self) -> dict:
        return {"routes": [r[1] for r in self._routes], "observing": bool(self._observers or self._responses or self._ends)}

    def _sync(self) -> None:
        self.page.evaluate(
            "(s) => { const st = window.__cadEngineNetState; if (st) { st.routes = s.routes; st.observing = s.observing } }",
            self._state(),
        )

    def _route_call(self, req: dict) -> dict:
        request = Request(req["url"], req["method"], req.get("postData"))
        for _pattern, regex, handler in self._routes:
            if not re.search(regex, request.url):
                continue
            self._token += 1
            route = Route(self, self._token, request)
            self._in_call = True
            try:
                handler(route)
            finally:
                self._in_call = False
            if route.decision is None:
                return {"pending": True, "token": route._token}  # held: decided later
            if route.decision["action"] != "continue":
                return route.decision
            # continue_ / fallback: the next route, as page.route's fallback; none, the engine
        return {"action": "continue"}

    # ---- watching -------------------------------------------------------------

    def on_request(self, fn) -> None:
        if not LOCAL:
            self.page.on("request", fn)
            return
        self._observers.append(fn)
        self._sync()

    def _observe_call(self, ev: dict) -> None:
        if ev.get("failed"):
            for kind, pending in self._ends:
                if kind == "requestfailed":
                    pending.append(Request(ev["url"], ev["method"]))
        elif ev.get("status") is None:
            for fn in self._observers:
                fn(Request(ev["url"], ev["method"]))
        else:
            for pending in self._responses:
                pending.append(Response(ev["url"], ev["method"], ev["status"]))
            for kind, pending in self._ends:
                if kind == "requestfinished":
                    pending.append(Request(ev["url"], ev["method"]))

    @contextmanager
    def expect_event(self, event: str, predicate=None, timeout: float = 30000):
        """page.expect_event for "requestfinished" / "requestfailed" (the predicate takes the request)"""
        if not LOCAL:
            with self.page.expect_event(event, predicate, timeout=timeout) as info:
                yield info
            return
        if event not in ("requestfinished", "requestfailed"):
            raise ValueError(event)
        seen: list[Request] = []
        entry = (event, seen)
        self._ends.append(entry)
        self._sync()
        holder = _Holder()
        try:
            yield holder
            deadline = time.monotonic() + timeout / 1000
            while True:
                found = next((r for r in seen if predicate is None or predicate(r)), None)
                if found is not None:
                    holder.value = found
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(f"no {event} from the engine")
                self.page.wait_for_timeout(20)
        finally:
            self._ends.remove(entry)
            self._sync()

    def expect_request_finished(self, predicate=None, timeout: float = 30000):
        if not LOCAL:
            return self.page.expect_request_finished(predicate, timeout=timeout)
        return self.expect_event("requestfinished", predicate, timeout)

    @contextmanager
    def expect_response(self, predicate, timeout: float = 30000):
        if not LOCAL:
            with self.page.expect_response(predicate, timeout=timeout) as info:
                yield info
            return
        seen: list[Response] = []
        self._responses.append(seen)
        self._sync()
        holder = _Holder()
        try:
            yield holder
            deadline = time.monotonic() + timeout / 1000
            while True:
                found = next((r for r in seen if predicate(r)), None)
                if found is not None:
                    holder.value = found
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("no matching response from the engine")
                self.page.wait_for_timeout(20)
        finally:
            self._responses.remove(seen)
            self._sync()


class _Holder:
    value = None


# ---- the API, as a script's own request (page.request over HTTP) ----------------------


class ApiResponse:
    def __init__(self, status: int, body=None, raw: bytes | None = None) -> None:
        self.status = status
        self.ok = 200 <= status < 300
        self._body = body
        self._raw = raw

    def json(self):
        return self._body if self._raw is None else json.loads(self._raw)

    def body(self) -> bytes:
        return self._raw if self._raw is not None else json.dumps(self._body).encode()

    def text(self) -> str:
        return self.body().decode("utf-8", "replace")


def _local(page, method: str, path: str, body=None) -> ApiResponse:
    r = page.evaluate("([m, p, b]) => window.__cadEngineRequest(m, p, b)", [method, path, body])
    if "base64" in r:
        return ApiResponse(r["status"], raw=base64.b64decode(r["base64"]))
    return ApiResponse(r["status"], body=r.get("body"))


def api(page, method: str, path: str, data=None, timeout: float = 120000):
    """a request to the engine's API (path from /api) as page.request makes it"""
    if LOCAL:
        return _local(page, method, path, data)
    from nav_common import BASE_URL  # noqa: PLC0415 — nav_common imports this module

    url = f"{BASE_URL}{path}"
    if method == "GET":
        return page.request.get(url, timeout=timeout)
    if method == "PUT":
        return page.request.put(url, data=data, timeout=timeout)
    if method == "POST":
        return page.request.post(url, data=data, timeout=timeout)
    raise ValueError(method)


def upload(page, path, timeout: float = 120000):
    """POST /api/models with the file, as page.request makes it"""
    path = Path(path)
    if LOCAL:
        return _local(page, "POST", "/api/models", {"name": path.name, "base64": base64.b64encode(path.read_bytes()).decode()})
    from nav_common import BASE_URL  # noqa: PLC0415

    return page.request.post(
        f"{BASE_URL}/api/models",
        multipart={"file": {"name": path.name, "mimeType": "application/octet-stream", "buffer": path.read_bytes()}},
        timeout=timeout,
    )
