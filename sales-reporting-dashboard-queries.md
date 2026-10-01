# Sales Reporting Dashboard — raw SQL

Every query the **Sales → Reports** page (`/dashboard/sales/reports`) runs, one
section per tab. They were **captured from the running API** (TypeORM query
log, be branch `feat/client-assignment`, 2026-09-30) rather than retyped from the
source, so the SQL is exactly what Postgres gets. Each block has its bind
parameters filled in and runs as-is in psql/DBeaver against `centric`. All of them
were executed against the local DB to check.

## Before you run anything

Every query is pinned to **one portal and one IST window**. The values used here
are below. To point a query somewhere else, find-and-replace these:

| What | Value in this file | Where to get another |
|---|---|---|
| Project (Trading) | `019e7932-bf05-74f2-a4be-928b097a74a5` | `SELECT id, name FROM projects;` |
| Portal / whitelabel (Tradex 1) | `9d49d719-12e6-489d-89db-c55d325bdfad` | `SELECT id, name FROM portals ORDER BY name;` |
| Window start (inclusive) | `'2026-09-01 00:00+05:30'` | IST midnight of the first day |
| Window end (**exclusive**) | `'2026-10-01 00:00+05:30'` | IST midnight of the day AFTER the last day |

Conventions worth knowing before reading the numbers:

- **Dates are IST.** The API turns the picker's `from`/`to` (IST calendar days,
  `to` inclusive) into a UTC `[from, to)` pair. Every per-day bucket is
  `to_char(ts AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD')`.
- **A lead's date is `date_of_lead`, never `created_at`** (`created_at` is the row
  insert time, which for imported books is the import day).
- **Follow-up status is resolved, not read raw**:
  `COALESCE(CASE WHEN deposit_observed_at IS NOT NULL THEN <deposited> END, follow_up_disposition_id, <new_lead>)`.
  The app looks the two system ids up first; here they are inlined as subqueries
  on `lead_follow_up_dispositions.system_key`, so only the portal id needs changing.
- **Source 1** is the parent of the lead's source 2 (`sources s2` → `s2.parent_id` → `sources s1`).
  A NULL `s1` row is "Unsourced".
- **Agents are labelled by e-mail** (`users.email`), with `user_profiles.full_name` as the tooltip.
- **What the SQL does not do.** The API reshapes the rows in TypeScript: it pivots
  long-format rows into the sheet, computes every percentage, folds week/month
  totals out of daily rows, and runs the SOP/SLA verdicts. Where that changes what
  you'd see, the section says so.

## The shared filter bar → extra WHERE clauses

Every lead-based tab builds its WHERE with the same function
(`be/src/admin/sales-reports/lead-report-filters.ts` → `buildLeadFilters`). With
no filters set it is just:

```sql
l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
AND l.deleted_at IS NULL
AND l.date_of_lead >= '2026-09-01 00:00+05:30'
AND l.date_of_lead <  '2026-10-01 00:00+05:30'
```

Each filter on the bar appends one clause (all of them AND together):

| Filter | Clause appended |
|---|---|
| Source 1 | `l.source_two_id IN (SELECT s.id FROM sources s WHERE s.parent_id = ANY(ARRAY['<src1>']::uuid[]) AND s.portal_id = '<portal>')` |
| Source 2 | `l.source_two_id = ANY(ARRAY['<src2>']::uuid[])` |
| Unassigned only | `l.follow_up_owner_id IS NULL` (overrides both owner pickers) |
| Follow-up owner | `l.follow_up_owner_id = ANY(ARRAY['<user>']::uuid[])` |
| Owner + their team | `EXISTS (SELECT 1 FROM users uo JOIN admin_hierarchy_closure cls ON cls.descendant_external_id = uo.external_admin_id JOIN users ua ON ua.external_admin_id = cls.ancestor_external_id WHERE uo.id = l.follow_up_owner_id AND ua.id = ANY(ARRAY['<manager>']::uuid[]))` |
| (both owner pickers set) | the two above are OR'd: `(owner-clause OR team-clause)` |
| Follow-up status | `<resolved status expression> = ANY(ARRAY['<status>']::uuid[])` |
| Tag | `EXISTS (SELECT 1 FROM lead_tag_assignments lta WHERE lta.lead_id = l.id AND lta.tag_id = ANY(ARRAY['<tag>']::uuid[]))` |
| Advanced filter | the rule tree compiled by the shared filter engine, wrapped in `( … )` |

The Dialer tab is different: it filters `call_logs`, not leads (see its section).

---
## 1 · Follow-up & Connectivity

`?tab=follow-up-connectivity` — calls `GET /admin/follow-up-report` and
`GET /admin/lead-connectivity-report`. Like Conversion, **this tab keeps its own
date window, defaulting to today.** The other filters are shared.

### 1a. Follow-up status catalog (the pivot's columns)

```sql
-- Follow-up status catalog = the pivot's columns, in drag order.
-- system_key 'new_lead' / 'deposited' are the two resolved (non-disposition) states.
SELECT id, name, system_key, color, active, sort_order, deleted_at
  FROM lead_follow_up_dispositions
 WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
 ORDER BY sort_order, name;
```

### 1b. Follow-up status × Source 1

Long format, one row per (source 1, resolved status). The API pivots it: one
column per catalog row, a Grand Count row on top, Unsourced pinned last.

```sql
SELECT s1.id AS "rowId", s1.name AS "rowName", NULL::text AS "rowFullName",
          COALESCE(
  CASE WHEN l.deposit_observed_at IS NOT NULL
       THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
  l.follow_up_disposition_id,
  (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS "statusId",
          count(*) AS total
     FROM leads l
       LEFT JOIN sources s2 ON s2.id = l.source_two_id
       LEFT JOIN sources s1 ON s1.id = s2.parent_id
    WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
        AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND l.deleted_at IS NULL
        AND l.date_of_lead >= '2026-09-01 00:00+05:30'
        AND l.date_of_lead < '2026-10-01 00:00+05:30'
    GROUP BY 1, 2, 3, 4;
```

### 1c. Connectivity by Source 1

`calls` = dialled calls (`status NOT IN ('placing','call_failed')`); `connected` =
`answered_at IS NOT NULL`. It counts **every call ever placed** to a lead that
arrived in the window, not only calls made inside the window. The API computes
connectivity % = connected ÷ calls, reach % = leadsConnected ÷ leads,
called % = leadsCalled ÷ leads, avg talk = talkSeconds ÷ connected.

```sql
WITH cohort AS (
    SELECT l.id, l.source_two_id, l.follow_up_owner_id
      FROM leads l
         LEFT JOIN sources s2 ON s2.id = l.source_two_id
         LEFT JOIN sources s1 ON s1.id = s2.parent_id
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calls AS (
  SELECT cl.lead_id,
         count(*) FILTER (WHERE cl.status NOT IN ('placing', 'call_failed'))                   AS calls,
         count(*) FILTER (WHERE cl.answered_at IS NOT NULL)                 AS connected,
         coalesce(sum(cl.duration_seconds) FILTER (WHERE cl.answered_at IS NOT NULL), 0) AS talk_seconds
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   GROUP BY 1)
  SELECT s1.id AS "keyId", s1.name AS "keyName", NULL::text AS "keyFullName",
         count(*) AS leads,
    count(*) FILTER (WHERE c.calls > 0) AS "leadsCalled",
    count(*) FILTER (WHERE c.connected > 0) AS "leadsConnected",
    coalesce(sum(c.calls), 0) AS calls,
    coalesce(sum(c.connected), 0) AS connected,
    coalesce(sum(c.talk_seconds), 0) AS "talkSeconds"
    FROM cohort l
         LEFT JOIN calls c ON c.lead_id = l.id
         LEFT JOIN sources s2 ON s2.id = l.source_two_id
         LEFT JOIN sources s1 ON s1.id = s2.parent_id
   GROUP BY 1, 2, 3;
```

