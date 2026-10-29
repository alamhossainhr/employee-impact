USE EmployeeImpactDB;
GO
/* Run under an authorized HR/Admin reporting identity, not an employee SQL login.
   App reports apply team restrictions. This standalone SQL is an all-factory report. */
DECLARE @AnchorDate DATE = '2026-10-05';
DECLARE @Period VARCHAR(10) = 'Weekly'; -- Weekly or Monthly
DECLARE @StartDate DATE;
DECLARE @EndDate DATE;
DECLARE @DepartmentId INT = NULL;
DECLARE @TeamId INT = NULL;
DECLARE @EmployeeId INT = NULL;

IF @Period = 'Weekly'
BEGIN
    -- 1900-01-06 was Saturday; independent of SET DATEFIRST/language.
    SET @StartDate = DATEADD(DAY,-((DATEDIFF(DAY,'19000106',@AnchorDate)%7+7)%7),@AnchorDate);
    SET @EndDate = DATEADD(DAY,7,@StartDate);
END
ELSE IF @Period = 'Monthly'
BEGIN
    SET @StartDate = DATEADD(DAY,1-DAY(@AnchorDate),@AnchorDate);
    SET @EndDate = DATEADD(MONTH,1,@StartDate);
END
ELSE
BEGIN
    RAISERROR('Period must be Weekly or Monthly.',16,1);
    RETURN;
END;

SELECT
    @StartDate AS PeriodStart, DATEADD(DAY,-1,@EndDate) AS PeriodEnd,
    d.Name AS Department, t.Name AS Team,
    re.EmployeeId, re.EmployeeCode,
    MAX(re.EmployeeName) AS EmployeeName,
    MAX(re.Designation) AS Designation,
    SUM(CASE WHEN r.Status='Approved' AND r.Kind='Good' THEN 1 ELSE 0 END) AS GoodWork,
    SUM(CASE WHEN r.Status='Approved' AND r.Kind='Mistake' THEN 1 ELSE 0 END) AS Mistakes,
    SUM(CASE WHEN r.Status='Approved' AND r.Kind='Improvement' THEN 1 ELSE 0 END) AS Improvements,
    CAST(SUM(CASE WHEN r.Status='Approved' AND r.Impact='Gain' THEN ISNULL(re.VerifiedCents,0) ELSE 0 END)/100.0 AS DECIMAL(18,2)) AS GainBDT,
    CAST(SUM(CASE WHEN r.Status='Approved' AND r.Impact='Loss' THEN ISNULL(re.VerifiedCents,0) ELSE 0 END)/100.0 AS DECIMAL(18,2)) AS LossBDT,
    CAST(SUM(CASE WHEN r.Status='Approved' AND r.Impact='Gain' THEN ISNULL(re.VerifiedCents,0)
                  WHEN r.Status='Approved' AND r.Impact='Loss' THEN -ISNULL(re.VerifiedCents,0) ELSE 0 END)/100.0 AS DECIMAL(18,2)) AS NetBDT,
    SUM(CASE WHEN r.Status IN ('Draft','Submitted','Reviewed','Returned') THEN 1 ELSE 0 END) AS Pending,
    SUM(CASE WHEN r.Status='Rejected' THEN 1 ELSE 0 END) AS Rejected
FROM dbo.RecordEmployees re
JOIN dbo.Records r ON r.Id=re.RecordId
JOIN dbo.Teams t ON t.Id=r.TeamId
JOIN dbo.Departments d ON d.Id=t.DepartmentId
WHERE r.OccurredAt>=@StartDate AND r.OccurredAt<@EndDate
  AND (@DepartmentId IS NULL OR d.Id=@DepartmentId)
  AND (@TeamId IS NULL OR t.Id=@TeamId)
  AND (@EmployeeId IS NULL OR re.EmployeeId=@EmployeeId)
GROUP BY d.Id,d.Name,t.Id,t.Name,re.EmployeeId,re.EmployeeCode
ORDER BY d.Name,t.Name,re.EmployeeCode;
