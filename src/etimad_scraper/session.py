import httpx


def build_session(cfg: dict) -> httpx.Client:
    """A plain HTTP session (no browser engine). Cookies are handled
    automatically by httpx.Client across requests, same as a browser's
    cookie jar. Falls back to Playwright-based session bootstrap (not
    implemented yet) if the site's WAF turns out to require executing a
    JS challenge instead of a plain Set-Cookie handshake.
    """
    headers = {
        "User-Agent": cfg["request"]["user_agent"],
        "Accept-Language": "en-US,en;q=0.9",
    }
    return httpx.Client(
        base_url=cfg["base_url"],
        headers=headers,
        timeout=cfg["request"]["timeout_seconds"],
        follow_redirects=True,
    )


def warm_up(client: httpx.Client, cfg: dict, page_number: int = 1) -> httpx.Response:
    """Visits the human-facing listing page first so the server issues its
    WAF/antiforgery cookies into the client's cookie jar, mirroring what a
    real browser does before the page's JS fires the AJAX call.
    """
    path = cfg["current_tenders"]["bootstrap_path"]
    resp = client.get(path, params={"PageNumber": page_number})
    resp.raise_for_status()
    return resp


def fetch_tenders_page(
    client: httpx.Client, cfg: dict, page_number: int, page_size: int
) -> httpx.Response:
    api_path = cfg["current_tenders"]["api_path"]
    params = dict(cfg["current_tenders"]["default_params"])
    params.update({"PageSize": page_size, "pageNumber": page_number})

    referer = f"{cfg['base_url']}{cfg['current_tenders']['bootstrap_path']}?PageNumber={page_number}"
    headers = {
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    return client.get(api_path, params=params, headers=headers)
