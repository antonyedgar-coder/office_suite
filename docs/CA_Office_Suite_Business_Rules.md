# CA Office Suite — Business Rules & Logic Guide

**Audience:** Office staff, approvers, and trainers  
**Purpose:** Explain how the system applies rules so you can use it correctly and answer client questions consistently.

---

## 1. Overview

CA Office Suite is organised into four main areas:

| Area | What it holds |
|------|----------------|
| **Masters** | Client Master, Group Master, Director Mapping, User Management |
| **MIS** | Fees, Receipts, Expenses, Tender, Bulk upload |
| **DIR-3 eKYC** | Director DIR-3 / e-KYC filings |
| **Reports** | Client Master, MIS, Director Mapping, DIR-3 KYC reports (with optional CSV export) |

What you see in the menu depends on your **permissions** (assigned by a superuser through access groups). If a screen is missing, ask an administrator to add the right permission.

---

## 2. Indian Financial Year (FY)

The system uses the **Indian financial year**: **1 April to 31 March**.

| Calendar dates | Financial year label |
|----------------|----------------------|
| 1 Apr 2026 – 31 Mar 2027 | **2026-27** |
| 1 Apr 2025 – 31 Mar 2026 | **2025-26** |

**How the label is built:** Take the year of the April that starts the FY (e.g. April 2026 → **2026-27**).

This FY definition is used for:

- Dashboard **MIS this financial year** totals  
- **MIS Report** (especially month-wise view)  
- **DIR-3 eKYC** next-filing rules and compliance  
- DIR-3 **pending** count on the dashboard  

---

## 3. Client Master

### 3.1 Approval workflow (very important)

Every client has an **approval status**:

| Status | Meaning |
|--------|---------|
| **Pending** | Saved in the system but **not** usable in MIS, Director Mapping, or DIR-3 KYC |
| **Approved** | Fully active for all other modules |

**When a record becomes pending**

- A normal user **creates** a new client → **pending** until approved.  
- A normal user **edits** an approved client → goes **pending again** until re-approved.  
- A **superuser** create/edit → **approved** immediately.

**Who can approve**

- Users with the **Approve client** permission see **Client approvals** and can accept pending clients.

**What you see in Client Master list**

- Approvers: all clients (subject to branch access).  
- Others: **approved** clients **plus** your own **pending** entries (so you can track what you submitted).

### 3.2 Where “approved only” applies

These screens only allow **approved** clients:

- MIS (Fees, Receipts, Expenses, Tender)  
- Director Mapping  
- DIR-3 KYC  
- MIS-related **reports** and dashboard FY totals  

**Pending clients** may still appear on MIS **entry** lists if old data exists, but **reports and dashboard totals exclude them**.

### 3.3 Client ID and branches

- **Client ID** is auto-generated (e.g. `AN0001`) from client name initial + branch + sequence.  
- **Branches:** Trivandrum, Nagercoil.  
- **Client types** include Individual, Partnership, LLP, Private/Public Limited, Branch, Foreign Citizen, Trust, etc.

### 3.4 Directors and DIN

- **Is Director** and **DIN** apply only to **Individual** or **Foreign Citizen**.  
- **Branch** clients cannot be marked as director or given a DIN.  
- If **Is Director** is ticked, **DIN is mandatory** (8 digits).  
- If not a director, DIN must be left blank.

### 3.5 PAN, name, and type rules (summary)

The system enforces consistency between **name**, **client type**, and **PAN** (including PAN 4th-character rules). Examples:

- Certain name words require a matching type (e.g. “PRIVATE LIMITED” → Private Limited).  
- PAN is required for most types (exceptions: Type “None”, Foreign Citizen, Branch).  
- Duplicate PAN in the database is only allowed for **Branch** type.  
- GSTIN (when entered) must align with PAN where applicable.

Full validation messages appear on the form when a rule fails.

### 3.6 Deleting a client

Deletion is blocked if the client is still linked to:

