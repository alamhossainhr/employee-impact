import csv
import hashlib
import io
import os
import secrets
import uuid
import zipfile
import re
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, session, g, render_template, redirect, url_for, abort, flash, send_file, Response
from werkzeug.security import generate_password_hash, check_password_hash
from db import Database

load_dotenv()
app = Flask(__name__)
key = os.getenv('SECRET_KEY', '')
if len(key) < 32 or key.startswith('REPLACE_'):
    raise RuntimeError('Set SECRET_KEY to at least 32 random characters in .env')
app.config.update(SECRET_KEY=key, MAX_CONTENT_LENGTH=25*1024*1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
db = Database()
upload_dir = Path(os.getenv('UPLOAD_DIR', './private_uploads')).resolve()
upload_dir.mkdir(parents=True, exist_ok=True)


def local_now():
    return datetime.now(ZoneInfo('Asia/Dhaka')).replace(tzinfo=None)

def valid_credential(value, max_length):
    return (
        6 <= len(value) <= max_length
        and re.search(r'[A-Za-z]', value) is not None
        and re.search(r'[0-9]', value) is not None
        and not any(ch.isspace() for ch in value)
    )

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None,microsecond=0)


def audit(tx, event, entity=None, details=''):
    tx.execute('INSERT INTO AuditLogs(UserId,Event,EntityId,Details,CreatedAt) VALUES(?,?,?,?,?)',
               (g.user['Id'] if getattr(g, 'user', None) else None, event, entity, details[:4000], now()))


def csrf():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_hex(32)
    return session['csrf']

app.jinja_env.globals['csrf'] = csrf
app.jinja_env.filters['money'] = lambda v: f'{Decimal(v or 0)/100:,.2f}'


@app.before_request
def authenticate():
    g.user = None
    if session.get('uid'):
        with db.transaction() as tx:
            g.user = tx.one('SELECT u.*,e.TeamId,e.Name AS EmployeeName FROM Users u LEFT JOIN Employees e ON e.Id=u.EmployeeId WHERE u.Id=? AND u.Active=1', (session['uid'],))
        if g.user and (g.user['AuthVersion'] != session.get('av') or (g.user['Role']=='Employee' and g.user['TeamId'] is None)):
            g.user = None
        if not g.user:
            session.clear()
    if request.method == 'POST':
        expected, supplied = session.get('csrf', ''), request.form.get('csrf', '')
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, 'Invalid form token. Reload this page.')

@app.after_request
def headers(response):
    is_preview = request.endpoint == 'preview_attachment'

    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = (
        'SAMEORIGIN' if is_preview else 'DENY'
    )

    ancestors = "'self'" if is_preview else "'none'"

    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self'; "
        "frame-src 'self'; "
        "script-src 'self'; "
        f"frame-ancestors {ancestors}; "
        "form-action 'self'; "
        "base-uri 'none'"
    )

    response.headers['Cache-Control'] = 'no-store'
    return response


def login_required(fn):
    @wraps(fn)
    def wrapped(*a, **kw):
        if not g.user:
            return redirect(url_for('login'))
        return fn(*a, **kw)
    return wrapped


def require_role(*roles):
    if g.user['Role'] not in roles:
        abort(403)


def scope(alias='r'):
    if g.user['Role'] in ('HR', 'Admin'):
        return '1=1', []
    return f'{alias}.TeamId=?', [g.user['TeamId']]


def record(tx, rid):
    condition, params = scope()
    result = tx.one('SELECT r.*,t.Name AS TeamName,d.Name AS DepartmentName,u.Username AS Reporter FROM Records r JOIN Teams t ON t.Id=r.TeamId JOIN Departments d ON d.Id=t.DepartmentId JOIN Users u ON u.Id=r.CreatedBy WHERE r.Id=? AND '+condition, [rid]+params)
    if not result:
        abort(404)
    return result


def editable(r):
    return r['CreatedBy'] == g.user['Id'] and r['Status'] in ('Draft','Returned')


def cents(value):
    try:
        n = Decimal(value)
        if not n.is_finite() or n < 0 or n > Decimal('99999999999.99') or n != n.quantize(Decimal('.01')):
            raise ValueError()
        return int(n*100)
    except (InvalidOperation, ValueError, TypeError):
        abort(400, 'Amount must be nonnegative, within limit, with at most 2 decimals.')


def text(name, limit, required=True):
    v = request.form.get(name, '').strip()
    if len(v) > limit or (required and not v):
        abort(400, 'Invalid '+name)
    return v


def int_field(name):
    try:
        return int(request.form[name])
    except (KeyError, ValueError):
        abort(400, 'Invalid '+name)


def allocate(total, ids):
    q, remainder = divmod(total, len(ids))
    return {eid:q+(i < remainder) for i,eid in enumerate(sorted(ids))}


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = text('username',80).lower()
        password = request.form.get('password', '')
        with db.transaction() as tx:
            # SQL Server row locks serialize failure counts. SQLite tests serialize writes.
            hint = ' WITH (UPDLOCK,ROWLOCK)' if db.mode != 'sqlite' else ''
            u = tx.one('SELECT * FROM Users'+hint+' WHERE Username=?', (username,))
            locked = u and u['LockedUntil'] and datetime.fromisoformat(str(u['LockedUntil'])) > now()
            if not u or not u['Active'] or locked or not check_password_hash(u['PasswordHash'], password):
                if u and not locked:
                    count = u['FailedAttempts']+1
                    tx.execute('UPDATE Users SET FailedAttempts=?,LockedUntil=? WHERE Id=?',
                               (count, now()+timedelta(minutes=15) if count >= 5 else None, u['Id']))
                flash('Login failed. Check credentials or wait 15 minutes if locked.', 'error')
                return render_template('login.html')
            tx.execute('UPDATE Users SET FailedAttempts=0,LockedUntil=NULL WHERE Id=?', (u['Id'],))
            session.clear()
            session['uid'], session['csrf'] = u['Id'], secrets.token_hex(32)
            session['av'] = u['AuthVersion']
            session.permanent = True
        return redirect(url_for('home'))
    return render_template('login.html')


