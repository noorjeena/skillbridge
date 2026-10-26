# SkillBridge Repair Audit

## Batch 1 status

The original findings below describe the pre-repair state. Batch 1 repaired the migration/schema drift, added the migration for the existing Notification model, and changed matching services to use `Notification.NotificationType` as the sole notification enum. The database now includes the LearningSession, Conversation, Message, and Notification tables; all migrations are applied and model/migration state is aligned. Django system checks pass, and the full 116-test suite passes.

## Batch 2 status

Batch 2 added direction-scoped reviews with completed-session eligibility, learner/teacher validation, ownership controls, one-review uniqueness, rating/comment validation, teacher notifications, profile/match rating summaries, and admin moderation. Partnership and learning pages now expose direction plans, progress, assignments, sessions, and review actions without a visual redesign. The existing chat namespace was also registered after the partnership page revealed its missing URL integration. The full suite passes with 136 tests.

## Batch 3 status

Batch 3 completed the authenticated student notification page with pagination, recipient-scoped read/open actions, safe local-link redirects, unread navigation badge, and read-only admin inspection. Assignment creation/activation, submission, evaluation, session schedule/update/cancel/complete, review, match request/accept/reject, and chat message events use the existing `Notification.NotificationType` definitions. Re-evaluating an already evaluated submission does not emit a duplicate evaluation notification. Focused tests cover direct-exchange and one-way workflows through review notification delivery. Django checks and migration consistency checks pass; the full suite passes with 151 tests.

## Premium UI redesign — Batch 1 status

Added the shared CSS design system, authenticated responsive sidebar/top navigation shell, public marketing home presentation, and centered login/registration styling. Navigation links use existing routes; feature templates remain unchanged for later batches. Django checks pass and the full suite passes with 152 tests.

## Critical problems

1. Database and migration drift is active.
   - `python manage.py showmigrations --plan` shows pending migrations for `learning.0006_learningsession` and `matching.0002_conversation_message`.
   - `python manage.py makemigrations --check --dry-run` reports model drift for `accounts.Notification` and a matching index rename.
   - The SQLite database currently contains tables for the earlier models, but it does not include `matching_conversation`, `matching_message`, and `learning_learningsession`, which means the schema and the app code are out of sync.

2. Notification implementation is inconsistent and unsafe.
   - `accounts.models.Notification` defines `NotificationType`, but matching services call `User.NotificationType.*` instead of `Notification.NotificationType.*`.
   - This creates runtime attribute failures whenever a match request, message, assignment, or session notification is created.
   - The project therefore has at least one authoritative notification model, but the rest of the codebase is not using it consistently.

3. Review/rating functionality is missing.
   - There is no `Review` or `Rating` model, no review views, no profile aggregate, and no learning-direction review rule enforcement.
   - The app has session, assignment, and evaluation flows, but it cannot enforce the required learner-to-teacher review workflow after completed sessions.

4. Core learning/session tables are incomplete.
   - `LearningSession` exists in the code and migration file, but the database schema is missing the actual table.
   - This blocks scheduled sessions, session status updates, and session-linked learning workflows.

5. Chat and conversation tables are not fully migrated.
   - `Conversation` and `Message` models are defined and referenced by views/services, but the migration state shows them as incomplete.
   - This leaves the chat feature partially implemented and likely unusable unless migrations are repaired first.

## Medium problems

- The base application shell is still a generic Bootstrap template with inline styles instead of a SaaS-style dashboard layout.
- The navigation is not a proper application shell; it lacks a clear sidebar + top bar structure and active-page emphasis required for the admin/student experience.
- The project has the building blocks for matching, partnerships, learning directions, and assignments, but their workflows are not assembled into a cohesive student journey.
- Several view/service layers are present, but the project does not consistently enforce ownership and status checks across partnership, lesson, session, and notification flows.

## UI problems

- `templates/base.html` is a minimal Bootstrap navbar with a few links and inline CSS. It does not match the required premium SaaS design language.
- The dashboard, discover page, profile page, and partnership page are not yet structured as modern cards, panels, dashboards, or mobile-first layouts.
- The design currently reads like a CRUD app with generic pages rather than a professional peer-learning product.
- There is no distinct admin dashboard shell or modern responsive sidebar experience.

## Database/migration problems

- `accounts` has a `Notification` model in code, but no migration file for it.
- `matching` has pending chat-related migration state (`Conversation`, `Message`), but the SQLite DB is missing those tables.
- `learning` has `LearningSession` in code and migration file, but the DB does not include the actual table.
- `makemigrations --check --dry-run` confirms model drift in both the `accounts` and `matching` apps.
- Django system checks pass, which hides the fact that the live database schema is stale, so the project is not safe to trust in its current state.

## Business logic problems

- The underlying learning model is mostly present, but the real workflow is fragmented: matching, requests, partnerships, learning directions, learning plans, sessions, and chat are not yet consistently connected into a single validated lifecycle.
- Matching logic exists in `matching.services`, but the project still needs a clean repair pass to ensure direct exchange and one-way learning flows are consistently explained and enforced.
- Notification creation is not consistently tied to the actual notification model/type definitions.
- Review enforcement rules (completed session required, one review per learner/direction, role/ownership checks) are not present at all.

## Missing functionality

- No proper review/rating model or workflow.
- No robust admin dashboard built from real data.
- No modern app shell with left sidebar + top bar for desktop, and responsive drawer behavior for mobile.
- No professional dashboard showing profile completion, active partnerships, skills, upcoming sessions, unread messages, notifications, and recent activity backed by real DB records.
- No complete partnership workspace that centralizes partner data, skills, schedules, chat, assignments, and reviews.

## Recommended repair order

1. Repair database and migration state first.
   - Reconcile the pending `learning` and `matching` migrations.
   - Add the missing `Notification` migration.
   - Verify the database schema against the model state.

2. Fix notification model/type consistency.
   - Align all notification creation points with the single authoritative `Notification` model and `NotificationType` enum.
   - Ensure recipient authorization and unread/read tracking remain consistent.

3. Restore the missing learning/session/chat tables and validate constraints.
   - Apply the pending migration set with the actual database schema and confirm no model drift remains.

4. Repair the core workflow around matching → partnership → learning direction → sessions → assignments → evaluation.
   - Confirm both direct exchange and one-way learning behavior.
   - Ensure only accepted partnerships can create directions, lessons, sessions, assignments, and chat.

5. Add the missing review/rating system.
   - Implement review rules on `LearningDirection`, including one review per learner/direction and completion requirements.

6. Rebuild the application shell and dashboard UI.
   - Move to a modern SaaS-style layout and remove generic CRUD styling.

7. Validate the student and admin flows end-to-end with focused checks.
   - Run `manage.py check` after each batch repair and avoid broad, speculative refactors before the schema is stable.
