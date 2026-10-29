"""Run AFTER schema.sql, with the real .env and a service account.
Does not commit any test rows. Tests SQL Server dialect, Unicode and FK writes.
python sqlserver_smoke.py
"""
import os
import uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from db import Session
load_dotenv()
import pyodbc
connection=os.getenv('SQL_CONNECTION_STRING')
if not connection:
    raise SystemExit('Set SQL_CONNECTION_STRING in .env first.')
c=pyodbc.connect(connection,autocommit=False,timeout=10)
try:
    tx=Session(c,'sqlserver')
    suffix=uuid.uuid4().hex[:12]
    dep=tx.insert('INSERT INTO Departments(Name) VALUES(?)',('পরীক্ষা '+suffix,))
    team=tx.insert('INSERT INTO Teams(DepartmentId,Name) VALUES(?,?)',(dep,'Test '+suffix))
    emp=tx.insert('INSERT INTO Employees(Code,Name,Designation,TeamId,Active) VALUES(?,?,?,?,1)',('TEST-'+suffix,'পরীক্ষার কর্মী','Officer',team))
    uid=tx.insert('INSERT INTO Users(Username,PasswordHash,Role,EmployeeId,Active,FailedAttempts) VALUES(?,?,?,?,1,0)',('test-'+suffix,'not-a-login-hash','Employee',emp))
    stamp=datetime.now(timezone.utc).replace(tzinfo=None,microsecond=0)
    rid=tx.insert('INSERT INTO Records(TeamId,CreatedBy,OccurredAt,Title,Description,Kind,Impact,EstimatedCents,Status,CreatedAt,UpdatedAt,Version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(team,uid,stamp,'বাংলা পরীক্ষা','Smoke test','Good','Gain',1001,'Submitted',stamp,stamp,1))
    tx.execute('INSERT INTO RecordEmployees(RecordId,EmployeeId,EmployeeCode,EmployeeName,Designation,EstimatedCents) VALUES(?,?,?,?,?,?)',(rid,emp,'TEST-'+suffix,'পরীক্ষার কর্মী','Officer',1001))
    assert tx.execute("UPDATE Records SET Status='Approved',VerifiedCents=1001,Version=Version+1 WHERE Id=? AND Version=1",(rid,)).rowcount==1
    tx.execute('UPDATE RecordEmployees SET VerifiedCents=1001 WHERE RecordId=?',(rid,))
    row=tx.one('SELECT Title,VerifiedCents FROM Records WHERE Id=?',(rid,))
    assert row['Title']=='বাংলা পরীক্ষা' and row['VerifiedCents']==1001
    assert tx.one('SELECT SUM(VerifiedCents) AS Total FROM RecordEmployees WHERE RecordId=?',(rid,))['Total']==1001
    tx.execute('INSERT INTO Reviews(RecordId,UserId,Action,Comment,CreatedAt) VALUES(?,?,?,?,?)',(rid,uid,'test','SQL smoke',stamp))
    tx.execute('INSERT INTO AuditLogs(UserId,Event,EntityId,Details,CreatedAt) VALUES(?,?,?,?,?)',(uid,'SQLSmoke',rid,'Temporary',stamp))
    print('PASS: SQL Server connection, identity output, Unicode, dates, FK, update and allocations. Test rows rolled back.')
finally:
    c.rollback()
    c.close()
