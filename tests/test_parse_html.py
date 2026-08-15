import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from etimad_scraper.parse_html import parse_awarding_results, parse_basic_info_report

# Real HTML captured from OpenTenderDetailsReportForVisitor (2026-08-14).
BASIC_INFO_REPORT_HTML = """
<div id="printDiv" class="row" dir="rtl" style="margin:20px;">
   <h2 class="col-sm-12 text-center">تفاصيل المنافسة</h2>
   <table class="table table-bordered col-sm-12">
      <caption></caption>
      <tr>
         <th scope="row">الجهة الحكومية</th>
         <td class="text-center">القوات البحرية</td>
      </tr>
      <tr>
         <th scope="row">المعلومات الأساسية</th>
         <td class="text-center">
            إسم المنافسة: توريد دهانات لمركز التدريب البحري بقاعدة الملك فيصل البحرية بجدة
            <br />
            رقم المنافسة: 27-26-07
         </td>
      </tr>
      <tr>
         <th scope="row">قيمة المنافسة</th>
         <td class="text-center"><span class="saudi-riyal-symbol">0.00</span></td>
      </tr>
      <tr>
         <th scope="row">الغاية من المنافسة</th>
         <td class="text-center">توريد دهانات لمركز التدريب البحري بقاعدة الملك فيصل البحرية بجدة</td>
      </tr>
      <tr>
         <th scope="row">اخر موعد لإستلام استفسارات الموردين و إضافة الملحقات</th>
         <td class="text-center">
            التاريخ: 12/03/1448
            <br />
            الموافق: 25/08/2026
         </td>
      </tr>
      <tr>
         <th scope="row">فترة التوقف</th>
         <td class="text-center"></td>
      </tr>
      <tr>
         <th scope="row">التاريخ المتوقع للترسية</th>
         <td class="text-center">
            التاريخ: 16/04/1448
            <br />
            الموافق: 28/09/2026
         </td>
      </tr>
      <tr>
         <th scope="row">تاريخ بدء الأعمال / الخدمات</th>
         <td class="text-center">
            التاريخ: 19/04/1448
            <br />
            الموافق: 01/10/2026
         </td>
      </tr>
      <tr>
         <th scope="row">مكان تقديم العروض</th>
         <td class="text-center"></td>
      </tr>
      <tr>
         <th scope="row">مكان فتح العروض</th>
         <td class="text-center">لا يوجد</td>
      </tr>
      <tr>
         <th scope="row">مكان التنفيذ</th>
         <td class="text-center">داخل المملكة</td>
      </tr>
      <tr>
         <th scope="row">مجال التصنيف</th>
         <td class="text-center">
            <ul>
            </ul>
         </td>
      </tr>
   </table>
</div>
"""

# Real HTML captured from GetAwardingResultsForVisitorViewComponenet (2026-08-14).
AWARDING_RESULTS_HTML_FULL_AWARD = """
<div class="row" id="offerDetials">
   <div class="col-md-12 col-sm-12 col-xs-12">
      <h4 class="text-primary">قائمة الموردين المتقدمين</h4>
      <table class="table  table-striped text-center table-bordered" summary="desc">
         <thead>
            <tr>
               <th class="text-center" scope="col">إسم المورد</th>
               <th class="text-center" scope="col">قيمة العرض المالي</th>
               <th class="text-center" scope="col">نتائج فحص العروض الفنية</th>
            </tr>
         </thead>
         <tbody class="text-center">
               <tr>
                  <td>شركة ألوان ألمجد للتجارة</td>
                  <td><h5 class="text-center">5750.00</h5></td>
                  <td><h5 class="text-center">مطابق</h5></td>
               </tr>
         </tbody>
      </table>
   </div>
</div>
<br />
<div class="row">
   <div class="col-md-12 col-sm-12 col-xs-12">
      <h4 class="text-primary">قائمة الموردين المرسى عليهم  -  ( ترسية كاملة )</h4>
      <table class="table table-striped text-center table-bordered" summary="desc">
         <thead>
            <tr>
               <th class="text-center" scope="col">إسم المورد</th>
               <th class="text-center" scope="col">قيمة العرض المالي</th>
               <th class="text-center" scope="col">قيمة الترسية</th>
            </tr>
         </thead>
         <tbody class="text-center">
               <tr>
                  <td>شركة ألوان ألمجد للتجارة</td>
                  <td><h5 class="text-center">5750.00</h5></td>
                  <td><h5 class="text-center">5750.00</h5></td>
               </tr>
         </tbody>
      </table>
   </div>
</div>
"""

NOT_YET_AWARDED_HTML = """
<div class="row">
   <div class="col-md-12 text-center">
      لم يتم اعلان نتائج الترسية بعد
   </div>
</div>
"""


def test_parse_basic_info_report_extracts_only_the_new_fields():
    result = parse_basic_info_report(BASIC_INFO_REPORT_HTML)

    assert result["tender_value"] == "0.00"
    assert (
        result["tender_purpose"]
        == "توريد دهانات لمركز التدريب البحري بقاعدة الملك فيصل البحرية بجدة"
    )
    assert result["standstill_period"] is None
    assert result["offer_submission_location"] is None
    assert result["offer_opening_location"] == "لا يوجد"
    assert result["execution_location"] == "داخل المملكة"
    assert result["classification"] is None


def test_parse_basic_info_report_splits_out_gregorian_dates():
    result = parse_basic_info_report(BASIC_INFO_REPORT_HTML)

    assert result["expected_award_date"] == "28/09/2026"
    assert result["work_start_date"] == "01/10/2026"


def test_parse_awarding_results_full_award():
    result = parse_awarding_results(AWARDING_RESULTS_HTML_FULL_AWARD)

    assert result["bidders"] == [
        {
            "supplier_name": "شركة ألوان ألمجد للتجارة",
            "financial_offer": 5750.0,
            "technical_result": "مطابق",
        }
    ]
    assert result["awarded"] == [
        {
            "supplier_name": "شركة ألوان ألمجد للتجارة",
            "financial_offer": 5750.0,
            "award_value": 5750.0,
        }
    ]


def test_parse_awarding_results_not_yet_awarded_returns_empty():
    result = parse_awarding_results(NOT_YET_AWARDED_HTML)

    assert result == {"bidders": [], "awarded": []}


def test_parse_awarding_results_multiple_bidders_only_one_awarded():
    html = """
    <h4 class="text-primary">قائمة الموردين المتقدمين</h4>
    <table><tbody>
      <tr><td>مورد أ</td><td>100.00</td><td>مطابق</td></tr>
      <tr><td>مورد ب</td><td>90.00</td><td>غير مطابق</td></tr>
    </tbody></table>
    <h4 class="text-primary">قائمة الموردين المرسى عليهم - ( ترسية كاملة )</h4>
    <table><tbody>
      <tr><td>مورد أ</td><td>100.00</td><td>100.00</td></tr>
    </tbody></table>
    """

    result = parse_awarding_results(html)

    assert len(result["bidders"]) == 2
    assert len(result["awarded"]) == 1
    assert result["awarded"][0]["supplier_name"] == "مورد أ"
