# Phase 10: Notifications - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 10-notifications
**Areas discussed:** Events & triggers, Recipients in login-only model, Invitation email vs NOTIF-01, Provider/templates/delivery

---

## Events & Triggers

**Q1: How should validation-ready and results-ready emails be triggered?**

| Option | Description | Selected |
|--------|-------------|----------|
| Manual admin CTA | Legacy parity: admin clicks the already-wired NextStepBanner buttons | ✓ |
| Automatic on status change | Backend sends when the intake hits the relevant status | |
| Both (auto + manual resend) | Automatic on transition plus a manual resend CTA | |

**Q2: How should reminder emails work?**

| Option | Description | Selected |
|--------|-------------|----------|
| Manual reminder button | Legacy parity: admin clicks "send reminder"; zero new infra | ✓ |
| Scheduled auto-reminders | Cloud Scheduler scans stale intakes and mails automatically | |
| Manual now, scheduled later | Ship manual; defer scheduled to a future phase | |

**Q3: Keep legacy `admin_validated` email (not listed in NOTIF-02)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Keep it | Automatic operator notification when the client validates | ✓ |
| Drop it | Admin can see the status change in the app | |

**Q4: When should the invitation email be sent?**

| Option | Description | Selected |
|--------|-------------|----------|
| Automatic on invite | invite_user sends the email as part of the flow | |
| Separate "send invite mail" action | Invite creates the account; a distinct action sends the email | ✓ |

---

## Recipients in Login-Only Model

**Q1: Who receives client-facing emails?**

| Option | Description | Selected |
|--------|-------------|----------|
| All active space members | Mail every active user-role membership | |
| Admin picks recipient(s) at send time | CTA opens a member picker | ✓ |
| Designated contact per space | Primary-contact flag on memberships | |

**Q2: Can the admin type a free email address (legacy override_email)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Members only | Non-members can't log in, so a free address is a dead end | ✓ |
| Members + free-text override | Legacy parity | |

**Q3: Where does `admin_validated` go?**

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable admin address | Single ops address from settings/env | ✓ |
| All superadmins | Mail every active superadmin | |

**Q4: Picker default + empty-space behavior?**

| Option | Description | Selected |
|--------|-------------|----------|
| Preselect all; block if empty | All members pre-checked; disabled CTA + invite hint when empty | ✓ |
| Preselect none; block if empty | Admin consciously picks each recipient | |
| You decide | Claude picks defaults during planning | |

---

## Invitation Email vs NOTIF-01

**Q1: Does the invite email carry the one-time Firebase set-password action link?**

| Option | Description | Selected |
|--------|-------------|----------|
| Action link allowed | NOTIF-01 targets never-expiring DATA bearer links; one-time auth-bootstrap link is exempt (interpretation documented) | ✓ |
| Pure notification only | "Go use Forgot password" — strictest reading, clunky first-run | |

**Q2: Where does "send invitation mail" live in the UI?**

| Option | Description | Selected |
|--------|-------------|----------|
| Both dialog + member list | InviteUserDialog success state + per-member resend action | ✓ |
| Invite dialog only | Only right after creating the invite | |
| Member list only | One place: the member row action | |

**Q3: Where does the invitee land after clicking the link?**

| Option | Description | Selected |
|--------|-------------|----------|
| Default Firebase page | Hosted handler + continue-URL; zero frontend work, generic look | |
| Custom in-app handler route | Branded route consumes the oobCode (confirmPasswordReset) | ✓ |

**Q4: Should the handler route serve both invite set-password and forgot-password?**

| Option | Description | Selected |
|--------|-------------|----------|
| Both flows, one route | Same Firebase operation; neutral wording | ✓ |
| Invite-only wording for now | Revisit when forgot-password entry point is added | |

---

## Provider, Templates & Delivery

**Q1: Which email provider?**

| Option | Description | Selected |
|--------|-------------|----------|
| Keep Resend | Domain already verified; key moves to Secret Manager | ✓ |
| SendGrid | New account + domain re-verification, no functional gain | |
| Gmail API / Workspace SMTP | OAuth scopes, send limits, deliverability headaches | |

**Q2: How are the email templates built?**

| Option | Description | Selected |
|--------|-------------|----------|
| Port legacy HTML to Jinja2 | Visual parity with existing Dutch mails, minus token links | ✓ |
| New minimal templates | Fresh simple notification mails | |
| You decide | Claude picks during planning | |

**Q3: How is the Agenic logo handled?**

| Option | Description | Selected |
|--------|-------------|----------|
| Frontend static asset URL | Logo in frontend/public/, referenced by deployed app URL | ✓ |
| Inline attachment (CID) | Embedded per mail; bigger payloads, client quirks | |
| No logo / text-only header | Cleanest deliverability, loses branding | |

**Q4: Send mechanics + failure UX?**

| Option | Description | Selected |
|--------|-------------|----------|
| Synchronous + toast | In-request Resend call; sent_at only on success; toast either way | ✓ |
| Background task + status poll | Fire-and-forget like AI skills; overkill, hides failures | |

---

## Claude's Discretion

- Mail module layout, endpoint shapes/naming, router placement
- Jinja2 setup and porting fidelity (recognizable parity, not pixel parity)
- Recipient-picker UI component choice (shadcn primitives)
- Resend fake in tests + denial-test coverage
- `admin_validated` failure handling (silent-log vs surfaced)
- Audit logging of sends
- Which app route each mail CTA points to (respecting role gating)

## Deferred Ideas

- Scheduled auto-reminders (Cloud Scheduler)
- Email i18n (Phase 11 or follow-up)
- Forgot-password entry-point UI on the login page
- Send-history visibility per intake
- `send-sales-mail` / `sales-friday-reminder` port (sales track)
