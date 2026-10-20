# ممیزی واقعی مخزن برای Orthopedic Intelligence

تاریخ بررسی: ۲۰۲۶-۱۰-۲۰. این گزارش از خواندن کد، تست و مستندات مخزن تهیه شده است؛ وجود قابلیت یا تست، آمادگی استفاده بالینی یا موفقیت اجرای تست در این مرحله را اثبات نمی‌کند. نتیجه اجرای واقعی تست‌های تحویل در گزارش همان PR ثبت می‌شود.

## شاخه‌ها و مبنای توسعه

| مرجع بررسی‌شده | Commit SHA | نتیجه |
| --- | --- | --- |
| `main` | `bc6fb3f15825d6eaccaa45503ad61a432baf1c5b` | مبنای نسخه اول؛ شامل سرویس‌های حاکمیت دانش و ثبت بالینی موجود است. |
| `codex/physician-clinical-intake` | `f454a4889fadfa5630096e4a7adb4a66bd31c5e2` | جد main است؛ main هشت commit جلوتر است. ویرایشگر شرح‌حال این شاخه در main موجود است. |
| `feature/dual-knowledge-cores-foundation` | `3fafc6224d17209ee47373aede4bf9dedfa76a72` | هفت commit مستقل پس از main؛ manifest خواندنی دو هسته و `docs/DUAL_KNOWLEDGE_CORES_FA.md` بررسی شد. |
| `feature/clinical-intelligence-integration` | `abb60d24f79efe498a19faaa9d7bc16967061ef7` | یک commit پس از main؛ قرارداد و orchestrator آزمایشی مستقل دارد و در main موجود نیست. |
| `feature/imaging-intelligence` | `502da58b71b174dc70983ac2c7958605259bb726` | مدل‌ها و adapter عمومی اعتبارسنجی آمادگی داده بررسی شد؛ اجرای آن در حوزه مسیر Imaging است. |