- MIS (fees, receipts, expenses)  
- Director mapping  
- DIR-3 KYC records  

Remove or reassign those links first.

### 3.7 Bulk import (Client Master)

- Upload → **preview** → **confirm** (all rows succeed or none are saved).  
- Non-superuser imports create **pending** clients until approved.

---

## 4. Group Master

- Groups get auto IDs like `GR…`.  
- Names are normalised (e.g. uppercased).  
- **Inactive** groups cannot be assigned to new clients.  
- A group cannot be deleted while clients are still linked to it.  
- Bulk delete of groups is **superuser only**.

---

## 5. Director Mapping

### 5.1 Who can be a director (in mapping)

- **Director side:** Approved **Individual** or **Foreign Citizen**, marked **Is Director**, with DIN.  
- **Company side:** Private Limited, Public Limited, Nidhi Co, FPO, Sec 8 Co, or LLP.

### 5.2 Appointment rules

- **Cessation date** cannot be before **appointment date**.  
- Cessation without appointment is not allowed.  
- If there is a cessation date, **reason** is required (Resigned, Disqualified, Terminated, Death).  
- Only **one active appointment** per director–company pair (no cessation date). End the old appointment before adding a new one.

### 5.3 Branch access

Users restricted to a branch only see directors/clients in that branch.

---

## 6. MIS (Management Information System)

### 6.1 Client selection

- Only **approved** clients from Client Master.  
- Must pick from suggestions (valid client ID).  
- If your user is branch-restricted, you cannot select clients from another branch.

### 6.2 Fees and GST

| Rule | Detail |
|------|--------|
| Total | **Total = Fees amount + GST amount** (calculated automatically) |
| Negatives | Fees, GST, and totals cannot be negative |
| GST with zero fees | **GST cannot be entered when Fees amount is 0** |

### 6.3 Receipts and expenses

- Amounts cannot be negative.  
- Receipts and expenses are stored per client and date like fees.

### 6.4 Tender

- At least one of **Tender fees** or **Tender deposit** must be entered.  
- Amounts cannot be negative.  
- Tender is included in **MIS Report** when you select tender columns; it is **not** in the dashboard FY fee/receipt/expense summary cards.

### 6.5 Bulk upload (MIS)

- **Combined file** can create fees, receipts, and expenses in one go (subject to your add permissions).  
- **CLIENT_ID** must exist, be **approved**, and match the name in the file.  
- Same GST rule: no GST when fees are zero/blank.  
- Each row must have at least one non-zero amount (for combined import).  
- Import is preview → confirm; lists on screen are capped (e.g. 500 rows).

### 6.6 Dashboard — “MIS this financial year”

| Aspect | Rule |
|--------|------|
| Period | **1 April of current FY** through **today** (or through 31 March if viewing after FY end) |
| Clients | **Approved clients only** |
| Branch | Respects your branch access |
| Figures | Sum of **fees total (incl. GST)**, **receipts**, **expenses** |
| Same as reports? | Same **approved-client** rule as **Reports → MIS Report** |

---

## 7. DIR-3 eKYC

### 7.1 Who can be filed

- Approved **Individual** or **Foreign Citizen** with **Is Director** and a valid **DIN**, chosen from Client Master.

### 7.2 Filing cadence (by financial year)

Rules are based on the **FY of the last filing date**, not “3 calendar years from the day”:

1. Find which **Indian FY** the last **Date of DIR-3 KYC done** falls in.  
2. The **next** filing for that director is allowed only from **1 April** of the calendar year that is **three years after the start year** of that FY.

**Example**

- Last filing on any date in **FY 2026-27** (1 Apr 2026 – 31 Mar 2027)  
- Next allowed from **1 April 2029** (start of FY **2029-30**)

If you try to save earlier, the system shows the earliest allowed date and FY.

### 7.3 Dashboard — “DIR-3 eKYC pending”

A director counts as **pending** if:

1. **Never filed**, or  
2. **Today is on or after** the next allowed filing date from their **last** filing (using the rule above).

Only **approved** directors in scope (with DIN, director flag, eligible type), filtered by branch access.

### 7.4 DIR-3 KYC Report — “≥3 FY” compliance

For compliance views, a director may be flagged when there has been **no filing for four or more FY start years** since the last filing FY (or never filed). Used for tracking overdue e-KYC by FY gap.

---

## 8. Reports

### 8.1 General

- Most MIS figures use **approved clients only**.  
- **Branch filter** on reports follows employee branch access (restricted users see their branch only).  
- **Export to CSV** requires separate export permissions per report type.

### 8.2 Client Master Report

- Filter by type, branch, name, DIN, PAN, GSTIN, CIN, LLPIN, director flag (combined filters).  
- Display capped (e.g. 500 rows on screen).

### 8.3 MIS Report (flexible)

**Views:** Transactions, Client wise, Type wise, Month wise.

**Filters:** Date range **or** (for month wise) one or more financial years; branch; client id/name/PAN; client type.

**Detail columns:** All, Fees, GST, Receipts, Expenses, Tender fees, Tender deposit (as selected).

**Month wise FY list:** From **2026-27** upward through the current FY (new FYs appear each 1 April).

### 8.4 Director Mapping Report

- **As-on date:** Shows appointments active on that date (appointed on or before; not ceased, or ceased after as-on date).

### 8.5 DIR-3 KYC Report

- All filings or latest per director; optional filters; compliance-oriented options including long gaps since last filing FY.

---

## 9. Access, permissions, and branches

### 9.1 Permissions

- Each screen/action needs the matching permission (view / add / change / delete / approve / export).  
- **Superusers** bypass permission checks.  
- **Access groups** (superuser only) bundle permissions for roles like “MIS entry”, “Approver”, “Reports only”.

### 9.2 Branch access (employees)

| Setting | Effect |
|---------|--------|
| **Blank** (all branches) | See all branches (superuser or unrestricted employee) |
| **Trivandrum** or **Nagercoil** | Client Master, MIS, directors, DIR-3, and reports limited to that branch |

### 9.3 Activity log

- **Superusers only** — records important actions and exports.

---

## 10. User accounts

| Topic | Rule |
|-------|------|
| **Login** | Official email + password |
| **Inactive account** | Cannot log in; active sessions are logged out with a message |
| **First login** | May be forced to change password |
| **Deactivate / delete** | Cannot target **your own** account or **superuser** accounts from User Management |
| **Client user** | Email must match exactly one Client Master record |
| **Employee user** | Name and date of joining required |

---

## 11. Quick reference — “Why can’t I…?”

| Situation | Likely reason |
|-----------|----------------|
| Client not in MIS dropdown | Client is **pending** or wrong **branch** |
| MIS totals differ from my entries | Dashboard/reports count **approved** clients only; period is **FY year-to-date** |
| Cannot add DIR-3 KYC | Too early — **next FY window** not open yet |
| Cannot delete client | Still used in MIS, mapping, or DIR-3 |
| Menu item missing | No **permission** — ask superuser |
| GST rejected on import | Fees are zero but GST column has a value |
| Edited client disappeared from MIS | Edit sent client back to **pending** |

---

## 12. Document control

| Item | Value |
|------|--------|
| System | CA Office Suite |
| Document | Business Rules & Logic Guide |
| Based on | Application logic as implemented in the codebase |

For **full detail** (every validation rule, tables, worked examples), see **`CA_Office_Suite_Business_Rules_Detailed.md`**.

For training, use the companion file: **`CA_Office_Suite_Employee_Presentation.html`** (open in a browser; use arrow keys to advance slides; print to PDF if needed).  
Optional PowerPoint: run `python docs/build_presentation.py` to generate **`CA_Office_Suite_Employee_Presentation.pptx`**.

---

*End of guide*
