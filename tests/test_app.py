import os
import sys
import io
import re
import sqlite3
from pathlib import Path
import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['SECRET_KEY']='test-secret-32-characters-minimum-abcdefgh'
os.environ['DB_MODE']='sqlite'
os.environ['UPLOAD_DIR']='/tmp/impact-test-uploads'
from app import app, db, allocate

@pytest.fixture
def env(tmp_path):
    db.mode='sqlite'
    db.path=str(tmp_path/'test.db')
    import app as module
    module.upload_dir=tmp_path/'uploads';module.upload_dir.mkdir()
    db.init_demo()
    app.config['TESTING']=True
    hashed=generate_password_hash('Secure-password-123',method='pbkdf2:sha256:600000')
    with db.transaction() as tx:
        for d in ('HR Department','Sewing'):
            tx.execute('INSERT INTO Departments(Name) VALUES(?)',(d,))
        for dep,name in ((2,'Team A'),(2,'Team B'),(1,'HR Team')):
            tx.execute('INSERT INTO Teams(DepartmentId,Name) VALUES(?,?)',(dep,name))
        for code,name,team in (('A1','Alice',1),('A2','Amina',1),('B1','Bob',2)):
            tx.execute('INSERT INTO Employees(Code,Name,Designation,TeamId,Active) VALUES(?,?,?,?,1)',(code,name,'Officer',team))
        for username,role,eid in (('alice','Employee',1),('bob','Employee',3),('hr','HR',None),('admin','Admin',None)):
            tx.execute('INSERT INTO Users(Username,PasswordHash,Role,EmployeeId,Active,FailedAttempts) VALUES(?,?,?,?,1,0)',(username,hashed,role,eid))
    return app.test_client()


def login(client,name):
    client.get('/login')
    with client.session_transaction() as s: token=s['csrf']
    r=client.post('/login',data={'csrf':token,'username':name,'password':'Secure-password-123'})
    assert r.status_code==302


def post(client,path,data):
    with client.session_transaction() as s: token=s['csrf']
    return client.post(path,data={'csrf':token,**data})


def create(client,ids=('1','2'), amount='10.01',impact='Gain',occurred='2026-10-05T10:00'):
    r=post(client,'/records/new',{'employee_ids':list(ids),'occurred_at':occurred,'title':'Evidence case','description':'Validated description','kind':'Good','impact':impact,'estimated':amount})
    assert r.status_code==302, r.data
    return int(r.location.split('/')[-1])


def version(rid):
    with db.transaction() as tx: return tx.one('SELECT Version FROM Records WHERE Id=?',(rid,))['Version']


def move(client,rid,action,**extra):
    return post(client,f'/records/{rid}/transition',{'version':version(rid),'action':action,'comment':'review reason',**extra})


def test_team_isolation_and_file_security(env):
    login(env,'alice');rid=create(env)
    r=post(env,f'/records/{rid}/upload',{'version':version(rid),'file':(io.BytesIO(b'%PDF-1.4 test'),'proof.pdf')})
    assert r.status_code==302
    with db.transaction() as tx: aid=tx.one('SELECT Id FROM Attachments WHERE RecordId=?',(rid,))['Id']
    assert env.get(f'/attachments/{aid}').status_code==200
    login(env,'bob')
    assert b'Evidence case' not in env.get('/').data
    assert env.get(f'/records/{rid}').status_code==404
    assert env.get(f'/records/{rid}/edit').status_code==404
    assert env.get(f'/attachments/{aid}').status_code==404
    assert b'Alice' not in env.get('/reports.csv?date=2026-10-05').data
    r=post(env,'/records/new',{'employee_ids':['1'],'occurred_at':'2026-10-05T10:00','title':'bad','description':'bad','kind':'Good','impact':'None','estimated':'0'})
    assert r.status_code==403
    login(env,'hr')
    assert env.get(f'/records/{rid}').status_code==200
    assert env.get(f'/attachments/{aid}').status_code==200


def test_approval_allocation_report_and_reopen(env):
    login(env,'alice');rid=create(env)
    assert move(env,rid,'submit').status_code==302
    assert move(env,rid,'approve',verified='10.01').status_code==403
    login(env,'hr')
    assert move(env,rid,'approve',verified='10.01').status_code==403
    assert move(env,rid,'review').status_code==302
    login(env,'admin')
    assert move(env,rid,'approve',verified='10.01').status_code==302
    with db.transaction() as tx:
        shares=tx.rows('SELECT VerifiedCents FROM RecordEmployees WHERE RecordId=?',(rid,))
    assert sum(r['VerifiedCents'] for r in shares)==1001
    assert sorted(r['VerifiedCents'] for r in shares)==[500,501]
    report=env.get('/reports.csv?period=weekly&date=2026-10-05').data.decode('utf-8-sig')
    assert '5.01' in report and '5.00' in report
    assert env.get('/reports?period=monthly&date=2026-10-05').status_code==200
    assert move(env,rid,'reopen').status_code==302
    report=env.get('/reports.csv?date=2026-10-05').data.decode('utf-8-sig')
    assert '5.01' not in report