### 1d. Connectivity by agent (follow-up owner)

Same cohort and `calls` CTE; grouped on the owner instead of the source.

```sql
WITH cohort AS (
    SELECT l.id, l.source_two_id, l.follow_up_owner_id
      FROM leads l
         LEFT JOIN sources s2 ON s2.id = l.source_two_id
         LEFT JOIN sources s1 ON s1.id = s2.parent_id
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calls AS (
  SELECT cl.lead_id,
         count(*) FILTER (WHERE cl.status NOT IN ('placing', 'call_failed'))                   AS calls,
         count(*) FILTER (WHERE cl.answered_at IS NOT NULL)                 AS connected,
         coalesce(sum(cl.duration_seconds) FILTER (WHERE cl.answered_at IS NOT NULL), 0) AS talk_seconds
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   GROUP BY 1)
  SELECT l.follow_up_owner_id AS "keyId",
    u.email AS "keyName",
    up.full_name AS "keyFullName",
         count(*) AS leads,
    count(*) FILTER (WHERE c.calls > 0) AS "leadsCalled",
    count(*) FILTER (WHERE c.connected > 0) AS "leadsConnected",
    coalesce(sum(c.calls), 0) AS calls,
    coalesce(sum(c.connected), 0) AS connected,
    coalesce(sum(c.talk_seconds), 0) AS "talkSeconds"
    FROM cohort l
         LEFT JOIN calls c ON c.lead_id = l.id
         LEFT JOIN users u ON u.id = l.follow_up_owner_id
         LEFT JOIN user_profiles up ON up.user_id = u.id
   GROUP BY 1, 2, 3;
```

The **Called only** switch adds `WHERE c.calls > 0` to the final SELECT of both
queries, just before `GROUP BY`. It runs after the per-lead roll-up.

---
## 2 · Conversion

`?tab=conversion` — calls `GET /admin/lead-conversion-report` (the daily sheet) and
`GET /admin/actual-conversion-report` (the source × period matrix). **This tab keeps
its own date window, defaulting to today.** The rest of the filter bar is shared.
The other tabs default to the last 30 days.

It runs two clocks on purpose, so the two client columns on one row are
expected to disagree:

- **Leads arm**: leads that *arrived* on the day (`date_of_lead`). That gives Leads,
  Non sign up, Sign ups, Referrals, Deposited, and **Actual Conversion** (`cohortClients`, a
  cohort that arrived that day and converted at any time).
- **Funded arm**: leads that *converted* on the day (`converted_at`), whenever
  they arrived. That gives **Conversion (Aggregated)** (`clients`).

The screen shows Total Leads (`followUp`), Non Sign Up (`nonSignups`), Full Sign Up
(`signups`, meaning a customer is linked now, however late the sign-up), Conversion (Aggregated) =
`clients` and `clients ÷ followUp`, Actual Conversion = `cohortClients` and `cohortClients ÷ followUp`,
and Total Deposited (`deposited`). `halfSignups`/`fullSignups` (frozen at the arrival day) and
`referrals` are still returned but not displayed. The week and month rows are folded from these daily rows in the API.

### 2a. Daily conversion sheet

```sql
SELECT date, weekday,
           sum("followUp") AS "followUp",
           sum(clients) AS clients,
           sum("halfSignups") AS "halfSignups",
           sum("fullSignups") AS "fullSignups",
           sum(signups) AS signups,
           sum("nonSignups") AS "nonSignups",
           sum(referrals) AS referrals,
           sum("cohortClients") AS "cohortClients",
           sum(deposited) AS deposited
      FROM (
        SELECT to_char((l.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS date,
               to_char((l.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'Dy') AS weekday,
               count(*) AS "followUp",
   0 AS clients,
   count(*) FILTER (WHERE NOT (c.registered_at IS NOT NULL
  AND (c.registered_at AT TIME ZONE 'Asia/Kolkata')::date <= (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')::date)) AS "halfSignups",
   count(*) FILTER (WHERE (c.registered_at IS NOT NULL
  AND (c.registered_at AT TIME ZONE 'Asia/Kolkata')::date <= (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')::date)) AS "fullSignups",
   count(*) FILTER (WHERE l.customer_id IS NOT NULL) AS signups,
   count(*) FILTER (WHERE l.customer_id IS NULL) AS "nonSignups",
   count(*) FILTER (WHERE ctp.referrer_client_id IS NOT NULL) AS referrals,
   count(*) FILTER (WHERE l.converted_at IS NOT NULL) AS "cohortClients",
   count(*) FILTER (WHERE l.deposit_observed_at IS NOT NULL) AS deposited
          FROM leads l
        LEFT JOIN customers c ON c.id = l.customer_id
        LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = c.id
         WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
         AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
         AND l.deleted_at IS NULL
         AND l.date_of_lead >= '2026-09-01 00:00+05:30'
         AND l.date_of_lead < '2026-10-01 00:00+05:30'
         GROUP BY 1, 2
        UNION ALL
        SELECT to_char((l.converted_at AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS date,
               to_char((l.converted_at AT TIME ZONE 'Asia/Kolkata'), 'Dy') AS weekday,
               0 AS "followUp",
   count(*) FILTER (WHERE l.converted_at IS NOT NULL) AS clients,
   0 AS "halfSignups",
   0 AS "fullSignups",
   0 AS signups,
   0 AS "nonSignups",
   0 AS referrals,
   0 AS "cohortClients",
   0 AS deposited
          FROM leads l
         WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
         AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
         AND l.deleted_at IS NULL
         AND l.converted_at >= '2026-09-01 00:00+05:30'
         AND l.converted_at < '2026-10-01 00:00+05:30'
         GROUP BY 1, 2
      ) arms
     GROUP BY 1, 2
     ORDER BY 1 DESC;
```

### 2b. Conversion by Source 1 × day (the matrix)

Same two arms, keyed on source 1 as well. `fundedClients` is the funded-day
arm. The API folds the day rows into the week or month grain.

