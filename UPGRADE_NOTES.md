# CampusQuest upgrade notes

This bundle includes the applied challenge, community, trust and retention improvements.

## Main additions and fixes

- Final submissions now enter a moderator review queue. Approval completes the quest and awards the Quest Finisher badge.
- “Needs changes” sends the participant back to final submission with reviewer feedback. “Reject” closes that submission and directs the participant to contact a moderator.
- Moderators cannot review their own final submissions.
- Check-ins are only accepted while a challenge is approved and active for the participant.
- Reporting a challenge and hiding it closes active/ready-to-submit participation on that challenge.
- Squad joining uses captain-reviewed requests; the old `/join` endpoint now creates a request rather than bypassing approval.
- A student can join only one squad for a given quest, and squad requests are revalidated when the captain accepts.
- Peer kudos require both students to be team members and have participated in the linked quest.
- Profile visibility is opt-in; leaderboard visibility remains a separate opt-in.
- The “Steady Spark” badge now counts distinct check-in days, not profile edits or other activity events.
- Light/dark appearance preference is stored locally and initially follows the device preference.

## Updating an existing local installation

1. Back up your existing `instance/campusquest.db` and `.env` file.
2. Extract this bundle into a new folder.
3. If you want to preserve existing local users and quests, copy your backed-up database into the new folder's `instance/campusquest.db` path (create the `instance` folder first). Otherwise, a new database will be created automatically.
4. Copy your existing `.env` into the new folder. Keep the same `SECRET_KEY` for an existing installation. Do not commit `.env` to GitHub.
5. Install requirements and start the app using the README instructions.
6. The application runs lightweight schema migrations on startup. Still keep the backup until you have checked login, profiles, quests and teams.

## Verification notes

Python and JavaScript syntax checks passed. The SQLite schema, migration statements and selected team SQL queries were validated. The Jinja template parsed, the HTML had no duplicate IDs, and the CSS parser reported no syntax errors.

The full Flask integration tests were not executed in the build environment because Flask was unavailable there and package downloads could not be completed. Run `py -m pip install -r requirements.txt` followed by `py -m unittest discover -s tests -v` on your laptop.

This remains an MVP. Add email verification, password reset, account deletion/export, user block/report, production backups, persistent production storage, HTTPS and security testing before a broad public launch.
