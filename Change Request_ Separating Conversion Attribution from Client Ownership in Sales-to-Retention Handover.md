# Change Request: Separate Conversion Attribution (Followup Owner) from Servicing Ownership (Client Owner) on Sales-to-Retention Handover

**Document type:** Business Requirements / Change Request specification
**System:** Nexora in-house CRM (Followup, Client, Calls, Ledger modules)
**Requested by:** Tanvik, Data Analytics & Operations
**Audience:** Internal CRM development team
**Status:** Draft for review. Items marked **[CONFIRM]** need a business decision before build.

The CRM must treat the **Followup Owner** as a permanent, locked record of the Sales CRE who converted a lead, and the **Client Owner** as a separate field that moves to a Retention team member at handover. Referral-team conversions move after a 30-day Sales hold; all other lead sources move at conversion. Every ownership change must be written to an append-only history table so CRE performance and Retention performance can be reported correctly at any point in time.

## TL;DR

- **Two owners, two meanings:** the Followup Owner records who converted the lead and never changes automatically after conversion. The Client Owner records who services the client today and changes at handover. All CRE performance reporting uses the Followup Owner / Converted By. All Retention performance reporting uses the Client Owner.
- **Two handover paths:** for Referral-team lead source conversions, the Client Owner stays with the converting Sales CRE for 30 days. A scheduled, idempotent job then hands the client to Retention. For all other lead sources, the client goes to Retention at conversion. In both paths the Followup Owner stays the same.
- **Build it auditable:** add Converted By, Conversion Date, Handover Due/Actual Date, Handover Type and Previous Client Owner fields, plus an append-only ownership history table. Open items for confirmation are the day-30 definition and timezone, the Retention assignment rule, and what "immediately" means. The recommended defaults are calendar days in Asia/Dubai time, load-balanced round-robin, and at conversion.

---

## 1. Purpose and Background

Nexora has two client-facing teams:

- **Sales:** Client Relationship Executives (CREs), about 49 people. They work leads and convert them into clients.
- **Retention:** they service and retain clients after conversion.

Every new lead is automatically assigned a **Followup Owner** (a Sales CRE) through the lead distribution process. When the CRE converts the lead, a **Client** record is created, and it carries a **Client Owner**.

Data Analytics measures CRE performance in Zoho Analytics, Metabase and PostgreSQL: conversions, and retention cohorts by lead source. These analyses only work if the field that identifies the converting CRE never changes after conversion. When a client moves to Retention, servicing responsibility changes but conversion credit does not. One owner field cannot carry both meanings. This change request formalises the two-field model and the handover rules.

## 2. Business Rules (as stated by the business, not to be altered)

| # | Rule |
|---|---|
| BR-1 | Every new lead is automatically assigned a Followup Owner (a Sales CRE). |
| BR-2 | The CRE converts the lead into a client. |
| BR-3 | **Referral-team lead source conversions:** Sales keeps the client for 30 days after conversion (Client Owner = the Sales CRE during this period). After 30 days the client is handed over to Retention. On handover the Followup Owner must **not** change (it stays the converting CRE), and the Client Owner changes to a Retention team member. |
| BR-4 | **All other lead sources:** on conversion the client is handed over to Retention immediately, with no 30-day hold. The Followup Owner stays the same and the Client Owner changes to a Retention team member. |
| BR-5 | **Purpose:** the Followup Owner is the permanent conversion attribution, so CRE performance can be analysed later. The Client Owner reflects current servicing responsibility. |

## 3. Scope

**In scope**
- Ownership logic on the Followup (lead) and Client modules at conversion and at handover.
- New fields on Client (and Followup where noted) and a new ownership history table.
- A scheduled job for the 30-day Referral handover.
- Field-level permissions for owner fields.
- Handover notifications (optional, configurable).
- A one-time backfill of existing clients.
- Reporting views/exports used by Zoho Analytics, Metabase and PostgreSQL.

**Out of scope**
- Changes to the lead distribution algorithm that assigns the initial Followup Owner (BR-1 already exists; this CR only consumes its output).
- Commission or incentive calculations. This CR supplies the data those calculations need but does not define payouts.
- The broker-referral (Brf) hierarchy logic itself, beyond using "Referral" as a lead source value.
- Changes to the Calls and Ledger modules, except that they must keep linking to the Client record and must not overwrite owner fields.

## 4. Definitions / Glossary

| Term | Definition |
|---|---|
| **Lead (Followup record)** | A prospective client record in the Followup module. It is created before conversion. |
| **Client** | A record in the Client module created when a lead is converted. |
| **Followup Owner** | The Sales CRE assigned to the lead through lead distribution. After conversion it is the permanent conversion-attribution field. Stored on the lead and copied to the client. |
| **Converted By / Conversion Owner** | The user who actually performed the conversion, captured as a system stamp at the moment of conversion. Normally equal to the Followup Owner. Kept separately so that any mismatch is visible (e.g. a conversion done by a covering CRE). |
| **Client Owner** | The user currently responsible for servicing the client: the Sales CRE during the Referral hold, then a Retention team member. |
| **CRE** | Client Relationship Executive, a Sales team member. |
| **Retention (team / member)** | The team that services clients after handover. A Retention member is any active user flagged as belonging to the Retention team. |
| **Referral lead source** | Leads whose lead source is the referral team (exact picklist value(s) to be confirmed, **[CONFIRM] OI-6**). |
| **Other lead source** | Any lead source value that is not a Referral lead source value. |
| **Conversion Date** | The UTC timestamp at which the lead was converted to a client (system-set, immutable). |
| **Handover Due Date** | For Referral conversions, the timestamp at which the client becomes due for transfer to Retention (Conversion Date + 30 days, per OI-1/OI-2). Null for other sources. |
| **Handover Date (Actual)** | The timestamp at which the Client Owner was actually changed to a Retention member. |
| **Handover Type** | How the handover happened: `IMMEDIATE_ON_CONVERSION`, `REFERRAL_30D_AUTO`, `MANUAL_ADMIN`, `EXCEPTION_RELEASE`, `BACKFILL`, `USER_DEACTIVATION`. |
| **Hold / Sales Hold** | The period during which a Referral client's Client Owner remains the Sales CRE. |