def test_workflow_csrf_optimistic_lock_and_readonly_approved(env):
    login(env,'alice');rid=create(env)
    assert env.post(f'/records/{rid}/transition',data={'action':'submit','version':1}).status_code==400
    assert post(env,f'/records/{rid}/transition',{'action':'submit','version':999}).status_code==409
    assert move(env,rid,'submit').status_code==302
    assert env.get(f'/records/{rid}/edit').status_code==403
    login(env,'admin');assert move(env,rid,'approve',verified='0').status_code==302
    assert post(env,f'/records/{rid}/upload',{'version':version(rid),'file':(io.BytesIO(b'%PDF-1.4'),'x.pdf')}).status_code==403
    assert move(env,rid,'approve',verified='10').status_code==409


def test_money_and_team_validation(env):
    login(env,'hr')
    common={'occurred_at':'2026-10-05T10:00','title':'t','description':'d','kind':'Good','impact':'Gain','estimated':'1'}
    assert post(env,'/records/new',{**common,'employee_ids':['1','3']}).status_code==400
    for invalid in ('NaN','Infinity','-1','1.005','100000000000'):
        assert post(env,'/records/new',{**common,'employee_ids':['1'],'estimated':invalid}).status_code==400
    assert allocate(1001,[3,1,2])=={1:334,2:334,3:333}


def test_attachment_signature_and_name(env):
    login(env,'alice');rid=create(env)
    assert post(env,f'/records/{rid}/upload',{'version':version(rid),'file':(io.BytesIO(b'<script>evil</script>'),'fake.png')}).status_code==400
    assert post(env,f'/records/{rid}/upload',{'version':version(rid),'file':(io.BytesIO(b'%PDF-1.4'),'../../proof.pdf')}).status_code==302
    with db.transaction() as tx: a=tx.one('SELECT * FROM Attachments WHERE RecordId=?',(rid,))
    assert a['OriginalName']=='proof.pdf'
    assert '/' not in a['StoredName']


def test_admin_settings_transfer_and_password_reset(env):
    login(env,'alice');rid=create(env)
    assert env.get('/settings').status_code==403
    login(env,'admin')
    assert env.get('/settings').status_code==200
    assert env.get('/audit').status_code==200
    assert post(env,'/settings',{'action':'department','name':'Cutting'}).status_code==302
    assert post(env,'/settings',{'action':'team','department':'3','name':'Cut team'}).status_code==302
    assert post(env,'/settings',{'action':'employee','code':'C1','name':'New Employee','designation':'Officer','team':'4'}).status_code==302
    assert post(env,'/settings',{'action':'user','username':'newuser','password':'Strong-secret-123','role':'Employee','employee':'4'}).status_code==302
    assert post(env,'/settings',{'action':'transfer','employee':'1','team':'2'}).status_code==302
    login(env,'alice')
    assert env.get(f'/records/{rid}').status_code==404
    other=app.test_client();login(other,'admin')
    assert post(other,'/settings',{'action':'reset','user_id':'1','password':'Different-secret-123'}).status_code==302
    assert env.get('/').location.endswith('/login')


def test_corrective_action_and_report_boundary(env):
    login(env,'alice');rid=create(env,occurred='2026-10-02T23:59')
    login(env,'hr')
    assert post(env,f'/records/{rid}/actions',{'description':'Fix process','owner':'3','due':'2026-10-01'}).status_code==400
    assert post(env,f'/records/{rid}/actions',{'description':'Fix process','owner':'1','due':'2026-10-01'}).status_code==302
    with db.transaction() as tx: aid=tx.one('SELECT Id FROM CorrectiveActions')['Id']
    login(env,'bob');assert post(env,f'/actions/{aid}/complete',{}).status_code==404
    login(env,'alice');assert post(env,f'/actions/{aid}/complete',{}).status_code==302
    assert b'Alice' not in env.get('/reports.csv?date=2026-10-03').data
    assert b'Alice' in env.get('/reports.csv?date=2026-10-02').data


def test_render_all_pages_and_return_edit(env):
    login(env,'alice');rid=create(env)
    for path in ['/', '/records/new',f'/records/{rid}',f'/records/{rid}/edit','/reports','/reports.csv']:
        assert env.get(path).status_code==200,path
    assert move(env,rid,'submit').status_code==302
    login(env,'admin');assert move(env,rid,'return').status_code==302
    login(env,'alice')
    response=post(env,f'/records/{rid}/edit',{'version':version(rid),'occurred_at':'2026-10-05T10:00','title':'Updated case','description':'Corrected','kind':'Mistake','impact':'Loss','estimated':'50'})
    assert response.status_code==302
    assert move(env,rid,'submit').status_code==302


def test_login_lockout(env):
    env.get('/login')
    for i in range(5):
        assert post(env,'/login',{'username':'alice','password':'wrong'}).status_code==200
    assert post(env,'/login',{'username':'alice','password':'Secure-password-123'}).status_code==200
    with db.transaction() as tx: assert tx.one("SELECT FailedAttempts FROM Users WHERE Username='alice'")['FailedAttempts']==5


def test_sqlserver_insert_output_contract():
    from db import Session
    class FakeCursor:
        def execute(self,sql,params):
            assert 'OUTPUT INSERTED.Id VALUES' in sql
            self.sql=sql
            return self
        def fetchone(self): return [41]
    class FakeConnection:
        def cursor(self): return FakeCursor()
    assert Session(FakeConnection(),'sqlserver').insert('INSERT INTO Teams(DepartmentId,Name) VALUES(?,?)',(1,'A'))==41
