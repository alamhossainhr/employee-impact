# Employee Work & Impact Tracker — লোকাল অফিস অ্যাপ

এই প্যাকেজে SQL Server 2008 R2-compatible schema, Python Flask web app, বাংলা-সহায়ক interface, weekly/monthly SQL report, automated tests ও Windows launcher আছে। এটি আপনার আগের HR/Payroll database পরিবর্তন করে না। নতুন `EmployeeImpactDB` ব্যবহার করে।

## ১. কী কাজ করে

- Admin বিভাগ, টিম, কর্মী ও user account তৈরি করবেন।
- Employee নিজের এবং নিজের **বর্তমান টিমের** এক বা একাধিক কর্মীর ঘটনা draft হিসেবে লিখতে পারবেন।
- একই বিভাগের অন্য টিমের তথ্যও Employee দেখতে পারবেন না। HR ও Admin সব বিভাগের তথ্য দেখতে পারবেন।
- Incident record-এ নিজের টিমের **সব রেকর্ড** Employee দেখতে পারবেন; অন্যের draft edit করতে পারবেন না। Record creator-ই Draft/Returned edit ও upload করবেন।
- ভালো কাজ / ভুল / উন্নয়ন, ঘটনার সময়, বিবরণ, estimated gain/loss, ছবি/ডকুমেন্ট জমা হবে।
- Draft → Submitted → HR Reviewed → Admin Approved/Rejected/Returned। Admin চাইলে HR review ছাড়াও Submitted record approve করতে পারবেন। HR চূড়ান্ত অনুমোদন দিতে পারবেন না।
- Admin approval-এর সময় verified amount দেবেন। Approved record সরাসরি edit করা যায় না। Admin reason দিয়ে Reopen করলে পুরোনো amount বর্তমান report থেকে বাদ যায়; correction এবং পুনরায় approval প্রয়োজন। Reviews/Audit-এ আগের সিদ্ধান্ত থাকবে।
- JPG/PNG/PDF/DOCX/XLSX, প্রতি ফাইল 10 MB। File signature checks, random private storage names, SHA-256; প্রত্যেক download-এ server authorization। ফাইলটি preview-এর বদলে attachment হিসেবে download হয়। DOC/XLS legacy binary এবং macro formats এই সংস্করণে নেই। Antivirus scanning সংযুক্ত নয়; প্রতিষ্ঠানের endpoint scanner দিয়ে private_uploads scan করুন।
- HR/Admin corrective action assign করবেন, due date থাকবে; owner বা HR/Admin complete করতে পারবেন। Overdue চিহ্ন দেখা যাবে।
- Saturday–Friday weekly এবং calendar-month summary। Event date অনুযায়ী filter; approval date অনুযায়ী নয়। Pending আলাদা। Employee/Team/Department filters, UTF-8 CSV (Excel-এ খুলবে), print layout থেকে PDF। সরাসরি XLSX/PDF generation এই সংস্করণে নেই।
- এই সংস্করণে periodic reports live হিসাব করে। Email scheduling/notifications নেই।

## ২. কোন কম্পিউটারে কী লাগবে

App server হিসেবে সমর্থিত Windows 10/11 বা Windows Server ব্যবহার করুন। SQL Server 2008 R2 অন্য LAN server-এ থাকলেও চলবে। App server-এ Python 3.11/3.12 64-bit, Microsoft SQL Server ODBC driver এবং এই source code লাগবে। Employee computer-এ শুধু browser দরকার। পুরোনো SQL host-এ Python install করা প্রয়োজন নেই।

Microsoft driver-এর version/OS compatibility এবং আপনার SQL Server-এর TLS patch level যাচাই করুন। Driver documentation-এ পুরোনো SQL version-এর compatibility matrix দেখুন। `.env.example`-এর ODBC 17 connection string একটি configuration example; এখানে আপনার instance-এ live compatibility যাচাই করা হয়নি। Encrypt=yes হলে server certificate এবং TLS configuration সঠিক থাকতে হবে। Connection error হলে network, instance TCP port, driver ও TLS patch DBA দিয়ে যাচাই করুন; কোড স্বয়ংক্রিয়ভাবে unencrypted connection-এ নামবে না।

## ৩. Database তৈরি