```sql
SELECT date, "sourceOneId", "sourceOneName",
           sum("followUp") AS "followUp",
           sum(clients) AS clients,
           sum(signups) AS signups,
           sum("nonSignups") AS "nonSignups",
           sum("halfSignups") AS "halfSignups",
           sum("fullSignups") AS "fullSignups",
           sum(referrals) AS referrals,
           sum(deposited) AS deposited,
           sum("fundedClients") AS "fundedClients"
      FROM (
        SELECT to_char((l.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS date,
   s1.id AS "sourceOneId",
   s1.name AS "sourceOneName",
               count(*) AS "followUp",
   count(*) FILTER (WHERE l.converted_at IS NOT NULL) AS clients,
   count(*) FILTER (WHERE l.customer_id IS NOT NULL) AS signups,
   count(*) FILTER (WHERE l.customer_id IS NULL) AS "nonSignups",
   count(*) FILTER (WHERE NOT (c.registered_at IS NOT NULL
  AND (c.registered_at AT TIME ZONE 'Asia/Kolkata')::date <= (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')::date)) AS "halfSignups",
   count(*) FILTER (WHERE (c.registered_at IS NOT NULL
  AND (c.registered_at AT TIME ZONE 'Asia/Kolkata')::date <= (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')::date)) AS "fullSignups",
   count(*) FILTER (WHERE ctp.referrer_client_id IS NOT NULL) AS referrals,
   count(*) FILTER (WHERE l.deposit_observed_at IS NOT NULL) AS deposited,
   0 AS "fundedClients"
          FROM leads l
        LEFT JOIN customers c ON c.id = l.customer_id
        LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = c.id
        LEFT JOIN sources s2 ON s2.id = l.source_two_id
        LEFT JOIN sources s1 ON s1.id = s2.parent_id
         WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
         AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
         AND l.deleted_at IS NULL
         AND l.date_of_lead >= '2026-09-01 00:00+05:30'
         AND l.date_of_lead < '2026-10-01 00:00+05:30'
         GROUP BY 1, 2, 3
        UNION ALL
        SELECT to_char((l.converted_at AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS date,
   s1.id AS "sourceOneId",
   s1.name AS "sourceOneName",
               0 AS "followUp",
   0 AS clients,
   0 AS signups,
   0 AS "nonSignups",
   0 AS "halfSignups",
   0 AS "fullSignups",
   0 AS referrals,
   0 AS deposited,
   count(*) AS "fundedClients"
          FROM leads l
        LEFT JOIN sources s2 ON s2.id = l.source_two_id
        LEFT JOIN sources s1 ON s1.id = s2.parent_id
         WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
         AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
         AND l.deleted_at IS NULL
         AND l.converted_at >= '2026-09-01 00:00+05:30'
         AND l.converted_at < '2026-10-01 00:00+05:30'
           AND l.converted_at IS NOT NULL
         GROUP BY 1, 2, 3
      ) arms
     GROUP BY 1, 2, 3
     ORDER BY 1 DESC;
```

---
## 3 · Lead Flow

`?tab=lead-flow` — calls `GET /admin/lead-flow-timing-report`. Rows are Source 1,
columns are the IST arrival hour (0–23).

- **Market hours** are fixed at Mon–Fri 09:15–15:30 IST, which is minutes 555–930. There is no exchange-holiday calendar.
- **Productive hours** come from query params `productiveFrom` / `productiveTo`, in minutes
  of the day. The default is **540 / 1080** (09:00–18:00). A window that wraps past midnight is handled
  by the `CASE`.
- The API computes non-productive as total − productive, plus the percentages and the peak hour.
- `conversions` counts leads that arrived in the cell and have converted at any time since.

```sql
SELECT s1.id AS "sourceOneId",
  s1.name AS "sourceOneName",
  EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int AS hour,
  count(*) AS total,
  count(*) FILTER (WHERE (EXTRACT(DOW FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int BETWEEN 1 AND 5
       AND (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) >= 555 AND (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 930)) AS market,
  count(*) FILTER (WHERE (CASE
       WHEN 540::int <= 1080::int
         THEN (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) >= 540::int AND (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 1080::int
         ELSE (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) >= 540::int OR  (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 1080::int
     END)) AS productive,
  count(*) FILTER (WHERE l.converted_at IS NOT NULL) AS conversions,
  count(*) FILTER (WHERE l.converted_at IS NOT NULL AND (EXTRACT(DOW FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int BETWEEN 1 AND 5
       AND (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) >= 555 AND (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 930)) AS "marketConversions",
  count(*) FILTER (WHERE l.converted_at IS NOT NULL AND (CASE
       WHEN 540::int <= 1080::int
         THEN (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) >= 540::int AND (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 1080::int
         ELSE (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) >= 540::int OR  (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 1080::int
     END)) AS "productiveConversions"
     FROM leads l
       LEFT JOIN sources s2 ON s2.id = l.source_two_id
       LEFT JOIN sources s1 ON s1.id = s2.parent_id
    WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
        AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND l.deleted_at IS NULL
        AND l.date_of_lead >= '2026-09-01 00:00+05:30'
        AND l.date_of_lead < '2026-10-01 00:00+05:30'
    GROUP BY 1, 2, 3;
```

---
## 4 · SOP & SLA

`?tab=lead-flow-sop` (the old tab key is kept so the Call SOP settings deep link
still works) — calls `GET /admin/lead-sop-report`.

**The SQL returns one row of facts per lead. It does not return the verdicts.**
The SLA verdicts (first-call timing and late-arrival nth call) and the SOP quota
verdict (met/short/exempt), along with the summary, sorting and paging, are
all computed in TypeScript (`be/src/admin/lead-sop-report/lead-sop-verdicts.ts`).

### 4a. Portal SOP settings

The query below inlines these values. On Tradex 1 they are business start 570,
business end 1110, working days = true, base calls 1, cadence 1 day.

```sql
SELECT * FROM lead_sop_settings WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad';
```

### 4b. Per-lead SOP facts

Parameters inlined from the settings above:

- `1110` is `business_end_minute`: a lead arriving after it starts its SOP clock the next morning.
- `570` is `business_start_minute`.
- `true` is `count_working_days`: weekends and `portal_holidays` don't age the lead.
- `1` / `1` are `default_base_calls` / `default_cadence_days`, used when no per-status `lead_sop_rules` row exists.

The calendar runs from the window start to **today (IST)**, not to the window end,
because an old lead keeps accruing quota.