در شروع کار، شاخه `feature/orthopedic-intelligence` در refs دریافت‌شده وجود نداشت؛ شاخه اختصاصی از main بالا ایجاد شد. [PR شماره ۴۳](https://github.com/kianariai-alt/4B-MOS/pull/43) هنگام بررسی GitHub باز، Draft و ادغام‌نشده بود و head آن `3fafc62` بود. صرف open بودن این PR به معنی وجود کد آن در main نیست. شاخه Integration نیز در این snapshot کد manifest دو هسته را وارد نکرده بود.

هیچ merge، force push، migration عملیاتی یا دسترسی به پایگاه بیماران برای این ممیزی انجام نشد. فایل `AGENTS.md` در درخت کاری مخزن مشاهده نشد.

## قابلیت‌های موجود و محدودیت واقعی

| قابلیت | شواهد کد و تست موجود | نتیجه و محل استفاده مجدد |
| --- | --- | --- |
| Medical Knowledge Registry | `models/medical_knowledge.py`، `schemas/medical_knowledge.py`، `services/medical_knowledge.py` و `tests/test_medical_knowledge.py` | `KnowledgeFactCreate` دارای منبع اجباری، DOI اختیاری، تاریخ/نسخه منبع، جمعیت، کاربرد، درجه شواهد و اعتبار زمانی است. `knowledge_content_digest` محتوا و منابع را hash می‌کند. ایجاد رکورد Draft است؛ تأیید توسط نویسنده محتوا ممنوع، approved غیرقابل‌ویرایش و نسخه جایگزین مستقل است. مصرف‌کنندگان باید از `MedicalKnowledgeService` استفاده کنند. |
| Structured Clinical Context | `schemas/clinical_context.py`، `services/clinical_context.py` و `tests/test_clinical_context.py` | intake، گزارش و observation نوع‌دار، hash، وضعیت Draft/Final و اصلاح نسخه‌دار دارد. `get_current_context` فقط رکوردهای Final فعلی را می‌خواند. معاینه intake هنوز عمدتاً متن آزاد است؛ Final بودن رکورد به تنهایی تأیید تخصصی هر یافته نیست. استخراج خودکار مفاهیم از متن آزاد نباید معتبر فرض شود. |
| Physician Question Bank | `schemas/physician_questions.py`، `services/physician_questions.py` و `tests/test_physician_questions.py` | `InterviewQuestion`، متن و هدف فارسی، پاسخ yes/no و انتخابی، شرط وابسته به سؤال قبلی، unknown/decline، نسخه و تأیید hash-bound موجود است. تغییر و تأیید بانک فقط توسط پزشک مالک انجام می‌شود؛ این با بررسی مستقل دانش پزشکی تفاوت دارد. بانک یا مخزن پاسخ موازی لازم نیست. |
| پرسشگری Portal | `services/portal_interview.py` و `tests/test_portal_interview.py` | `_next` به‌صورت قطعی اولین سؤال واجد شرط و پاسخ‌داده‌نشده را انتخاب می‌کند. snapshot رمز‌شده بانک تأییدشده، پاسخ unknown/declined، idempotency، کنترل نسخه پاسخ و توقف پس از تغییر/بازنشستگی بانک وجود دارد. پاسخ بیمار intake پزشک را Final نمی‌کند. شکاف موجود، قواعد تخصصی زانو برای اطلاعات ناقص/متناقض و پیوند به منابع علمی است. |
| Reception & Clinical Intake | `services/reception.py`، ویرایشگر `web/clinical-intake.js` و `tests/test_reception.py` | پذیرش و رضایت هدف‌مند، انتساب پزشک و مرز نقش‌ها موجود است. ثبت پذیرش جای تشخیص پزشک نیست. intake تخصصی زانو باید به داده‌های قبلی ارجاع دهد و آن‌ها را بازنویسی نکند. |
| Clinical Safety Rule Engine | `schemas/clinical_safety.py`، `services/clinical_safety.py` و `tests/test_clinical_safety.py` | DSL محدود و غیرقابل‌اجرا، ارجاع به دانش approved و معتبر، بررسی مستقل قاعده، hash context/rule/result، ارزیابی append-only، inbox و escalation موجود است. تست صریح «نبود قواعد، تأیید ایمنی نیست» دارد. بسته زانو نباید موتور یا هشدار عملیاتی موازی فعال کند. |
| Physician Copilot | `services/physician_copilot.py`، `schemas/physician_copilot.py` و `tests/test_physician_copilot.py` | snapshot خواندنی context، safety inbox، escalation، evidence brief و outcomes با manifest/hash است؛ قابلیت تشخیص، رتبه‌بندی درمان یا پرسشگری تخصصی از نام Copilot قابل استنتاج نیست. |
| Clinical Evidence Briefs | `services/clinical_evidence.py` و `tests/test_clinical_evidence.py` | پزشک منابع approved فعلی را با نسخه/hash دقیق انتخاب می‌کند؛ brief به context نهایی و مجموعه دانش مشخص متصل و غیرقابل‌ویرایش است. انتخاب خودکار بهترین درمان یا اثبات کاربرد منبع برای بیمار انجام نمی‌شود. |
| Similar-Patient Treatment Options Roadmap | `services/treatment_options_roadmap.py` و `tests/test_treatment_options_roadmap.py` | cohort محلی با معیارهای محدود، بازه پیگیری، حداقل پنج بیمار یکتا برای نمایش metric و suppression گروه کوچک دارد. گزینه‌ها بر اساس کد/نسخه پروتکل مرتب می‌شوند؛ بهبود مشاهده‌ای رتبه اثربخشی نیست. کنترل تازگی safety/context وجود دارد. |
| Clinical Outcomes Registry | `services/treatment_outcome.py` و `tests/test_treatment_outcomes.py` | outcomes ثبت‌شده پزشک به treatment، finalization و context با hash متصل هستند؛ کنترل تغییرناپذیری و tamper وجود دارد. این داده‌ها مشاهده‌ای‌اند و خودکار به دانش approved ارتقا نمی‌یابند. |
| Clinician Decision Feedback Loop | `services/treatment_decision.py`، `services/clinical_learning_review.py` و تست‌های متناظر | تصمیم پزشک، دلیل، lineage تصمیم→درمان→پیامد و پوشش داده ثبت/بررسی می‌شود؛ data-quality review بدون امتیاز اثربخشی بین پروتکل‌ها است. حلقه یادگیری خودکار توصیه درمان از این کد نتیجه نمی‌شود. |

مسیرهای جدول نسبت به `backend/app/` هستند، جز مسیرهای `tests/` که نسبت به `backend/` هستند. تست‌های اشاره‌شده هنگام ممیزی خوانده شدند؛ نتیجه اجرای آن‌ها باید جداگانه گزارش شود.

## شکاف‌های لازم برای بسته زانو

1. Registry فعلی فیلد اختصاصی ناحیه بدن، محدودیت هر گزاره، روابط مفهومی، روش معاینه و ساختار یکسان شواهد درمان ندارد. افزونه نوع‌دار بسته باید این موارد را به همان `fact_key`، نسخه و hash محتوای Registry متصل کند؛ Registry دوم ایجاد نشود.
2. enum فعلی `therapy_type` در schema و constraint پایگاه فقط `PRP/PRGF/ACS/PL/SVF/EXOSOME/MSC` است. HA و درمان استاندارد را بدون هماهنگی با Integration به این enum اضافه نکنید؛ در metadata بسته نوع درمان را مستقل نگه دارید و برای Registry از مقدار مجاز یا null استفاده کنید.
3. محتوا و قاعده Draft برای بازبینی/آزمایش باقی بمانند. موفقیت تست نرم‌افزار، تأیید پزشکی گزاره یا مجوز فعال‌سازی سؤال/قاعده نیست. هیچ مسیر startup یا import خودکار نباید Draft را approved کند.
4. پرسشگر تخصصی به اطلاعات نوع‌دارِ حداقلی، وضعیت پاسخ و منطق قابل‌توضیح وابسته باشد. داده مفقود، unknown، declined، partial، contradictory و یافته تصویری تأییدنشده نباید حضور معتبر یافته تلقی شوند. مسئلهٔ خارج از زانو باید برای بررسی پزشک مشخص شود.
5. افتراق‌ها به شکل روابط و یافته‌های مؤید/مخالف برای بازبینی عرضه شوند؛ بدون درصد احتمال، رتبه‌بندی متن‌محور یا انتخاب پروتکل درمان.

## قراردادهای موازی و تصمیم معماری

قرارداد `CoreInput/CoreOutput` نسخه `1.0.0` در شاخه Integration، observations و findings با `RecordReference` و provenance را می‌پذیرد. `KnowledgeReference` فقط approved است؛ CoreOutput محل قراردادی برای پرسش، افتراق و information gap ندارد. `FinalRecordAdapter` موجود پاس‌دادن رکورد نهایی است و هسته تخصصی ارتوپدی را پیاده نمی‌کند. در adapter عمومی مسیر Imaging، `DecisionModelAdapter` برای data readiness است؛ آن را در مسیر ارتوپدی بازپیاده‌سازی نمی‌کنیم.

برای نسخه اول، قرارداد افزایشی و مستقل ارتوپدی با شماره نسخه، منشأ و hash تعریف شود و mapping آینده آن در PR برای بازبینی تیم Integration ارائه شود. هیچ تغییری در فایل قرارداد مشترک، orchestrator، migration Integration یا اجرای مدل Imaging لازم نیست. دامنه `orthopedics_knee` با manifest پیشنهادی PR ۴۳ هم‌راستاست؛ Draftهای بسته نباید در manifest approved آن شمرده شوند.

PostgreSQL موجود، روابط معمول بین جداول و JSON نوع‌دار برای مجموعه کوچک روابط نسخه اول کافی است. در این مرحله نیاز فنی اثبات‌شده‌ای به queryهای graph پیچیده، graph database جدید یا Neo4j وجود ندارد. منبع حقیقت دانش همچنان Registry است؛ بسته محلی، محتوای کاندیدا و قراردادهای ارجاع آن را برای بررسی و ورود به همان Registry آماده می‌کند.

## وابستگی‌های باقی‌مانده

- بازبینی مستقل متخصص ارتوپدی برای گزاره‌ها، تعاریف معاینه و قواعد پرسشگری؛ Approved اولیه نباید ادعا شود.
- توافق مسیر Integration درباره مصرف envelope افزایشی، نگاشت provenance و نمایش Draft جدا از یافته و دانش تأییدشده.
- هر قاعده جدید ایمنی تنها پس از ورود دانش approved و طی گردش بررسی مستقل موتور فعلی قابل فعال‌سازی است.
- برای انتشار بالینی، اعتبارسنجی مستقل مجموعه موارد، کنترل UI/نقش‌ها و CI کامل لازم است؛ این ممیزی صرفاً وضعیت پیاده‌سازی در commitهای مشخص را توصیف می‌کند.
