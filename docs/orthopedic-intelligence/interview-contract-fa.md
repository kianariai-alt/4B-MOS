# قرارداد مصاحبه و خلاصهٔ پزشکیار، نسخهٔ 1.0.0

این قرارداد توسعهٔ `BankContent` و `PortalAnswerCreate` موجود است. موتور، جدول موازی یا مسیر فعال‌سازی تازه ندارد. بانک در چرخهٔ اختصاصی پزشک draft و approve/retire موجود می‌ماند. تأیید بانک پرسش، تأیید تشخیص یا درمان نیست.

## سؤال و شرط نمایش

بانک جدید `contract_version: "1.0.0"` دارد. هر سؤال دارای id پایدار، question_version، text_fa، purpose_fa و provenance است. منشأ شامل kind و reference است؛ نوع‌های آن physician_authored، reference، clinic_protocol یا design_draft هستند. در دادهٔ قدیمی فاقد منشأ، `unspecified` و نسخهٔ `legacy-unspecified` صادقانه گزارش می‌شود؛ منبع یا تاریخ قدیمی جعل نمی‌شود. هش بانک قدیمی با اضافه شدن پیش‌فرض‌های جدید تغییر نمی‌کند.

| answer_type | مقدار ثبت‌شده | قیود |
| --- | --- | --- |
| yes_no | کد `yes` یا `no` | به‌جای true/false |
| number | عدد JSON | عدد متناهی، numeric_unit و numeric_min/max در سؤال؛ unit مطابق در پاسخ |
| single_choice | یک کد از choices | گزینه‌های ثابت بانک |
| text | متن | حداکثر ۳۰۰۰ نویسه |

همهٔ سؤال‌ها unknown و declined را می‌پذیرند. متن اختیاری supplementary_text توضیح اضافهٔ پاسخ است. واحد تبدیل نمی‌شود؛ ارسال واحد متفاوت نیازمند اصلاح است. صفر عددی ثبت‌شده با null یا نبود پاسخ متفاوت است.

شرط قدیمی `depends_on_id` همراه `show_when_answer_in` حفظ شده است. شرط جدید `display_condition` یکی از این ساختارهاست:

```json
{"all": [
  {"question_id": "earlier_flag", "operator": "eq", "value": "yes"},
  {"any": [
    {"question_id": "earlier_measurement", "operator": "gte", "value": 2},
    {"question_id": "earlier_measurement", "operator": "state_in", "states": ["unknown"]}
  ]}
]}
```

نام‌های بالا نمونهٔ فنی‌اند و پرسش یا قاعدهٔ پزشکی نیستند. عملگرها eq/ne/in/gt/gte/lt/lte/state_in هستند. شرط‌ها فقط به سؤال پیشین اشاره می‌کنند، نوع مقدارشان کنترل می‌شود و عمق و تعداد شرط‌ها محدود است. شرط قدیمی و جدید روی یک سؤال هم‌زمان مجاز نیست.

مقایسهٔ مقدار برای unknown، declined و missing نتیجهٔ نامعین دارد؛ `ne` نیز unknown را «خیر» نمی‌کند. در all، وجود false نتیجه را false می‌کند و در غیر این صورت وجود نامعین نتیجه را نامعین نگه می‌دارد. در any، وجود true کافی است و در غیر این صورت نامعین حفظ می‌شود. فقط نتیجهٔ true سؤال را فعال می‌کند. `state_in` برای مسیر صریح unknown/declined/missing است و سؤال پیشین باید خودش در مسیر واجد نمایش باشد. چند شاخه می‌توانند هم‌زمان فعال باشند؛ نتیجه به یک تشخیص تقلیل داده نمی‌شود.

## ثبت و اصلاح پاسخ

مسیر موجود:

```text
POST /api/v1/patient-portal/requests/{request_id}/interview-answers
```

```json
{
  "request_key": "unique-command-key",
  "expected_version": 0,
  "question_id": "earlier_measurement",
  "state": "answered",
  "value": 0,
  "unit": "test-unit",
  "supplementary_text": null
}
```

