"""A Common Crawl stand-in for tests."""

import json

import httpx

COLLINFO = [
    {"id": "CC-MAIN-2026-05", "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-05-index"},
    {"id": "CC-MAIN-2025-50", "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2025-50-index"},
]


def lines(*urls):
    return "\n".join(json.dumps({"url": u}) for u in urls) + "\n"


def fake_index(pages_by_host, *, fail_with=None, seen=None):
    """A Common Crawl stand-in. `pages_by_host` maps a host to its list of result pages."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if seen is not None:
            seen.append(str(request.url))
        if request.url.path == "/collinfo.json":
            return httpx.Response(200, json=COLLINFO)
        assert request.url.path == "/CC-MAIN-2026-05-index"  # the latest index only
        if fail_with is not None:
            return httpx.Response(fail_with)
        host = request.url.params["url"].removesuffix("/*")
        pages = pages_by_host[host]
        if request.url.params.get("showNumPages") == "true":
            return httpx.Response(200, json={"pages": len(pages), "pageSize": 5, "blocks": 9})
        return httpx.Response(200, text=pages[int(request.url.params["page"])])

    return httpx.Client(transport=httpx.MockTransport(handle))