## 5. Current Behaviour / Problem Statement (to be completed by the business)

> The as-is behaviour has not been verified. Please complete before submission. Developers: please confirm or correct each row during estimation.

| Area | Current behaviour (fill in) | Observed impact |
|---|---|---|
| Followup Owner on handover | ☐ Overwritten with Retention user ☐ Unchanged ☐ Unknown | _e.g. CRE loses conversion credit in reports_ |
| Client Owner on conversion | ☐ Set to CRE ☐ Set to Retention ☐ Left blank ☐ Unknown | |
| Client Owner after 30 days (Referral) | ☐ Changed manually ☐ Not changed ☐ Changed automatically ☐ Unknown | |
| Ownership history / audit | ☐ None ☐ Partial (which fields?) ☐ Full | |
| Who can edit owner fields today | _list roles_ | |
| Example records showing the problem | _client IDs_ | |

**Problem summary (draft):** CRE performance analysis relies on the Followup Owner. If handover overwrites this field, or the Client Owner is not updated consistently, conversions are credited to the wrong person and retention cohorts by CRE and lead source become unreliable.\[1\] The business also has no dependable record of when and why ownership changed.\[2\]

## 6. Expected Behaviour (To-Be) – Summary

1. A lead is created → Followup Owner is assigned automatically (unchanged process).
2. The CRE converts the lead → the system stamps Converted By, Conversion Date and the lead source snapshot. It copies the Followup Owner onto the Client and locks it.
3. The system decides the handover path from the lead source at conversion:
   - **Referral:** Client Owner = converting CRE, Handover Due Date = conversion + 30 days, status `IN_SALES_HOLD`.
   - **Other:** Client Owner = Retention member selected by the assignment rule, Handover Date = now, Handover Type = `IMMEDIATE_ON_CONVERSION`.
4. A scheduled job finds Referral clients whose Handover Due Date has passed and that are still in hold. It changes the Client Owner to a Retention member (Handover Type = `REFERRAL_30D_AUTO`).
5. Every owner change writes one row to the ownership history table.
6. The Followup Owner never changes automatically after conversion.

## 7. Decision Table / Rules Matrix

| Stage | Referral lead source: Followup Owner | Referral: Client Owner | Other lead sources: Followup Owner | Other: Client Owner |
|---|---|---|---|---|
| **At lead creation** | Sales CRE (auto-assigned) | n/a (no client yet) | Sales CRE (auto-assigned) | n/a (no client yet) |
| **At conversion** | Same CRE, locked | Converting Sales CRE | Same CRE, locked | **Retention member** (handover now, `IMMEDIATE_ON_CONVERSION`)* |
| **During 30-day hold** | Same CRE, locked | Converting Sales CRE | n/a (no hold) | Retention member |
| **After handover (day 30)** | Same CRE, locked | **Retention member** (`REFERRAL_30D_AUTO`) | Same CRE, locked | Retention member |
| **Any later reassignment** | Unchanged (admin-only correction, audited) | Any Retention member (audited) | Unchanged (admin-only correction, audited) | Any Retention member (audited) |

\*Subject to OI-4: if "immediately" is confirmed to mean first deposit/activation, the Client Owner sits with the CRE until that event, and the handover happens then.

**Rule evaluation logic (pseudo-code):**

```
ON lead_converted(lead, converting_user, now_utc):
    client.followup_owner_id      = lead.followup_owner_id        -- copied and locked
    client.converted_by_id        = converting_user.id
    client.conversion_date_utc    = now_utc
    client.lead_source_at_conversion = lead.lead_source            -- snapshot, immutable
    IF lead.lead_source IN referral_sources_config:
        client.client_owner_id    = converting_user.id   -- see OI-7 if converter ≠ followup owner
        client.handover_status    = 'IN_SALES_HOLD'
        client.handover_due_at_utc = compute_due(now_utc)  -- per OI-1/OI-2
    ELSE:
        client.client_owner_id    = select_retention_owner(client)  -- per OI-3
        client.handover_status    = 'HANDED_OVER'
        client.handover_type      = 'IMMEDIATE_ON_CONVERSION'
        client.handover_at_utc    = now_utc
        client.previous_client_owner_id = converting_user.id
    write_ownership_history(...)
```

## 8. Process Flow (diagram-ready)

**Swimlanes:** Lead Distribution (system) | Sales CRE | CRM Conversion Service | Scheduler | Retention | Analytics

1. **[Start]** A lead is created in the Followup module.
2. **[System]** Lead distribution assigns the Followup Owner (Sales CRE). → History row: `FOLLOWUP_OWNER_ASSIGNED`.
3. **[CRE]** Works the lead (Calls etc.).
4. **[CRE]** Converts the lead → **[Conversion Service]** creates the Client and stamps Converted By, Conversion Date, Lead Source snapshot, and Followup Owner (locked).
5. **[Decision]** Is the lead source a Referral source?
   - **Yes →** 6a. Client Owner = CRE; status `IN_SALES_HOLD`; Handover Due = conversion + 30 days. History row: `CLIENT_OWNER_SET (SALES_HOLD)`. (Optional: notify CRE of the due date.)
     - 7a. **[Scheduler]** runs on schedule → **[Decision]** Is Handover Due ≤ now AND status = `IN_SALES_HOLD` AND no active exception?
       - **No →** wait for the next run.
       - **Yes →** 8a. Select a Retention owner → set Client Owner, Previous Client Owner, Handover Date, Handover Type `REFERRAL_30D_AUTO`, status `HANDED_OVER` → history row → notifications (CRE + Retention owner) → **[End]**.
   - **No →** 6b. Select a Retention owner → set Client Owner, Previous Client Owner = CRE, Handover Date = now, Handover Type `IMMEDIATE_ON_CONVERSION`, status `HANDED_OVER` → history row → notifications → **[End]**.
9. **[Analytics]** CRE reports read `followup_owner_id` / `converted_by_id`. Retention reports read `client_owner_id` plus the ownership history for point-in-time views.

## 9. Functional Requirements

### 9.1 Conversion and attribution