```sql
WITH cohort AS (
    SELECT l.id, l.reference_no, l.date_of_lead, l.source_two_id,
           l.follow_up_owner_id, l.phone_calling_bidx, l.converted_at,
           l.first_assigned_at,
           COALESCE(
    CASE WHEN l.deposit_observed_at IS NOT NULL
         THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
    l.follow_up_disposition_id,
    (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS status_id,
           ((CASE
         WHEN (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) > 1110::int
           THEN date_trunc('day', (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')) + interval '1 day' + make_interval(mins => 570::int)
         WHEN (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 570::int
           THEN date_trunc('day', (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')) + make_interval(mins => 570::int)
         ELSE (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')
       END))::date AS sop_start_day
      FROM leads l
         LEFT JOIN sources s2 ON s2.id = l.source_two_id
         LEFT JOIN sources s1 ON s1.id = s2.parent_id
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calendar AS (
  SELECT d::date AS day,
         ((EXTRACT(DOW FROM d) NOT IN (0, 6) AND h.holiday_date IS NULL)
           OR NOT true::boolean) AS is_working,
         sum(CASE WHEN ((EXTRACT(DOW FROM d) NOT IN (0, 6) AND h.holiday_date IS NULL)
                         OR NOT true::boolean)
                  THEN 1 ELSE 0 END) OVER (ORDER BY d) AS wd
    FROM generate_series('2026-09-01'::date, (now() AT TIME ZONE 'Asia/Kolkata')::date::date, interval '1 day') d
    LEFT JOIN portal_holidays h
           ON h.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND h.holiday_date = d::date),
  cal_end AS (
  SELECT wd FROM calendar WHERE day = (now() AT TIME ZONE 'Asia/Kolkata')::date::date),
  call_ranks AS (
  SELECT cl.lead_id,
         cl.started_at,
         row_number() OVER (PARTITION BY cl.lead_id ORDER BY cl.started_at) AS rn
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   WHERE cl.status NOT IN ('placing', 'call_failed')),
  call_stats AS (
  SELECT lead_id,
         count(*) AS total_calls,
         min(started_at) AS first_call_at,
         max(started_at) AS last_call_at
    FROM call_ranks
   GROUP BY 1),
  callback AS (
  SELECT DISTINCT ON (cb.lead_id)
         cb.lead_id,
         cb.due_at,
         COALESCE(cbp.full_name, cbu.email) AS set_by
    FROM lead_callbacks cb
    JOIN cohort k ON k.id = cb.lead_id
    LEFT JOIN users cbu ON cbu.id = cb.created_by
    LEFT JOIN user_profiles cbp ON cbp.user_id = cbu.id
   WHERE cb.completed_at IS NULL
     AND cb.cancelled_at IS NULL
   ORDER BY cb.lead_id, cb.due_at)
  SELECT l.id,
    l.reference_no AS "referenceNo",
    to_char((l.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD HH24:MI') AS "arrivedAt",
    s1.name AS "sourceOneName",
    s2.name AS "sourceTwoName",
    u.email AS "ownerName",
    up.full_name AS "ownerFullName",
    l.follow_up_owner_id AS "ownerId",
    d.name AS "statusName",
    (l.phone_calling_bidx IS NOT NULL) AS "hasPhone",
    (l.converted_at IS NOT NULL) AS converted,
    (x.user_id IS NOT NULL) AS "ownerExcluded",
    COALESCE(r.exempt, false) AS "ruleExempt",
    COALESCE(r.day_one_only, false) AS "ruleDayOneOnly",
    r.late_arrival_nth_call AS "nthCall",
    days.elapsed AS "daysElapsed",
    (CASE
         WHEN l.phone_calling_bidx IS NULL THEN 0
         WHEN x.user_id IS NOT NULL THEN 0
         WHEN l.converted_at IS NOT NULL THEN 0
         WHEN COALESCE(r.exempt, false) THEN 0
         WHEN COALESCE(r.day_one_only, false) AND days.elapsed > 1 THEN 0
         WHEN days.elapsed <= 1 THEN COALESCE(r.base_calls, 1::int)
         WHEN COALESCE(r.cadence_days, 1::int) = 0
           THEN COALESCE(r.base_calls, 1::int)
         ELSE COALESCE(r.base_calls, 1::int)
              + floor((days.elapsed - 1) / COALESCE(r.cadence_days, 1::int))
       END)::int AS "requiredCalls",
    COALESCE(cs.total_calls, 0) AS "actualCalls",
    l.first_assigned_at AS "firstAssignedAt",
    cs.first_call_at AS "firstCallAt",
    cs.last_call_at AS "lastCallAt",
    nth.started_at AS "nthCallAt",
    cb.due_at AS "callbackDueAt",
    cb.set_by AS "callbackSetBy",
    (CASE
         WHEN (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) > 1110::int
           THEN date_trunc('day', (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')) + interval '1 day' + make_interval(mins => 570::int)
         WHEN (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) < 570::int
           THEN date_trunc('day', (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')) + make_interval(mins => 570::int)
         ELSE (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')
       END) AS "sopStartAt",
    (EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int * 60 + EXTRACT(MINUTE FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int) AS "arrivalMinute"
    FROM cohort l
         LEFT JOIN sources s2 ON s2.id = l.source_two_id
         LEFT JOIN sources s1 ON s1.id = s2.parent_id
         LEFT JOIN users u ON u.id = l.follow_up_owner_id
         LEFT JOIN user_profiles up ON up.user_id = u.id
         LEFT JOIN lead_follow_up_dispositions d ON d.id = l.status_id
         LEFT JOIN lead_sop_rules r
                ON r.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND r.disposition_id = l.status_id
         LEFT JOIN lead_sop_excluded_owners x
                ON x.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND x.user_id = l.follow_up_owner_id
         LEFT JOIN call_stats cs ON cs.lead_id = l.id
         LEFT JOIN call_ranks nth
                ON nth.lead_id = l.id AND nth.rn = r.late_arrival_nth_call
         LEFT JOIN callback cb ON cb.lead_id = l.id
         CROSS JOIN cal_end
         LEFT JOIN LATERAL (
           SELECT (cal_end.wd - c.wd + CASE WHEN c.is_working THEN 1 ELSE 0 END) AS elapsed
             FROM calendar c
            WHERE c.day = l.sop_start_day
         ) days ON true;
```

---
## 5 · Agent status

`?tab=follow-up-owner` — calls `GET /admin/follow-up-report/by-owner`. This is the
same status pivot as 1b, with rows by follow-up owner instead of by source. The
columns come from the same catalog as 1a.

```sql
SELECT l.follow_up_owner_id AS "rowId",
  u.email AS "rowName",
  up.full_name AS "rowFullName",
          COALESCE(
  CASE WHEN l.deposit_observed_at IS NOT NULL
       THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
  l.follow_up_disposition_id,
  (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS "statusId",
          count(*) AS total
     FROM leads l
       LEFT JOIN sources s2 ON s2.id = l.source_two_id
       LEFT JOIN sources s1 ON s1.id = s2.parent_id
       LEFT JOIN users u ON u.id = l.follow_up_owner_id
       LEFT JOIN user_profiles up ON up.user_id = u.id
    WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
        AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND l.deleted_at IS NULL
        AND l.date_of_lead >= '2026-09-01 00:00+05:30'
        AND l.date_of_lead < '2026-10-01 00:00+05:30'
    GROUP BY 1, 2, 3, 4;
```

---
## 6 · Conversions by agent

`?tab=agent-conversion` — calls `GET /admin/agent-conversion-report`.

- **Credit** = `COALESCE(converted_owner_id, follow_up_owner_id)`. Very few converted
  leads carry the explicit converter, so crediting it alone would give an empty sheet.
- **Two clocks.** Leads are *filtered* on `date_of_lead` (the shared bar) and *bucketed*
  on the IST day of `converted_at`. A column can therefore fall after the window end.
- The API folds the monthly sheet out of these daily rows.

```sql
SELECT COALESCE(l.converted_owner_id, l.follow_up_owner_id) AS "agentId",
  u.email AS "agentName",
  up.full_name AS "agentFullName",
  to_char((l.converted_at AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS date,
          count(*) AS conversions,
  count(*) FILTER (WHERE ctp.referrer_client_id IS NOT NULL) AS referrals
     FROM leads l
       LEFT JOIN sources s2 ON s2.id = l.source_two_id
       LEFT JOIN sources s1 ON s1.id = s2.parent_id
       LEFT JOIN users u ON u.id = COALESCE(l.converted_owner_id, l.follow_up_owner_id)
       LEFT JOIN user_profiles up ON up.user_id = u.id
       LEFT JOIN customers c ON c.id = l.customer_id
       LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = c.id
    WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
        AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND l.deleted_at IS NULL
        AND l.date_of_lead >= '2026-09-01 00:00+05:30'
        AND l.date_of_lead < '2026-10-01 00:00+05:30'
      AND l.converted_at IS NOT NULL
    GROUP BY 1, 2, 3, 4;
```

---
## 7 · Tag Status

`?tab=tag-status` (the code still calls it `trading-activity`) — calls
`GET /admin/trading-activity-report` (cards + strips) and
`GET /admin/trading-activity-report/rows` (the paged 20-column sheet). Every query
shares one `facts` CTE:

- **Trades** come from the `customer_trade_rollup` materialized view, which the worker
  refreshes every 5 minutes. They are never read from the raw `customer_activity_events` feed.
- **Call count** is `leads.call_count` (from `lead_calls`), because migrated Zoho history has no
  `call_logs`. **Connected** can only come from `call_logs.answered_at`.
- `Call_Status` is the resolved follow-up status. `Call_Outcome` is the disposition of the lead's **newest** `lead_calls` row.
- Converted leads are included.

The board's own filters (call state, migration, trade, deposit, call outcome,
trade-value band, last/first trade and first deposit dates) are applied as a
`WHERE` on `facts f` (shown here as `WHERE TRUE`, meaning no board filter set).