@app.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def home():
    today = local_now().date()
    start_value = request.args.get('start_date') or today.isoformat()
    end_value = request.args.get('end_date') or start_value
    try:
        start_date = date.fromisoformat(start_value)
        end_date = date.fromisoformat(end_value)
        if end_date < start_date:
            abort(400, 'To date must be on or after From date.')
        exclusive_end = end_date + timedelta(days=1)
    except (ValueError, OverflowError):
        abort(400, 'Invalid date range.')
    status = request.args.get('status', '')
    if status not in ('', 'Draft', 'Submitted', 'Reviewed', 'Approved', 'Rejected', 'Returned'):
        abort(400, 'Invalid status.')
    condition, parameters = scope('r')
    condition += ' AND r.OccurredAt>=? AND r.OccurredAt<?'
    parameters += [start_date, exclusive_end]
    if status:
        condition += ' AND r.Status=?'
        parameters.append(status)
    with db.transaction() as tx:
        rows = tx.rows(
            'SELECT r.*,t.Name AS TeamName,d.Name AS DepartmentName '
            'FROM Records r JOIN Teams t ON t.Id=r.TeamId '
            'JOIN Departments d ON d.Id=t.DepartmentId '
            'WHERE '+condition+' ORDER BY r.OccurredAt DESC,r.Id DESC',
            parameters
        )
    approved = [r for r in rows if r['Status']=='Approved']
    gain = sum(r['VerifiedCents'] or 0 for r in approved if r['Impact']=='Gain')
    loss = sum(r['VerifiedCents'] or 0 for r in approved if r['Impact']=='Loss')
    return render_template('home.html',records=rows,gain=gain,loss=loss,
                           start_date=start_date,end_date=end_date,today=today,
                           selected_status=status)


def available_employees(tx):
    cond, params = scope('e')
    return tx.rows('SELECT e.*,t.Name AS TeamName FROM Employees e JOIN Teams t ON t.Id=e.TeamId WHERE e.Active=1 AND '+cond+' ORDER BY e.Name', params)


def record_input(tx):
    try:
        ids = sorted(set(int(i) for i in request.form.getlist('employee_ids')))
        occurred = datetime.fromisoformat(request.form['occurred_at'])
        if occurred.tzinfo or occurred > local_now() or occurred.year < 2000:
            raise ValueError()
    except (ValueError, KeyError):
        abort(400, 'Invalid employees or event time. Use Bangladesh local time.')
    if not ids:
        abort(400, 'Select at least one employee.')
    allowed = {e['Id']:e for e in available_employees(tx)}
    if any(eid not in allowed for eid in ids):
        abort(403)
    employees = [allowed[eid] for eid in ids]
    if len({e['TeamId'] for e in employees}) != 1:
        abort(400, 'All selected employees must belong to the same team.')
    kind, impact = request.form.get('kind'), request.form.get('impact')
    if kind not in ('Good','Mistake','Improvement') or impact not in ('Gain','Loss','None'):
        abort(400)
    amount = cents(request.form.get('estimated', '0'))
    if impact == 'None' and amount:
        abort(400, 'No financial impact requires zero amount.')
    return employees, occurred, text('title',200), text('description',4000), kind, impact, amount


def set_subjects(tx, rid, employees, amount, updating=False):
    portions = allocate(amount, [e['Id'] for e in employees])
    if updating:
        # Preserve subjects and team after initial creation; avoids history ambiguity.
        for e in employees:
            tx.execute('UPDATE RecordEmployees SET EstimatedCents=?,VerifiedCents=NULL WHERE RecordId=? AND EmployeeId=?', (portions[e['Id']],rid,e['Id']))
    else:
        for e in employees:
            tx.execute('INSERT INTO RecordEmployees(RecordId,EmployeeId,EmployeeCode,EmployeeName,Designation,EstimatedCents) VALUES(?,?,?,?,?,?)',
                       (rid,e['Id'],e['Code'],e['Name'],e['Designation'],portions[e['Id']]))