- **FR-1 Followup Owner auto-assignment.** The existing lead distribution must keep assigning a Followup Owner to every new lead. A lead must not be convertible without a Followup Owner.
- **FR-2 Conversion stamping.** On conversion the system must set these fields on the Client record in the same transaction: `followup_owner_id` (copied from the lead), `converted_by_id` (the acting user), `conversion_date_utc`, and `lead_source_at_conversion`.
- **FR-3 Followup Owner immutability.** After conversion, `followup_owner_id` on both the lead and the client must be read-only for all roles except the designated CRM Admin role (see §13). No automated process (handover job, user deactivation, mass transfer, import, integration, merge) may change it.
- **FR-4 Admin correction with reason.** An admin correction of `followup_owner_id` must require a mandatory reason (picklist + free text). It must write a history row and must not change `converted_by_id`.
- **FR-5 Converted By is system-only.** `converted_by_id` and `conversion_date_utc` must be set only by the system at conversion. They can only be changed by a database-level, audited data fix approved by the business, never through the UI.

### 9.2 Handover routing

- **FR-6 Lead source classification.** Referral lead source values must be held in a configuration table, not hard-coded, so new referral sub-sources can be added without a code release.
- **FR-7 Referral hold.** For Referral conversions the Client Owner must be set to the converting CRE (see OI-7), `handover_status = IN_SALES_HOLD`, and `handover_due_at_utc` computed per §11.
- **FR-8 Immediate handover.** For all other lead sources the Client Owner must be set to a Retention member at conversion (or at the trigger defined by OI-4). The system must set `previous_client_owner_id`, `handover_at_utc`, `handover_type = IMMEDIATE_ON_CONVERSION` and `handover_status = HANDED_OVER`.
- **FR-9 Followup Owner unchanged on any handover.** Every handover path must leave `followup_owner_id` and `converted_by_id` unchanged. This must be enforced in the service layer and protected by a database constraint or trigger (see FR-26).
- **FR-10 Retention owner selection.** The Retention owner must be chosen by a configurable strategy (see §10.3 and OI-3). Only active users flagged as Retention may be selected. If no eligible user exists, the client must go to a configurable "Retention Unassigned" queue user and an alert must be raised. The Client Owner must never be left null.
- **FR-11 Referral exception override.** Authorised users must be able to put a Referral client on an "extended Sales hold" with a mandatory reason and a new end date (or "until released"). While the exception is active the handover job must skip the client. Setting, changing or releasing an exception must write history rows.
- **FR-12 Manual early handover.** Authorised users may hand a Referral client to Retention before day 30 (Handover Type = `MANUAL_ADMIN`, reason required).

### 9.3 Audit and history

- **FR-13 Ownership history table.** Every change to `followup_owner_id` or `client_owner_id`, and every hold/exception state change, must insert one immutable row into `client_ownership_history` (see §10.2).\[3\] Rows may never be updated or deleted through the application.
- **FR-14 History visibility.** The Client detail page must show an "Ownership History" related list with old owner, new owner, changed at, changed by (user or "System – job name"), change type and reason.
- **FR-15 Retention of history.** Ownership history must be kept for the life of the client record plus the company's data-retention period, and never auto-purged on a short rolling window (see §16 note on vendor limits).

### 9.4 Reporting

- **FR-16 Attribution fields exposed.** `followup_owner_id`, `converted_by_id`, `conversion_date_utc`, `lead_source_at_conversion`, `client_owner_id`, `handover_type`, `handover_at_utc`, `handover_status` must be available in exports/APIs/DB views consumed by Zoho Analytics, Metabase and PostgreSQL.
- **FR-17 Point-in-time view.** Provide a view (e.g. `v_client_owner_periods`) with one row per client per ownership period: `client_id, owner_id, owner_team, valid_from_utc, valid_to_utc, is_current`.

### 9.5 Notifications (optional, configurable)

- **FR-18 Handover notifications.** On any handover, notify the new Retention owner (new client assigned, with CRE name and conversion date) and the converting CRE (client handed over, conversion credit retained). Each channel (in-app/email) must be switchable on and off by configuration.
- **FR-19 Pre-handover reminder.** Optionally notify the CRE N days (default 3) before a Referral client's Handover Due Date.
- **FR-20 Job failure alert.** Notify CRM admins / Ops when the handover job fails, or leaves clients overdue by more than 24 hours.

## 10. Data / Field Requirements

### 10.1 New or changed fields

**Client module**

| Field (suggested API name) | Type | Set by | Editable by | Notes |
|---|---|---|---|---|
| `followup_owner_id` | FK → users | System at conversion (copied from lead) | CRM Admin only, with reason | Permanent conversion attribution. |
| `converted_by_id` | FK → users | System at conversion | No one via UI | Actual converting user. |
| `conversion_date_utc` | timestamptz | System at conversion | No one via UI | Store in UTC. |
| `lead_source_at_conversion` | varchar / FK | System at conversion | No one via UI | Snapshot; later lead-source edits don't change it. |
| `lead_id` | FK → followup | System | No one | Link back to the originating lead. |
| `client_owner_id` | FK → users | System / authorised users | See §13 | Current servicing owner. Never null. |
| `previous_client_owner_id` | FK → users | System on each Client Owner change | No one | Convenience field. History table is the source of truth. |
| `handover_status` | enum: `IN_SALES_HOLD`, `EXTENDED_HOLD`, `HANDED_OVER`, `PENDING_ACTIVATION` (if OI-4) | System | System / authorised users via actions | |
| `handover_due_at_utc` | timestamptz | System (Referral only) | Changed only via exception action | |
| `handover_at_utc` | timestamptz | System | No one | Actual handover time. |
| `handover_type` | enum (see glossary) | System | No one | |
| `hold_exception_reason` / `hold_exception_until_utc` / `hold_exception_by_id` | text / timestamptz / FK | Exception action | Authorised users | |

**Users**

| Field | Type | Notes |
|---|---|---|
| `team` | enum: `SALES`, `RETENTION`, `OTHER` | Required for eligibility and reporting. |
| `is_active` | boolean | Deactivated users are not eligible as new owners. |
| `retention_capacity` (optional) | integer | For load-balanced assignment. |

**Configuration tables**