### 7a. Call-status strip + the three cards

One row per resolved status. The cards are the column sums: Ids = `leads`, and
the migrated, traded, deposited and not-called counts.

```sql
WITH cohort AS (
    SELECT l.id, l.customer_id, l.follow_up_owner_id,
         l.converted_owner_id, l.date_of_lead,
         coalesce(l.call_count, 0) AS call_count,
         COALESCE(
    CASE WHEN l.deposit_observed_at IS NOT NULL
         THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
    l.follow_up_disposition_id,
    (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS status_id
      FROM leads l
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calls AS (
  SELECT lc.lead_id,
         max(lc.created_at) AS last_call
    FROM lead_calls lc
    JOIN cohort k ON k.id = lc.lead_id
   GROUP BY 1),
  connected AS (
  SELECT cl.lead_id,
         count(*)               AS connected_count,
         max(cl.answered_at)    AS last_connected
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   WHERE cl.answered_at IS NOT NULL
   GROUP BY 1),
  trades AS (
  SELECT r.customer_id,
         r.trades,
         r.trade_value,
         r.last_leg  AS last_trade,
         r.first_leg
    FROM customer_trade_rollup r
    JOIN (SELECT DISTINCT customer_id FROM cohort
           WHERE customer_id IS NOT NULL) k ON k.customer_id = r.customer_id),
  facts AS (
  SELECT l.id,
         l.date_of_lead,
         l.status_id,
         ctp.arc_client_id,
         ctp.zynixx_client_id,
         fo.email                       AS followup_owner,
         fop.full_name                  AS followup_owner_name,
         co.email                       AS client_owner,
         cop.full_name                  AS client_owner_name,
         ctp.arc_client_id IS NOT NULL                    AS migrated,
         (ctp.first_trade_date IS NOT NULL OR t.trades > 0)                  AS traded,
         (ctp.first_deposit_date IS NOT NULL OR ctp.total_deposit > 0)               AS deposited,
         l.call_count,
         ca.last_call,
         coalesce(cn.connected_count, 0) AS connected_count,
         cn.last_connected,
         t.last_trade,
         coalesce(ctp.first_trade_date, t.first_leg) AS first_trade,
         ctp.first_deposit_amount,
         ctp.total_deposit,
         ctp.first_deposit_date,
         coalesce(t.trade_value, 0)     AS total_traded_value,
         (SELECT d.name FROM lead_calls lc
            JOIN lead_call_dispositions d ON d.id = lc.disposition_id
           WHERE lc.lead_id = l.id
           ORDER BY lc.created_at DESC, lc.id DESC
           LIMIT 1)                     AS call_outcome
    FROM cohort l
         LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = l.customer_id
         LEFT JOIN calls ca ON ca.lead_id = l.id
         LEFT JOIN connected cn ON cn.lead_id = l.id
         LEFT JOIN trades t ON t.customer_id = l.customer_id
         LEFT JOIN users fo ON fo.id = l.follow_up_owner_id
         LEFT JOIN user_profiles fop ON fop.user_id = fo.id
         LEFT JOIN users co ON co.id = l.converted_owner_id
         LEFT JOIN user_profiles cop ON cop.user_id = co.id)
  SELECT f.status_id AS "statusId",
         count(*) AS leads,
         count(*) FILTER (WHERE f.migrated) AS migrated,
         count(*) FILTER (WHERE f.traded) AS traded,
         count(*) FILTER (WHERE f.deposited) AS deposited,
         count(*) FILTER (WHERE f.call_count = 0) AS "notCalled"
    FROM facts f
   WHERE TRUE
   GROUP BY 1;
```

### 7b. Call-outcome strip

```sql
WITH cohort AS (
    SELECT l.id, l.customer_id, l.follow_up_owner_id,
         l.converted_owner_id, l.date_of_lead,
         coalesce(l.call_count, 0) AS call_count,
         COALESCE(
    CASE WHEN l.deposit_observed_at IS NOT NULL
         THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
    l.follow_up_disposition_id,
    (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS status_id
      FROM leads l
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calls AS (
  SELECT lc.lead_id,
         max(lc.created_at) AS last_call
    FROM lead_calls lc
    JOIN cohort k ON k.id = lc.lead_id
   GROUP BY 1),
  connected AS (
  SELECT cl.lead_id,
         count(*)               AS connected_count,
         max(cl.answered_at)    AS last_connected
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   WHERE cl.answered_at IS NOT NULL
   GROUP BY 1),
  trades AS (
  SELECT r.customer_id,
         r.trades,
         r.trade_value,
         r.last_leg  AS last_trade,
         r.first_leg
    FROM customer_trade_rollup r
    JOIN (SELECT DISTINCT customer_id FROM cohort
           WHERE customer_id IS NOT NULL) k ON k.customer_id = r.customer_id),
  facts AS (
  SELECT l.id,
         l.date_of_lead,
         l.status_id,
         ctp.arc_client_id,
         ctp.zynixx_client_id,
         fo.email                       AS followup_owner,
         fop.full_name                  AS followup_owner_name,
         co.email                       AS client_owner,
         cop.full_name                  AS client_owner_name,
         ctp.arc_client_id IS NOT NULL                    AS migrated,
         (ctp.first_trade_date IS NOT NULL OR t.trades > 0)                  AS traded,
         (ctp.first_deposit_date IS NOT NULL OR ctp.total_deposit > 0)               AS deposited,
         l.call_count,
         ca.last_call,
         coalesce(cn.connected_count, 0) AS connected_count,
         cn.last_connected,
         t.last_trade,
         coalesce(ctp.first_trade_date, t.first_leg) AS first_trade,
         ctp.first_deposit_amount,
         ctp.total_deposit,
         ctp.first_deposit_date,
         coalesce(t.trade_value, 0)     AS total_traded_value,
         (SELECT d.name FROM lead_calls lc
            JOIN lead_call_dispositions d ON d.id = lc.disposition_id
           WHERE lc.lead_id = l.id
           ORDER BY lc.created_at DESC, lc.id DESC
           LIMIT 1)                     AS call_outcome
    FROM cohort l
         LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = l.customer_id
         LEFT JOIN calls ca ON ca.lead_id = l.id
         LEFT JOIN connected cn ON cn.lead_id = l.id
         LEFT JOIN trades t ON t.customer_id = l.customer_id
         LEFT JOIN users fo ON fo.id = l.follow_up_owner_id
         LEFT JOIN user_profiles fop ON fop.user_id = fo.id
         LEFT JOIN users co ON co.id = l.converted_owner_id
         LEFT JOIN user_profiles cop ON cop.user_id = co.id)
  SELECT f.call_outcome AS outcome, count(*) AS leads
    FROM facts f
   WHERE TRUE
   GROUP BY 1;
```

### 7c. The sheet (page 1, 50 rows, default sort)

The sort column and direction come from `sortBy`/`sortDir`. The default is `date_of_lead DESC`.