@app.route('/records/new', methods=['GET','POST'])
@login_required
def new_record():
    with db.transaction() as tx:
        employees = available_employees(tx)
        if request.method == 'POST':
            subjects, occurred, title, description, kind, impact, amount = record_input(tx)
            rid = tx.insert('INSERT INTO Records(TeamId,CreatedBy,OccurredAt,Title,Description,Kind,Impact,EstimatedCents,Status,CreatedAt,UpdatedAt,Version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                            (subjects[0]['TeamId'],g.user['Id'],occurred,title,description,kind,impact,amount,'Draft',now(),now(),1))
            set_subjects(tx,rid,subjects,amount)
            audit(tx,'RecordCreated',rid)
            return redirect(url_for('detail',rid=rid))
    return render_template('record_form.html', employees=employees, r=None, selected=[])


@app.route('/records/<int:rid>/edit', methods=['GET','POST'])
@login_required
def edit_record(rid):
    with db.transaction() as tx:
        r = record(tx,rid)
        if not editable(r):
            abort(403)
        subjects = tx.rows('SELECT * FROM RecordEmployees WHERE RecordId=? ORDER BY EmployeeId', (rid,))
        if request.method == 'POST':
            try:
                occurred = datetime.fromisoformat(request.form['occurred_at'])
                if occurred.tzinfo or occurred.year < 2000 or occurred > local_now():
                    raise ValueError()
            except (KeyError,ValueError):
                abort(400)
            kind, impact = request.form.get('kind'),request.form.get('impact')
            if kind not in ('Good','Mistake','Improvement') or impact not in ('Gain','Loss','None'):
                abort(400)
            amount = cents(request.form.get('estimated','0'))
            if impact=='None' and amount:
                abort(400)
            c=tx.execute("UPDATE Records SET OccurredAt=?,Title=?,Description=?,Kind=?,Impact=?,EstimatedCents=?,VerifiedCents=NULL,UpdatedAt=?,Version=Version+1 WHERE Id=? AND Version=? AND Status IN ('Draft','Returned')",
                         (occurred,text('title',200),text('description',4000),kind,impact,amount,now(),rid,int_field('version')))
            if c.rowcount!=1:
                abort(409, 'Record changed; reload.')
            set_subjects(tx,rid,[{'Id':e['EmployeeId']} for e in subjects],amount,True)
            audit(tx,'RecordEdited',rid)
            return redirect(url_for('detail',rid=rid))
    return render_template('record_form.html',r=r,employees=[],selected=subjects)


@app.get('/records/<int:rid>')
@login_required
def detail(rid):
    with db.transaction() as tx:
        r=record(tx,rid)
        subjects=tx.rows('SELECT * FROM RecordEmployees WHERE RecordId=? ORDER BY EmployeeId',(rid,))
        attachments=tx.rows('SELECT * FROM Attachments WHERE RecordId=?',(rid,))
        reviews=tx.rows('SELECT v.*,u.Username FROM Reviews v JOIN Users u ON u.Id=v.UserId WHERE v.RecordId=? ORDER BY v.Id',(rid,))
        actions=tx.rows('SELECT a.*,e.Name AS Owner FROM CorrectiveActions a JOIN Employees e ON e.Id=a.OwnerEmployeeId WHERE a.RecordId=?',(rid,))
        owners=tx.rows('SELECT * FROM Employees WHERE TeamId=? AND Active=1 ORDER BY Name',(r['TeamId'],))
    return render_template('detail.html', r=r,subjects=subjects,attachments=attachments,reviews=reviews,actions=actions,owners=owners,can_edit=editable(r),today=local_now().date().isoformat())


@app.post('/records/<int:rid>/transition')
@login_required
def transition(rid):
    action=request.form.get('action')
    with db.transaction() as tx:
        r=record(tx,rid)
        comment=text('comment',2000,False)
        if action=='submit':
            if not editable(r): abort(403)
            target='Submitted'
        elif action=='review':
            require_role('HR')
            if r['Status']!='Submitted': abort(409)
            target='Reviewed'
        elif action in ('approve','reject','return','reopen'):
            require_role('Admin')
            if action=='reopen':
                if r['Status'] not in ('Approved','Rejected'): abort(409)
                target='Returned'
            else:
                if r['Status'] not in ('Submitted','Reviewed'): abort(409)
                target={'approve':'Approved','reject':'Rejected','return':'Returned'}[action]
            if action!='approve' and not comment: abort(400,'A reason is required.')
        else:
            abort(400)
        verified = cents(request.form.get('verified','')) if target=='Approved' else None
        if r['Impact']=='None' and verified not in (None,0): abort(400)
        c=tx.execute('UPDATE Records SET Status=?,VerifiedCents=?,Version=Version+1,UpdatedAt=? WHERE Id=? AND Version=? AND Status=?',
                     (target,verified,now(),rid,int_field('version'),r['Status']))
        if c.rowcount!=1: abort(409,'Record changed; reload.')
        subjects=tx.rows('SELECT EmployeeId FROM RecordEmployees WHERE RecordId=? ORDER BY EmployeeId',(rid,))
        amounts=allocate(verified,[e['EmployeeId'] for e in subjects]) if verified is not None else {}
        for e in subjects:
            tx.execute('UPDATE RecordEmployees SET VerifiedCents=? WHERE RecordId=? AND EmployeeId=?',(amounts.get(e['EmployeeId']),rid,e['EmployeeId']))
        tx.execute('INSERT INTO Reviews(RecordId,UserId,Action,Comment,CreatedAt) VALUES(?,?,?,?,?)',(rid,g.user['Id'],action,comment,now()))
        audit(tx,'RecordTransition',rid,f'{r["Status"]} -> {target}; verified paisa={verified}; {comment}')
    return redirect(url_for('detail',rid=rid))


def valid_file(name, data):
    ext=Path(name).suffix.lower()
    if ext in ('.jpg','.jpeg'): return data.startswith(b'\xff\xd8\xff')
    if ext=='.png': return data.startswith(b'\x89PNG\r\n\x1a\n')
    if ext=='.pdf': return data.startswith(b'%PDF-')
    if ext in ('.docx','.xlsx'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names=z.namelist()
                total=sum(i.file_size for i in z.infolist())
                return total < 100*1024*1024 and '[Content_Types].xml' in names and any(n.startswith('word/' if ext=='.docx' else 'xl/') for n in names) and not any('vbaproject' in n.lower() for n in names)
        except zipfile.BadZipFile: return False
    return False


@app.post('/records/<int:rid>/upload')
@login_required
def upload(rid):
    saved=None
    try:
        with db.transaction() as tx:
            r=record(tx,rid)
            if not editable(r): abort(403)
            file=request.files.get('file')
            if not file or not file.filename: abort(400)
            name=file.filename.replace('\\','/').split('/')[-1][:255]
            data=file.read(10*1024*1024+1)
            if not data or len(data)>10*1024*1024 or not valid_file(name,data):
                abort(400,'Allowed: genuine JPG, PNG, PDF, DOCX, XLSX; max 10 MB. Macro files excluded.')
            # This conditional write coordinates uploads with simultaneous submission.
            c=tx.execute("UPDATE Records SET Version=Version+1,UpdatedAt=? WHERE Id=? AND Version=? AND Status IN ('Draft','Returned')",(now(),rid,int_field('version')))
            if c.rowcount!=1: abort(409,'Record changed; reload.')
            stored=uuid.uuid4().hex+Path(name).suffix.lower()
            saved=upload_dir/stored
            saved.write_bytes(data)
            tx.execute('INSERT INTO Attachments(RecordId,StoredName,OriginalName,SizeBytes,SHA256,UploadedBy,CreatedAt) VALUES(?,?,?,?,?,?,?)',
                       (rid,stored,name,len(data),hashlib.sha256(data).hexdigest(),g.user['Id'],now()))
            audit(tx,'AttachmentUploaded',rid,name)
    except Exception:
        if saved: saved.unlink(missing_ok=True)
        raise
    return redirect(url_for('detail',rid=rid))


@app.get('/attachments/<int:aid>')
@login_required
def download(aid):
    with db.transaction() as tx:
        a=tx.one('SELECT * FROM Attachments WHERE Id=?',(aid,))
        if not a: abort(404)
        record(tx,a['RecordId'])
        audit(tx,'AttachmentDownloaded',a['RecordId'],str(aid))
    p=upload_dir/a['StoredName']
    if not p.is_file(): abort(404)
    return send_file(p,as_attachment=True,download_name=a['OriginalName'],mimetype='application/octet-stream')


@app.post('/records/<int:rid>/actions')
@login_required
def add_action(rid):
    require_role('HR','Admin')
    with db.transaction() as tx:
        r=record(tx,rid)
        owner=int_field('owner')
        if not tx.one('SELECT Id FROM Employees WHERE Id=? AND TeamId=? AND Active=1',(owner,r['TeamId'])): abort(400)
        try: due=date.fromisoformat(request.form['due'])
        except (KeyError,ValueError): abort(400)
        aid=tx.insert('INSERT INTO CorrectiveActions(RecordId,Description,OwnerEmployeeId,DueDate,Status,CreatedBy) VALUES(?,?,?,?,?,?)',(rid,text('description',2000),owner,due,'Open',g.user['Id']))
        audit(tx,'ActionCreated',rid,str(aid))
    return redirect(url_for('detail',rid=rid))


@app.post('/actions/<int:aid>/complete')
@login_required
def complete_action(aid):
    with db.transaction() as tx:
        a=tx.one('SELECT * FROM CorrectiveActions WHERE Id=?',(aid,))
        if not a: abort(404)
        record(tx,a['RecordId'])
        if g.user['Role'] not in ('HR','Admin') and a['OwnerEmployeeId']!=g.user['EmployeeId']: abort(403)
        tx.execute("UPDATE CorrectiveActions SET Status='Done' WHERE Id=? AND Status='Open'",(aid,))
        audit(tx,'ActionCompleted',a['RecordId'],str(aid))
    return redirect(url_for('detail',rid=a['RecordId']))


def report_rows():
    period=request.args.get('period','weekly')
    try: anchor=date.fromisoformat(request.args.get('date',local_now().date().isoformat()))
    except ValueError: abort(400)
    if period=='weekly':
        start=anchor-timedelta(days=(anchor.weekday()-5)%7)
        end=start+timedelta(days=7)
    elif period=='monthly':
        start=anchor.replace(day=1)
        end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    else: abort(400)
    cond,params=scope()
    filters=[]
    for field,column in [('department','t.DepartmentId'),('team','r.TeamId'),('employee','re.EmployeeId')]:
        value=request.args.get(field,'')
        if value:
            try: value=int(value)
            except ValueError: abort(400)
            filters.append(column+'=?');params.append(value)
    with db.transaction() as tx:
        rows=tx.rows('SELECT re.EmployeeId,re.EmployeeCode,re.EmployeeName,re.Designation,r.TeamId,t.Name AS TeamName,d.Name AS DepartmentName,r.Kind,r.Impact,r.Status,re.VerifiedCents FROM RecordEmployees re JOIN Records r ON r.Id=re.RecordId JOIN Teams t ON t.Id=r.TeamId JOIN Departments d ON d.Id=t.DepartmentId WHERE '+cond+(' AND '+' AND '.join(filters) if filters else '')+' AND r.OccurredAt>=? AND r.OccurredAt<?',params+[start,end])
        teams=tx.rows('SELECT t.*,d.Name AS DepartmentName FROM Teams t JOIN Departments d ON d.Id=t.DepartmentId WHERE '+('1=1' if g.user['Role'] in ('HR','Admin') else 't.Id=?'), [] if g.user['Role'] in ('HR','Admin') else [g.user['TeamId']])
        employees=available_employees(tx)
    summary={}
    for r in rows:
        key=(r['EmployeeId'],r['TeamId'])
        if key not in summary:
            summary[key] = {
                k: r[k]
                for k in (
                    'EmployeeId',
                    'TeamId',
                    'EmployeeCode',
                    'EmployeeName',
                    'Designation',
                    'TeamName',
                    'DepartmentName'
                )
            }
            summary[key].update(
                Good=0,
                Mistake=0,
                Improvement=0,
                Gain=0,
                Loss=0,
                Pending=0,
                Rejected=0
            )
        s=summary[key]
        if r['Status']=='Approved':
            s[r['Kind']]+=1
            if r['Impact']!='None': s[r['Impact']]+=r['VerifiedCents'] or 0
        elif r['Status']=='Rejected': s['Rejected']+=1
        else: s['Pending']+=1
    return start,end,list(summary.values()),teams,employees

@app.get('/reports/employee/<int:employee_id>/team/<int:team_id>')
@login_required
def employee_entries(employee_id, team_id):
    try:
        start = date.fromisoformat(request.args.get('start', ''))
        end = date.fromisoformat(request.args.get('end', ''))

        if end < start:
            abort(400, 'Invalid date range.')

        exclusive_end = end + timedelta(days=1)

    except (ValueError, OverflowError):
        abort(400, 'Invalid date range.')

    condition, parameters = scope('r')

    with db.transaction() as tx:
        records = tx.rows(
            'SELECT r.Id,r.Title,r.OccurredAt,r.Kind,r.Impact,'
            'r.Status,re.EmployeeCode,re.EmployeeName,'
            're.VerifiedCents AS AllocatedCents,'
            't.Name AS TeamName,d.Name AS DepartmentName '
            'FROM Records r '
            'JOIN RecordEmployees re ON re.RecordId=r.Id '
            'JOIN Teams t ON t.Id=r.TeamId '
            'JOIN Departments d ON d.Id=t.DepartmentId '
            'WHERE ' + condition +
            " AND r.Status='Approved' "
            'AND re.EmployeeId=? AND r.TeamId=? '
            'AND r.OccurredAt>=? AND r.OccurredAt<? '
            'ORDER BY r.OccurredAt DESC,r.Id DESC',
            parameters + [
                employee_id,
                team_id,
                start,
                exclusive_end
            ]
        )

    if not records:
        abort(404, 'No approved entries found in this period.')

    return render_template(
        'employee_entries.html',
        records=records,
        start=start,
        end=end
    )


def monthly_report_charts():
    try:
        anchor = date.fromisoformat(request.args.get('date', local_now().date().isoformat()))
    except ValueError:
        abort(400, 'Invalid date.')
    month_start = anchor.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    condition, params = scope('r')
    for field, column in [('department','t.DepartmentId'),('team','r.TeamId'),('employee','re.EmployeeId')]:
        value = request.args.get(field, '')
        if value:
            try: value = int(value)
            except ValueError: abort(400, 'Invalid filter.')
            condition += ' AND ' + column + '=?'
            params.append(value)
    with db.transaction() as tx:
        entries = tx.rows(
            'SELECT r.Id,r.Kind,r.Impact,re.VerifiedCents '
            'FROM Records r JOIN RecordEmployees re ON re.RecordId=r.Id '
            'JOIN Teams t ON t.Id=r.TeamId WHERE '+condition+
            " AND r.Status='Approved' AND r.OccurredAt>=? AND r.OccurredAt<?",
            params+[month_start,month_end]
        )
    gain = sum(e['VerifiedCents'] or 0 for e in entries if e['Impact']=='Gain')
    loss = sum(e['VerifiedCents'] or 0 for e in entries if e['Impact']=='Loss')
    unique = {e['Id']:e['Kind'] for e in entries}
    counts = {kind:sum(v==kind for v in unique.values()) for kind in ('Good','Mistake','Improvement')}
    total = len(unique)
    good_pct = counts['Good']*100/total if total else 0
    mistake_pct = counts['Mistake']*100/total if total else 0
    maximum = max(gain,loss,1)
    return dict(month=month_start.strftime('%B %Y'),start=month_start,
                end=month_end-timedelta(days=1),gain=gain,loss=loss,net=gain-loss,
                gain_height=gain*100/maximum,loss_height=loss*100/maximum,
                counts=counts,total=total,good_pct=good_pct,mistake_pct=mistake_pct,
                improvement_pct=counts['Improvement']*100/total if total else 0,
                good_stop=good_pct,mistake_stop=good_pct+mistake_pct)


@app.get('/reports')
@login_required
def reports():
    start,end,rows,teams,employees=report_rows()
    charts=monthly_report_charts()
    return render_template('reports.html',start=start,end=end-timedelta(days=1),rows=rows,teams=teams,employees=employees,charts=charts)


@app.get('/reports.csv')
@login_required
def report_csv():
    start,end,rows,_,_=report_rows()
    stream=io.StringIO(newline='')
    writer=csv.writer(stream)
    writer.writerow(['Code','Employee','Designation','Department','Team','Good','Mistake','Improvement','Gain BDT','Loss BDT','Net BDT','Pending','Rejected'])
    def safe(v):
        v=str(v)
        return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r')) else v
    for r in rows:
        writer.writerow([safe(r[k]) for k in ('EmployeeCode','EmployeeName','Designation','DepartmentName','TeamName')]+[r[k] for k in ('Good','Mistake','Improvement')]+[f'{Decimal(n)/100:.2f}' for n in (r['Gain'],r['Loss'],r['Gain']-r['Loss'])]+[r['Pending'],r['Rejected']])
    with db.transaction() as tx: audit(tx,'ReportExported',None,f'{start} to {end}; rows={len(rows)}')
    return Response('\ufeff'+stream.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename=employee-impact-{start}.csv'})


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    require_role('Admin')

    with db.transaction() as tx:
        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'department':
                tx.execute(
                    'INSERT INTO Departments(Name) VALUES(?)',
                    (text('name', 120),)
                )

            elif action == 'team':
                department_id = int_field('department')

                if not tx.one(
                    'SELECT Id FROM Departments WHERE Id=?',
                    (department_id,)
                ):
                    abort(400, 'Invalid department.')

                tx.execute(
                    'INSERT INTO Teams(DepartmentId,Name) VALUES(?,?)',
                    (department_id, text('name', 120))
                )

            elif action == 'employee':
                team_id = int_field('team')

                if not tx.one(
                    'SELECT Id FROM Teams WHERE Id=?',
                    (team_id,)
                ):
                    abort(400, 'Invalid team.')

                tx.execute(
                    'INSERT INTO Employees'
                    '(Code,Name,Designation,TeamId,Active) '
                    'VALUES(?,?,?,?,1)',
                    (
                        text('code', 40),
                        text('name', 160),
                        text('designation', 120),
                        team_id
                    )
                )

            elif action == 'user':
                role = request.form.get('role')

                if role not in ('Employee', 'HR', 'Admin'):
                    abort(400, 'Invalid role.')

                employee_value = request.form.get('employee', '')

                try:
                    employee_id = (
                        int(employee_value)
                        if employee_value else None
                    )
                except ValueError:
                    abort(400, 'Invalid employee.')

                if role == 'Employee' and employee_id is None:
                    abort(400, 'Employee role requires an employee.')

                if employee_id is not None:
                    if not tx.one(
                        'SELECT Id FROM Employees '
                        'WHERE Id=? AND Active=1',
                        (employee_id,)
                    ):
                        abort(400, 'Select an active employee.')

                username = request.form.get('username', '').lower()
                password = request.form.get('password', '')

                if not valid_credential(username, 80):
                    abort(
                        400,
                        'Username must contain 6-80 characters, '
                        'at least one English letter and one number; '
                        'spaces are not allowed.'
                    )

                if not valid_credential(password, 256):
                    abort(
                        400,
                        'Password must contain 6-256 characters, '
                        'at least one English letter and one number; '
                        'spaces are not allowed.'
                    )

                if tx.one(
                    'SELECT Id FROM Users WHERE Username=?',
                    (username,)
                ):
                    abort(400, 'Username already exists.')

                if employee_id is not None:
                    if tx.one(
                        'SELECT Id FROM Users WHERE EmployeeId=?',
                        (employee_id,)
                    ):
                        abort(
                            400,
                            'This employee already has an account.'
                        )

                password_hash = generate_password_hash(
                    password,
                    method='pbkdf2:sha256:600000'
                )

                tx.execute(
                    'INSERT INTO Users'
                    '(Username,PasswordHash,Role,EmployeeId,'
                    'Active,FailedAttempts) '
                    'VALUES(?,?,?,?,1,0)',
                    (
                        username,
                        password_hash,
                        role,
                        employee_id
                    )
                )

            elif action in ('disable', 'enable', 'reset'):
                user_id = int_field('user_id')

                user = tx.one(
                    'SELECT * FROM Users WHERE Id=?',
                    (user_id,)
                )

                if not user:
                    abort(404, 'User not found.')

                if action == 'disable' and user['Role'] == 'Admin':
                    abort(
                        400,
                        'Admin disabling is blocked; '
                        'review access with the DBA.'
                    )

                if action == 'reset':
                    password = request.form.get('password', '')

                    if not valid_credential(password, 256):
                        abort(
                            400,
                            'Password must contain 6-256 characters, '
                            'at least one English letter and one number; '
                            'spaces are not allowed.'
                        )

                    password_hash = generate_password_hash(
                        password,
                        method='pbkdf2:sha256:600000'
                    )

                    tx.execute(
                        'UPDATE Users '
                        'SET PasswordHash=?, FailedAttempts=0, '
                        'LockedUntil=NULL, AuthVersion=AuthVersion+1 '
                        'WHERE Id=?',
                        (password_hash, user_id)
                    )

                else:
                    tx.execute(
                        'UPDATE Users '
                        'SET Active=?, AuthVersion=AuthVersion+1 '
                        'WHERE Id=?',
                        (
                            0 if action == 'disable' else 1,
                            user_id
                        )
                    )

            elif action == 'transfer':
                employee_id = int_field('employee')
                team_id = int_field('team')

                if not tx.one(
                    'SELECT Id FROM Employees WHERE Id=?',
                    (employee_id,)
                ):
                    abort(400, 'Invalid employee.')

                if not tx.one(
                    'SELECT Id FROM Teams WHERE Id=?',
                    (team_id,)
                ):
                    abort(400, 'Invalid team.')

                tx.execute(
                    'UPDATE Employees SET TeamId=? WHERE Id=?',
                    (team_id, employee_id)
                )

            else:
                abort(400, 'Invalid action.')

            audit(
                tx,
                'Settings:' + action,
                None,
                request.form.get('username')
                or request.form.get('name')
                or request.form.get('employee')
                or request.form.get('user_id', '')
            )

            flash('Saved successfully.', 'success')
            return redirect(url_for('settings'))

        departments = tx.rows(
            'SELECT * FROM Departments ORDER BY Name'
        )

        teams = tx.rows(
            'SELECT t.*, d.Name AS DepartmentName '
            'FROM Teams t '
            'JOIN Departments d ON d.Id=t.DepartmentId '
            'ORDER BY d.Name,t.Name'
        )

        employees = tx.rows(
            'SELECT e.*, t.Name AS TeamName '
            'FROM Employees e '
            'JOIN Teams t ON t.Id=e.TeamId '
            'ORDER BY e.Name'
        )

        users = []
        directory = account_directory(tx)

    return render_template(
        'settings.html',
        departments=departments,
        teams=teams,
        employees=employees,
        users=users,
        directory=directory
    )


@app.get('/audit')
@login_required
def audit_page():
    require_role('Admin')
    with db.transaction() as tx:
        top='TOP 500 ' if db.mode!='sqlite' else ''
        limit=' LIMIT 500' if db.mode=='sqlite' else ''
        rows=tx.rows('SELECT '+top+'a.*,u.Username FROM AuditLogs a LEFT JOIN Users u ON u.Id=a.UserId ORDER BY a.Id DESC'+limit)
    return render_template('audit.html',rows=rows)


@app.errorhandler(Exception)
def error(exc):
    from werkzeug.exceptions import HTTPException
    if isinstance(exc,HTTPException):
        return render_template('error.html',code=exc.code,message=exc.description),exc.code
    # Do not expose DB connection strings, SQL statements or personal data to clients.
    app.logger.error('Unhandled server error (%s)',type(exc).__name__)
    return render_template('error.html',code=500,message='Server operation failed. Contact Admin; check duplicate values and database availability.'),500


@app.cli.command('init-demo')
def init_demo():
    db.init_demo()
    print('SQLite demo schema initialized. Not production SQL Server.')


@app.cli.command('create-admin')
def create_admin():
    import getpass

    username = input(
        'Admin username (6+ characters; letter and number): '
    ).lower()

    password = getpass.getpass(
        'Password (6+ characters; letter and number): '
    )

    if not valid_credential(username, 80):
        raise RuntimeError(
            'Username requires 6-80 characters, '
            'an English letter and a number; no spaces.'
        )

    if not valid_credential(password, 256):
        raise RuntimeError(
            'Password requires 6-256 characters, '
            'an English letter and a number; no spaces.'
        )

    with db.transaction() as tx:
        if tx.one(
            'SELECT Id FROM Users WHERE Username=?',
            (username,)
        ):
            raise RuntimeError('Username already exists.')

        tx.execute(
            'INSERT INTO Users'
            '(Username,PasswordHash,Role,EmployeeId,'
            'Active,FailedAttempts) '
            'VALUES(?,?,?,NULL,1,0)',
            (
                username,
                generate_password_hash(
                    password,
                    method='pbkdf2:sha256:600000'
                ),
                'Admin'
            )
        )

    print('Admin created successfully.')



def document_preview_data(path):
    """Limited text/table preview; no macros or external URLs executed."""
    import xml.etree.ElementTree as ET

    def read_xml(archive, name):
        info = archive.getinfo(name)

        if info.file_size > 5 * 1024 * 1024:
            abort(413, 'Document is too large for preview. Download it.')

        data = archive.read(name)

        if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
            abort(400, 'Unsupported document XML.')

        return ET.fromstring(data)

    extension = path.suffix.lower()

    try:
        with zipfile.ZipFile(path) as archive:
            if extension == '.docx':
                root = read_xml(archive, 'word/document.xml')

                namespace = {
                    'w': (
                        'http://schemas.openxmlformats.org/'
                        'wordprocessingml/2006/main'
                    )
                }

                paragraphs = []

                for paragraph in root.findall('.//w:p', namespace):
                    content = ''.join(
                        node.text or ''
                        for node in paragraph.findall('.//w:t', namespace)
                    )

                    if content.strip():
                        paragraphs.append(content)

                return {
                    'paragraphs': paragraphs[:1000],
                    'sheets': []
                }

            namespace = {
                's': (
                    'http://schemas.openxmlformats.org/'
                    'spreadsheetml/2006/main'
                )
            }

            shared_strings = []

            if 'xl/sharedStrings.xml' in archive.namelist():
                root = read_xml(archive, 'xl/sharedStrings.xml')

                for item in root.findall('s:si', namespace):
                    shared_strings.append(
                        ''.join(
                            node.text or ''
                            for node in item.findall('.//s:t', namespace)
                        )
                    )

            sheet_files = sorted(
                name
                for name in archive.namelist()
                if name.startswith('xl/worksheets/')
                and name.endswith('.xml')
                and '/' not in name[len('xl/worksheets/'):]
            )

            sheets = []

            for sheet_file in sheet_files[:5]:
                root = read_xml(archive, sheet_file)
                rows = []

                for row in root.findall('.//s:sheetData/s:row', namespace)[:200]:
                    cells = []

                    for cell in row.findall('s:c', namespace):
                        reference = cell.get('r', '')
                        column = 0

                        for letter in reference:
                            if 'A' <= letter <= 'Z':
                                column = column * 26 + ord(letter) - ord('A') + 1
                            else:
                                break

                        if not 1 <= column <= 50:
                            continue

                        while len(cells) < column:
                            cells.append('')

                        cell_type = cell.get('t', '')
                        value = cell.findtext('s:v', default='', namespaces=namespace)

                        if cell_type == 's':
                            try:
                                index = int(value)

                                value = (
                                    shared_strings[index]
                                    if 0 <= index < len(shared_strings)
                                    else ''
                                )
                            except ValueError:
                                value = ''

                        elif cell_type == 'inlineStr':
                            value = ''.join(
                                node.text or ''
                                for node in cell.findall('.//s:t', namespace)
                            )

                        elif cell_type == 'b':
                            value = 'True' if value == '1' else 'False'

                        cells[column - 1] = value

                    rows.append(cells)

                sheets.append({
                    'name': Path(sheet_file).name,
                    'rows': rows
                })

            return {
                'paragraphs': [],
                'sheets': sheets
            }

    except (
        zipfile.BadZipFile,
        KeyError,
        ET.ParseError,
        RuntimeError
    ):
        abort(400, 'Document could not be previewed. Download it instead.')


@app.get('/attachments/<int:aid>/preview')
@login_required
def preview_attachment(aid):
    with db.transaction() as tx:
        attachment = tx.one(
            'SELECT * FROM Attachments WHERE Id=?',
            (aid,)
        )

        if not attachment:
            abort(404)

        # Same team/HR/Admin authorization as record details.
        record(tx, attachment['RecordId'])

        audit(
            tx,
            'AttachmentViewed',
            attachment['RecordId'],
            str(aid)
        )

    path = (upload_dir / attachment['StoredName']).resolve()

    if path.parent != upload_dir.resolve() or not path.is_file():
        abort(404)

    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.pdf': 'application/pdf'
    }

    extension = path.suffix.lower()

    if extension in mime_types:
        return send_file(
            path,
            as_attachment=False,
            download_name=attachment['OriginalName'],
            mimetype=mime_types[extension]
        )

    if extension in ('.docx', '.xlsx'):
        preview = document_preview_data(path)

        return render_template(
            'document_preview.html',
            filename=attachment['OriginalName'],
            paragraphs=preview['paragraphs'],
            sheets=preview['sheets']
        )

    abort(415, 'Preview is unavailable for this file type.')



def account_directory(tx):
    query = request.args.get('q', '').strip()[:160]
    try:
        page = max(1, int(request.args.get('page', '1')))
    except ValueError:
        abort(400, 'Invalid page.')
    base = '''
        SELECT 'employee' AS PersonType,e.Id AS PersonId,
               e.Id AS EmployeeId,u.Id AS UserId,e.Code,e.Name,
               e.Designation,t.Name AS TeamName,d.Name AS DepartmentName,
               u.Username,u.Role,u.Active
        FROM Employees e
        LEFT JOIN Users u ON u.EmployeeId=e.Id
        JOIN Teams t ON t.Id=e.TeamId
        JOIN Departments d ON d.Id=t.DepartmentId
        UNION ALL
        SELECT 'user' AS PersonType,u.Id AS PersonId,
               NULL AS EmployeeId,u.Id AS UserId,'' AS Code,
               '' AS Name,'' AS Designation,'' AS TeamName,
               '' AS DepartmentName,u.Username,u.Role,u.Active
        FROM Users u WHERE u.EmployeeId IS NULL
    '''
    condition = '1=1'
    params = []
    if query:
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        if db.mode != 'sqlite':
            escaped = escaped.replace('[', '\\[')
        columns = ['Code','Name','Username','TeamName','DepartmentName']
        condition = '(' + ' OR '.join("p."+col+" LIKE ? ESCAPE '\\'" for col in columns) + ')'
        params = ['%'+escaped+'%'] * len(columns)
    total = tx.one('SELECT COUNT(*) AS Total FROM ('+base+') p WHERE '+condition, params)['Total']
    pages = max(1, (total + 19)//20)
    page = min(page, pages)
    sql = ('SELECT * FROM (SELECT p.*, ROW_NUMBER() OVER '
           '(ORDER BY p.Code,p.Username,p.PersonType,p.PersonId) AS RowNumber '
           'FROM ('+base+') p WHERE '+condition+') numbered '
           'WHERE RowNumber BETWEEN ? AND ? ORDER BY RowNumber')
    rows = tx.rows(sql, params+[(page-1)*20+1,page*20])
    return {'rows':rows,'total':total,'page':page,'pages':pages,'q':query}


@app.route('/settings/person/<kind>/<int:person_id>', methods=['GET','POST'])
@login_required
def person_settings(kind, person_id):
    require_role('Admin')
    if kind not in ('employee','user'):
        abort(404)
    with db.transaction() as tx:
        employee = None
        if kind == 'employee':
            employee = tx.one('SELECT * FROM Employees WHERE Id=?',(person_id,))
            if not employee: abort(404)
            user = tx.one('SELECT * FROM Users WHERE EmployeeId=?',(person_id,))
        else:
            user = tx.one('SELECT * FROM Users WHERE Id=? AND EmployeeId IS NULL',(person_id,))
            if not user: abort(404)
        teams = tx.rows('SELECT t.*,d.Name AS DepartmentName FROM Teams t JOIN Departments d ON d.Id=t.DepartmentId ORDER BY d.Name,t.Name')
        if request.method == 'POST':
            action = request.form.get('action','')
            if action == 'name':
                if not employee: abort(400,'This account has no linked employee name.')
                name = text('name',160)
                tx.execute('UPDATE Employees SET Name=? WHERE Id=?',(name,employee['Id']))
                audit(tx,'EmployeeNameChanged',employee['Id'],name)
            elif action == 'team':
                if not employee: abort(400)
                team_id = int_field('team')
                if not tx.one('SELECT Id FROM Teams WHERE Id=?',(team_id,)): abort(400)
                tx.execute('UPDATE Employees SET TeamId=? WHERE Id=?',(team_id,employee['Id']))
                audit(tx,'EmployeeTeamChanged',employee['Id'],str(team_id))
            elif action == 'username':
                if not user: abort(400,'Create an account for this employee first.')
                username = request.form.get('username','').lower()
                if username != user['Username']:
                    if not valid_credential(username,80):
                        abort(400,'Username: 6-80 characters; English letter and number; no spaces.')
                    if tx.one('SELECT Id FROM Users WHERE Username=? AND Id<>?',(username,user['Id'])):
                        abort(400,'Username already exists.')
                    tx.execute('UPDATE Users SET Username=?,AuthVersion=AuthVersion+1 WHERE Id=?',(username,user['Id']))
                    audit(tx,'UsernameChanged',user['Id'],user['Username']+' -> '+username)
            elif action == 'password':
                if not user: abort(400)
                password = request.form.get('password','')
                if not valid_credential(password,256):
                    abort(400,'Password: 6-256 characters; English letter and number; no spaces.')
                tx.execute('UPDATE Users SET PasswordHash=?,FailedAttempts=0,LockedUntil=NULL,AuthVersion=AuthVersion+1 WHERE Id=?',
                           (generate_password_hash(password,method='pbkdf2:sha256:600000'),user['Id']))
                audit(tx,'PasswordReset',user['Id'],'Password changed; existing sessions invalidated.')
            elif action in ('enable','disable'):
                if not user: abort(400)
                if action == 'disable' and user['Role']=='Admin': abort(400,'Admin disabling is blocked.')
                tx.execute('UPDATE Users SET Active=?,AuthVersion=AuthVersion+1 WHERE Id=?',(1 if action=='enable' else 0,user['Id']))
                audit(tx,'Account:'+action,user['Id'])
            else:
                abort(400,'Invalid action.')
            flash('Updated successfully.','success')
            return redirect(url_for('person_settings',kind=kind,person_id=person_id))
    # Password hash is never passed to the template.
    public_user = {k:user[k] for k in ('Id','Username','Role','Active')} if user else None
    return render_template('person_settings.html',employee=employee,user=public_user,teams=teams)


if __name__=='__main__':
    from waitress import serve
    serve(app,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8080')),threads=4)
