PRAGMA foreign_keys=ON;
CREATE TABLE Departments (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, Name NVARCHAR(120) NOT NULL UNIQUE
);
CREATE TABLE Teams (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, DepartmentId INT NOT NULL REFERENCES Departments(Id),
 Name NVARCHAR(120) NOT NULL, UNIQUE(DepartmentId,Name)
);
CREATE TABLE Employees (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, Code NVARCHAR(40) NOT NULL UNIQUE,
 Name NVARCHAR(160) NOT NULL, Designation NVARCHAR(120) NOT NULL,
 TeamId INT NOT NULL REFERENCES Teams(Id), Active BIT NOT NULL DEFAULT 1
);
CREATE TABLE Users (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, Username NVARCHAR(80) NOT NULL UNIQUE,
 PasswordHash NVARCHAR(255) NOT NULL,
 Role NVARCHAR(20) NOT NULL CHECK(Role IN ('Employee','HR','Admin')),
 EmployeeId INT NULL REFERENCES Employees(Id), Active BIT NOT NULL DEFAULT 1,
 FailedAttempts INT NOT NULL DEFAULT 0, LockedUntil DATETIME2 NULL, AuthVersion INT NOT NULL DEFAULT 1,
 CHECK(Role <> 'Employee' OR EmployeeId IS NOT NULL)
);
CREATE TABLE Records (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, TeamId INT NOT NULL REFERENCES Teams(Id),
 CreatedBy INT NOT NULL REFERENCES Users(Id), OccurredAt DATETIME2 NOT NULL,
 Title NVARCHAR(200) NOT NULL, Description NVARCHAR(4000) NOT NULL,
 Kind NVARCHAR(20) NOT NULL CHECK(Kind IN ('Good','Mistake','Improvement')),
 Impact NVARCHAR(20) NOT NULL CHECK(Impact IN ('Gain','Loss','None')),
 EstimatedCents BIGINT NOT NULL CHECK(EstimatedCents >= 0),
 VerifiedCents BIGINT NULL CHECK(VerifiedCents >= 0),
 Status NVARCHAR(20) NOT NULL DEFAULT 'Draft'
 CHECK(Status IN ('Draft','Submitted','Reviewed','Approved','Rejected','Returned')),
 CreatedAt DATETIME2 NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')),
 UpdatedAt DATETIME2 NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now')), Version INT NOT NULL DEFAULT 1,
 CHECK(Impact <> 'None' OR EstimatedCents=0),
 CHECK(Impact <> 'None' OR VerifiedCents IS NULL OR VerifiedCents=0),
 CHECK(Status <> 'Approved' OR VerifiedCents IS NOT NULL)
);
CREATE TABLE RecordEmployees (
 RecordId INT NOT NULL REFERENCES Records(Id),
 EmployeeId INT NOT NULL REFERENCES Employees(Id),
 EmployeeCode NVARCHAR(40) NOT NULL, EmployeeName NVARCHAR(160) NOT NULL,
 Designation NVARCHAR(120) NOT NULL,
 EstimatedCents BIGINT NOT NULL CHECK(EstimatedCents >= 0),
 VerifiedCents BIGINT NULL CHECK(VerifiedCents >= 0),
 PRIMARY KEY(RecordId,EmployeeId)
);
CREATE TABLE Attachments (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, RecordId INT NOT NULL REFERENCES Records(Id),
 StoredName NVARCHAR(100) NOT NULL UNIQUE, OriginalName NVARCHAR(255) NOT NULL,
 SizeBytes BIGINT NOT NULL, SHA256 CHAR(64) NOT NULL,
 UploadedBy INT NOT NULL REFERENCES Users(Id), CreatedAt DATETIME2 NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE TABLE Reviews (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, RecordId INT NOT NULL REFERENCES Records(Id),
 UserId INT NOT NULL REFERENCES Users(Id), Action NVARCHAR(30) NOT NULL,
 Comment NVARCHAR(2000) NOT NULL, CreatedAt DATETIME2 NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE TABLE CorrectiveActions (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, RecordId INT NOT NULL REFERENCES Records(Id),
 Description NVARCHAR(2000) NOT NULL, OwnerEmployeeId INT NOT NULL REFERENCES Employees(Id),
 DueDate DATE NOT NULL, Status NVARCHAR(20) NOT NULL DEFAULT 'Open'
 CHECK(Status IN ('Open','Done')), CreatedBy INT NOT NULL REFERENCES Users(Id)
);
CREATE TABLE AuditLogs (
 Id INTEGER PRIMARY KEY AUTOINCREMENT, UserId INT NULL REFERENCES Users(Id),
 Event NVARCHAR(80) NOT NULL, EntityId INT NULL, Details NVARCHAR(4000) NOT NULL,
 CreatedAt DATETIME2 NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
CREATE UNIQUE INDEX UX_Users_Employee ON Users(EmployeeId) WHERE EmployeeId IS NOT NULL;
CREATE INDEX IX_Records_Team_Date ON Records(TeamId,OccurredAt,Status);
CREATE INDEX IX_RecordEmployees_Employee ON RecordEmployees(EmployeeId,RecordId);
CREATE INDEX IX_Attachments_Record ON Attachments(RecordId);
CREATE INDEX IX_Reviews_Record ON Reviews(RecordId);
CREATE INDEX IX_Actions_Record ON CorrectiveActions(RecordId);
