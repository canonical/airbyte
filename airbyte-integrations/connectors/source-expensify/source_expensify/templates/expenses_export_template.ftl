<#if addHeader == true>
reportID,transactionID,type,created,modifiedCreated,inserted,merchant,modifiedMerchant,amount,modifiedAmount,convertedAmount,currency,currencyConversionRate,category,categoryGlCode,categoryPayrollCode,tag,tagGlCode,comment,bank,billable,reimbursable,isDistance,hasTax,taxAmount,modifiedTaxAmount,taxName,taxRate,taxRateName,taxCode,mcc,modifiedMCC,receiptFilename,receiptID,receiptURL,attendees,unitsCount,unitsRate,unitsUnit,unitsName,reportSubmitted,reportApproved,reportReimbursed
</#if>
<#list reports as report>
<#list report.transactionList as expense>
<#-- Extract attendee emails into a single CSV string -->
<#assign attendeeEmails = "">
<#if expense.attendees??>
  <#assign attList = []>
  <#list expense.attendees as att>
    <#if att.email??><#assign attList = attList + [att.email]></#if>
  </#list>
  <#assign attendeeEmails = attList?join(", ")>
</#if>
<#-- Safe boolean parsing -->
<#assign billable = ""><#if expense.billable??><#assign billable = expense.billable?string("true", "false")></#if>
<#assign reimbursable = ""><#if expense.reimbursable??><#assign reimbursable = expense.reimbursable?string("true", "false")></#if>
<#assign isDistance = ""><#if expense.isDistance??><#assign isDistance = expense.isDistance?string("true", "false")></#if>
<#assign hasTax = ""><#if expense.hasTax??><#assign hasTax = expense.hasTax?string("true", "false")></#if>
<#-- Safe numeric parsing (cents format) -->
<#assign amt = ""><#if expense.amount??><#assign amt = expense.amount?c></#if>
<#assign modAmt = ""><#if expense.modifiedAmount??><#assign modAmt = expense.modifiedAmount?c></#if>
<#assign convAmt = ""><#if expense.convertedAmount??><#assign convAmt = expense.convertedAmount?c></#if>
<#assign taxAmt = ""><#if expense.taxAmount??><#assign taxAmt = expense.taxAmount?c></#if>
<#assign modTaxAmt = ""><#if expense.modifiedTaxAmount??><#assign modTaxAmt = expense.modifiedTaxAmount?c></#if>
<#-- Output transaction line -->
"${(report.reportID!"")?replace('"', '""')}",<#t>
"${(expense.transactionID!"")?replace('"', '""')}",<#t>
"${(expense.type!"")?replace('"', '""')}",<#t>
"${(expense.created!"")?replace('"', '""')}",<#t>
"${(expense.modifiedCreated!"")?replace('"', '""')}",<#t>
"${(expense.inserted!"")?replace('"', '""')}",<#t>
"${(expense.merchant!"")?replace('"', '""')}",<#t>
"${(expense.modifiedMerchant!"")?replace('"', '""')}",<#t>
"${amt}",<#t>
"${modAmt}",<#t>
"${convAmt}",<#t>
"${(expense.currency!"")?replace('"', '""')}",<#t>
"${(expense.currencyConversionRate!"")?replace('"', '""')}",<#t>
"${(expense.category!"")?replace('"', '""')}",<#t>
"${(expense.categoryGlCode!"")?replace('"', '""')}",<#t>
"${(expense.categoryPayrollCode!"")?replace('"', '""')}",<#t>
"${(expense.tag!"")?replace('"', '""')}",<#t>
"${(expense.tagGlCode!"")?replace('"', '""')}",<#t>
"${(expense.comment!"")?replace('"', '""')}",<#t>
"${(expense.bank!"")?replace('"', '""')}",<#t>
"${billable}",<#t>
"${reimbursable}",<#t>
"${isDistance}",<#t>
"${hasTax}",<#t>
"${taxAmt}",<#t>
"${modTaxAmt}",<#t>
"${(expense.taxName!"")?replace('"', '""')}",<#t>
"${(expense.taxRate!"")?replace('"', '""')}",<#t>
"${(expense.taxRateName!"")?replace('"', '""')}",<#t>
"${(expense.taxCode!"")?replace('"', '""')}",<#t>
"${(expense.mcc!"")?replace('"', '""')}",<#t>
"${(expense.modifiedMCC!"")?replace('"', '""')}",<#t>
"${(expense.receiptFilename!"")?replace('"', '""')}",<#t>
"${(expense.receiptID!"")?replace('"', '""')}",<#t>
"${((expense.receiptObject.url)!"")?replace('"', '""')}",<#t>
"${attendeeEmails?replace('"', '""')}",<#t>
"${((expense.units.count)!"")?replace('"', '""')}",<#t>
"${((expense.units.rate)!"")?replace('"', '""')}",<#t>
"${((expense.units.unit)!"")?replace('"', '""')}",<#t>
"${((expense.units.name)!"")?replace('"', '""')}",<#t>
"${(report.submitted!"")?replace('"', '""')}",<#t>
"${(report.approved!"")?replace('"', '""')}",<#t>
"${(report.reimbursed!"")?replace('"', '""')}"<#lt>
</#list>
</#list>
