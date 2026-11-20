# CampusQuest

A student-powered challenge community built with **HTML, CSS, vanilla JavaScript, Python Flask and SQLite**. The design combines a warm editorial landing page, floating pastel quest cards, a contribution-style activity garden, badge keepsakes (no XP) and a playful Quest Muse idea assistant.

## What is working in this MVP

- Student registration, sign-in and sign-out with hashed passwords.
- CSRF token checks for state-changing API requests.
- Login attempt throttling by IP + email.
- Demo login for local exploration (both UI and endpoint disabled when `APP_ENV=production` or `ENABLE_DEMO_LOGIN=0`).
- Challenge discovery across 11 activity categories: Tech, Creative, Social, Wellbeing, Sports, Career, Community, Sustainability, Culture, Games and Learning.
- Activity-format filtering: mini-projects, skill sprints, campus meetups, friendly competitions, creative jams, community actions, wellbeing habits, peer learning and campus exploration.
- A seeded activity library that is added safely to existing databases without overwriting student data.
- Join a challenge and check in once per campus-local day.
- Final work submission after the required check-ins, with moderator approval before the completion badge is awarded.
- Clear review outcomes: approved, changes requested (resubmittable), or rejected (closed with moderator-contact guidance).
- Daily check-in uniqueness protected by a database constraint and a write transaction.
- Badges for meaningful participation; no XP or points currency. The “First Step” badge is a low-friction participation marker; “Quest Finisher” requires moderated final-work approval.
- Student-created challenges enter a moderation queue before appearing publicly.
- Admin review screen for approving or declining proposed challenges.
- Squads with capacity checks, captain-reviewed join requests and one-squad-per-quest eligibility; joining a squad requires joining its challenge first.
- Peer kudos between teammates after both have participated in the linked quest.
- Student profile details with a separate opt-in for public profile visibility.
- Activity garden, weekly rotating quest spotlight and a friendly completion/badge leaderboard.
- Challenge reporting and an admin queue to review reports, submissions and community-created quests.
- Quest Muse uses curated rule-based recommendations. It is not a live generative AI integration.
- Light/dark theme toggle. The initial theme follows the device preference and a manual choice is saved in local storage.


## Expanded activity catalog

The challenge board now supports 11 categories: Tech, Creative, Social, Wellbeing, Sports, Career, Community, Sustainability, Culture, Games and Learning. Students can also filter by activity format: Mini-project, Skill sprint, Campus meetup, Friendly competition, Creative jam, Community action, Wellbeing habit, Peer learning or Campus exploration.

The database seeds 20 additional activity ideas on startup. This is additive and safe for an existing SQLite database: it checks challenge titles before inserting and does not replace user-created records. Existing databases are migrated automatically to add the `activity_type` column and its index.

When students create a community quest, they now choose a category, activity type, duration and whether the activity is solo or team-friendly. New community quests still enter the moderation queue.

## Run locally on Windows

1. Install Python 3.10 or newer.
2. Open this folder in VS Code.
3. Copy `.env.example` to `.env`. You can leave the local defaults for a first run.
4. Open Terminal → New Terminal.
5. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use Command Prompt and run `.venv\Scripts\activate.bat`.

6. Install dependencies:

   ```powershell
   py -m pip install -r requirements.txt
   ```

7. Start the application:

   ```powershell
   py app.py
   ```

8. Open `http://127.0.0.1:5000`.

SQLite is created automatically at `instance/campusquest.db`.

## Admin review setup

Do not grant admin privileges by checking a public registration email. Create the admin from the trusted local/server terminal instead:

```powershell
flask --app app create-admin --name "Your Name" --email "you@example.com"
```

The command securely prompts for an admin password (minimum 12 characters). It creates the account or promotes the existing account and sets the password. Sign in with it; the admin review section will appear. Only run this command yourself on the machine/server you control. Keep `.env` private and never upload it to GitHub.

## Demo account

- Email: `demo@campusquest.local`
- Password: `questdemo`

The demo login is for local exploration only. Both its button and backend endpoint are disabled automatically when `APP_ENV=production` or `ENABLE_DEMO_LOGIN=0`. Do not use the demo credentials as a real student's account.

## Important limitations before a public launch

This is a learning MVP, **not a security-audited production service**. Important remaining work:

- Add email verification and password reset.
- Add user reporting/blocking and extend the existing challenge/submission moderation audit workflow.
- Add broader consent/privacy controls for public profile details and team visibility. Leaderboard visibility is already opt-in.
- Add stronger content moderation for user-generated challenge descriptions.
- Expand the included smoke tests, then run the full suite against the actual deployment environment.
- Move production data to PostgreSQL and file storage to S3 when needed.
- Add backups, monitoring, operational error logging and HTTPS.
- Add an account deletion/export flow and a published privacy policy/community guidelines.
- Review the self-reported check-in model; check-ins are not proof that work was independently verified. Final-work approval is a moderator review, not automated verification of originality.
- Add a real AI provider only if it provides user value; keep credentials in the server environment.

## Production settings

Before production, set:

```env
APP_ENV=production
FLASK_DEBUG=0
SECRET_KEY=<long-random-secret>
COOKIE_SECURE=1
ENABLE_DEMO_LOGIN=0
APP_TIMEZONE=Asia/Kolkata
```

Use a production WSGI server (Waitress on Windows or Gunicorn on Linux), HTTPS, persistent storage and database backups. Never expose Flask's development server to the public internet.

## Future AWS path

- **EC2 or another suitable compute service:** host Flask.
- **RDS PostgreSQL:** managed production database.
- **S3:** proof uploads and profile images.
- **SES:** transactional emails.
- **CloudWatch:** logs, metrics and alarms.
- **IAM:** least-privilege service permissions.

Migrate from SQLite to PostgreSQL using a migration plan rather than copying the database file directly. Set AWS budgets/alerts and verify current prices before enabling services.

## AWS Elastic Beanstalk
See `AWS_DEPLOY_GUIDE.md` for the Windows deployment walkthrough and important HTTP-preview/data-persistence warnings.
