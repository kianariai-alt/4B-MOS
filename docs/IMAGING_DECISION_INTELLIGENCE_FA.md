# 4B-MOS | پایه Imaging Intelligence و Decision Validation

## وضعیت مبنا و مالکیت مسیرها

بررسی GitHub در ۲۰۲۶-۱۰-۱۹ انجام شد:

| مسیر | وضعیت بررسی‌شده | مرز مالکیت |
| --- | --- | --- |
| [main](https://github.com/kianariai-alt/4B-MOS/tree/main) | `bc6fb3f15825d6eaccaa45503ad61a432baf1c5b`؛ شاخه محافظت‌شده با بررسی Backend CI | زیرساخت فعلی FastAPI، SQLAlchemy و PostgreSQL |
| [PR #43](https://github.com/kianariai-alt/4B-MOS/pull/43) | باز، Draft؛ `feature/dual-knowledge-cores-foundation` در `3fafc6224d17209ee47373aede4bf9dedfa76a72` | manifest مشترک دو هسته و سند معماری فارسی |
| [PR #44](https://github.com/kianariai-alt/4B-MOS/pull/44) | باز، Draft؛ `feature/clinical-intelligence-integration` در `abb60d24f79efe498a19faaa9d7bc16967061ef7` | قرارداد مشترک، orchestration، snapshot و بررسی پزشک |
| این تغییر | شاخه مستقل `feature/imaging-intelligence` بر مبنای main | خواندن متادیتای محلی، کنترل داده و adapter فقط‌خواندنی دانش تصویری |

این شناسه‌ها وضعیت هنگام بررسی هستند؛ پیش از اتصال یا ادغام، وضعیت شاخه‌ها باید دوباره خوانده شود. هیچ‌یک از PRهای دیگر در این تغییر ادغام نمی‌شود. سند مبنا در [شاخه PR #43](https://github.com/kianariai-alt/4B-MOS/blob/feature/dual-knowledge-cores-foundation/docs/DUAL_KNOWLEDGE_CORES_FA.md) بررسی شد؛ نبودن آن در main به معنی نیاز به ساخت نسخه تکراری نیست.

## استفاده از زیرساخت موجود

رجیستری فعلی `MedicalKnowledgeService` از قبل نسخه، منشأ، hash محتوا، بازه اعتبار و بررسی مستقل را مدیریت می‌کند. `list_approved(db, *, as_of, clinical_domain, skip, limit)` رکوردهای مجاز را خوانده و در مسیر `_to_read` یکپارچگی محتوا را کنترل می‌کند. نویسنده نمی‌تواند محتوای خودش را تأیید کند. این ماژول رجیستری جدید، جدول جدید یا مسیر تأیید خودکار نمی‌سازد.

`ClinicalSafetyRuleService` و `ClinicalSafetyEvaluationService` فعلی قواعد ایمنی، پیوند به دانش تأییدشده، نسخه و digest مستقل دارند. `PhysicianCopilotService` نیز snapshot فقط‌خواندنی از زمینه بالینی، صندوق ایمنی، شواهد و پیامدها می‌سازد. کنترل داده در این تغییر، جایگزین هیچ‌یک از این خدمات نیست و نتیجه آن مجوز عبور از قواعد ایمنی نیست.

## اجزای قابل‌آزمون

| جزء | فایل | مسئولیت |
| --- | --- | --- |
| قرارداد متادیتا | `backend/app/imaging_intelligence/models.py` | خروجی تغییرناپذیر، issueهای کددار، نسخه و digest |
| خواندن DICOM محلی | `backend/app/imaging_intelligence/reader.py` | خواندن محدود متادیتای مجاز با pydicom و شناسایی نقص یا ناسازگاری فنی |
| adapter رجیستری دانش | `backend/app/imaging_intelligence/knowledge.py` | خواندن referenceهای معتبر یک domain برای مصرف‌کننده تصویری |
| قرارداد تصمیم | `backend/app/decision_intelligence/models.py` | `DecisionModelAdapter` و ورودی/خروجی مستقل از وب و پایگاه داده |
| کنترل قانون‌محور داده | `backend/app/decision_intelligence/adapter.py` | کامل‌بودن ورودی، سازگاری زمینه و جلوگیری از استفاده از یافته تأییدنشده |
| تبدیل صریح قرارداد | `backend/app/imaging_intelligence/decision_projection.py` | تبدیل خروجی reader به ورودی مستقل کنترل داده، بدون تغییر قرارداد PR #44 |
| نمونه ساختگی | `backend/tools/imaging_metadata_demo.py` | ساخت DICOM آزمایشی، خواندن و عبور خروجی از کنترل داده |

مسیر اولیه، کتابخانه Python و ابزار محلی است. API عمومی برای دریافت مسیر فایل، لینک مرکز تصویربرداری یا ادعای تأیید پزشک ایجاد نمی‌شود. بازکردن نشست پایگاه داده و احراز مجوز همچنان وظیفه لایه فراخواننده مجاز است.

### متادیتای DICOM و حریم خصوصی

خواندن فقط از فایل محلی آزمایشی انجام می‌شود. انتخاب whitelist به‌جای صادرکردن همه tagها، احتمال ورود متن آزاد و اطلاعات هویتی به JSON را کم می‌کند. `DicomMetadataReader(reference_key=..., max_file_bytes=...).read(path)` کلیدی با حداقل ۳۲ بایت و محدودیت فایل حداکثر ۶۴ MiB می‌گیرد. `force=False` حفظ می‌شود؛ فایل نامعتبر با حدس و اجبار به DICOM معتبر تبدیل نمی‌شود. خواندن متادیتا از پردازش pixelها جدا است. UID نوع فایل در محدوده اولیه CT/MR/CR/DX/MG/US/SC پشتیبانی می‌شود. Deflated پیش از بازشدن رد می‌شود؛ pixel فشرده decode نمی‌شود.

- نام و شناسه بیمار، تاریخ تولد، تاریخ/زمان مطالعه، accession، نام پزشک/مرکز، توضیحات آزاد، private tagها و مسیر فایل در خروجی قرار نمی‌گیرند.
- شناسه‌های خام Study، Series و SOP Instance فقط برای کنترل ساختاری و ساخت reference با HMAC در حافظه استفاده می‌شوند؛ مقدار خام در JSON نیست. کلید باید از لایه مورداعتماد تأمین شود و نباید در خروجی یا log قرار گیرد. استفاده از یک کلید، امکان پیوندپذیری referenceها را ایجاد می‌کند؛ سیاست چرخش و محدوده کلید پیش از اتصال واقعی لازم است.
- SOP Class UID و Transfer Syntax UID شناسه نوع استاندارد و قالب انتقال هستند، نه شناسه یکتای بیمار یا مطالعه. فقط مقادیر فنی مجاز قابل صدورند.
- پیام‌های issue کد ثابت و نام فیلد دارند؛ مقدار خراب، warning کتابخانه و متن exception نباید به خروجی یا log عمومی منتقل شود.
- `pixel_data_validated=false` و `dicom_identity_verified=false` صریح باقی می‌مانند. `valid` فقط عبور از کنترل‌های متادیتای همین نسخه است؛ کامل‌بودن سری، صحت اتصال بیمار، کیفیت تصویر یا انطباق کامل IOD را ثابت نمی‌کند.

این پردازش، ناشناس‌سازی فایل DICOM یا تضمین حذف نوشته‌های داخل pixel نیست. داده خام تغییر نمی‌کند و تصویر برای تحلیل بالینی تفسیر نمی‌شود. پشتیبانی از مدل‌های تصویرخوانی، فایل‌های encapsulated، کنترل حجم بازشده داده فشرده و سری چندفایلی باید با ارزیابی جدا توسعه یابد.

مراجع فنی: [pydicom dcmread](https://pydicom.github.io/pydicom/stable/reference/generated/pydicom.filereader.dcmread.html)، [DICOM PS3.15، پروفایل محرمانگی](https://dicom.nema.org/medical/dicom/current/output/chtml/part15/sect_E.2.html). پروفایل DICOM علاوه بر هویت مستقیم، UIDها، زمان‌ها و private attributes را نیز از عوامل پیوندپذیری می‌داند؛ حذف PatientName به‌تنهایی کافی نیست.

### پایه دانش تصویربرداری

`ImagingKnowledgeRegistryAdapter.collect(db, domain=..., as_of=...)` تنها `MedicalKnowledgeService.list_approved` را برای یک domain انتخاب‌شده فراخوانی می‌کند. import سرویس تا زمان فراخوانی به تعویق می‌افتد؛ import ماژول آفلاین تنظیمات یا SQLAlchemy را بارگذاری نمی‌کند. فراخواننده نشست موجود و مجوز لازم را تأمین می‌کند؛ adapter به‌تنهایی یک مرز احراز هویت نیست. manifest چندبسته‌ای و مشترک دو هسته همچنان در مالکیت PR #43 است و این adapter آن را بازتولید نمی‌کند.

دو domain مجاز به‌صورت exact-match با PR #43 هماهنگ‌اند: `imaging_knee_xray` و `imaging_knee_mri`. هر فراخوانی فقط یکی را می‌خواند. هیچ محتوای ارتوپدی یا دامنه مشابه خودکار منتقل نمی‌شود. کنترل وضعیت approved، تاریخ اعتبار شامل دو انتهای بازه، انتساب بررسی مستقل، شناسه و نسخه معتبر، digest معتبر از نظر قالب و نبود تکرار، پیش از صدور reference انجام می‌شود. بررسی کامل hash محتوا به رجیستری موجود واگذار شده است؛ قالب درست hash به‌تنهایی اثبات درستی محتوا نیست.

`ImagingKnowledgeReferences` فقط شناسه fact، کلید، نسخه، content hash و شناسه sourceها را نگه می‌دارد. متن پزشکی، محتوای source و هویت نویسنده/بازبین صادر نمی‌شود. ترتیب factها و sourceها ثابت است و domain و تاریخ ارزیابی در `references_sha256` نقش دارند؛ این digest صرفاً snapshot ورودی مصرف‌کننده است، نه manifest مرجع PR #43. خروجی درونی dataclassهای frozen و tuple است؛ `to_dict()` یک کپی JSON-compatible می‌دهد. تعداد factها حداکثر ۲۰۰۰ و اندازه صفحه حداکثر ۲۰۰ است؛ پاسخ بیش‌ازحد یا نامعتبر fail closed می‌شود.

`references_available` فقط وجود مرجع تأییدشده را نشان می‌دهد؛ کاربرد برای بیمار، اعتبارسنجی بالینی یا توصیه را ثابت نمی‌کند. domain بدون منبع صادقانه `empty` است. این تغییر هیچ گزاره پزشکی، وزن مدل، محتوای ساختگی approved یا درخواست تأیید به رجیستری وارد نمی‌کند. callable تزریق‌شده برای آزمون، یک وابستگی مورداعتماد است و باید همان تضمین بررسی یکپارچگی رجیستری را داشته باشد.

### Decision Validation و نسخه‌ها

موتور اولیه قواعد قطعی دارد: وجود فیلدهای لازم، وضعیت متادیتا، ناسازگاری modality/ناحیه/laterality، منشأ و وضعیت بررسی یافته‌ها. ورودی‌ها شامل علامت حضور فیلدهای بالینی و کدهای کنترل‌شده‌اند؛ متن شرح‌حال یا اطلاعات بیمار در این قرارداد لازم نیست. نیازهای هر مصرف‌کننده یک policy نسخه‌دار و مورداعتماد است؛ «فیلد لازم برای پردازش» به معنی دستور انجام تصویربرداری یا توصیه پزشکی نیست.

`verified` یک ادعای لایه یکپارچه‌سازی احرازشده است؛ این کتابخانه مرجع هویت پزشک نیست. تطبیق منشأ، reference متادیتا و نسخه سیاست بررسی همچنان لازم است. یافته تأییدنشده یا ناسازگار مسدود می‌شود؛ confidence جای بررسی مستقل را نمی‌گیرد. `data_ready` فقط آمادگی داده برای گام بعدی است و اجازه تشخیص، درمان یا اقدام بالینی نمی‌دهد.

خروجی نسخه adapter، نسخه policy، hash ورودی، hash قواعد/پیکربندی، hash نتیجه و trace هر قاعده را ثبت می‌کند. تغییر قواعد یا policy باید نسخه و تست متناظر داشته باشد؛ hash به‌تنهایی امضای دیجیتال، تأیید پزشکی یا زمان معتبر بیرونی نیست. ورودی نامعتبر باید فقط کدهای ثابت خطا تولید کند و مقدار ردشده را بازتاب ندهد.

## انتخاب ابزار بر اساس نیاز فعلی

| ابزار بررسی‌شده | کاربرد مستند | تصمیم فاز نخست |
| --- | --- | --- |
| [pgmpy](https://pgmpy.org/) | مدل‌های گرافی، استنتاج احتمالاتی و علّی | فعلاً نصب نمی‌شود؛ مدل/پارامتر و اعتبارسنجی پزشکی مورداعتماد موجود نیست |
| [pyAgrum](https://pyagrum.readthedocs.io/en/stable/) | شبکه بیزی و influence diagram با کتابخانه C++ | برای پژوهش آتی پشت adapter؛ در کنترل کامل‌بودن داده ضرورتی ندارد |
| [GoRules ZEN](https://docs.gorules.io/developers/sdks/python) | اجرای قواعد و decision model با tracing | گزینه آینده برای جدول قواعد تحت حاکمیت؛ افزودن runtime و JDM برای قواعد محدود فعلی لازم نیست |
| [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) | orchestration حالت‌دار، persistence و human-in-the-loop | خارج از این هسته؛ هماهنگی جریان کار با مسیر یکپارچه‌سازی است |
| [pydicom](https://pydicom.github.io/pydicom/stable/) | خواندن Dataset و tagهای DICOM | وابستگی افزوده ضروری برای خواننده فاز نخست |

انتخاب فاز اول Python قطعی با Protocol مستقل است. موتور بیرونی بعداً می‌تواند همین مرز را پیاده کند؛ خروجی احتمالاتی نباید قواعد ایمنی مستقل را تغییر دهد. هیچ کلید سرویس پولی یا حساب جدید لازم نیست.

## اتصال بعدی و قرارداد PR #44

[Unified Clinical Data Contract 1.0.0](https://github.com/kianariai-alt/4B-MOS/blob/feature/clinical-intelligence-integration/docs/contracts/unified-clinical-data-v1.md) قرارداد سخت‌گیر با exact version و `extra=forbid` است؛ افزودن فیلد نیز نیاز به هماهنگی دارد. در نسخه فعلی `ImagingStudyReference` فقط proxy گزارش موجود است؛ داده DICOM خام نمی‌تواند بی‌واسطه به `CoreOutput` تبدیل شود. این تغییر wire contract را عوض نمی‌کند، modality ناشناخته adapter فعلی را بازنویسی نمی‌کند و DICOM reference را به شناسه معتبر بیمار/گزارش ارتقا نمی‌دهد.

برای اتصال واقعی، adapter جدا باید خروجی تصویری را به گزارش/observation پیش‌نویس مجاز و نسخه‌دار متصل کند، هویت مطالعه/سری را کنترل کند و بررسی مسئول را از سرور دریافت کند. تا آن زمان اجرای آفلاین مستقل می‌ماند. خروجی synthetic نمونه، قرارداد production برای تأیید پزشک نیست.

مرزهای قابل افزودن:

1. **Orthanc / DICOMweb:** adapter دریافت با احراز هویت، مجوز، محدودیت حجم/زمان، SSRF و کنترل نگهداری؛ آدرس یا توکن مرکز در رجیستری دانش قرار نمی‌گیرد. مرجع [DICOM PS3.18](https://dicom.nema.org/medical/dicom/current/output/chtml/part18/PS3.18.html).
2. **OHIF:** مرز نمایش و بازبینی مجاز، مستقل از متادیتای کوچک این کتابخانه؛ هیچ لینک فعال مرکز در فاز اول نیست.
3. **MONAI:** پردازش task-specific با شناسه checkpoint، نسخه preprocessing، کیفیت و موارد خارج از توزیع؛ محصول آن تا بررسی مسئول، یافته تأییدنشده است.
4. **هسته دانش و Safety:** دسترسی فقط‌خواندنی به منابع تأییدشده؛ اتصال قواعد درمانی تنها در workflow حاکمیت موجود و پس از بررسی مستقل.

## اجرای محلی با داده ساختگی

از ریشه مخزن و داخل virtual environment اختصاصی:

```bash
python -m pip install -r backend/requirements-imaging.txt
python -m unittest discover -s backend/tests/imaging_intelligence -v
python -m backend.tools.imaging_metadata_demo
```

این مسیر تست از `unittest` استفاده می‌کند و `backend/tests/conftest.py` مربوط به pytest/پایگاه داده را بارگذاری نمی‌کند. آزمون‌های دانش با reader تزریق‌شده اجرا می‌شوند؛ آزمون‌های DICOM باید فایل ساختگی سالم، خراب و ناقص را در پوشه موقت بسازند. برای اجرای نمونه به لینک مرکز، فایل بیمار، اعتبارنامه، پایگاه داده یا migration نیازی نیست. نصب requirements اصلی backend تنها برای اجرای کل سامانه لازم است.

## نتیجه واقعی بررسی و آزمون

بازبینی نهایی در ۲۰۲۶-۱۰-۲۰ نشان داد main همچنان در `bc6fb3f` است، PRهای ۴۳ و ۴۴ باز و Draft هستند و شاخه اختصاصی این تغییر از همان main ساخته شد.

در Python 3.12.14، تعداد **۵۳ آزمون** مستقل موفق شد: ۱۹ آزمون reader، ۲۱ آزمون Decision Validation، ۱۲ آزمون adapter دانش و یک آزمون سرتاسری. `python -m compileall -q backend` نیز موفق بود. داده‌های DICOM در خود آزمون تولید و در پوشه موقت نگهداری شدند؛ نه فایل نمونه بیمار دریافت شد و نه DB یا migration برای این آزمون‌ها لازم بود.

دسترسی شبکه مستقیم محیط اجرا به proxy برقرار نبود؛ نصب با pip در این محیط موفق نشد. برای اجرای واقعی آزمون‌ها، source رسمی و دست‌نخورده `pydicom==3.0.1` از commit `50cd981a068c74b01d854c6cac9bb897fe0b74a9` در `/tmp/4b-deps` آماده شد؛ SHA هر ۸۱ فایل دریافت‌شده با blob رسمی Git تطبیق داده شد. این dependency داخل مخزن کپی نشده است. دستور محلی اجراشده:

```bash
PYTHONPATH=/tmp/4b-deps python -m unittest discover -s backend/tests/imaging_intelligence -q
PYTHONPATH=/tmp/4b-deps python -m backend.tools.imaging_metadata_demo
python -m compileall -q backend
```

خروجی واقعی و قابل بازتولید نمونه در [`examples/imaging_decision_synthetic.json`](examples/imaging_decision_synthetic.json) ذخیره شده است:

| سناریوی ساختگی | وضعیت متادیتا | کنترل داده |
| --- | --- | --- |
| فایل سالم MR | `valid` | `data_ready` |
| نبودن SeriesInstanceUID | `incomplete` | `needs_data` |
| فایل خراب | `invalid` | `needs_data` |
| یافته تأییدنشده | متادیتای سالم | `needs_data`؛ یافته مسدود |

`data_ready` فقط عبور از نیازهای داده همان policy است. ورودی متادیتای `invalid` یک ورودی ساختاری معتبر برای کنترل داده است و با نتیجه `needs_data` متوقف می‌شود؛ `invalid_input` مختص نقص schema قرارداد ورودی موتور است.

workflow مستقل `.github/workflows/imaging-intelligence-ci.yml` همین آزمون‌های بدون DB و نمونه را برای Python 3.12 و 3.14 اجرا می‌کند. requirements توسعه موجود نیز dependency تصویربرداری را نصب می‌کند تا آزمون‌های جدید در Backend CI اصلی قابل جمع‌آوری باشند. اجرای محلی کل Backend CI/PostgreSQL و مسیر پیش‌فرض adapter روی Registry واقعی انجام نشده است؛ آزمون adapter از reader تزریق‌شده استفاده می‌کند. وضعیت CI بیرونی باید در PR بررسی شود. آزمون نرم‌افزار جای تأیید بالینی را نمی‌گیرد.

## محدودیت‌ها و مرز پذیرش

این مرحله metadata reader، کنترل آمادگی داده و inventory منابع است. صحت محتوای تصویر، تشخیص، segmentation، تأیید هویت بیمار، کامل‌بودن مطالعه/سری، terminology server، ارزیابی عملکرد بالینی و تبادل FHIR پیاده نشده‌اند. داده ساختگی برای آزمون نرم‌افزار است؛ منبع دانش پزشکی محسوب نمی‌شود. ادغام با main، نصب عملیاتی، اتصال واقعی مراکز یا اعمال migration به پایگاه کلینیک خارج از این تغییر و نیازمند مجوز جداگانه است.