```sql
WITH cohort AS (
    SELECT l.id, l.customer_id, l.follow_up_owner_id,
         l.converted_owner_id, l.date_of_lead,
         coalesce(l.call_count, 0) AS call_count,
         COALESCE(
    CASE WHEN l.deposit_observed_at IS NOT NULL
         THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
    l.follow_up_disposition_id,
    (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS status_id
      FROM leads l
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calls AS (
  SELECT lc.lead_id,
         max(lc.created_at) AS last_call
    FROM lead_calls lc
    JOIN cohort k ON k.id = lc.lead_id
   GROUP BY 1),
  connected AS (
  SELECT cl.lead_id,
         count(*)               AS connected_count,
         max(cl.answered_at)    AS last_connected
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   WHERE cl.answered_at IS NOT NULL
   GROUP BY 1),
  trades AS (
  SELECT r.customer_id,
         r.trades,
         r.trade_value,
         r.last_leg  AS last_trade,
         r.first_leg
    FROM customer_trade_rollup r
    JOIN (SELECT DISTINCT customer_id FROM cohort
           WHERE customer_id IS NOT NULL) k ON k.customer_id = r.customer_id),
  facts AS (
  SELECT l.id,
         l.date_of_lead,
         l.status_id,
         ctp.arc_client_id,
         ctp.zynixx_client_id,
         fo.email                       AS followup_owner,
         fop.full_name                  AS followup_owner_name,
         co.email                       AS client_owner,
         cop.full_name                  AS client_owner_name,
         ctp.arc_client_id IS NOT NULL                    AS migrated,
         (ctp.first_trade_date IS NOT NULL OR t.trades > 0)                  AS traded,
         (ctp.first_deposit_date IS NOT NULL OR ctp.total_deposit > 0)               AS deposited,
         l.call_count,
         ca.last_call,
         coalesce(cn.connected_count, 0) AS connected_count,
         cn.last_connected,
         t.last_trade,
         coalesce(ctp.first_trade_date, t.first_leg) AS first_trade,
         ctp.first_deposit_amount,
         ctp.total_deposit,
         ctp.first_deposit_date,
         coalesce(t.trade_value, 0)     AS total_traded_value,
         (SELECT d.name FROM lead_calls lc
            JOIN lead_call_dispositions d ON d.id = lc.disposition_id
           WHERE lc.lead_id = l.id
           ORDER BY lc.created_at DESC, lc.id DESC
           LIMIT 1)                     AS call_outcome
    FROM cohort l
         LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = l.customer_id
         LEFT JOIN calls ca ON ca.lead_id = l.id
         LEFT JOIN connected cn ON cn.lead_id = l.id
         LEFT JOIN trades t ON t.customer_id = l.customer_id
         LEFT JOIN users fo ON fo.id = l.follow_up_owner_id
         LEFT JOIN user_profiles fop ON fop.user_id = fo.id
         LEFT JOIN users co ON co.id = l.converted_owner_id
         LEFT JOIN user_profiles cop ON cop.user_id = co.id)
  SELECT f.id,
    to_char((f.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'DD/MM/YYYY HH12:MI AM') AS "createdTime",
    f.arc_client_id AS "arcClientId",
    f.zynixx_client_id AS "zynixxClientId",
    f.followup_owner AS "followupOwner",
    f.followup_owner_name AS "followupOwnerName",
    f.client_owner AS "clientOwner",
    f.client_owner_name AS "clientOwnerName",
    'In CRM'::text AS "crmStatus",
    CASE WHEN f.traded THEN 'Traded' ELSE 'Not Traded' END AS "tradeStatus",
    CASE WHEN f.migrated THEN 'Migrated' ELSE NULL END AS "migrationStatus",
    fud.name AS "callStatus",
    f.last_call AS "lastCall",
    f.call_count AS "callCount",
    f.last_connected AS "lastConnectedCall",
    f.connected_count AS "connectedCallCount",
    f.last_trade AS "lastTrade",
    f.first_deposit_amount AS "firstDeposit",
    f.total_deposit AS "totalDeposit",
    f.first_deposit_date AS "firstDepositDate",
    f.call_outcome AS "callOutcome",
    f.first_trade AS "firstTrade",
    f.total_traded_value AS "totalTradedValue"
    FROM facts f
         LEFT JOIN lead_follow_up_dispositions fud ON fud.id = f.status_id
   WHERE TRUE
   ORDER BY f.date_of_lead DESC NULLS LAST, f.id DESC
   LIMIT 50 OFFSET 0;
```

### 7d. The sheet's total row count

```sql
WITH cohort AS (
    SELECT l.id, l.customer_id, l.follow_up_owner_id,
         l.converted_owner_id, l.date_of_lead,
         coalesce(l.call_count, 0) AS call_count,
         COALESCE(
    CASE WHEN l.deposit_observed_at IS NOT NULL
         THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
    l.follow_up_disposition_id,
    (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) AS status_id
      FROM leads l
     WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
          AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
          AND l.deleted_at IS NULL
          AND l.date_of_lead >= '2026-09-01 00:00+05:30'
          AND l.date_of_lead < '2026-10-01 00:00+05:30'),
  calls AS (
  SELECT lc.lead_id,
         max(lc.created_at) AS last_call
    FROM lead_calls lc
    JOIN cohort k ON k.id = lc.lead_id
   GROUP BY 1),
  connected AS (
  SELECT cl.lead_id,
         count(*)               AS connected_count,
         max(cl.answered_at)    AS last_connected
    FROM call_logs cl
    JOIN cohort k ON k.id = cl.lead_id
   WHERE cl.answered_at IS NOT NULL
   GROUP BY 1),
  trades AS (
  SELECT r.customer_id,
         r.trades,
         r.trade_value,
         r.last_leg  AS last_trade,
         r.first_leg
    FROM customer_trade_rollup r
    JOIN (SELECT DISTINCT customer_id FROM cohort
           WHERE customer_id IS NOT NULL) k ON k.customer_id = r.customer_id),
  facts AS (
  SELECT l.id,
         l.date_of_lead,
         l.status_id,
         ctp.arc_client_id,
         ctp.zynixx_client_id,
         fo.email                       AS followup_owner,
         fop.full_name                  AS followup_owner_name,
         co.email                       AS client_owner,
         cop.full_name                  AS client_owner_name,
         ctp.arc_client_id IS NOT NULL                    AS migrated,
         (ctp.first_trade_date IS NOT NULL OR t.trades > 0)                  AS traded,
         (ctp.first_deposit_date IS NOT NULL OR ctp.total_deposit > 0)               AS deposited,
         l.call_count,
         ca.last_call,
         coalesce(cn.connected_count, 0) AS connected_count,
         cn.last_connected,
         t.last_trade,
         coalesce(ctp.first_trade_date, t.first_leg) AS first_trade,
         ctp.first_deposit_amount,
         ctp.total_deposit,
         ctp.first_deposit_date,
         coalesce(t.trade_value, 0)     AS total_traded_value,
         (SELECT d.name FROM lead_calls lc
            JOIN lead_call_dispositions d ON d.id = lc.disposition_id
           WHERE lc.lead_id = l.id
           ORDER BY lc.created_at DESC, lc.id DESC
           LIMIT 1)                     AS call_outcome
    FROM cohort l
         LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = l.customer_id
         LEFT JOIN calls ca ON ca.lead_id = l.id
         LEFT JOIN connected cn ON cn.lead_id = l.id
         LEFT JOIN trades t ON t.customer_id = l.customer_id
         LEFT JOIN users fo ON fo.id = l.follow_up_owner_id
         LEFT JOIN user_profiles fop ON fop.user_id = fo.id
         LEFT JOIN users co ON co.id = l.converted_owner_id
         LEFT JOIN user_profiles cop ON cop.user_id = co.id)
  SELECT count(*) AS total FROM facts f WHERE TRUE;
```

### 7e. Lookups

```sql
-- "Trade data refreshed at …" under the cards
SELECT max(refreshed_at) AS "refreshedAt" FROM customer_trade_rollup;

-- Call-outcome catalog (the outcome strip's columns)
SELECT id, name, active, sort_order, deleted_at
  FROM lead_call_dispositions
 WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
 ORDER BY sort_order, name;
```