1. SSMS-এ DBA account দিয়ে `schema.sql` খুলুন।
2. পুরো script একবার চালান। এটি `EmployeeImpactDB` তৈরি করে tables/indexes বসাবে। Existing Users table থাকলে থামবে। আবার চালিয়ে reset করার script নয়।
3. নতুন instance-এ failure হলে partial database আছে কি না DBA দিয়ে পরীক্ষা করুন; payroll database delete করবেন না।
4. App-এর জন্য আলাদা SQL login অথবা dedicated Windows service account দিন। Script-এর শেষে table-level least-privilege permission উদাহরণ আছে। `sa` / `db_owner` ব্যবহার করবেন না।
5. Employee-কে SQL account দেবেন না। **টিমের isolation app server-এ enforce হয়; SQL login হাতে পেলে এই boundary প্রযোজ্য নয়।** Runtime account, DBA ও server filesystem administrator trusted privileged operator। Stored-procedure-only access এবং database-side row policies এই সংস্করণে নেই; SQL 2008 R2-এর row-level security feature নেই।

## ৪. Install — Windows PowerShell

ZIP extract করে folder খুলে PowerShell চালান:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

শেষ command-এর random value `.env`-এর `SECRET_KEY`-এ দিন। একই server-এ স্থায়ী secret রাখুন; change করলে sessions invalidate হবে। তারপর `.env` edit করুন:

```dotenv
DB_MODE=sqlserver
SQL_CONNECTION_STRING=DRIVER={ODBC Driver 17 for SQL Server};SERVER=YOUR_SERVER\YOUR_INSTANCE;DATABASE=EmployeeImpactDB;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=no;
UPLOAD_DIR=./private_uploads
HOST=127.0.0.1
PORT=8080
COOKIE_SECURE=false
```

Windows integrated authentication হলে যে Windows account দিয়ে app run হবে সেই account-কে database permission দিতে হবে। SQL login ব্যবহার করলে DBA প্রদত্ত connection string secret হিসেবে `.env`-এ রাখুন; password কোড বা ZIP-এ দেবেন না। `.env`, backups ও upload folder শুধু service account/authorized IT-র জন্য filesystem permissions দিন।

## ৫. প্রথম Admin তৈরি ও SQL connection পরীক্ষা

```powershell
.\.venv\Scripts\python.exe sqlserver_smoke.py
.\.venv\Scripts\python.exe -m flask --app app create-admin
.\.venv\Scripts\python.exe app.py
```

Smoke script temporary rows লিখে rollback করে—identity, Unicode, dates, FK এবং approval arithmetic যাচাই করে। SQL identity sequence-এ gap হতে পারে। কোনো preset admin password নেই; create-admin-এ minimum 12-character password দিন। নিজের PC-তে `http://127.0.0.1:8080` খুলুন। `start_windows.bat` দিয়েও চালাতে পারবেন।

Login → Settings → Department → Team → Employee → User account, এই ক্রমে setup করুন। HR/Admin account linked employee ছাড়াও তৈরি করা যায়। Employee account-এ employee link বাধ্যতামূলক, এক কর্মীর একটি account। Admin password reset করলে পুরোনো sessions invalid হয়; Disable করলে পরের request থেকেই access বন্ধ। Admin account disabling app-এ block করা হয়েছে; privileged admin-access changes DBA/IT review করে করবেন।

## ৬. LAN-এ চালানো

Local test শেষ হলে `.env`-এ `HOST=0.0.0.0` অথবা server-এর নির্দিষ্ট LAN IP দিন, restart করুন। Windows Firewall-এ app port শুধু office subnet-এ allow করুন। Server IP উদাহরণ `192.168.1.50` হলে colleague browser-এ `http://192.168.1.50:8080`। স্থায়ী IP/DNS দিন। SQL port শুধু app server/DBA host-এর জন্য রাখুন, employee computers-এর জন্য নয়।

প্রকৃত employee data ও passwords ব্যবহার করার আগে LAN HTTPS reverse proxy configure করুন—যেমন IIS/approved internal proxy with trusted internal certificate। তখন app loopback-এ রাখুন, reverse proxy-র HTTPS address ব্যবহার করুন এবং `COOKIE_SECURE=true` দিন। HTTP mode কেবল প্রথম local connectivity test-এর জন্য। Waitress production WSGI server ব্যবহার হয়েছে; Flask debug server নয়। IT Windows service/Task Scheduler দিয়ে dedicated account-এর অধীনে auto-start setup করতে পারবেন।

## ৭. রিপোর্ট ও টাকার নিয়ম

সব amount BDT; SQL-এ integer **পয়সা**। ৳10.01 = 1001। Floating-point-এ টাকা সংরক্ষণ করা হয় না। Negative amount বা দুই decimal-এর বেশি amount reject হয়। None financial impact হলে amount অবশ্যই 0।