- `config_referral_lead_sources(lead_source_value, active_from, active_to)`
- `config_handover(hold_days = 30, day_basis = 'CALENDAR', business_timezone = 'Asia/Dubai', cutoff_rule = 'START_OF_LOCAL_DAY', assignment_strategy, unassigned_queue_user_id, reminder_days = 3, trigger_for_other_sources = 'ON_CONVERSION')`

### 10.2 Ownership history / audit table

`client_ownership_history` (append-only)

| Column | Type | Description |
|---|---|---|
| `id` | bigserial PK | |
| `client_id` | FK | |
| `lead_id` | FK | |
| `field_name` | enum: `FOLLOWUP_OWNER`, `CLIENT_OWNER`, `HANDOVER_STATUS` | |
| `old_value` / `new_value` | FK users / text | |
| `old_owner_team` / `new_owner_team` | enum | Team snapshot at the time of change (users may move teams later). |
| `change_type` | enum: `FOLLOWUP_OWNER_ASSIGNED`, `CONVERSION`, `IMMEDIATE_ON_CONVERSION`, `REFERRAL_30D_AUTO`, `MANUAL_ADMIN`, `EXCEPTION_SET`, `EXCEPTION_RELEASED`, `USER_DEACTIVATION`, `ADMIN_CORRECTION`, `BACKFILL`, `MERGE` | |
| `reason` | text | Mandatory for manual/admin changes. |
| `changed_by_user_id` | FK, nullable | Null when the system made the change. |
| `changed_by_process` | varchar | e.g. `handover_job_v1`, `conversion_service`, `backfill_2026`. |
| `job_run_id` | FK, nullable | Links to the job run log. |
| `changed_at_utc` | timestamptz | |
| `effective_from_utc` | timestamptz | Usually = changed_at; may differ for backfill. |

Implementation notes:
- Write history in the same database transaction as the owner change (service layer), with a PostgreSQL `AFTER UPDATE` trigger as a safety net. The trigger catches changes made outside the service (scripts, imports) and records `changed_by_process = 'db_trigger'`.\[4\]
- Revoke `UPDATE`/`DELETE` on the history table from the application role.\[5\]
- Index on `(client_id, changed_at_utc)` and `(new_value, field_name, changed_at_utc)`.

### 10.3 Retention owner assignment strategy (configurable) – OI-3

| Option | Behaviour | Pros | Cons |
|---|---|---|---|
| `ROUND_ROBIN` | Next eligible Retention member in fixed rotation | Simple, equal count | Ignores current book size and absences |
| `LOAD_BALANCED` | Member with the fewest active clients (or furthest below capacity) | Even workload | A newly added member receives every new client until their book catches up with the team |
| `ROUND_ROBIN_WITH_CAP` *(recommended)* | Rotation, skipping anyone at or above capacity or inactive | Fair and capacity-aware | Needs capacity values maintained |
| `RETENTION_LEAD_QUEUE` | Assign to Retention lead/queue, who distributes manually | Full control | Manual effort; clients can wait unassigned |
| `MANUAL` | Converter or admin picks the Retention user | Flexible | Inconsistent, slow |

**Recommendation:** `ROUND_ROBIN_WITH_CAP`, with the unassigned-queue fallback (FR-10). Assignment must be serialised (row lock or advisory lock) so that two concurrent conversions cannot both take the same "next" slot.\[6\]

## 11. Scheduled Job: 30-Day Referral Handover

**JOB-1 Schedule.** Run at least hourly. Recommended: every 15 minutes, plus one run at 00:05 Asia/Dubai. Schedule the job in UTC and evaluate business dates in the configured IANA timezone (`Asia/Dubai`).\[7\]

**JOB-2 Due-date computation (default, pending OI-1/OI-2).** `handover_due_at = start of local day (Asia/Dubai) of [local conversion date + 30 calendar days]`, converted to UTC. Example: converted 2026-03-01 15:40 Dubai time → due 2026-03-31 00:00 Dubai (2026-03-30 20:00 UTC). The CRE therefore keeps the client for the whole of the 30 days after the conversion day. Asia/Dubai is UTC+4 with no daylight saving, so the offset is stable all year.\[8\]\[9\] The due date is stored at conversion. Later changes to the config apply only to new conversions unless a recalculation is explicitly run.

**JOB-3 Selection criteria.** `handover_status = 'IN_SALES_HOLD' AND handover_due_at_utc <= now() AND (hold_exception_until_utc IS NULL OR hold_exception_until_utc <= now()) AND client is not merged/deleted`.

**JOB-4 Idempotency.**
- Each client handover uses a deterministic key `('REFERRAL_30D', client_id, handover_due_at_utc)`, stored with a unique constraint in `handover_job_items`.\[10\]
- The update must be conditional: `UPDATE ... WHERE id = :id AND handover_status = 'IN_SALES_HOLD'`. If no row is affected, the client was already handled and the item is marked `SKIPPED_ALREADY_DONE`.
- Running the job twice, or overlapping runs, must produce exactly one ownership change and one history row per client.\[11\]
- Use a single-runner lock (e.g. `pg_try_advisory_lock`) so only one instance runs at a time.

**JOB-5 Transactions.** Process each client in its own transaction covering: owner selection, client update, history insert, job-item insert, and notification enqueue (outbox). One client failing must not roll back others.

**JOB-6 Failure handling and retries.**
- Transient errors (DB timeout, deadlock, lock not acquired): retry up to 3 times with exponential backoff plus jitter, within the run.\[12\]\[13\] If still failing, the item stays pending and is picked up on the next run.
- Permanent errors (no eligible Retention user, invalid data, missing client owner): do not retry blindly.\[12\] Assign to the unassigned queue user if configured, otherwise mark `FAILED_NEEDS_ATTENTION` and alert.
- Catch-up: if the job has been down, the next run must process all overdue clients (the `<= now()` criterion), not only those due "today".

**JOB-7 Logging.** `handover_job_runs(run_id, started_at_utc, ended_at_utc, status, selected_count, success_count, skipped_count, failed_count, error_summary)` and `handover_job_items(run_id, client_id, idempotency_key, outcome, old_owner_id, new_owner_id, error_message, attempts)`. Keep for at least 12 months.

**JOB-8 Monitoring.** Alert when (a) a run fails, (b) no successful run in 2 hours, or (c) any client is more than 24 hours past `handover_due_at_utc` and still `IN_SALES_HOLD` without an exception.

