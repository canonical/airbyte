<#if addHeader == true>
Number,ReportID,ReportName,AccountEmail,Approved,Created,Currency,PolicyID,Reimbursed,Status,Submitted
</#if>
<#assign reportNumber = 1>
<#list reports as report>
"${reportNumber?c?replace('"', '""')}",<#t>
"${report.reportID?replace('"', '""')}",<#t>
"${report.reportName?replace('"', '""')}",<#t>
"${report.accountEmail?replace('"', '""')}",<#t>
"${report.approved?replace('"', '""')}",<#t>
"${report.created?replace('"', '""')}",<#t>
"${report.currency?replace('"', '""')}",<#t>
"${report.policyID?replace('"', '""')}",<#t>
"${report.reimbursed?replace('"', '""')}",<#t>
"${report.status?replace('"', '""')}",<#t>
"${report.submitted?replace('"', '""')}"<#lt>
<#assign reportNumber = reportNumber + 1>
</#list>