برای unknown یا declined، value و unit باید null یا حذف‌شده باشند. نشست بیمار، CSRF، Origin، محدودیت اندازه و مالکیت درخواست همان پورتال قبلی است. مشخصات منبع و زمان از بیمار پذیرفته نمی‌شود؛ سرور recorded_at به UTC، source، bank_sha256، question_version، provenance و answer_event_id را ثبت می‌کند.

پرسش جاری یا پاسخ فعال قبلی قابل اصلاح است. expected_version قدیمی پاسخ 409 می‌گیرد. request_key تکراری با همان فرمان، رویداد جدید ایجاد نمی‌کند؛ همان کلید با محتوای متفاوت 409 است، حتی اگر پاسخ قبلی از مسیر فعال خارج شده باشد.

اصلاح، رویداد جدید می‌افزاید؛ پاسخ پیشین با `answer_replaced` و فرزند نامرتبط با `condition_no_longer_satisfied` ابطال می‌شود. تاریخچه و علت/زمان/نسخهٔ ابطال در answer_history باقی می‌ماند. بازگشت بعدی به شاخه، سؤال را دوباره می‌پرسد. اطلاعات در همان encrypted_answers موجود نگهداری می‌شود؛ قالب ذخیره‌سازی داخلی schema_version=2 است و با نسخهٔ عمومی قرارداد یکسان نیست. دادهٔ قدیمی در اولین نوشتن به این قالب منتقل می‌شود؛ recorded_at قدیمی نامعلوم و source برابر legacy_patient_portal است.

تغییر یا بازنشستگی بانک تأییدشده و پس‌گرفتن درخواست، پاسخ‌گویی را می‌بندد؛ اطلاعات ثبت‌شده برای بررسی باقی می‌ماند.

## خلاصهٔ پزشکیار

در پاسخ workspace بیمار، صندوق کارکنان و endpoint patient-report ویزیت linked، کلید `interview.assistant_summary` قرارداد مستقلی دارد:

| فیلد | معنا |
| --- | --- |
| schema_version | `1.0.0` |
| source / patient_reported_only / requires_clinician_review | patient_portal / true / true |
| request_id / physician_id / bank_sha256 / interview_version | منشأ و نسخهٔ دقیق |
| items | فقط پاسخ‌های مسیر فعال با تعریف سؤال، مقدار، واحد، وضعیت و متادیتای رویداد |
| missing_question_ids | سؤال‌های واجد نمایش بدون پاسخ |
| unknown_question_ids / declined_question_ids | وضعیت‌های مستقلِ پاسخ‌های فعال |
| inactive_question_ids | سؤال‌های خارج از مسیر فعلی؛ با unknown یکسان نیستند |
| summary_fa | خلاصهٔ خوانا برای مرور انسانی |

خلاصه با مدل strict اعتبارسنجی می‌شود. این خروجی نه احتمال تشخیص می‌سازد، نه درمان پیشنهاد می‌کند و نه پاسخ unknown را منفی ثبت می‌کند. draft شرح‌حال موجود یا final پزشک با اصلاح پاسخ بیمار بازنویسی نمی‌شود. برداشت یا تأیید بالینی باید صریحاً در مسیر Clinical Context موجود ثبت شود. قرارداد #44 منابع self-report را نمی‌پذیرد؛ این خلاصه به آن تزریق نمی‌شود.

Schema قابل پردازش از مدل‌های زمان اجرا صادر می‌شود:

```powershell
.venv\Scripts\python.exe -m backend.tools.export_interview_contract --output docs/orthopedic-intelligence/interview-contract-v1.schema.json
```

نسخهٔ مرجع در [interview-contract-v1.schema.json](interview-contract-v1.schema.json) نگهداری می‌شود. هیچ نمونهٔ بالینی همراه این schema در بانک فعال ثبت نمی‌شود.
