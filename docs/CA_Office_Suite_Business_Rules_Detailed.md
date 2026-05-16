# CA Office Suite — Detailed Business Rules & Logic Manual

**Version:** For employee training and administration  
**Companion documents:**
- Summary guide: `CA_Office_Suite_Business_Rules.md`
- Slide deck: `CA_Office_Suite_Employee_Presentation.html`

This manual explains **what the system does**, **why**, and **exact validation rules** as implemented in the application. Use it when training staff, writing office procedures, or answering “why did the system reject this?”

---

## Table of contents

1. [System overview](#1-system-overview)  
2. [Indian financial year (FY)](#2-indian-financial-year-fy)  
3. [Client Master](#3-client-master)  
4. [Group Master](#4-group-master)  
5. [Director mapping](#5-director-mapping)  
6. [MIS — Management Information System](#6-mis--management-information-system)  
7. [Tender (MIS)](#7-tender-mis)  
8. [DIR-3 eKYC](#8-dir-3-ekyc)  
9. [Reports](#9-reports)  
10. [Dashboard](#10-dashboard)  
11. [Permissions and access groups](#11-permissions-and-access-groups)  
12. [Branch access](#12-branch-access)  
13. [User accounts and login](#13-user-accounts-and-login)  
14. [Activity log and test data reset](#14-activity-log-and-test-data-reset)  
15. [Worked examples](#15-worked-examples)  
16. [Glossary](#16-glossary)  
17. [Appendix — validation messages](#17-appendix--validation-messages)

---

## 1. System overview

### 1.1 Modules

| Module | Screens | Primary data |
|--------|---------|--------------|
| **Masters** | Client Master, Group Master, Client approvals, Director Mapping, User Management, Access groups (superuser) | Clients, groups, director–company relationships, users |
| **MIS** | Fees, Receipts, Expenses, Tender, Bulk upload | Day-to-day financial entries per client |
| **DIR-3 eKYC** | DIR-3 KYC list/create/edit | MCA filing dates and SRN per director |
| **Reports** | Client Master, MIS, Director Mapping, DIR-3 KYC | Read-only analysis and CSV export |

### 1.2 Central principle: approved clients

Many modules share one rule:

> **Only clients with approval status = Approved** are used for new MIS rows, director mapping, DIR-3 KYC, MIS reports, and dashboard FY totals.

**Pending** clients exist in Client Master but are **blocked** from operational use until an approver accepts them.

### 1.3 Who sees what

- **Superuser:** Full access; client creates/edits are auto-approved; bypasses permission checks.  
- **Other users:** Menus and buttons depend on **assigned permissions** (via Django groups / user permissions).  
- **Branch-restricted employees:** Data limited to **Trivandrum** or **Nagercoil** (see [Section 12](#12-branch-access)).

---

## 2. Indian financial year (FY)

### 2.1 Definition

| Term | Meaning |
|------|---------|
| **Indian FY** | 1 **April** to 31 **March** |
| **FY label** | Two years, e.g. **2026-27** = 1 Apr 2026 – 31 Mar 2027 |
| **FY start year** | Calendar year of the April that opens the FY |

**Formula (conceptual):**  
- If date is in April–December → FY start year = that calendar year.  
- If date is in January–March → FY start year = previous calendar year.

**Examples:**

| Date | FY label |
|------|----------|
| 15 Apr 2026 | 2026-27 |
| 30 Jun 2026 | 2026-27 |
| 10 Jan 2027 | 2026-27 |
| 1 Apr 2027 | 2027-28 |

### 2.2 Where FY is used

| Feature | How FY is applied |
|---------|-------------------|
| Dashboard “MIS this financial year” | From **1 Apr** of current FY through **today** (or 31 Mar if later) |
| MIS Report — month wise | Select one or more FY labels (from **2026-27** through current FY) |
| DIR-3 next filing | Based on **FY of last filing date**, not rolling 3 calendar years |
| DIR-3 dashboard pending | Compare today to **earliest next allowed date** from last filing |
| DIR-3 compliance (≥3 FY) | Gap measured in **FY start years** between last filing and “as on” date |

### 2.3 Month order in MIS month-wise report

Months are ordered **April → March** (April = month 1 of the FY, March = month 12).

---

## 3. Client Master

### 3.1 Branches and client types

**Branches (required):**

- Trivandrum  
- Nagercoil  

**Client types (dropdown):**

Individual, Partnership, LLP, Branch, Private Limited, Public Limited, Nidhi Co, FPO, Trust, Sec 8 Co, Society, Foreign Citizen, None.

### 3.2 Client ID generation

- Format: **`{L1}{L2}{NNNN}`** — 6 characters.  
- **L1:** First letter A–Z in **client name** (default X if none).  
- **L2:** First letter A–Z in **branch** name.  
- **NNNN:** 4-digit serial **per prefix** (e.g. all `AN` clients share one counter).  
- **Example:** Name “Antony & Co”, branch Nagercoil → prefix **AN** → `AN0001`, `AN0002`, …  
- ID is assigned on **first save**; cannot be edited.

### 3.3 Approval workflow

| Action | Superuser | Other user with add/change permission |
|--------|-----------|-------------------------------------|
| Create client | **Approved** immediately | **Pending** |
| Edit approved client | Stays **approved** | Becomes **pending** again |
| Approve | N/A (already approved) | User needs **`masters.approve_client`** |

**After create (pending), user sees:**  
*"Client saved as {id} and is pending approval. An approver must accept it before it can be used in MIS, director mapping, or DIR-3 KYC."*

**After edit (pending again):**  
*"Changes saved and this client is pending approval again before use elsewhere in the system."*

**Approver screen:** Client approvals — lists pending records; approve action is **POST only**.

### 3.4 Who sees which clients in the list

| User | Clients shown |
|------|----------------|
| Superuser or approver | All (subject to branch filter) |
| Other users | **Approved** clients **+** pending clients **they created** |

### 3.5 Fields — normalisation

On save/validate, the system typically:

- Uppercases: client name, PAN, GSTIN, LLPIN, CIN, passport (compact, no spaces/hyphens).  
- Normalises DIN (8 digits, leading zeros from Excel).  
- Strips Aadhaar to 12 digits.

### 3.6 Client name rules

- **Required.**  
- Allowed characters: letters, numbers, spaces, and `. , ' & ( ) / : + * # % = -`  
- **Name → type (when PAN is present):**

| Name contains (whole words) | Client type must be |
|----------------------------|---------------------|
| PRIVATE LIMITED | Private Limited |
| LLP | LLP |
| NIDHI | Nidhi Co |
| TRUST | Trust |
| FARMER | FPO |
| LIMITED (not Private Limited / Nidhi Limited / Farmer context) | Public Limited |

- If name triggers **conflicting** keywords (e.g. LLP + PUBLIC LIMITED rules clash), save is rejected.  
- **Special rule — PAN blank:** If PAN is empty and name contains company-style keywords, **Client Type must be None** (even if name says Private Limited, etc.).

### 3.7 Client type → name rules

| Client type | Name must contain |
|-------------|-------------------|
| Private Limited | **PRIVATE LIMITED** |
| Public Limited | **LIMITED** (whole word) |
| Nidhi Co | **NIDHI** |
| FPO | **FARMER** |

### 3.8 PAN rules

| Rule | Detail |
|------|--------|
| Format | `AAAAA9999A` (5 letters, 4 digits, 1 letter) |
| Mandatory | All types **except** None, Foreign Citizen, Branch |
| Uniqueness | **Unique** for all non-Branch clients; **Branch** may duplicate PAN |
| 4th character vs type | When PAN valid and not Branch, type must match table below |

**PAN 4th character → allowed client types:**

| 4th char | Allowed types |
|----------|----------------|
| P | Individual, None, Foreign Citizen |
| T | Trust, None |
| C | Private Limited, FPO, Nidhi Co, Sec 8 Co, Public Limited, None |
| F | LLP, Partnership, None |

### 3.9 Passport and Aadhaar

- Only for **Individual** and **Foreign Citizen**.  
- **Foreign Citizen:** Passport **mandatory** (6–24 alphanumeric after normalisation).  
- Aadhaar: optional; if entered, exactly **12 digits**.  
- Other types: passport and aadhaar must be **blank**.

### 3.10 GSTIN rules

- Length **15** characters.  
- Characters **3–12** must match **PAN** (positions 1–10 of PAN in GSTIN segment).  
- If GSTIN entered and type is not Foreign Citizen: **PAN required**.  
- Foreign Citizen: PAN/GSTIN match checked only when PAN is provided.

### 3.11 LLPIN and CIN

| Field | Applies to |
|-------|------------|
| **LLPIN** | LLP only; format `AAA-9999` |
| **CIN** | Private Limited, Public Limited, FPO, Sec 8 Co, Nidhi Co; 21 alphanumeric |

### 3.12 Director flag and DIN

| Client type | Is Director | DIN |
|-------------|-------------|-----|
| Individual, Foreign Citizen | Optional | Required if Is Director; 8 digits; blank if not director |
| Branch | **Not allowed** | **Not allowed** |
| All other types | **Not allowed** | **Not allowed** |

### 3.13 Other client validations

- **DOB:** Cannot be in the future.  
- **Group:** Cannot assign an **inactive** group.  
- **Delete:** Blocked if linked to MIS (fees/receipts/expenses/tender), director mapping, or DIR-3 KYC.

### 3.14 Client Master bulk import

1. Upload file → **Preview** (validation per row).  
2. **Confirm** → all rows import in one transaction (**all succeed or none**).  
3. Non-superuser: imported clients are **pending** until approved.  
4. Validations include branch, duplicate PAN in file, model rules, existing PAN in database.

---

## 4. Group Master

| Item | Rule |
|------|------|
| **Group ID** | Auto: `GR` + first letter of name + 3-digit serial (e.g. `GRJ001`) |
| **Name** | Required; uppercased; must contain A–Z; same character rules as client name |
| **Inactive** | Cannot assign to new/edited clients |
| **Delete** | Blocked if any client still linked |
| **Bulk delete** | Superuser only |

---

## 5. Director mapping

### 5.1 Purpose

Links a **person** (director in Client Master) to a **company** (another client) with appointment and optional cessation.

### 5.2 Director side (picker)

Must be:

- Client type **Individual** or **Foreign Citizen**  
- **Approved**  
- **Is Director** = Yes  
- **DIN** filled in Client Master  

### 5.3 Company side (picker)

Must be **approved** and one of:

Private Limited, Public Limited, Nidhi Co, FPO, Sec 8 Co, LLP.

### 5.4 Dates and cessation

| Rule | Message / behaviour |
|------|---------------------|
| Cessation without appointment | Not allowed |
| Cessation before appointment | Not allowed |
| Cessation date set | **Reason required:** Resigned, Disqualified, Terminated, Death |
| Reason without cessation | Not allowed |
| Active appointment | At most **one** row per director+company with **no cessation date** |
| New appointment while active exists | Blocked — end previous appointment first |

### 5.5 Uniqueness

Same director + company + **appointment date** cannot duplicate (when appointment date is set).

---

## 6. MIS — Management Information System

### 6.1 Common rules (all MIS entry types)

| Rule | Detail |
|------|--------|
| Client | Must select from suggestions — **approved** client only |
| Branch | Branch-restricted users cannot pick other branch’s clients |
| PAN on row | Copied from client on save |
| List screens | Typically capped at **500** rows displayed |
| Delete client | Protected while MIS rows exist |

### 6.2 Fees details

| Field | Rule |
|-------|------|
| Date | Entry date (no special “no future” rule in MIS) |
| Fees amount | ≥ 0 |
| GST amount | ≥ 0; **cannot be > 0 when fees = 0** |
| Total amount | **Auto = fees + GST** (stored, not typed) |

### 6.3 Receipts

| Field | Rule |
|-------|------|
| Amount received | ≥ 0 |

### 6.4 Expenses

| Field | Rule |
|-------|------|
| Expenses paid | ≥ 0 |
| Notes | Optional text |

### 6.5 Bulk upload (combined and separate)

**Workflow:** Upload → Preview → Confirm (transactional).

**Combined file (typical columns):** CLIENT_ID, CLIENT_NAME, DATE, FEES_AMOUNT, GST_AMOUNT, RECEIPT, EXPENSE, etc.

| Check | Rule |
|-------|------|
| CLIENT_ID | Must exist in master, **approved**, name in row must match master |
| DATE | Valid date format |
| GST | GST_AMOUNT not allowed when FEES_AMOUNT is 0/blank |
| Row amounts | At least one non-zero amount (combined import) |
| Permissions | Non-superuser: fees rows need `mis.add_feesdetail`; receipt/expense rows need respective add permissions |
| Superuser | Can import all types regardless of granular add perms |

**Separate imports:** Fees-only, receipts-only, expenses-only files follow same client ID/name and GST rules where applicable.

---

## 7. Tender (MIS)

| Field | Rule |
|-------|------|
| Tender fees | ≥ 0 |
| Tender deposit | ≥ 0 |
| At least one | **Tender fees and/or tender deposit** must be entered |
| Dashboard FY card | **Not included** in fees/receipts/expenses summary |
| MIS Report | Included when user selects tender columns |

---

## 8. DIR-3 eKYC

### 8.1 Record contents

- **Director:** From Client Master (eligible type, approved, Is Director, DIN).  
- **Date of DIR-3 KYC done:** Calendar date of filing.  
- **SRN:** MCA reference from DIR e-KYC.

### 8.2 Filing cadence (detailed)

**Rule:** The system looks at the **Indian FY** that contains the **last** `date_done`, then blocks new filings until **1 April** of calendar year **(FY start year + 3)**.

**Steps:**

1. Find `fy_start_year(last_done_date)`.  
2. Next allowed date = **1 April** of year **`fy_start_year + 3`**.  
3. Any new `date_done` must be **on or after** that date.

**Example A**

| Last filing date | FY of that date | Next allowed from |
|------------------|-----------------|-------------------|
| 10 May 2026 | 2026-27 | **1 Apr 2029** (FY 2029-30) |
| 28 Feb 2027 | 2026-27 | **1 Apr 2029** (same — same FY) |

**Example B**

| Last filing date | FY | Next allowed from |
|------------------|-----|-------------------|
| 5 Apr 2024 | 2024-25 | **1 Apr 2027** (FY 2027-28) |

**Error message (shortened):**  
*"The next DIR-3 e-KYC for this director is allowed only from {date} (start of FY {label}). Cadence is by financial year… (last filing FY was {last_fy})."*

### 8.3 Dashboard — pending directors

A director is counted **pending** if:

1. **No DIR-3 record** ever, **OR**  
2. **Today ≥ earliest_next_dirkyc_allowed_date** from their latest filing.

**Scope:** Approved directors only; Individual/Foreign Citizen; Is Director; DIN not empty; branch filter applied.

### 8.4 DIR-3 KYC Report — long-gap compliance

For compliance filtering, a director may be treated as **not done for ≥3 FY** when:

- Never filed, **OR**  
- `(fy_start_year(as_on_date) - fy_start_year(last_kyc_date)) >= 4`  

(Implemented as a gap of **four or more FY start years** — equivalent to “3 full FY gaps” after the filing FY.)

---

## 9. Reports

### 9.1 General

- MIS-related totals: **`client.approval_status = approved`** always.  
- Branch: Employee branch access **overrides** report branch dropdown.  
- On-screen results often capped (e.g. **500** rows).  
- **Export** requires separate **export_*** permissions per report.

### 9.2 Client Master Report

**Permission:** `reports.view_client_master_report`  
**Export:** `reports.export_client_master_report`

**Filters (AND logic):** Client type, branch, name, DIN, PAN, GSTIN, CIN, LLPIN, Is director flag.

### 9.3 MIS Report (flexible)

**Permission:** `reports.access_reports_menu` (and export: `reports.export_mis_report`)

**Report views:**

| View | Purpose |
|------|---------|
| Transactions | Line-by-line entries |
| Client wise | Aggregated per client |
| Type wise | Aggregated per client type |
| Month wise | Pivot by FY months (Apr–Mar) |

**Filters:**

- Date **from / to**, **OR** (month wise) one or more **FY labels**  
- Branch, client ID, client name, PAN, client type  
- **Details:** ALL, Fees, GST, Receipts, Expenses, Tender fees, Tender deposit  

**Month-wise FY picker:** From **2026-27** through **current FY** (new FYs added each 1 April).

**Validation:** Month wise requires at least one FY; other views require from/to dates.

### 9.4 Director Mapping Report

**Permission:** `reports.view_director_mapping_report`  
**Export:** `reports.export_director_mapping_report`

**As-on date:** Appointment is **active** if:

- `appointed_date ≤ as_on_date`, and  
- No cessation, **or** `cessation_date > as_on_date`

### 9.5 DIR-3 KYC Report

**Permission:** `reports.view_dir3kyc_report`  
**Export:** `reports.export_dir3kyc_report`

Modes include all filings vs latest per director; filters for director, dates, last KYC FY, and long-gap compliance flags.

### 9.6 Reports menu entry

If user has only `access_reports_menu`, index may redirect to first available sub-report they can open.

---

## 10. Dashboard

### 10.1 Client summary

- Counts by **client type** — **approved** clients only, branch-filtered.

### 10.2 MIS this financial year

| Aspect | Rule |
|--------|------|
| Label | Current FY, e.g. `2026-27` |
| Period shown | `1 Apr {FY start}` – `{today}` (or through 31 Mar) |
| Fees total | Sum of **`total_amount`** (fees + GST) |
| Receipts | Sum of `amount_received` |
| Expenses | Sum of `expenses_paid` |
| Clients | Approved only |
| Tender | **Excluded** |

### 10.3 Director mapping count

- Count of mapping rows (branch-filtered on **director’s** branch).

### 10.4 DIR-3 eKYC pending

- Count of directors matching pending rules in [Section 8.3](#83-dashboard--pending-directors).

### 10.5 Quick links

- Shown based on user permissions (MIS, DIR-3, Reports, etc.).

---

## 11. Permissions and access groups

### 11.1 How access works

1. User belongs to **groups** and/or has **direct permissions**.  
2. Each screen/action checks Django permission codenames.  
3. **Superuser** bypasses all checks.  
4. Missing permission → **403** page: *"You do not have permission to access this page…"*

### 11.2 Models managed in Access Groups UI

| App | Model | Typical use |
|-----|-------|-------------|
| masters | client | Client Master CRUD + **approve_client** |
| masters | clientgroup | Group Master |
| masters | directormapping | Director Mapping |
| core | employee | User Management |
| reports | reportpolicy | Report view/export permissions |
| mis | feesdetail, receipt, expensedetail, tenderdetail | MIS modules |
| dirkyc | dir3kyc | DIR-3 KYC |

### 11.3 Custom permissions (not default Django)

| Permission | Meaning |
|------------|---------|
| `masters.approve_client` | Approve pending clients |
| `reports.access_reports_menu` | Open Reports section / MIS report |
| `reports.view_client_master_report` | Client Master report |
| `reports.export_client_master_report` | Export Client Master CSV |
| `reports.export_mis_report` | Export flexible MIS CSV |
| `reports.export_mis_client_wise_report` | Client-wise export |
| `reports.export_mis_type_wise_report` | Type-wise export |
| `reports.export_mis_period_report` | Period export (legacy codename) |
| `reports.view_director_mapping_report` | Director mapping report |
| `reports.export_director_mapping_report` | Export mapping CSV |
| `reports.view_dir3kyc_report` | DIR-3 report |
| `reports.export_dir3kyc_report` | Export DIR-3 CSV |

### 11.4 Menu visibility (sidebar)

| Section | Shown when user has |
|---------|---------------------|
| Masters | Any of: view client, view group, approve client, view director mapping, view employee |
| MIS | Any view on fees / tender / receipt / expense |
| Bulk upload | `mis.add_feesdetail` |
| DIR-3 eKYC | `dirkyc.view_dir3kyc` |
| Reports | `access_reports_menu` or specific report view/export perms |
| Activity log | **Superuser only** |

**Access groups** (create/edit/delete): **Superuser only**.

---

## 12. Branch access

Configured on **Employee** profile (`branch_access`):

| Value | Effect |
|-------|--------|
| **(blank) — All branches** | No branch filter (same as superuser for scope) |
| **Trivandrum** | Only clients (and linked MIS, directors, DIR-3, reports) for Trivandrum |
| **Nagercoil** | Only Nagercoil |

**Applies to:** Client Master lists/pickers, MIS entry, director mapping, DIR-3, report branch filter (forced to user’s branch).

**Does not apply to:** Superuser (sees all branches).

---

## 13. User accounts and login

### 13.1 Login

- Email + password.  
- **Inactive** (`is_active = False`): *"This account is inactive. Contact your administrator."*  
- If deactivated while logged in: session ended with same message (`InactiveUserMiddleware`).

### 13.2 User types

| Type | Requirements |
|------|----------------|
| **Employee** | Official email, name, date of joining; optional branch access |
| **Client user** | Email must match **exactly one** Client Master record |

### 13.3 Password

- Minimum **8 characters** on create.  
- **Force password change** on first login may apply (`force_password_change` flag).

### 13.4 User Management actions

| Action | Permission | Restrictions |
|--------|------------|--------------|
| Create / edit | `core.add_employee` / `core.change_employee` | — |
| Deactivate / activate | `core.change_employee` (POST toggle) | Cannot target **self** or **superuser** |
| Delete | `core.delete_employee` | Cannot target **self** or **superuser** |

### 13.5 Active checkbox

**Active (can sign in)** on user form maps to Django `is_active`.

---

## 14. Activity log and test data reset

### 14.1 Activity log

- **Superuser only.**  
- Logs successful mutating requests and GET exports (CSV, templates).  
- Failed requests (status ≥ 400) are not logged.

### 14.2 Reset test data (superuser)

Optional wipe of MIS, director mappings, DIR-3, clients (with dependency handling). Used for training/demo environments only.

---

## 15. Worked examples

### Example 1 — New client cannot be used in MIS

1. Staff creates client **BK0001** → status **Pending**.  
2. Staff opens MIS Fees → client not in suggestions / selection rejected.  
3. Approver opens **Client approvals** → approves **BK0001**.  
4. Staff can now enter MIS for **BK0001**.

### Example 2 — Edit sends client back to pending

1. **BK0001** is approved and has MIS rows.  
2. Staff changes client name → status **Pending** again.  
3. **Existing MIS rows remain** in database but reports/dashboard **exclude** pending client from totals.  
4. Approver re-approves → client back in report totals.

### Example 3 — DIR-3 blocked too early

1. Last filing **15-08-2026** (FY 2026-27).  
2. Next allowed **01-04-2029**.  
3. User tries **01-01-2029** → validation error with allowed date and FY.

### Example 4 — GST on bulk import

| FEES_AMOUNT | GST_AMOUNT | Result |
|-------------|------------|--------|
| 1000 | 180 | OK |
| 0 | 180 | **Rejected** |
| blank | 50 | **Rejected** |

### Example 5 — Branch-restricted user

1. Employee branch = **Nagercoil**.  
2. Can only see/edit Nagercoil clients in master and MIS.  
3. Trivandrum client ID typed manually → *"This client is not in your branch."*

---

## 16. Glossary

| Term | Meaning |
|------|---------|
| **Approved client** | Client Master record with approval status Approved |
| **Pending client** | Saved but not cleared for MIS/mapping/KYC/reports |
| **FY** | Indian financial year, 1 Apr – 31 Mar |
| **DIN** | Director Identification Number (8 digits) |
| **SRN** | Service Request Number from MCA DIR e-KYC |
| **MIS** | Internal fees, receipts, expenses, tender tracking (not statutory books) |
| **Superuser** | Administrator with full system access |
| **Access group** | Named set of permissions assigned to users |

---

## 17. Appendix — validation messages

Common messages users may see (paraphrased groups):

**Client Master**

- Client Name is required.  
- Since PAN is blank, Client Type must be None…  
- PAN already exists for another non-Branch client…  
- For this PAN (4th character 'X'), Client Type must be one of: …  
- DIN is mandatory when Is Director is selected.  
- This client cannot be deleted while it is still used by MIS records…

**MIS**

- Please select a client from the suggestions.  
- This client is not in your branch.  
- GST amount cannot be entered when Fees amount is 0.  
- Enter tender fees and/or tender deposit.

**Director mapping**

- This director already has an active appointment with this company…  
- Cessation date cannot be before appointment date.

**DIR-3**

- The next DIR-3 e-KYC for this director is allowed only from …

**Access**

- You do not have permission to access this page.  
- This account is inactive. Contact your administrator.

---

## Document history

| Item | Detail |
|------|--------|
| Purpose | Detailed training and reference for CA Office Suite business rules |
| Source | Application logic in `masters`, `mis`, `dirkyc`, `reports`, `core` apps |
| Related | `CA_Office_Suite_Business_Rules.md`, `CA_Office_Suite_Employee_Presentation.html` |

---

*End of detailed manual*