---
## 8 · Dialer

`?tab=dialer` — calls `GET /admin/dialer-report`. This tab reads **`call_logs`**, not
leads: a call is counted when it was *placed* inside the window (`started_at`),
whoever it went to. The team leader is the agent's `admin_reports_to` manager. The API
computes connect %, average talk, calls per hour and the per-active-day averages.

The dialer's own filters append to the `WHERE` of every query below:

| Filter | Clause |
|---|---|
| Call type = Customer | `AND cl.lead_id IS NULL` |
| Call type = Lead | `AND cl.lead_id IS NOT NULL` |
| Team leader | `AND tl.id = '<user>'` |
| Agent | `AND cl.agent_user_id = ANY(ARRAY['<user>']::uuid[])` |

(Call type = All, the default, adds nothing. That is what's shown below.)

### 8a. Per-agent metrics

```sql
SELECT cl.agent_user_id AS "agentId",
        u.email AS "agentName",
        up.full_name AS "agentFullName",
        tl.id AS "teamLeaderId",
        tl.email AS "teamLeaderName",
        tlp.full_name AS "teamLeaderFullName",
        count(*) AS calls,
        count(DISTINCT COALESCE(cl.lead_id, cl.customer_id)) AS "uniqueDials",
        count(*) FILTER (WHERE cl.answered_at IS NOT NULL) AS connected,
        COALESCE(
      SUM(EXTRACT(EPOCH FROM (cl.ended_at - cl.answered_at)))
        FILTER (WHERE cl.answered_at IS NOT NULL AND cl.ended_at IS NOT NULL),
      0) AS "talkSec",
        count(DISTINCT date_trunc('day', (cl.started_at AT TIME ZONE 'Asia/Kolkata'))) AS "activeDays",
        count(DISTINCT date_trunc('hour', (cl.started_at AT TIME ZONE 'Asia/Kolkata'))) AS "activeHours",
        count(DISTINCT (date_trunc('day', (cl.started_at AT TIME ZONE 'Asia/Kolkata')), COALESCE(cl.lead_id, cl.customer_id))) AS "dailyUniqueDials"
   FROM call_logs cl
   JOIN users u ON u.id = cl.agent_user_id
      LEFT JOIN user_profiles up ON up.user_id = u.id
      LEFT JOIN admin_reports_to art
             ON art.member_external_admin_id = u.external_admin_id
      LEFT JOIN users tl ON tl.external_admin_id = art.manager_external_admin_id
      LEFT JOIN user_profiles tlp ON tlp.user_id = tl.id
  WHERE cl.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND cl.started_at >= '2026-09-01 00:00+05:30'
        AND cl.started_at < '2026-10-01 00:00+05:30'
        AND cl.status NOT IN ('placing', 'call_failed')
  GROUP BY 1, 2, 3, 4, 5, 6;
```

### 8b. Disposition split per agent

Lead calls take their disposition from `lead_calls`. Customer calls take it from
the newest `interactions.disposition` on that call and appear as
`customer:<key>`.

```sql
WITH w AS (
     SELECT cl.id, cl.agent_user_id, cl.lead_id
       FROM call_logs cl
       JOIN users u ON u.id = cl.agent_user_id
       LEFT JOIN user_profiles up ON up.user_id = u.id
       LEFT JOIN admin_reports_to art
              ON art.member_external_admin_id = u.external_admin_id
       LEFT JOIN users tl ON tl.external_admin_id = art.manager_external_admin_id
       LEFT JOIN user_profiles tlp ON tlp.user_id = tl.id
      WHERE cl.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
         AND cl.started_at >= '2026-09-01 00:00+05:30'
         AND cl.started_at < '2026-10-01 00:00+05:30'
         AND cl.status NOT IN ('placing', 'call_failed')
            ),
   ci AS (
     SELECT DISTINCT ON (i.call_log_id) i.call_log_id, i.disposition
       FROM interactions i
       JOIN w ON w.id = i.call_log_id AND w.lead_id IS NULL
      WHERE i.disposition IS NOT NULL
      ORDER BY i.call_log_id, i.dispositioned_at DESC NULLS LAST, i.created_at DESC)
  SELECT w.agent_user_id AS "agentId",
         COALESCE(lc.disposition_id::text,
                  'customer:' || ci.disposition) AS "dispositionId",
         COALESCE(d.name, ci.disposition) AS "dispositionName",
         count(*) AS calls
    FROM w
    LEFT JOIN lead_calls lc ON lc.call_log_id = w.id
    LEFT JOIN lead_call_dispositions d ON d.id = lc.disposition_id
    LEFT JOIN ci ON ci.call_log_id = w.id
   GROUP BY 1, 2, 3;
```

### 8c. Unique dials per team leader + grand total

`ROLLUP` gives one row per team leader plus the total row (`isTotal = 1`). A unique
dial is counted once per leader, so it can't be summed from the agent rows.

```sql
SELECT GROUPING(tl.id) AS "isTotal",
        tl.id AS "teamLeaderId",
        count(DISTINCT COALESCE(cl.lead_id, cl.customer_id)) AS "uniqueDials"
   FROM call_logs cl
   JOIN users u ON u.id = cl.agent_user_id
      LEFT JOIN user_profiles up ON up.user_id = u.id
      LEFT JOIN admin_reports_to art
             ON art.member_external_admin_id = u.external_admin_id
      LEFT JOIN users tl ON tl.external_admin_id = art.manager_external_admin_id
      LEFT JOIN user_profiles tlp ON tlp.user_id = tl.id
  WHERE cl.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND cl.started_at >= '2026-09-01 00:00+05:30'
        AND cl.started_at < '2026-10-01 00:00+05:30'
        AND cl.status NOT IN ('placing', 'call_failed')
  GROUP BY ROLLUP(tl.id);
```

### 8d. Lead disposition catalog (the split's columns)

```sql
SELECT d.id, d.name
   FROM lead_call_dispositions d
  WHERE d.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
    AND d.deleted_at IS NULL
  ORDER BY d.sort_order, d.name;
```

---

## Drill-down drawers (clicking any number)

Every clickable cell on tabs 1, 2, 3, 5 and 6 opens the same lead drawer
(`be/src/admin/sales-reports/lead-drilldown.service.ts`). It takes the tab's WHERE
from above, ANDs on the **cell's bucket predicate** and the cell's row/column key,
and runs two queries: a page query and a lean count query. They share the same predicate, so the
drawer's total always equals the number clicked. The Dialer and SOP & SLA tabs have no lead drawer.

### Example: Conversion tab → "Conversion (Aggregated)" cell for 15 Sep

The page (25 rows):

```sql
SELECT l.id,
   l.reference_no AS "referenceNo",
   COALESCE(NULLIF(btrim(l.client_name), ''), c.name) AS "clientName",
   ctp.zynixx_client_id AS "clientId",
   ctp.referrer_client_id AS "parentClientId",
   to_char((l.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS "dateOfLead",
   s1.id AS "sourceOneId",
   s1.name AS "sourceOneName",
   s2.id AS "sourceTwoId",
   s2.name AS "sourceTwoName",
   l.follow_up_owner_id AS "ownerId",
   u.email AS "ownerName",
   up.full_name AS "ownerFullName",
   fud.name AS "statusName",
   COALESCE(l.call_count, 0) AS "callCount",
   (SELECT MAX(lc.created_at) FROM lead_calls lc
     WHERE lc.lead_id = l.id) AS "lastCallAt",
   l.converted_at AS "convertedAt",
   (l.customer_id IS NOT NULL) AS "signedUp",
   (c.registered_at IS NOT NULL
  AND (c.registered_at AT TIME ZONE 'Asia/Kolkata')::date <= (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')::date) AS "fullSignup"
        FROM leads l
        LEFT JOIN sources s2 ON s2.id = l.source_two_id
        LEFT JOIN sources s1 ON s1.id = s2.parent_id
        LEFT JOIN customers c ON c.id = l.customer_id
        LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = c.id
        LEFT JOIN users u ON u.id = l.follow_up_owner_id
        LEFT JOIN user_profiles up ON up.user_id = u.id
        LEFT JOIN lead_follow_up_dispositions fud ON fud.id = COALESCE(
   CASE WHEN l.deposit_observed_at IS NOT NULL
        THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
   l.follow_up_disposition_id,
   (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid)
       WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
         AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
         AND l.deleted_at IS NULL
         AND l.converted_at >= '2026-09-01 00:00+05:30'
         AND l.converted_at < '2026-10-01 00:00+05:30'
         AND l.converted_at IS NOT NULL
         AND (l.converted_at AT TIME ZONE 'Asia/Kolkata')::date = '2026-09-15'::date
       ORDER BY l.converted_at DESC, l.id DESC
       LIMIT 25 OFFSET 0;
```

The count:

```sql
SELECT count(*) AS total
   FROM leads l
   LEFT JOIN sources s2 ON s2.id = l.source_two_id
   LEFT JOIN sources s1 ON s1.id = s2.parent_id
  WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
    AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
    AND l.deleted_at IS NULL
    AND l.converted_at >= '2026-09-01 00:00+05:30'
    AND l.converted_at < '2026-10-01 00:00+05:30'
    AND l.converted_at IS NOT NULL
    AND (l.converted_at AT TIME ZONE 'Asia/Kolkata')::date = '2026-09-15'::date;
```

### Example: Follow-up tab → the "New Lead" column total

```sql
SELECT l.id,
  l.reference_no AS "referenceNo",
  COALESCE(NULLIF(btrim(l.client_name), ''), c.name) AS "clientName",
  ctp.zynixx_client_id AS "clientId",
  ctp.referrer_client_id AS "parentClientId",
  to_char((l.date_of_lead AT TIME ZONE 'Asia/Kolkata'), 'YYYY-MM-DD') AS "dateOfLead",
  s1.id AS "sourceOneId",
  s1.name AS "sourceOneName",
  s2.id AS "sourceTwoId",
  s2.name AS "sourceTwoName",
  l.follow_up_owner_id AS "ownerId",
  u.email AS "ownerName",
  up.full_name AS "ownerFullName",
  fud.name AS "statusName",
  COALESCE(l.call_count, 0) AS "callCount",
  (SELECT MAX(lc.created_at) FROM lead_calls lc
    WHERE lc.lead_id = l.id) AS "lastCallAt",
  l.converted_at AS "convertedAt",
  (l.customer_id IS NOT NULL) AS "signedUp"
       FROM leads l
       LEFT JOIN sources s2 ON s2.id = l.source_two_id
       LEFT JOIN sources s1 ON s1.id = s2.parent_id
       LEFT JOIN customers c ON c.id = l.customer_id
       LEFT JOIN customer_trading_profiles ctp ON ctp.customer_id = c.id
       LEFT JOIN users u ON u.id = l.follow_up_owner_id
       LEFT JOIN user_profiles up ON up.user_id = u.id
       LEFT JOIN lead_follow_up_dispositions fud ON fud.id = COALESCE(
  CASE WHEN l.deposit_observed_at IS NOT NULL
       THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
  l.follow_up_disposition_id,
  (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid)
      WHERE l.project_id = '019e7932-bf05-74f2-a4be-928b097a74a5'
        AND l.portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad'
        AND l.deleted_at IS NULL
        AND l.date_of_lead >= '2026-09-01 00:00+05:30'
        AND l.date_of_lead < '2026-10-01 00:00+05:30'
        AND COALESCE(
  CASE WHEN l.deposit_observed_at IS NOT NULL
       THEN (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'deposited')::uuid END,
  l.follow_up_disposition_id,
  (SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')::uuid) = ANY(ARRAY[(SELECT id FROM lead_follow_up_dispositions WHERE portal_id = '9d49d719-12e6-489d-89db-c55d325bdfad' AND system_key = 'new_lead')]::uuid[])
      ORDER BY l.date_of_lead DESC, l.id DESC
      LIMIT 25 OFFSET 0;
```

### Bucket predicates

To reproduce any other cell, swap in its bucket predicate and its key:

| Tab | Bucket | Predicate ANDed on |
|---|---|---|
| Conversion (sheet + matrix) | `all` | `TRUE` |
| | `clients` / `funded` | `l.converted_at IS NOT NULL`, on the **`converted_at` clock** (window and day are on `converted_at`) |
| | `cohort_clients` | `l.converted_at IS NOT NULL` (on the `date_of_lead` clock) |
| | `signups` / `non_signup` | `l.customer_id IS NOT NULL` / `IS NULL` |
| | `full` / `half` | `c.registered_at IS NOT NULL AND (c.registered_at AT TIME ZONE 'Asia/Kolkata')::date <= (l.date_of_lead AT TIME ZONE 'Asia/Kolkata')::date` / `NOT (…)`. Needs `LEFT JOIN customers c ON c.id = l.customer_id` in the count query as well |
| | `referrals` | `EXISTS (SELECT 1 FROM customer_trading_profiles … referrer_client_id IS NOT NULL)` |
| | `deposited` | `l.deposit_observed_at IS NOT NULL` |
| | cell key | day: `(… AT TIME ZONE 'Asia/Kolkata')::date = '<YYYY-MM-DD>'`. Week: `>= '<weekStart>' AND < '<weekStart>'::date + 7`. Month: `date_trunc('month', …)::date = '<YYYY-MM>-01'`. The matrix adds the source 1 of the row |
| Follow-up / Agent status | status column | `<resolved status> = ANY(ARRAY['<status>']::uuid[])`, plus the row's source 1 (or `s1.id IS NULL` for Unsourced) or the row's owner |
| Connectivity | `leads` | `TRUE` |
| | `called` | `EXISTS (SELECT 1 FROM call_logs cl WHERE cl.lead_id = l.id AND cl.status NOT IN ('placing','call_failed'))` |
| | `connected` | `EXISTS (SELECT 1 FROM call_logs cl WHERE cl.lead_id = l.id AND cl.answered_at IS NOT NULL)` |
| | `never_called` | `NOT EXISTS (…the called predicate…)` |
| Lead Flow | `market` / `productive` / `nonProductive` | the market-hours / productive-hours expressions from §3 (`NOT` for non-productive), plus `EXTRACT(HOUR FROM (l.date_of_lead AT TIME ZONE 'Asia/Kolkata'))::int = <hour>` for an hour cell |
| | `conversions`, `marketConversions`, … | the same, ANDed with `l.converted_at IS NOT NULL` |
| Conversions by agent | `conversions` | `l.converted_at IS NOT NULL` + credit agent = `<user>` (or `IS NULL` for Unassigned) + `to_char(l.converted_at AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD'` or `'YYYY-MM') = '<period>'` |
| | `referrals` | the above AND `EXISTS (SELECT 1 FROM customer_trading_profiles ctp2 WHERE ctp2.customer_id = l.customer_id AND ctp2.referrer_client_id IS NOT NULL)` |

Drawer **Export** runs the page query with no `LIMIT`, capped at 50,000 rows.
The per-tab **Export** buttons call the same report queries as the screen, so a
workbook can't disagree with what's shown.
