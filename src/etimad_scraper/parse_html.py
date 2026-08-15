"""Parsers for the two per-tender HTML sources (not JSON APIs):

- OpenTenderDetailsReportForVisitor: a static "print view" page with a
  single <th>label</th><td>value</td> table. Chosen over the interactive
  DetailsForVisitor page specifically because it's plain server-rendered
  HTML with no client-side Vue state to fight with.
- GetAwardingResultsForVisitorViewComponenet: an HTML fragment (not JSON)
  with up to two tables - all bidders, and whichever of them were awarded.
  Empty (no tables) for tenders not yet awarded.

Both take raw HTML text and return plain dicts/lists - no network code
here, so these can be tested directly against real captured HTML without
hitting the site.
"""

import re

from bs4 import BeautifulSoup

# Only the fields not already covered by current_tenders (see db.FIELD_MAP).
# Maps the exact <th> label text on the report page to our output key.
_BASIC_INFO_LABELS = {
    "قيمة المنافسة": "tender_value",
    "الغاية من المنافسة": "tender_purpose",
    "فترة التوقف": "standstill_period",
    "التاريخ المتوقع للترسية": "expected_award_date_raw",
    "تاريخ بدء الأعمال / الخدمات": "work_start_date_raw",
    "مكان تقديم العروض": "offer_submission_location",
    "مكان فتح العروض": "offer_opening_location",
    "مكان التنفيذ": "execution_location",
    "مجال التصنيف": "classification",
}


def _extract_gregorian_date(text: str) -> str | None:
    """Etimad prints these date fields as 'التاريخ: <hijri>\nالموافق: <gregorian>'.
    Hijri conversion is out of scope for now - just pull the Gregorian half,
    since that's directly usable for analysis."""
    match = re.search(r"الموافق:\s*([\d/]+)", text)
    return match.group(1) if match else None


def parse_basic_info_report(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {key: None for key in _BASIC_INFO_LABELS.values()}

    for row in soup.select("table tr"):
        label_cell = row.find("th")
        value_cell = row.find("td")
        if label_cell is None or value_cell is None:
            continue

        label = label_cell.get_text(strip=True)
        key = _BASIC_INFO_LABELS.get(label)
        if key is None:
            continue

        if key == "classification":
            items = [li.get_text(strip=True) for li in value_cell.find_all("li")]
            result[key] = ", ".join(item for item in items if item) or None
            continue

        text = value_cell.get_text(separator="\n", strip=True)
        result[key] = text or None

    for raw_key, gregorian_key in (
        ("expected_award_date_raw", "expected_award_date"),
        ("work_start_date_raw", "work_start_date"),
    ):
        raw_value = result.get(raw_key)
        result[gregorian_key] = _extract_gregorian_date(raw_value) if raw_value else None

    return result


def _parse_money(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_awarding_results(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    bidders: list[dict] = []
    awarded: list[dict] = []

    for heading in soup.find_all("h4"):
        table = heading.find_next("table")
        if table is None:
            continue

        rows = table.select("tbody tr")
        is_award_table = "المرسى عليهم" in heading.get_text()

        for row in rows:
            cells = row.find_all("td")
            if len(cells) != 3:
                continue
            supplier_name = cells[0].get_text(strip=True)
            financial_offer = _parse_money(cells[1].get_text(strip=True))

            if is_award_table:
                awarded.append(
                    {
                        "supplier_name": supplier_name,
                        "financial_offer": financial_offer,
                        "award_value": _parse_money(cells[2].get_text(strip=True)),
                    }
                )
            else:
                bidders.append(
                    {
                        "supplier_name": supplier_name,
                        "financial_offer": financial_offer,
                        "technical_result": cells[2].get_text(strip=True),
                    }
                )

    return {"bidders": bidders, "awarded": awarded}