এক ঘটনায় N কর্মী থাকলে estimated ও approved amount তাঁদের মধ্যে সমান ভাগ হয়; অবশিষ্ট পয়সা ascending Employee ID অনুযায়ী যায়। উদাহরণ: 2 কর্মীর ৳10.01 = ৳5.01 + ৳5.00। Financial total তাই duplicate হয় না। Good/Mistake incident count প্রতিটি involved employee-র জন্য 1; employee counts যোগ করলে unique factory incident count পাওয়া যাবে না। Dashboard header record-level এবং report employee allocations আলাদা। Custom percentage allocation এখন নেই।

Report-এ শুধু incident আছে এমন কর্মীদের row আসবে; zero-incident manpower report নয়। Event-এর team এবং employee name/designation snapshot অপরিবর্তিত। Employee transfer করলে বর্তমান employee login নতুন টিম দেখবে, পুরোনো team incident নিজের হলেও দেখতে পাবে না; HR/Admin history দেখবেন। একটি period-এ একই employee দুই incident team-এ থাকলে আলাদা row হবে।

`weekly_monthly_reports.sql` হলো all-factory direct SQL report; কেবল authorized HR/Admin/DBA reporting identity দিয়ে চালাবেন। App report আলাদাভাবে scope enforce করে। Summary ঘটনার local Bangladesh time অনুযায়ী; database audit timestamps UTC। পুরোনো period approval/reopen হলে live summary বদলায়; locked period closing এই সংস্করণে নেই।

## ৮. পরীক্ষা

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

Tests isolated SQLite fixture-এ application flow যাচাই করে; SQL Server production path-এ কোনো automatic SQLite fallback নেই। Tests team/file/report isolation, permissions, approval workflow, cent allocation, CSRF, stale-version conflicts, upload signature, team transfer, account reset এবং weekly boundaries cover করে। Fake cursor test SQL Server OUTPUT INSERTED contract যাচাই করে। Real engine verification-এর জন্য section 5-এর SQL smoke এবং অফিস acceptance checks চালান।

Test-only/demo চাইলে আলাদা `.env`-এ `DB_MODE=sqlite` ও `SQLITE_PATH=demo.db` দিয়ে `python -m flask --app app init-demo`, তারপর create-admin। Demo database প্রকৃত SQL Server নয়। `init-demo` নতুন demo file-এ একবার চালান।

## ৯. অফিস acceptance checklist

- Team A এবং Team B-তে আলাদা employee login: dashboard, direct record URL, attachment URL, CSV ও filters-এ cross-team access বন্ধ।
- HR সব record দেখে, approve করতে পারে না; Admin final verified amount দিয়ে approve করে।
- Bengali name/document, actual SQL Server money/date roundtrip, weekly Friday 23:59/Saturday 00:00 boundary পরীক্ষা।
- একই form দুইবার/stale tab submit-এ 409; Approved record immutable until reasoned reopen।
- Backup restore exercise: SQL database এবং private_uploads দুটোই restore করে attachment check।

## ১০. Backup ও সীমা

DBA দিয়ে daily full database backup ও প্রয়োজনমতো transaction-log backup schedule করুন। একই recovery point-এর `private_uploads`, secret configuration এবং source version সংরক্ষণ করুন। Restore-এর পর missing attachment reconciliation চালান। Upload file write ও SQL commit এক distributed transaction নয়; normal failure-এ cleanup হয়, server crash হলে orphan file থাকতে পারে। Delete UI নেই, ফলে accidental record deletion হয় না। Retention/purge আলাদা reviewed workflow।

এই delivery একটি কার্যকর প্রথম source-code সংস্করণ। আপনার অফিস server-এ install/deploy হয়নি; real SQL 2008 R2 runtime/driver integration এখানে চালানো হয়নি। Large-scale pagination, custom allocation, Active Directory SSO, malware scanning integration, automated email summaries ও separate Department Manager role এই সংস্করণে নেই। আপনার নির্দেশ অনুযায়ী Employee/HR/Admin তিন role-ই আছে। Logs app-এ append-only; privileged DBA account দিয়ে tamper প্রতিরোধের জন্য off-server audit backups দরকার।

## Technical references

- Microsoft ODBC version compatibility: https://learn.microsoft.com/en-us/sql/connect/odbc/windows/system-requirements-installation-and-driver-files
- SQL connection driver history: https://learn.microsoft.com/en-us/sql/connect/connect-history
- SQL 2008/R2 TLS patch guidance: https://learn.microsoft.com/en-us/troubleshoot/sql/database-engine/connect/tls-1-2-support-microsoft-sql-server
- Flask uploads: https://flask.palletsprojects.com/en/stable/patterns/fileuploads/
