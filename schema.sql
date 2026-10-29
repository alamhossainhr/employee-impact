/* Employee Work & Impact Tracker | SQL Server 2008 R2
   Run with SSMS as a database administrator. NEW database only.
   Never run against your payroll database. No existing tables are dropped. */
USE master;
GO
IF DB_ID(N'EmployeeImpactDB') IS NULL
    CREATE DATABASE EmployeeImpactDB;
GO
USE EmployeeImpactDB;
GO
IF OBJECT_ID(N'dbo.Users', N'U') IS NOT NULL
BEGIN
    RAISERROR('Schema already exists. Stop; use a reviewed migration instead.',16,1);
    SET NOEXEC ON;
END;
GO
CREATE TABLE dbo.Departments (
 Id INT IDENTITY PRIMARY KEY, Name NVARCHAR(120) NOT NULL UNIQUE
);
CREATE TABLE dbo.Teams (
 Id INT IDENTITY PRIMARY KEY, DepartmentId INT NOT NULL REFERENCES dbo.Departments(Id),
 Name NVARCHAR(120) NOT NULL, UNIQUE(DepartmentId,Name)
);
CREATE TABLE dbo.Employees (
 Id INT IDENTITY PRIMARY KEY, Code NVARCHAR(40) NOT NULL UNIQUE,
 Name NVARCHAR(160) NOT NULL, Designation NVARCHAR(120) NOT NULL,
 TeamId INT NOT NULL REFERENCES dbo.Teams(Id), Active BIT NOT NULL DEFAULT 1
);
CREATE TABLE dbo.Users (
 Id INT IDENTITY PRIMARY KEY, Username NVARCHAR(80) NOT NULL UNIQUE,
 PasswordHash NVARCHAR(255) NOT NULL,
 Role NVARCHAR(20) NOT NULL CHECK(Role IN ('Employee','HR','Admin')),
 EmployeeId INT NULL REFERENCES dbo.Employees(Id), Active BIT NOT NULL DEFAULT 1,
 FailedAttempts INT NOT NULL DEFAULT 0, LockedUntil DATETIME2 NULL, AuthVersion INT NOT NULL DEFAULT 1,
 CHECK(Role <> 'Employee' OR EmployeeId IS NOT NULL)
);
CREATE TABLE dbo.Records (
 Id INT IDENTITY PRIMARY KEY, TeamId INT NOT NULL REFERENCES dbo.Teams(Id),
 CreatedBy INT NOT NULL REFERENCES dbo.Users(Id), OccurredAt DATETIME2 NOT NULL,
 Title NVARCHAR(200) NOT NULL, Description NVARCHAR(4000) NOT NULL,
 Kind NVARCHAR(20) NOT NULL CHECK(Kind IN ('Good','Mistake','Improvement')),
 Impact NVARCHAR(20) NOT NULL CHECK(Impact IN ('Gain','Loss','None')),
 EstimatedCents BIGINT NOT NULL CHECK(EstimatedCents >= 0),
 VerifiedCents BIGINT NULL CHECK(VerifiedCents >= 0),
 Status NVARCHAR(20) NOT NULL DEFAULT 'Draft'
 CHECK(Status IN ('Draft','Submitted','Reviewed','Approved','Rejected','Returned')),
 CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
 UpdatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(), Version INT NOT NULL DEFAULT 1,
 CHECK(Impact <> 'None' OR EstimatedCents=0),
 CHECK(Impact <> 'None' OR VerifiedCents IS NULL OR VerifiedCents=0),
 CHECK(Status <> 'Approved' OR VerifiedCents IS NOT NULL)
);
CREATE TABLE dbo.RecordEmployees (
 RecordId INT NOT NULL REFERENCES dbo.Records(Id),
 EmployeeId INT NOT NULL REFERENCES dbo.Employees(Id),
 EmployeeCode NVARCHAR(40) NOT NULL, EmployeeName NVARCHAR(160) NOT NULL,
 Designation NVARCHAR(120) NOT NULL,
 EstimatedCents BIGINT NOT NULL CHECK(EstimatedCents >= 0),
 VerifiedCents BIGINT NULL CHECK(VerifiedCents >= 0),
 PRIMARY KEY(RecordId,EmployeeId)
);
CREATE TABLE dbo.Attachments (
 Id INT IDENTITY PRIMARY KEY, RecordId INT NOT NULL REFERENCES dbo.Records(Id),
 StoredName NVARCHAR(100) NOT NULL UNIQUE, OriginalName NVARCHAR(255) NOT NULL,
 SizeBytes BIGINT NOT NULL, SHA256 CHAR(64) NOT NULL,
 UploadedBy INT NOT NULL REFERENCES dbo.Users(Id), CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.Reviews (
 Id INT IDENTITY PRIMARY KEY, RecordId INT NOT NULL REFERENCES dbo.Records(Id),
 UserId INT NOT NULL REFERENCES dbo.Users(Id), Action NVARCHAR(30) NOT NULL,
 Comment NVARCHAR(2000) NOT NULL, CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE TABLE dbo.CorrectiveActions (
 Id INT IDENTITY PRIMARY KEY, RecordId INT NOT NULL REFERENCES dbo.Records(Id),
 Description NVARCHAR(2000) NOT NULL, OwnerEmployeeId INT NOT NULL REFERENCES dbo.Employees(Id),
 DueDate DATE NOT NULL, Status NVARCHAR(20) NOT NULL DEFAULT 'Open'
 CHECK(Status IN ('Open','Done')), CreatedBy INT NOT NULL REFERENCES dbo.Users(Id)
);
CREATE TABLE dbo.AuditLogs (
 Id INT IDENTITY PRIMARY KEY, UserId INT NULL REFERENCES dbo.Users(Id),
 Event NVARCHAR(80) NOT NULL, EntityId INT NULL, Details NVARCHAR(4000) NOT NULL,
 CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE UNIQUE INDEX UX_Users_Employee ON dbo.Users(EmployeeId) WHERE EmployeeId IS NOT NULL;
CREATE INDEX IX_Records_Team_Date ON dbo.Records(TeamId,OccurredAt,Status);
CREATE INDEX IX_RecordEmployees_Employee ON dbo.RecordEmployees(EmployeeId,RecordId);
CREATE INDEX IX_Attachments_Record ON dbo.Attachments(RecordId);
CREATE INDEX IX_Reviews_Record ON dbo.Reviews(RecordId);
CREATE INDEX IX_Actions_Record ON dbo.CorrectiveActions(RecordId);
GO
/* Separate server login is created by your DBA, not with a bundled password.
   Example AFTER a login [impact_service] exists:
   CREATE USER [impact_service] FOR LOGIN [impact_service];
   CREATE ROLE [impact_runtime];
   EXEC sp_addrolemember N'impact_runtime', N'impact_service';
   GRANT SELECT, INSERT, UPDATE ON dbo.Departments TO impact_runtime;
   GRANT SELECT, INSERT, UPDATE ON dbo.Teams TO impact_runtime;
   GRANT SELECT, INSERT, UPDATE ON dbo.Employees TO impact_runtime;
   GRANT SELECT, INSERT, UPDATE ON dbo.Users TO impact_runtime;
   GRANT SELECT, INSERT, UPDATE ON dbo.Records TO impact_runtime;
   GRANT SELECT, INSERT, UPDATE ON dbo.RecordEmployees TO impact_runtime;
   GRANT SELECT, INSERT ON dbo.Attachments TO impact_runtime;
   GRANT SELECT, INSERT ON dbo.Reviews TO impact_runtime;
   GRANT SELECT, INSERT, UPDATE ON dbo.CorrectiveActions TO impact_runtime;
   GRANT SELECT, INSERT ON dbo.AuditLogs TO impact_runtime;
   No end-user SQL accounts. App identity has database access; employee accounts
   only access the application. Authorization is enforced by server queries,
   not SQL row-level security. Do not grant db_owner or give connection details
   to employee browsers. DBA remains a trusted privileged operator. */
