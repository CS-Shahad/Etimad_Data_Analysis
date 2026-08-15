import httpx

from .http_retry import get_with_retry


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


def _get_with_rate_limit_retry(
    client: httpx.Client, cfg: dict, context_label: str, **get_kwargs
) -> httpx.Response:
    retry_cfg = cfg["request"].get("rate_limit_retry", {})

    def on_retry(attempt: int, wait_seconds: float) -> None:
        print(
            f"    429 على {context_label} (محاولة {attempt}) -> "
            f"انتظار {wait_seconds:.0f} ثانية"
        )

    return get_with_retry(
        lambda: client.get(**get_kwargs),
        max_retries=retry_cfg.get("max_retries", 6),
        default_backoff_seconds=retry_cfg.get("default_backoff_seconds", 5.0),
        max_backoff_seconds=retry_cfg.get("max_backoff_seconds", 90.0),
        on_retry=on_retry,
    )


def fetch_tenders_page(
    client: httpx.Client, cfg: dict, page_number: int, page_size: int
) -> httpx.Response:
    """Fetches one page, transparently retrying on 429 (observed in
    production around page ~177 of a full collection run) instead of
    letting a temporary rate limit abort a multi-minute run.
    """
    api_path = cfg["current_tenders"]["api_path"]
    params = dict(cfg["current_tenders"]["default_params"])
    params.update({"PageSize": page_size, "pageNumber": page_number})

    referer = f"{cfg['base_url']}{cfg['current_tenders']['bootstrap_path']}?PageNumber={page_number}"
    headers = {
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    return _get_with_rate_limit_retry(
        client, cfg, f"صفحة {page_number}", url=api_path, params=params, headers=headers
    )


def fetch_awarding_results(
    client: httpx.Client, cfg: dict, tender_id_string: str
) -> httpx.Response:
    """GetAwardingResultsForVisitorViewComponenet - an HTML fragment (not
    JSON), empty for tenders not yet awarded. tenderIdStr is the same
    obfuscated id stored as tender_id_string in current_tenders.
    """
    referer = f"{cfg['base_url']}{cfg['tender_details']['details_page_path']}?STenderId={tender_id_string}"
    headers = {
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer,
    }
    return _get_with_rate_limit_retry(
        client,
        cfg,
        f"نتائج ترسية {tender_id_string}",
        url=cfg["tender_details"]["awarding_results_path"],
        params={"tenderIdStr": tender_id_string},
        headers=headers,
    )


def fetch_basic_info_report(
    client: httpx.Client, cfg: dict, tender_id_string: str
) -> httpx.Response:
    """OpenTenderDetailsReportForVisitor - the static print-view page. No
    Referer needed (observed opening it directly, e.g. via window.open,
    carries none)."""
    return _get_with_rate_limit_retry(
        client,
        cfg,
        f"تقرير أساسي {tender_id_string}",
        url=cfg["tender_details"]["basic_info_report_path"],
        params={"tenderIdString": tender_id_string},
        headers={"Accept": "text/html"},
    )
