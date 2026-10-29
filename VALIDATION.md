# Validation — 2026-10-11

Executed: `python -m pytest employee-impact/tests -q` — **10 passed**.
Executed: Python compileall — passed.

Verified with isolated SQLite application fixtures:
- Employee cannot read another team's dashboard/record/edit page/attachment/CSV.
- HR reads all teams and cannot approve; Admin approves.
- Multi-employee allocation preserves each paisa and report totals.
- Reopening removes approved amounts from the live summary.
- CSRF failures and optimistic-lock conflicts reject writes.
- Submitted/approved record edits and uploads are blocked.
- Invalid amount, cross-team subjects and fake file signatures reject.
- Admin setup, account reset session invalidation and team transfer boundaries.
- Corrective action owner restrictions and Friday/Saturday report boundary.
- All primary page templates render and return/edit/resubmit works.
- Per-account login lockout.

A fake SQL cursor verifies the SQL Server `OUTPUT INSERTED.Id` insert shape.
SQL source avoids post-2008 constructs (TRY_CONVERT, OFFSET/FETCH, CREATE OR ALTER,
STRING_AGG, JSON, DATEFROMPARTS, DROP IF EXISTS and database row-level security).

**Not verified here:** Actual SQL Server 2008 R2 execution, ODBC/TLS connection,
Windows installation, LAN browser/device behavior, production concurrency/load,
HTTPS proxy, antivirus integration and backup restore.

Run `sqlserver_smoke.py` against the configured office SQL Server and perform
README_BN.md acceptance checks before using real employee data. No office
server was contacted or deployed to during delivery.