**JOB-9 Dry-run mode.** Provide a dry-run flag that lists the clients that would be handed over, and their proposed Retention owner, without writing. Used for UAT and first go-live.

## 12. Edge Cases

| # | Case | Required behaviour |
|---|---|---|
| EC-1 | **Clients converted before go-live (backfill)** | One-time migration: (a) populate `followup_owner_id`, `converted_by_id` (best available source, otherwise = Followup Owner, flagged `inferred`), `conversion_date_utc`, `lead_source_at_conversion` from the lead. (b) Referral clients converted < 30 days before go-live → `IN_SALES_HOLD` with due date per JOB-2. (c) Referral clients ≥ 30 days old still owned by Sales → handed over by the first job run (Handover Type `BACKFILL`), or listed for review if the business prefers. (d) Non-referral clients still owned by Sales → listed for business decision, not auto-moved. (e) Where the Followup Owner was previously overwritten, restore it from existing logs/backups/Call history if possible. Otherwise flag `attribution_uncertain = true` for exclusion from CRE analysis. Insert one `BACKFILL` history row per client. Run in dry-run first and deliver a reconciliation report. **[CONFIRM] OI-8** |
| EC-2 | **CRE leaves / is deactivated** | `followup_owner_id` and `converted_by_id` keep pointing to the deactivated user, and historical credit is preserved. Clients where the deactivated CRE is the **Client Owner** (in Sales hold) must be reassigned: default = early handover to Retention (`USER_DEACTIVATION`), or to another CRE if the business chooses. Deactivation must be blocked, or a reassignment prompt raised, while the user still owns active-hold clients. Open leads not yet converted follow the existing lead redistribution process. Deactivated users must remain selectable in report filters. |
| EC-3 | **Retention member leaves** | Their clients are reassigned to other Retention members using the assignment strategy or bulk transfer. Each move writes a history row (`USER_DEACTIVATION`). Followup Owner is untouched. |
| EC-4 | **Manual reassignment by admins** | Allowed for Client Owner per §13, with a reason, and audited. Mass-transfer tools must change only `client_owner_id`, never `followup_owner_id`. |
| EC-5 | **Lead source changed after conversion** | `lead_source_at_conversion` does not change and continues to drive the handover path. If an admin corrects the source (data error): Other → Referral while still within 30 days of conversion → no automatic move back to Sales; admin may set an exception manually. Referral → Other while in hold → the client is handed over at the next job run (`MANUAL_ADMIN`). Every correction is audited. **[CONFIRM] OI-9** |
| EC-6 | **Client re-converted / reactivated** | A dormant client who becomes active again keeps the original `followup_owner_id`, and no new conversion is credited by default. If a new lead for an existing client is converted by a different CRE, the system must link it to the existing client and record a separate "reactivation" event (`reactivated_by_id`, `reactivation_date`). Ownership history stays continuous. Whether reactivation earns separate CRE credit is **[CONFIRM] OI-10**. |
| EC-7 | **Duplicate / parent-child client accounts** | On merge, the surviving record keeps the earliest conversion's `followup_owner_id`, `converted_by_id` and `conversion_date_utc`. The merged record's values are kept in history (`MERGE`). Child accounts (e.g. sub-accounts under one client) inherit the Client Owner of the parent by default but keep their own conversion attribution if separately converted. **[CONFIRM] OI-11** |
| EC-8 | **Referral client stays with Sales beyond 30 days** | Via FR-11 exception: mandatory reason, end date or "until released", approval by Sales Manager (configurable). The job skips the client while the exception is active. When the exception ends, the next job run hands over (`EXCEPTION_RELEASE`). Report on all active exceptions. |
| EC-9 | **Timezone boundary at day 30** | Due time is calculated once at conversion in `Asia/Dubai` per JOB-2 and stored in UTC. Conversions at 23:59 vs 00:01 Dubai time differ by one business day, which is expected. Staff working in IST (UTC+5:30) or UTC see the converted local time in the UI. The rule is always evaluated in the configured business timezone. Tests must cover conversions within one hour either side of midnight Dubai and midnight UTC. |
| EC-10 | **Converter ≠ Followup Owner** | Both are recorded. Followup Owner stays as assigned. Who holds the Referral client during the hold (converter vs Followup Owner) is **[CONFIRM] OI-7**. Default: Followup Owner. |
| EC-11 | **Conversion reversed / deleted** | Soft-delete only. History is retained. If a conversion is undone, the hold is cancelled and the client is excluded from conversion counts, while audit rows remain. |
| EC-12 | **No eligible Retention user** | Assign to the unassigned queue user, alert Ops (FR-10). Never leave the Client Owner null or keep the client in Sales silently. |
| EC-13 | **User changes team (Sales → Retention or vice versa)** | Historical rows keep the team snapshot (`old_owner_team`/`new_owner_team`), so past reporting stays correct. |

## 13. Permissions and Roles

| Action | Sales CRE | Sales Manager | Retention Member | Retention Lead | CRM Admin | System |
|---|---|---|---|---|---|---|
| View Followup Owner / Converted By | ✔ | ✔ | ✔ | ✔ | ✔ | – |
| Edit Followup Owner **before** conversion | ✖ (existing distribution rules) | ✔ (per existing process) | ✖ | ✖ | ✔ | ✔ (distribution) |
| Edit Followup Owner **after** conversion | ✖ | ✖ | ✖ | ✖ | ✔ with reason, audited | ✖ |
| Edit Converted By / Conversion Date | ✖ | ✖ | ✖ | ✖ | ✖ (DB-level approved fix only) | ✔ at conversion |
| Change Client Owner during Sales hold | ✖ | ✔ (to another CRE, or early handover), reason | ✖ | ✖ | ✔ | ✔ |
| Change Client Owner after handover (within Retention) | ✖ | ✖ | ✖ | ✔ reason | ✔ | ✔ |
| Move a handed-over client back to Sales | ✖ | ✖ | ✖ | ✖ | ✔ reason, audited | ✖ |
| Set / release Referral hold exception | ✖ (may request) | ✔ | ✖ | ✖ | ✔ | ✔ (auto-release) |
| View ownership history | Own clients | Team | Own clients | Team | All | – |
| Edit/delete ownership history | ✖ | ✖ | ✖ | ✖ | ✖ | ✖ |

