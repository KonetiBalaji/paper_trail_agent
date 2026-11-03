# Explicit historical period checks

Private service uploads with verified identities enqueue cross-case comparisons.
The worker records supported carry discrepancies in the monitoring timeline,
where reviewers can record review and resolution. The timeline links to both
source statements. Hosted worker verification and support for more historical
statement formats remain open.

The local/service read endpoint is `GET /api/cases/{id}/historical`. Service
requests can select an immutable `version`; normal workspace authentication and
viewer permissions apply. The frontend's **Check historical rules** button
fetches that exact report version and shows named equations, review reasons,
calculator operands and clickable source evidence. The original report and
human decisions remain unchanged. The JSON contains case ID, report version,
rules version and normalized policy-source SHA-256 for reproducibility.

These are explicit native-text contracts, not inferred lender meanings. Each
document must contain exactly one `Historical rules:` declaration, `Account:`,
`Currency:`, `Period start:` and `Period end:`. Dates are ISO YYYY-MM-DD and
period endpoints are inclusive. Supported two-decimal currencies are USD, EUR,
GBP and INR. There is no exchange-rate conversion.

For `Historical rules: PTA-BANK-PERIOD-V1`, require exactly one opening balance,
closing balance and transaction count. Signed transaction rows use:

```
Transaction PAYMENT-1 | 2026-10-31 | Amount: -100.00
```

The count must match the fully parsed unique transaction IDs; every posting date
must fall within the explicit period. The named equation is opening balance plus
all signed movements equals closing balance. An explicit count of zero permits
a zero-movement period. At most 999 movements are accepted.

For `Historical rules: PTA-LOAN-PRINCIPAL-V1`, require these five fields:

```
Historical principal opening: 1000.00
Principal disbursed: 0.00
Principal repaid: 100.00
Principal adjustments: 0.00
Historical principal closing: 900.00
```

The equation is opening principal plus disbursements minus allocated principal
repaid plus signed adjustments equals closing principal. All fields except
adjustments must be nonnegative. A total payment cannot stand in for principal
repaid: interest, fees and payment allocation are never invented. Decimal
arithmetic is independently replayed in integer cents.

Every pair in the case is considered (maximum eight documents). Only equal
account, currency and rules with consecutive periods may compare the earlier
closing balance to the later opening balance. Identical periods compare opening and closing balances separately.
Gaps, partially overlapping periods,
different identities/currencies/rules, duplicate PDFs, repeated labels, OCR or
incomplete evidence require review. A change between closing balances is never
itself a contradiction. A passed named equation is not a clean account-history
verdict, and it does not erase any existing same-period review findings.
