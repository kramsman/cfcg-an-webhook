# Plan: Email & Sheet Logic Redesign
_Branch: `change_email_append_logic`_

## Goal
Make test mode explicit and safe. No real volunteer should ever receive an email
during testing. No empty list should silently act as a flag.

---

## Current Problems

1. **Empty list as implicit test flag** — `ALLOWED_RECIPIENT_EMAILS` empty = production,
   non-empty = test. Easy to miss; no clear signal you're in test mode.

2. **Sheet written before email gate** — `_append_to_sheet()` is called on line 828 of
   `main.py`, *before* the `SEND_RECIPIENT_EMAILS` check on line 830. Test payloads
   pollute the real sheet.

3. **No startup validation** — `SEND_NOTIFICATION_EMAILS=true` with empty
   `NOTIFICATION_EMAIL_LIST` silently fails. Same risk for any flag+list pair.

4. **Unclear naming** — `NOTIFICATION_EMAIL_LIST` and `PAYLOAD_NOTIFICATION_LIST`
   sound similar but serve different audiences (error alerts vs. payload observers).

---

## Proposed Changes

### A. Replace `ALLOWED_RECIPIENT_EMAILS` with explicit `TEST_MODE` + `TEST_RECIPIENT_EMAILS`

**Remove:** `ALLOWED_RECIPIENT_EMAILS`

**Add:**
```
TEST_MODE = true/false
TEST_RECIPIENT_EMAILS = you@example.com,other@example.com
```

- `TEST_MODE=true` → welcome emails go only to `TEST_RECIPIENT_EMAILS`, never to real
  volunteers. Log: `"TEST MODE: would have sent to real@volunteer.com — redirecting to test list"`
- `TEST_MODE=false` → emails go to real volunteers as normal
- Startup error if `TEST_MODE=true` and `TEST_RECIPIENT_EMAILS` is empty

### B. Add startup validation for all flag+list pairs

In `config.py`, after loading all vars, add checks:
- `TEST_MODE=true` + empty `TEST_RECIPIENT_EMAILS` → `ValueError`
- `SEND_NOTIFICATION_EMAILS=true` + empty `ADMIN_ALERT_EMAILS` → `ValueError`
- `APPEND_TO_SHEET=true` + empty `GOOGLE_SHEET_ID` → `ValueError` (already partially done)

### C. Gate sheet append on test mode

When `TEST_MODE=true`, skip `_append_to_sheet()` (or write to a separate test sheet tab
controlled by a `TEST_SHEET_TAB` env var). Sheet and email should behave consistently.

Move the `_append_to_sheet()` call in `process_recipient()` to *after* all skip/gate
checks, not before.

### D. Rename lists for clarity

| Old | New | Purpose |
|-----|-----|---------|
| `ALLOWED_RECIPIENT_EMAILS` | *(removed)* | replaced by TEST_MODE |
| `NOTIFICATION_EMAIL_LIST` | `ADMIN_ALERT_EMAILS` | error/warning alerts |
| `PAYLOAD_NOTIFICATION_LIST` | `PAYLOAD_OBSERVER_EMAILS` | copy of every webhook payload |

---

## Files to Change

- `cfcg_an_webhook/config.py` — add TEST_MODE, TEST_RECIPIENT_EMAILS, startup validation,
  rename lists
- `cfcg_an_webhook/main.py` — update `_send_welcome_email()` test mode logic,
  move `_append_to_sheet()` call, update all list references
- `.env.example` — update variable names and add TEST_MODE examples
- `set-env-vars.sh` — update env var names
- `STATUS.md` — update testing section

---

## Logic Flow After Changes

```
process_recipient()
  1. attach_organizer_info()      — zip lookup; fail → notify + stop
  2. check email exists           — blank → stop
  3. CHECK_ALREADY_EMAILED?       — AN lookup; found + skip flag → stop
  4. CHECK_SHEET_FOR_EMAIL?       — sheet lookup; found → stop
  5. osdi type check              — send_email=False → stop
  6. SEND_RECIPIENT_EMAILS?       — false → stop (before sheet write)
  7. _append_to_sheet()           — ← MOVED: only runs if we're going to email
       └─ skip if TEST_MODE=true (unless TEST_SHEET_TAB configured)
  8. _send_welcome_email()
       └─ TEST_MODE=true?
            → send to TEST_RECIPIENT_EMAILS instead of real volunteer
            → log the redirect
       └─ TEST_MODE=false?
            → send to real volunteer
  9. UPDATE_GROUP_KEY?            — write region key back to AN
       └─ skip if TEST_MODE=true (don't modify real AN records during test)
```

---

## Status
- [ ] Not started — agreed on design, ready to implement