Role names are indicative and must be mapped to existing CRM profiles. **[CONFIRM] OI-12**

## 14. Reporting and Analytics Requirements

- **RPT-1 CRE performance** (conversions, conversion rate, deposits/ledger metrics, retention cohorts by lead source) must group by `followup_owner_id` (primary) and show `converted_by_id` as a secondary/reconciliation dimension. Never group by `client_owner_id`.
- **RPT-2 Retention performance** must group by `client_owner_id` for current book views, and by `v_client_owner_periods` for period metrics. Activity and ledger events are attributed to the owner whose ownership period covers the event timestamp.
- **RPT-3 Sales-hold performance (Referral):** metrics for the 30-day hold period must be attributable to the CRE using the ownership period, so CRE impact during the hold can be measured separately from Retention's later results.
- **RPT-4 Point-in-time queries.** Analysts must be able to answer "who owned client X on date D?". Example: `SELECT owner_id FROM v_client_owner_periods WHERE client_id = X AND D >= valid_from_utc AND (valid_to_utc IS NULL OR D < valid_to_utc)`.
- **RPT-5 Operational reports:** (a) Referral clients in hold with days remaining, (b) overdue handovers, (c) active exceptions with reason and approver, (d) handovers per day by type, (e) Retention book size per member, (f) admin corrections of Followup Owner (should be rare, so watch this one).
- **RPT-6 Data feed.** The fields in FR-16 and the views in FR-17 must be available in the PostgreSQL replica/schema used by Metabase and in the Zoho Analytics sync. Document the field definitions in the data dictionary.

## 15. Acceptance Criteria / Test Scenarios (Given-When-Then)

**AC-1 Lead auto-assignment**
Given a new lead is created
When lead distribution runs
Then the lead has a Followup Owner who is an active Sales CRE
And a history row `FOLLOWUP_OWNER_ASSIGNED` exists.

**AC-2 Referral conversion – hold starts**
Given a lead with a Referral lead source and Followup Owner = CRE-A
When CRE-A converts it at 2026-03-01 15:40 Asia/Dubai
Then the Client has Followup Owner = CRE-A, Converted By = CRE-A, Client Owner = CRE-A
And handover_status = `IN_SALES_HOLD`
And handover_due_at = 2026-03-31 00:00 Asia/Dubai (2026-03-30 20:00 UTC).

**AC-3 Referral – not handed over early**
Given the client from AC-2
When the handover job runs at 2026-03-30 23:59 Asia/Dubai
Then the Client Owner is still CRE-A.

**AC-4 Referral – handover at day 30**
Given the client from AC-2
When the handover job runs at or after 2026-03-31 00:00 Asia/Dubai
Then Client Owner = a Retention member selected by the configured strategy
And Previous Client Owner = CRE-A
And Followup Owner = CRE-A (unchanged) and Converted By = CRE-A (unchanged)
And handover_type = `REFERRAL_30D_AUTO`, handover_status = `HANDED_OVER`
And exactly one `CLIENT_OWNER` history row is written.

**AC-5 Other lead source – immediate handover**
Given a lead with lead source "Website" (non-Referral) and Followup Owner = CRE-B
When CRE-B converts it
Then Client Owner = a Retention member, Previous Client Owner = CRE-B
And Followup Owner = CRE-B and Converted By = CRE-B
And handover_type = `IMMEDIATE_ON_CONVERSION`, handover_at = conversion time.

**AC-6 Followup Owner immutability (non-admin)**
Given a converted client with Followup Owner = CRE-A
When a Sales Manager or Retention Lead tries to edit Followup Owner via UI or API
Then the change is rejected with a permission error and nothing changes.

**AC-7 Admin correction**
Given a converted client with Followup Owner = CRE-A
When a CRM Admin changes it to CRE-C without a reason
Then the save is rejected
When the admin supplies a reason
Then Followup Owner = CRE-C, Converted By remains unchanged, and an `ADMIN_CORRECTION` history row records old/new values, admin and reason.

**AC-8 Idempotent job**
Given 10 Referral clients are overdue
When the handover job is executed twice in parallel (or re-run after a crash)
Then each client has exactly one `REFERRAL_30D_AUTO` history row and one Retention owner.

**AC-9 Transient failure retry**
Given a DB timeout occurs while processing client X
When the job retries
Then client X is handed over on retry or on the next run, the failure is logged in `handover_job_items`, and other clients in the run are unaffected.

**AC-10 Job outage catch-up**
Given the job did not run for 2 days
When it next runs
Then all Referral clients whose due time has passed are handed over, and a monitoring alert was raised during the outage.

**AC-11 No eligible Retention user**
Given all Retention users are inactive or at capacity
When a client needs handover
Then the Client Owner is set to the unassigned queue user and Ops is alerted. The Client Owner is never null.

**AC-12 Exception override**
Given a Referral client in hold
When a Sales Manager sets an exception until 2026-05-15 with a reason
Then the job skips the client until that time
And when the exception ends, the next run hands the client over with handover_type `EXCEPTION_RELEASE`.

**AC-13 Exception without reason / unauthorised**
Given a CRE (not a manager) tries to set an exception, or a manager omits the reason
Then the action is rejected.

**AC-14 CRE deactivated during hold**
Given CRE-A is Client Owner of 5 Referral clients in hold
When an admin deactivates CRE-A
Then the system prompts for (or automatically performs) reassignment per EC-2
And Followup Owner and Converted By on all of CRE-A's clients remain CRE-A
And CRE-A remains available as a filter in CRE reports.

**AC-15 Retention member deactivated**
Given Retention member R1 owns 100 clients
When R1 is deactivated and clients are bulk-transferred
Then only Client Owner changes, each with a `USER_DEACTIVATION` history row, and Followup Owner is unchanged.

**AC-16 Mass transfer protection**
Given an admin runs mass transfer of records from CRE-A to CRE-D
Then converted clients' Followup Owner and Converted By are not changed.

**AC-17 Lead source corrected after conversion**
Given a Referral client in hold
When an admin corrects the lead source to a non-Referral value with a reason
Then lead_source_at_conversion history shows the correction, and the client is handed over on the next job run (per EC-5 / OI-9).

**AC-18 Reactivation**
Given an existing client converted by CRE-A becomes active again through a new lead worked by CRE-E
When the lead is linked to the existing client
Then Followup Owner remains CRE-A and a reactivation event records CRE-E (per OI-10).

**AC-19 Merge**
Given two duplicate clients converted by CRE-A (Jan) and CRE-F (Mar)
When they are merged
Then the survivor shows Followup Owner = CRE-A, conversion date = Jan, and a `MERGE` history row preserves CRE-F's values.

**AC-20 Timezone boundary**
Given conversions at 23:59 and 00:01 Asia/Dubai on consecutive dates
Then their due dates differ by exactly one day
And a conversion at 22:00 UTC (02:00 Dubai next day) gets a due date based on the Dubai date.

**AC-21 Backfill**
Given pre-go-live clients
When the backfill runs in dry-run mode
Then a reconciliation report lists counts per category (EC-1 a–e) without writing
And after approval the live run populates fields and writes one `BACKFILL` history row per client.

**AC-22 Point-in-time reporting**
Given a Referral client owned by CRE-A from 1 Mar to 31 Mar and by R2 from 31 Mar
When an analyst queries ownership on 15 Mar and on 10 Apr
Then the results are CRE-A and R2 respectively.

**AC-23 Notifications (if enabled)**
Given notifications are on
When any handover occurs
Then the new Retention owner and the converting CRE each receive exactly one notification. When notifications are off, none are sent and the handover still completes.

**AC-24 History immutability**
Given any history row
When the application role attempts UPDATE or DELETE
Then the database rejects it.

## 16. Industry Best-Practice Notes (from research)

- **Separate "who converted" from "who owns now."** Mature CRMs keep one record owner but record other people's roles on the account separately.\[2\] Salesforce Account Teams, for example, grant a user access to an account "in a named role, separate from ownership", with standard roles such as Sales Rep and Account Manager.\[14\]\[15\] Salesforce also keeps the converted lead, with a `ConvertedDate`, available for historical reporting even after the account is reassigned.\[16\]\[17\] This CR follows the same pattern with a locked Followup Owner plus a separate Client Owner.
- **Hunter-to-farmer handover needs explicit rules of engagement.** Alexander Group describes this as "bifurcated account ownership", in which the hunter "passes off newly acquired accounts to an AM (i.e., farmer)".\[18\] In its webinar "Coverage Model and Hunter/Farmer Concepts", Alexander Group frames the key design question as "how long does the hunter hold on or the account executive hold on to a brand new logo before passing it on to the account manager or the account team?" Its article "The Hunter/Farmer Model for Driving Growth" adds that "Leading companies have well defined rules of engagement and RACI to ensure customer handoff from AE to AM + CSM is seamless", and that the model "typically works best in select segments (mid-market/SMB) or verticals (financial technology and e-commerce)". The 30-day Referral hold is exactly such a rule and should be written down, configurable and reported on.
- **Attribution after handover is a known incentive issue.** Practitioners note that hunters want credit for clients they acquired while farmers claim the retention work. One suggested approach evaluates the hunter on whether the client was onboarded and "remained with the company for the first 90 days".\[19\] Keeping the Followup Owner permanent makes these hybrid measures possible later without rework.
- **Track owner fields with history.** Field-history guidance recommends enabling history tracking on the Owner field and on "other custom fields you have that represent some form of ownership".\[20\] HubSpot similarly exposes a per-record history of owners.\[21\] A typical history record holds field, old value, new value, who changed it and when.\[20\]\[22\] That is the model used in §10.2.
- **Don't depend on short vendor retention windows.** Salesforce's "Field History Tracking Overview" states: "When Field Audit Trail is turned off, Salesforce retains field history data for up to 18 months, and up to 24 months via the API." Zoho's "Monitoring Audit Log" help page says the Audit Log "displays all the actions performed by all users over the last 3 years", and Zoho's Export Audit Log API limits filtered exports to "up to 6 months (180 days) of audit log data". Because Nexora's CRM is in-house, ownership history should be kept in its own permanent table rather than in a rolling log.
- **Point-in-time reporting uses Type 2 history.** Slowly-changing-dimension Type 2 keeps every version with effective dates.\[3\]\[23\] Without it, metrics like "account owner at the time of deal close" become "inaccurate or impossible to compute correctly".\[24\] `v_client_owner_periods` (FR-17) is a Type 2 view of ownership.
- **Deactivation does not reassign records automatically.** Salesforce Help ("Deactivate Users") states: "Deactivating the user doesn't affect the records they owned until ownership is transferred to others." For Zoho CRM, a Zoho staff member confirmed in the Zoho Community: "The system will not prompt to transfer the data when a user is deactivated. This will happen only when are deleting a user and have activated Reporting Hierarchy in your CRM." Hence EC-2's explicit reassignment step.
- **Scheduled jobs must be idempotent.** Standard practice is at-least-once execution plus idempotent handlers, using a stable key "derived from job id plus the scheduled instant".\[10\] Transient failures are retried with exponential backoff and jitter, and bad input is not retried.\[12\]
- **Timezones:** store instants in UTC, store the business timezone as an IANA name (not a fixed offset), and compute business-day windows in that zone.\[7\]\[25\] Asia/Dubai is UTC+4 year-round with no daylight saving, which keeps the day-30 cutoff stable.\[9\]
- **Assignment method:** round robin gives equal counts but ignores workload. Load balancing evens workload but can flood a newly added rep. "Capping" (rotation that skips reps at capacity) is a middle path, which is the basis for the recommendation in §10.3.\[26\]\[27\]

## 17. Open Items for Confirmation

| ID | Question | Recommended default (used in this spec) |
|---|---|---|
| OI-1 | Is the 30-day hold **calendar** days or **business** days? | Calendar days (simpler, predictable). If business days: define weekend (Sat–Sun in UAE) and holiday calendar. |
| OI-2 | Which **timezone** defines "day 30", and is the cutoff start-of-day or exactly 30×24h after conversion? | `Asia/Dubai`, cutoff at 00:00 local on conversion date + 30 days. Alternative: exact timestamp + 720 hours. |
| OI-3 | How is the Retention owner chosen? | `ROUND_ROBIN_WITH_CAP` with unassigned-queue fallback. |
| OI-4 | Does "immediately" (non-referral) mean at **conversion** or at **first deposit/activation**? | At conversion. If activation: add status `PENDING_ACTIVATION`, CRE stays Client Owner until the first-deposit event from Ledger, then handover `IMMEDIATE_ON_ACTIVATION`. Define a timeout if no deposit arrives. |
| OI-5 | Is the Referral handover fully automatic, or does it need approval? | Fully automatic via scheduled job, with exceptions (FR-11). |
| OI-6 | Exact lead source values that count as "Referral team" (including any Brf/broker-referral sub-sources)? | Maintained in `config_referral_lead_sources`. Business to supply the list. |
| OI-7 | During the hold, is the Client Owner the **converting user** or the **Followup Owner** if they differ? | Followup Owner. |
| OI-8 | Backfill: should old Referral clients still with Sales be auto-moved on go-live, or reviewed first? | Dry-run report first, then auto-move after sign-off. |
| OI-9 | Lead source corrected after conversion: does the handover path follow the corrected value? | Yes, for Referral → Other (handover at next run). No automatic move back to Sales for Other → Referral. |
| OI-10 | Does reactivation of a dormant client earn separate CRE credit? | No new conversion credit; record a separate reactivation event. |
| OI-11 | Parent-child/duplicate accounts: which conversion is credited? | Earliest conversion on the surviving record. |
| OI-12 | Mapping of roles in §13 to existing CRM profiles; who approves hold exceptions? | Sales Manager approves; CRM Admin can override. |
| OI-13 | Should the CRE keep read access to clients after handover? | Read-only access to own converted clients (for continuity); no edit. |
| OI-14 | Notification channels and recipients (in-app, email; include Sales Manager/Retention Lead?) | In-app + email to new owner and CRE; managers via daily digest. |

## 18. Caveats

- Industry practices cited above come from vendor documentation and practitioner sources (Salesforce, HubSpot, Zoho, Alexander Group and engineering blogs). They are design guidance, not requirements of any regulator. Nexora's own compliance and data-retention policies take precedence for audit retention periods.
- Field names, enum values and role names are suggestions. Developers should map them to the existing schema and naming conventions, and confirm feasibility during estimation.
- The as-is section (§5) must be completed before the CR is approved. The size of the backfill (EC-1) depends on it.

## Sources

1. [CRM Data Analysis: Types, Metrics & How-To (2026 Guide)](https://www.default.com/post/crm-data-analysis)
2. [CRM Data Drift: How Record Ownership Breaks Salesforce](https://www.imarkinfotech.com/salesforce/blogs/crm-data-drift-how-record-ownership-breaks-salesforce/)
3. [Design a Table to Keep Historical Changes in Database - DEV Community](https://dev.to/zhiyueyi/design-a-table-to-keep-historical-changes-in-database-10fn)
4. [PostgreSQL Audit Trigger](https://hoop.dev/blog/postgresql-audit-trigger)
5. [The Ultimate Guide to PostgreSQL Data Change Tracking](https://exaspark.medium.com/the-ultimate-guide-to-postgresql-data-change-tracking-c3fa88779572)
6. [Round Robin Lead Routing vs Capacity](https://thatsgonna.help/blog/round-robin-vs-capacity-based-lead-routing)
7. [Scheduled Jobs and Time Zones: The Midnight Bug I Keep Seeing - DEV Community](https://dev.to/raxxostudios/scheduled-jobs-and-time-zones-the-midnight-bug-i-keep-seeing-1hgg)
8. [Time in Dubai Now (+04) — Live Clock](https://time.now/dubai/)
9. [Current Time in Dubai — GST Live Clock](https://worldtimeconverter.net/current-time/dubai)
10. [Design a Distributed Job Scheduler: System Design Walkthrough](https://copilotinterview.com/blog/design-a-job-scheduler)
11. [Job Scheduler Design — Preventing Duplicate Execution](https://thecodeforge.io/interview/design-job-scheduler-interview/)
12. [Cron Scheduling Best Practices](https://crontabsheet.com/guides/scheduling-best-practices.html)
13. [How to Design an Idempotent Job Queue](https://www.benmoataz.com/posts/idempotent-job-queue/)
14. [Account Team - Definition & Examples](https://salesforcedictionary.com/terms/account-team)
15. [Account Team Member - Definition & Examples](https://salesforcedictionary.com/terms/account-team-member)
16. [Report for leads given to sales people and converted leads](https://help.zoho.com/portal/en/community/topic/report-for-leads-given-to-sales-people-and-converted-leads?page=14)
17. [Salesforce Leads: Lifecycle Guide](https://www.salesforcetutorial.com/salesforce-leads/)
18. [What is the Hunter Farmer Sales Model?](https://www.alexandergroup.com/insights/technology-the-hunter-farmer-model-for-driving-growth/)
19. [Farming vs. Hunting](https://righthello.com/farming-vs-hunting/)
20. [The complete guide to Salesforce field history tracking](https://www.gradient.works/blog/salesforce-field-history-tracking)
21. [View and manage user access to a record](https://knowledge.hubspot.com/records/view-record-access)
22. [Field History Tracking Control](https://help.salesforce.com/s/articleView?language=en_US&id=xcloud.shr_field_history_tracking.htm&type=5)
23. [Slowly Changing Dimensions - Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/iq/plan/powertable-concept-slowly-changing-dimensions)
24. [Slowly Changing Dimensions: Types and Examples](https://www.luzmo.com/blog/slowly-changing-dimensions)
25. [Your Nightly Job Ran Twice on the DST Switch: Making Scheduled Jobs Timezone-Safe - DEV Community](https://dev.to/libme/your-nightly-job-ran-twice-on-the-dst-switch-making-scheduled-jobs-timezone-safe-32hn)
26. [Advanced round robin assignment](https://www.gradient.works/blog/how-to-make-round-robin-assignment-smarter)
27. [How to Set Up Round-Robin Assignment in Front (2026)](https://www.getmacha.com/blog/how-to-set-up-round-robin-in-front)
