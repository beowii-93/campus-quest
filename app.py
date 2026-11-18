from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from pathlib import Path
from functools import wraps
from contextlib import contextmanager

from flask import Flask, jsonify, render_template, request, session
import click
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    # Environment variables can also be provided directly by the shell/hosting service.
    pass

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.environ.get("DATABASE_PATH", INSTANCE_DIR / "campusquest.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
IS_PRODUCTION = os.environ.get("APP_ENV", "development").lower() == "production"
APP_TIMEZONE = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Kolkata"))
SECRET_KEY = os.environ.get("SECRET_KEY")
if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")

app = Flask(__name__)
CHALLENGE_CATEGORIES = {
    "Tech", "Creative", "Social", "Wellbeing", "Sports", "Career",
    "Community", "Sustainability", "Culture", "Games", "Learning",
}
ACTIVITY_TYPES = {
    "Mini-project", "Skill sprint", "Campus meetup", "Friendly competition",
    "Creative jam", "Community action", "Wellbeing habit", "Peer learning",
    "Campus exploration",
}

app.config.update(
    SECRET_KEY=SECRET_KEY or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # For the first Elastic Beanstalk HTTP smoke test, set COOKIE_SECURE=0.
    # After configuring HTTPS, set COOKIE_SECURE=1. Production defaults to secure cookies.
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1" if IS_PRODUCTION else "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    JSON_SORT_KEYS=False,
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def app_today():
    """Use the campus timezone consistently for activity/check-in dates."""
    return datetime.now(APP_TIMEZONE).date()


def get_csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_template_helpers():
    demo_enabled = (not IS_PRODUCTION) and os.environ.get("ENABLE_DEMO_LOGIN", "1") == "1"
    return {"csrf_token": get_csrf_token, "demo_enabled": demo_enabled}


@app.before_request
def protect_state_changing_requests():
    # The token is tied to the signed Flask session and is sent by the same-origin frontend.
    get_csrf_token()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf_token", "")
        if not supplied or not secrets.compare_digest(supplied, expected):
            return api_error("Your session token expired. Refresh the page and try again.", 400)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if IS_PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def init_db():
    with get_db() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student',
                leaderboard_public INTEGER NOT NULL DEFAULT 0,
                profile_public INTEGER NOT NULL DEFAULT 0,
                department TEXT NOT NULL DEFAULT '',
                study_year TEXT NOT NULL DEFAULT '',
                bio TEXT NOT NULL DEFAULT '',
                interests TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                activity_type TEXT NOT NULL DEFAULT 'Skill sprint',
                difficulty TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                description TEXT NOT NULL,
                details TEXT NOT NULL,
                badge_name TEXT NOT NULL,
                badge_emoji TEXT NOT NULL,
                accent TEXT NOT NULL,
                team_allowed INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER,
                status TEXT NOT NULL DEFAULT 'approved',
                reviewed_by INTEGER,
                reviewed_at TEXT,
                review_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS challenge_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                challenge_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                progress INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(user_id, challenge_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(challenge_id) REFERENCES challenges(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                challenge_id INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                proof_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                is_final INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'logged',
                reviewed_by INTEGER,
                reviewed_at TEXT,
                review_feedback TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(challenge_id) REFERENCES challenges(id) ON DELETE CASCADE,
                FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS challenge_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id INTEGER NOT NULL,
                reported_by INTEGER NOT NULL,
                reason TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                reviewed_by INTEGER,
                reviewed_at TEXT,
                UNIQUE(challenge_id, reported_by),
                FOREIGN KEY(challenge_id) REFERENCES challenges(id) ON DELETE CASCADE,
                FOREIGN KEY(reported_by) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                emoji TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                badge_id INTEGER NOT NULL,
                earned_at TEXT NOT NULL,
                UNIQUE(user_id, badge_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(badge_id) REFERENCES badges(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                activity_date TEXT NOT NULL,
                kind TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                capacity INTEGER NOT NULL DEFAULT 4,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(challenge_id) REFERENCES challenges(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS team_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT NOT NULL,
                UNIQUE(team_id, user_id),
                FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS team_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                reviewed_by INTEGER,
                reviewed_at TEXT,
                UNIQUE(team_id, user_id),
                FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS peer_kudos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL,
                challenge_id INTEGER NOT NULL,
                from_user_id INTEGER NOT NULL,
                to_user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(team_id, from_user_id, to_user_id),
                CHECK(from_user_id <> to_user_id),
                FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE,
                FOREIGN KEY(challenge_id) REFERENCES challenges(id) ON DELETE CASCADE,
                FOREIGN KEY(from_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(to_user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS checkin_guard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                challenge_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, challenge_id, checkin_date),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(challenge_id) REFERENCES challenges(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS auth_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT NOT NULL,
                email TEXT NOT NULL,
                attempted_at TEXT NOT NULL,
                succeeded INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_members_user_status ON challenge_members(user_id, status);
            CREATE INDEX IF NOT EXISTS idx_activity_user_date ON activity(user_id, activity_date);
            CREATE INDEX IF NOT EXISTS idx_team_members_team ON team_members(team_id);
            CREATE INDEX IF NOT EXISTS idx_challenges_category ON challenges(category);
            CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup ON auth_attempts(ip_address, email, attempted_at, succeeded);
            """
        )
        # Lightweight migrations keep existing student databases working after updates.
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "role" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'student'")
        if "leaderboard_public" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN leaderboard_public INTEGER NOT NULL DEFAULT 0")
        for column, declaration in {
            "profile_public": "INTEGER NOT NULL DEFAULT 0",
            "department": "TEXT NOT NULL DEFAULT ''",
            "study_year": "TEXT NOT NULL DEFAULT ''",
            "bio": "TEXT NOT NULL DEFAULT ''",
            "interests": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in user_columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} {declaration}")
        submission_columns = {row[1] for row in db.execute("PRAGMA table_info(submissions)").fetchall()}
        for column, declaration in {
            "is_final": "INTEGER NOT NULL DEFAULT 0",
            "status": "TEXT NOT NULL DEFAULT 'logged'",
            "reviewed_by": "INTEGER",
            "reviewed_at": "TEXT",
            "review_feedback": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in submission_columns:
                db.execute(f"ALTER TABLE submissions ADD COLUMN {column} {declaration}")

        challenge_columns = {row[1] for row in db.execute("PRAGMA table_info(challenges)").fetchall()}
        for column, declaration in {
            "activity_type": "TEXT NOT NULL DEFAULT 'Skill sprint'",
            "status": "TEXT NOT NULL DEFAULT 'approved'",
            "reviewed_by": "INTEGER",
            "reviewed_at": "TEXT",
            "review_note": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in challenge_columns:
                db.execute(f"ALTER TABLE challenges ADD COLUMN {column} {declaration}")

        # Add indexes only after migrations so existing databases with older
        # submissions tables can be upgraded safely.
        db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_review ON submissions(is_final, status, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_reports_status ON challenge_reports(status, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_challenges_activity_type ON challenges(activity_type)")

        # Carry previous check-ins into the uniqueness guard using campus-local dates.
        old_submissions = db.execute(
            "SELECT user_id, challenge_id, created_at FROM submissions ORDER BY created_at"
        ).fetchall()
        for old in old_submissions:
            try:
                stamp = datetime.fromisoformat(old["created_at"].replace("Z", "+00:00"))
                local_day = stamp.astimezone(APP_TIMEZONE).date().isoformat()
            except (TypeError, ValueError):
                local_day = old["created_at"][:10]
            db.execute(
                "INSERT OR IGNORE INTO checkin_guard(user_id, challenge_id, checkin_date, created_at) VALUES (?, ?, ?, ?)",
                (old["user_id"], old["challenge_id"], local_day, old["created_at"]),
            )

        badge_rows = [
            ("first-quest", "First Step", "Joined your first campus challenge and began a new quest.", "✦"),
            ("quest-finisher", "Quest Finisher", "Completed a challenge from start to finish.", "🏁"),
            ("squad-star", "Squad Star", "Joined or created your first challenge team.", "✧"),
            ("steady-spark", "Steady Spark", "Checked in on three different days.", "☀"),
            ("quest-maker", "Quest Maker", "Created a challenge for the community.", "✳"),
            ("community-spark", "Community Spark", "A teammate recognized your contribution.", "♡"),
        ]
        db.executemany(
            "INSERT OR IGNORE INTO badges(slug, name, description, emoji) VALUES (?, ?, ?, ?)",
            badge_rows,
        )

        challenge_rows = [
            ("Ship a tiny website", "Tech", "Beginner", 5,
             "Build and publish one small website in five days.",
             "Day 1: choose a tiny problem. Day 2: sketch the page. Day 3: build it. Day 4: polish it. Day 5: share a live link or repository.",
             "Tiny Shipper", "🚀", "blue", 1),
            ("DSA, one bite at a time", "Tech", "Beginner", 5,
             "Solve five carefully chosen problems without burning out.",
             "Pick one easy problem each day. Write down the approach, edge cases and one thing you learned. Share a solution link or short reflection.",
             "Logic Sprout", "🌱", "mint", 1),
            ("The campus photo walk", "Creative", "All levels", 3,
             "Capture three little details that make your campus yours.",
             "Take one photo each day around campus. Try a different angle or theme each time. Upload your favourite three photos at the end.",
             "Campus Storyteller", "📸", "peach", 1),
            ("Make someone's day", "Social", "All levels", 3,
             "Do one thoughtful, low-key act of kindness each day.",
             "Help a classmate, thank a staff member or share a useful resource. Check in with a short reflection. No photos of other people without consent.",
             "Good Energy", "💛", "pink", 1),
            ("Git without the panic", "Tech", "Beginner", 3,
             "Get comfortable with the Git basics through tiny practice.",
             "Create a repository, make meaningful commits, create a branch and open a pull request. Share your repository when done.",
             "Commit Club", "⌘", "lilac", 1),
            ("A 20-minute reset", "Wellbeing", "All levels", 5,
             "Take a small screen-free reset on five days this week.",
             "Choose a walk, stretching, journaling or quiet reading. Log how you feel afterwards. This is about balance, not competition.",
             "Soft Reset", "☁", "mint", 0),
            ("The mini pitch", "Creative", "All levels", 5,
             "Turn one everyday annoyance into a 60-second idea pitch.",
             "Spot a problem, talk to one potential user, sketch a solution, make a one-slide pitch and share it with the community.",
             "Idea Spark", "💡", "peach", 1),
            ("Teach-back trio", "Social", "All levels", 3,
             "Learn a tiny concept, then explain it to another student.",
             "Choose one concept, prepare a simple explanation, teach a friend and write what you would explain differently next time.",
             "Clear Explainer", "🫶", "pink", 1),
        ]
        count = db.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
        if count == 0:
            db.executemany(
                """INSERT INTO challenges(title, category, difficulty, duration_days, description,
                   details, badge_name, badge_emoji, accent, team_allowed, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [row + (now_iso(),) for row in challenge_rows],
            )

        # Expand the activity library even for existing databases. This is deliberately
        # additive: existing student data and custom challenges are never overwritten.
        extra_activity_rows = [
            ("Build a useful campus mini-tool", "Tech", "Mini-project", "Beginner", 7,
             "Make a small tool that solves one everyday campus annoyance.",
             "Day 1: choose one problem. Day 2: sketch the simplest flow. Days 3–5: build the core. Day 6: ask a student to try it. Day 7: share the demo or repository.",
             "Campus Maker", "🛠️", "blue", 1),
            ("Your first open-source contribution", "Tech", "Skill sprint", "Beginner", 5,
             "Get comfortable exploring a public repository and making a tiny improvement.",
             "Find a beginner-friendly repository, read its README, run it locally if possible, identify a small documentation or issue improvement, and share what you learned. Never submit code you do not understand.",
             "Open Door", "🌱", "mint", 1),
            ("Resume buddy swap", "Career", "Peer learning", "All levels", 3,
             "Pair up with another student and give each other kind, specific resume feedback.",
             "Day 1: exchange resumes privately with consent. Day 2: use the review checklist to suggest clearer impact and formatting. Day 3: each person makes one improvement. Do not upload someone else's resume publicly.",
             "Helpful Eye", "📝", "peach", 1),
            ("Mock interview circle", "Career", "Campus meetup", "Beginner", 5,
             "Form a small group and practise short, friendly interview rounds.",
             "Create a group of 3–4. Take turns asking one technical, one project and one behavioral question. Share respectful feedback and one next step after each round.",
             "Calm Communicator", "🎤", "lilac", 1),
            ("Portfolio polish party", "Career", "Skill sprint", "All levels", 3,
             "Make one small improvement to your portfolio, GitHub profile or project README.",
             "Choose one thing to improve, ask a peer to review it, make the change and share the updated link. Keep personal contact details private if the profile is public.",
             "Showcase Sprout", "✨", "blue", 1),
            ("Campus badminton mini ladder", "Sports", "Friendly competition", "All levels", 5,
             "Organize a friendly, beginner-welcoming badminton ladder with classmates.",
             "Find a suitable court and agree on simple rules. Play short matches across the week, rotate partners and record results only with participants' consent. Keep it friendly; no one needs to play through pain.",
             "Rally Buddy", "🏸", "mint", 1),
            ("Try-a-sport sampler", "Sports", "Campus meetup", "Beginner", 3,
             "Invite friends to try one accessible sport or movement game together.",
             "Choose a safe campus space and a low-pressure activity. Explain basic rules, keep sessions short, allow spectators or alternative roles, and reflect on what was fun.",
             "Game for Anything", "⚽", "peach", 1),
            ("Board-game lunch table", "Games", "Campus meetup", "All levels", 1,
             "Host a relaxed board-game or card-game table and invite someone new to join.",
             "Pick an easy-to-learn game, reserve an appropriate common area if needed, explain the rules and make sure new players feel welcome. No betting or money stakes.",
             "Table Opener", "🎲", "lilac", 1),
            ("The campus clue trail", "Games", "Friendly competition", "All levels", 3,
             "Create a short, safe clue trail using public campus landmarks.",
             "Write 4–6 clues that lead only to accessible public areas. Do not enter restricted buildings, disturb classes or collect personal information. Let another team test the trail.",
             "Clue Finder", "🧩", "pink", 1),
            ("Language exchange coffee chat", "Culture", "Campus meetup", "All levels", 3,
             "Meet students who speak or are learning a language and exchange a few useful phrases.",
             "Agree on a language pair, meet in a public campus space, teach each other five everyday phrases and share one cultural fact you learned. Be respectful of different backgrounds.",
             "Word Wanderer", "🌍", "peach", 1),
            ("Campus story walk", "Culture", "Campus exploration", "All levels", 3,
             "Notice the small stories, architecture or traditions that make your campus distinctive.",
             "Walk through permitted public areas, note three details and create a short written or illustrated story. Ask permission before photographing people or private spaces.",
             "Campus Chronicler", "📍", "lilac", 1),
            ("Bottle refill buddy week", "Sustainability", "Community action", "All levels", 5,
             "Help classmates notice refill points and reduce single-use bottle waste.",
             "Identify public refill points, verify they are usable, make a simple shareable guide and invite classmates to use reusable bottles. Do not make claims about water safety without official information.",
             "Refill Friend", "💧", "mint", 1),
            ("Campus waste spotter", "Sustainability", "Community action", "All levels", 3,
             "Notice one waste issue on campus and suggest a practical, respectful improvement.",
             "Observe only public areas, describe the issue without identifying individuals, suggest a low-cost solution and share it with the relevant campus group or maintenance channel.",
             "Green Observer", "♻️", "blue", 1),
            ("Teach one tiny thing", "Community", "Peer learning", "All levels", 3,
             "Teach a classmate a small skill or concept you know, then learn something from them.",
             "Choose a 10–20 minute topic, explain it using a simple example, invite questions and note one thing you learned from the other person. Teaching is collaborative, not a test.",
             "Tiny Teacher", "🫶", "pink", 1),
            ("Make a welcome map for juniors", "Community", "Community action", "All levels", 5,
             "Create a friendly guide to useful student spaces and resources on campus.",
             "Ask juniors what they wish they had known. Map only public, approved locations and useful resources. Keep the guide accurate, inclusive and easy to update.",
             "Friendly Guide", "🗺️", "peach", 1),
            ("Five-day reading nook", "Learning", "Wellbeing habit", "All levels", 5,
             "Make a little time for reading and share one idea that stayed with you.",
             "Choose any permitted book or article. Read for 10–15 minutes on five days. Share a short reflection or recommendation; do not upload copyrighted text.",
             "Page Turner", "📚", "lilac", 0),
            ("Focus buddy sessions", "Learning", "Peer learning", "All levels", 5,
             "Pair with another student for short, distraction-light study sessions.",
             "Agree on one manageable goal, work quietly for 25 minutes, take a short break and share what you completed. Keep the tone supportive rather than competitive.",
             "Focus Friend", "⏳", "blue", 1),
            ("One-minute campus story", "Creative", "Creative jam", "All levels", 3,
             "Create a one-minute video, photo story or audio piece about an ordinary campus moment.",
             "Choose a theme, plan a simple beginning-middle-end, create your piece and share it. Get consent before including identifiable people and use music/media you have permission to use.",
             "Little Filmmaker", "🎬", "pink", 1),
            ("Sketchbook in small moments", "Creative", "Creative jam", "Beginner", 5,
             "Make one tiny sketch, doodle or visual note each day.",
             "Pick a theme, spend 5–10 minutes a day creating, and assemble your five pages into a small digital or physical collection. No drawing experience needed.",
             "Everyday Artist", "🎨", "peach", 0),
            ("Neighbourhood kindness chain", "Social", "Community action", "All levels", 3,
             "Do one thoughtful, low-key helpful act and invite a friend to continue the chain.",
             "Offer practical help, share a useful resource or thank someone. Keep participation voluntary, do not record people without consent and avoid posting private details.",
             "Kindness Loop", "💛", "mint", 1),
        ]
        for row in extra_activity_rows:
            exists = db.execute("SELECT 1 FROM challenges WHERE title=? LIMIT 1", (row[0],)).fetchone()
            if not exists:
                db.execute(
                    """INSERT INTO challenges(title, category, activity_type, difficulty, duration_days,
                       description, details, badge_name, badge_emoji, accent, team_allowed, status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?)""",
                    row + (now_iso(),),
                )

        # Assign helpful activity formats to the original starter challenges.
        default_type_by_category = {
            "Tech": "Skill sprint", "Creative": "Creative jam", "Social": "Peer learning",
            "Wellbeing": "Wellbeing habit", "Sports": "Friendly competition", "Career": "Skill sprint",
            "Community": "Community action", "Sustainability": "Community action", "Culture": "Campus exploration",
            "Games": "Friendly competition", "Learning": "Peer learning",
        }
        for category, activity_type in default_type_by_category.items():
            db.execute("UPDATE challenges SET activity_type=? WHERE category=? AND (activity_type IS NULL OR activity_type='' OR activity_type='Challenge')", (activity_type, category))
        original_seed_types = {
            "Ship a tiny website": "Mini-project",
            "DSA, one bite at a time": "Skill sprint",
            "The campus photo walk": "Campus exploration",
            "Make someone's day": "Community action",
            "Git without the panic": "Skill sprint",
            "A 20-minute reset": "Wellbeing habit",
            "The mini pitch": "Creative jam",
            "Teach-back trio": "Peer learning",
        }
        for title, activity_type in original_seed_types.items():
            db.execute("UPDATE challenges SET activity_type=? WHERE title=? AND activity_type='Skill sprint'", (activity_type, title))

        # Seed a demo account only for local development/showcase environments.
        demo_enabled = (not IS_PRODUCTION) and os.environ.get("ENABLE_DEMO_LOGIN", "1") == "1"
        demo = db.execute("SELECT id FROM users WHERE email = ?", ("demo@campusquest.local",)).fetchone()
        if demo_enabled and not demo:
            cur = db.execute(
                "INSERT INTO users(name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                ("Aarav", "demo@campusquest.local", generate_password_hash("questdemo"), now_iso()),
            )
            demo_id = cur.lastrowid
            quest_ids = [
                db.execute("SELECT id FROM challenges WHERE title = ?", ("DSA, one bite at a time",)).fetchone()[0],
                db.execute("SELECT id FROM challenges WHERE title = ?", ("The campus photo walk",)).fetchone()[0],
            ]
            for idx, quest_id in enumerate(quest_ids):
                db.execute(
                    "INSERT INTO challenge_members(user_id, challenge_id, status, progress, joined_at) VALUES (?, ?, 'active', ?, ?)",
                    (demo_id, quest_id, idx + 1, (app_today() - timedelta(days=idx)).isoformat() + "T09:00:00Z"),
                )
            for days_ago in [0, 1, 3, 5, 8, 10, 13, 17, 20, 23, 26, 30, 34, 38, 42, 49, 54, 61, 68, 75, 82, 90]:
                db.execute(
                    "INSERT INTO activity(user_id, activity_date, kind, detail) VALUES (?, ?, 'check-in', 'Demo activity')",
                    (demo_id, (app_today() - timedelta(days=days_ago)).isoformat()),
                )
            first_badge = db.execute("SELECT id FROM badges WHERE slug='first-quest'").fetchone()[0]
            db.execute("INSERT OR IGNORE INTO user_badges(user_id, badge_id, earned_at) VALUES (?, ?, ?)", (demo_id, first_badge, now_iso()))
            db.execute("UPDATE users SET leaderboard_public=1 WHERE id=?", (demo_id,))
        if not demo_enabled:
            db.execute("UPDATE users SET leaderboard_public=0 WHERE email='demo@campusquest.local'")


def api_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status


def current_user(db=None):
    user_id = session.get("user_id")
    if not user_id:
        return None
    if db is not None:
        row = db.execute("SELECT id, name, email, role, leaderboard_public, profile_public, department, study_year, bio, interests, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    else:
        with get_db() as own_db:
            row = own_db.execute("SELECT id, name, email, role, leaderboard_public, profile_public, department, study_year, bio, interests, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return api_error("Please sign in to do that.", 401)
        return fn(*args, **kwargs)
    return wrapped


def record_activity(db, user_id, kind, detail=""):
    db.execute(
        "INSERT INTO activity(user_id, activity_date, kind, detail) VALUES (?, ?, ?, ?)",
        (user_id, app_today().isoformat(), kind, detail[:240]),
    )


def award_badge(db, user_id, slug):
    badge = db.execute("SELECT id FROM badges WHERE slug = ?", (slug,)).fetchone()
    if not badge:
        return False
    cur = db.execute(
        "INSERT OR IGNORE INTO user_badges(user_id, badge_id, earned_at) VALUES (?, ?, ?)",
        (user_id, badge["id"], now_iso()),
    )
    return cur.rowcount > 0


def challenge_json(row, joined=False, progress=0, status=None):
    return {
        "id": row["id"], "title": row["title"], "category": row["category"],
        "activity_type": row["activity_type"] if "activity_type" in row.keys() else "Skill sprint",
        "difficulty": row["difficulty"], "duration_days": row["duration_days"],
        "description": row["description"], "details": row["details"],
        "badge_name": row["badge_name"], "badge_emoji": row["badge_emoji"],
        "accent": row["accent"], "team_allowed": bool(row["team_allowed"]),
        "joined": joined, "progress": progress, "status": status,
        "participant_count": row["participant_count"] if "participant_count" in row.keys() else 0,
        "approval_status": row["status"] if "status" in row.keys() else "approved",
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/me")
def api_me():
    user = current_user()
    if not user:
        return jsonify({"ok": True, "user": None})
    with get_db() as db:
        stats = db.execute(
            """SELECT COUNT(*) AS joined,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed
               FROM challenge_members WHERE user_id=?""", (user["id"],)
        ).fetchone()
        badge_count = db.execute("SELECT COUNT(*) FROM user_badges WHERE user_id=?", (user["id"],)).fetchone()[0]
        kudos_received = db.execute("SELECT COUNT(*) FROM peer_kudos WHERE to_user_id=?", (user["id"],)).fetchone()[0]
    user.update({"joined_count": stats["joined"] or 0, "completed_count": stats["completed"] or 0,
                 "badge_count": badge_count, "kudos_received": kudos_received})
    return jsonify({"ok": True, "user": user})


@app.post("/api/profile")
@login_required
def update_profile():
    user = current_user()
    data = request.get_json(silent=True) or {}
    department = str(data.get("department", "")).strip()[:80]
    study_year = str(data.get("study_year", "")).strip()[:30]
    bio = str(data.get("bio", "")).strip()[:280]
    interests = str(data.get("interests", "")).strip()[:240]
    profile_public = 1 if data.get("profile_public") is True else 0
    if study_year and study_year not in {"1st Year", "2nd Year", "3rd Year", "4th Year", "Graduate", "Other"}:
        return api_error("Choose a valid study year.")
    with get_db() as db:
        db.execute(
            "UPDATE users SET department=?, study_year=?, bio=?, interests=?, profile_public=? WHERE id=?",
            (department, study_year, bio, interests, profile_public, user["id"]),
        )
        record_activity(db, user["id"], "profile", "Updated their student profile")
    return jsonify({"ok": True, "message": "Your student profile has been updated.", "user": current_user()})


@app.get("/api/profiles/<int:profile_id>")
def public_profile(profile_id):
    viewer = current_user()
    with get_db() as db:
        person = db.execute(
            "SELECT id, name, department, study_year, bio, interests, profile_public, created_at FROM users WHERE id=?",
            (profile_id,),
        ).fetchone()
        if not person:
            return api_error("This student profile could not be found.", 404)
        if not person["profile_public"] and (not viewer or viewer["id"] != profile_id):
            return api_error("This student has kept their profile private.", 403)
        stats = db.execute(
            """SELECT COUNT(*) AS joined,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed
               FROM challenge_members WHERE user_id=?""", (profile_id,)
        ).fetchone()
        badge_count = db.execute("SELECT COUNT(*) FROM user_badges WHERE user_id=?", (profile_id,)).fetchone()[0]
        kudos_count = db.execute("SELECT COUNT(*) FROM peer_kudos WHERE to_user_id=?", (profile_id,)).fetchone()[0]
    return jsonify({"ok": True, "profile": dict(person) | {
        "joined_count": stats["joined"] or 0, "completed_count": stats["completed"] or 0,
        "badge_count": badge_count, "kudos_received": kudos_count
    }})


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or len(name) > 60:
        return api_error("Please enter a name between 2 and 60 characters.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email) or len(email) > 120:
        return api_error("Please enter a valid email address.")
    if len(password) < 8 or len(password) > 128:
        return api_error("Use a password between 8 and 128 characters.")
    try:
        with get_db() as db:
            cur = db.execute(
                "INSERT INTO users(name, email, password_hash, role, leaderboard_public, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name, email, generate_password_hash(password), "student", 1 if data.get("show_on_leaderboard") is True else 0, now_iso()),
            )
            user_id = cur.lastrowid
            record_activity(db, user_id, "joined", "Joined CampusQuest")
        csrf = session.get("csrf_token")
        session.clear()
        session["csrf_token"] = csrf or secrets.token_urlsafe(32)
        session["user_id"] = user_id
        session.permanent = True
        return jsonify({"ok": True, "message": "Welcome to CampusQuest!", "user": current_user()})
    except sqlite3.IntegrityError:
        return api_error("An account with that email already exists.", 409)


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()[:120]
    password = str(data.get("password", ""))
    if not email or not password or len(password) > 128:
        return api_error("Enter your email and password.", 400)

    ip_address = (request.remote_addr or "unknown")[:64]
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with get_db() as db:
        one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        db.execute("DELETE FROM auth_attempts WHERE attempted_at < ?", (one_day_ago,))
        failures = db.execute(
            "SELECT COUNT(*) FROM auth_attempts WHERE ip_address=? AND email=? AND succeeded=0 AND attempted_at>=?",
            (ip_address, email, cutoff),
        ).fetchone()[0]
        if failures >= 10:
            return api_error("Too many sign-in attempts. Please try again in 15 minutes.", 429)

        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        valid = bool(user and check_password_hash(user["password_hash"], password))
        db.execute(
            "INSERT INTO auth_attempts(ip_address, email, attempted_at, succeeded) VALUES (?, ?, ?, ?)",
            (ip_address, email, now_iso(), 1 if valid else 0),
        )
        if not valid:
            return api_error("Email or password doesn't match.", 401)
        db.execute(
            "DELETE FROM auth_attempts WHERE ip_address=? AND email=? AND succeeded=0",
            (ip_address, email),
        )
    csrf = session.get("csrf_token")
    session.clear()
    session["csrf_token"] = csrf or secrets.token_urlsafe(32)
    session["user_id"] = user["id"]
    session.permanent = True
    return jsonify({"ok": True, "message": "You're back!", "user": current_user()})


@app.post("/api/auth/demo")
def demo_login():
    # Never rely only on hiding the demo button in the template. The endpoint
    # must enforce the same restriction because it can be called directly.
    demo_enabled = (not IS_PRODUCTION) and os.environ.get("ENABLE_DEMO_LOGIN", "1") == "1"
    if not demo_enabled:
        return api_error("Demo access is disabled.", 404)
    with get_db() as db:
        user = db.execute("SELECT id FROM users WHERE email='demo@campusquest.local'").fetchone()
    if not user:
        return api_error("The demo account is not available. Please register instead.", 503)
    csrf = session.get("csrf_token")
    session.clear()
    session["csrf_token"] = csrf or secrets.token_urlsafe(32)
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "message": "Welcome to the demo space!", "user": current_user()})


@app.post("/api/auth/logout")
def logout():
    csrf = session.get("csrf_token")
    session.clear()
    session["csrf_token"] = csrf or secrets.token_urlsafe(32)
    return jsonify({"ok": True})


@app.get("/api/challenges")
def get_challenges():
    user = current_user()
    with get_db() as db:
        rows = db.execute(
            """SELECT c.*,
               (SELECT COUNT(*) FROM challenge_members cm WHERE cm.challenge_id=c.id AND cm.status <> 'left') AS participant_count
               FROM challenges c WHERE c.status='approved' ORDER BY c.created_at DESC, c.id DESC"""
        ).fetchall()
        joined = {}
        if user:
            joined = {
                r["challenge_id"]: (r["progress"], r["status"])
                for r in db.execute("SELECT challenge_id, progress, status FROM challenge_members WHERE user_id=?", (user["id"],)).fetchall()
            }
    items = []
    for row in rows:
        progress, status = joined.get(row["id"], (0, None))
        items.append(challenge_json(row, row["id"] in joined, progress, status))
    return jsonify({"ok": True, "challenges": items})


@app.get("/api/challenges/<int:challenge_id>")
def get_challenge_detail(challenge_id):
    user = current_user()
    with get_db() as db:
        row = db.execute(
            """SELECT c.*,
               (SELECT COUNT(*) FROM challenge_members cm WHERE cm.challenge_id=c.id AND cm.status <> 'left') AS participant_count
               FROM challenges c WHERE c.id=? AND c.status='approved'""",
            (challenge_id,),
        ).fetchone()
        if not row:
            return api_error("This quest is unavailable or still awaiting approval.", 404)
        membership = None
        if user:
            membership = db.execute(
                "SELECT progress, status FROM challenge_members WHERE user_id=? AND challenge_id=?",
                (user["id"], challenge_id),
            ).fetchone()
    payload = challenge_json(
        row,
        joined=bool(membership),
        progress=membership["progress"] if membership else 0,
        status=membership["status"] if membership else None,
    )
    return jsonify({"ok": True, "challenge": payload})


@app.get("/api/weekly-quest")
def weekly_quest():
    """Rotate one approved challenge as a weekly prompt; no engagement score is involved."""
    user = current_user()
    today = app_today()
    iso_year, iso_week, _ = today.isocalendar()
    with get_db() as db:
        rows = db.execute(
            """SELECT c.*,
               (SELECT COUNT(*) FROM challenge_members cm WHERE cm.challenge_id=c.id AND cm.status <> 'left') AS participant_count
               FROM challenges c WHERE c.status='approved' ORDER BY c.id"""
        ).fetchall()
        if not rows:
            return api_error("The quest board is being prepared. Check back soon.", 404)
        chosen = rows[(iso_year * 53 + iso_week) % len(rows)]
        membership = None
        if user:
            membership = db.execute(
                "SELECT progress, status FROM challenge_members WHERE user_id=? AND challenge_id=?",
                (user["id"], chosen["id"]),
            ).fetchone()
    payload = challenge_json(chosen, bool(membership), membership["progress"] if membership else 0,
                             membership["status"] if membership else None)
    return jsonify({"ok": True, "challenge": payload, "week": f"{iso_year}-W{iso_week:02d}"})


@app.get("/api/my-quests")
@login_required
def my_quests():
    user = current_user()
    with get_db() as db:
        rows = db.execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM challenge_members x WHERE x.challenge_id=c.id AND x.status <> 'left') AS participant_count,
                      cm.progress, cm.status, cm.joined_at,
                      (SELECT s.status FROM submissions s WHERE s.user_id=cm.user_id AND s.challenge_id=cm.challenge_id AND s.is_final=1 ORDER BY s.id DESC LIMIT 1) AS final_submission_status,
                      (SELECT s.review_feedback FROM submissions s WHERE s.user_id=cm.user_id AND s.challenge_id=cm.challenge_id AND s.is_final=1 ORDER BY s.id DESC LIMIT 1) AS final_review_feedback
               FROM challenge_members cm JOIN challenges c ON c.id=cm.challenge_id
               WHERE cm.user_id=? ORDER BY CASE cm.status WHEN 'active' THEN 0 ELSE 1 END, cm.joined_at DESC""",
            (user["id"],),
        ).fetchall()
    items = [challenge_json(row, True, row["progress"], row["status"]) | {
        "joined_at": row["joined_at"],
        "final_submission_status": row["final_submission_status"],
        "final_review_feedback": row["final_review_feedback"] or "",
    } for row in rows]
    return jsonify({"ok": True, "quests": items})


@app.post("/api/challenges/<int:challenge_id>/join")
@login_required
def join_challenge(challenge_id):
    user = current_user()
    with get_db() as db:
        challenge = db.execute("SELECT * FROM challenges WHERE id=? AND status='approved'", (challenge_id,)).fetchone()
        if not challenge:
            return api_error("That quest could not be found or is still awaiting review.", 404)
        try:
            db.execute(
                "INSERT INTO challenge_members(user_id, challenge_id, status, progress, joined_at) VALUES (?, ?, 'active', 0, ?)",
                (user["id"], challenge_id, now_iso()),
            )
        except sqlite3.IntegrityError:
            return api_error("You're already part of this quest.", 409)
        record_activity(db, user["id"], "joined", f"Joined {challenge['title']}")
        new_badges = []
        if award_badge(db, user["id"], "first-quest"):
            new_badges.append("First Quest")
    return jsonify({"ok": True, "message": "You're in! Your quest is now in My Quests.", "new_badges": new_badges})


@app.post("/api/challenges/<int:challenge_id>/checkin")
@login_required
def checkin(challenge_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    note = str(data.get("note", "")).strip()[:500]
    proof_url = str(data.get("proof_url", "")).strip()[:300]
    if proof_url:
        parsed = urlsplit(proof_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return api_error("Enter a complete proof link starting with https:// or http://.")

    today = app_today().isoformat()
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT cm.*, c.duration_days, c.title FROM challenge_members cm
               JOIN challenges c ON c.id=cm.challenge_id
               WHERE cm.user_id=? AND cm.challenge_id=? AND c.status='approved'""",
            (user["id"], challenge_id),
        ).fetchone()
        if not row:
            return api_error("Join this quest before checking in.", 404)
        if row["status"] == "completed":
            return api_error("You've already completed this quest. Enjoy the badge!")
        if row["status"] == "submitted":
            return api_error("Your final work is waiting for review. We'll let you know when it's reviewed.", 409)
        if row["status"] == "submission_rejected":
            return api_error("This submission was rejected. Contact a moderator if you believe this was a mistake.", 409)
        if row["progress"] >= row["duration_days"]:
            return jsonify({"ok": True, "progress": row["progress"], "duration_days": row["duration_days"],
                            "status": "ready_to_submit", "message": "You've completed the daily steps. Submit your final work for review."})

        try:
            db.execute(
                "INSERT INTO checkin_guard(user_id, challenge_id, checkin_date, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], challenge_id, today, now_iso()),
            )
        except sqlite3.IntegrityError:
            return api_error("You've already checked in for this quest today. Come back tomorrow for the next step.", 409)

        progress = min(row["progress"] + 1, row["duration_days"])
        status = "ready_to_submit" if progress >= row["duration_days"] else "active"
        db.execute(
            "UPDATE challenge_members SET progress=?, status=? WHERE user_id=? AND challenge_id=?",
            (progress, status, user["id"], challenge_id),
        )
        db.execute(
            "INSERT INTO submissions(user_id, challenge_id, note, proof_url, created_at, is_final, status) VALUES (?, ?, ?, ?, ?, 0, 'logged')",
            (user["id"], challenge_id, note, proof_url, now_iso()),
        )
        record_activity(db, user["id"], "check-in", f"Checked in for {row['title']}")
        active_days = db.execute(
            "SELECT COUNT(DISTINCT checkin_date) FROM checkin_guard WHERE user_id=?", (user["id"],)
        ).fetchone()[0]
        new_badges = []
        if active_days >= 3 and award_badge(db, user["id"], "steady-spark"):
            new_badges.append("Steady Spark")
    return jsonify({
        "ok": True, "progress": progress, "duration_days": row["duration_days"],
        "status": status,
        "message": "Daily check-in saved. Your final badge is awarded after your work is reviewed." if status == "ready_to_submit" else "Check-in saved. Keep your momentum gentle and steady.",
        "new_badges": new_badges,
    })


@app.post("/api/challenges/<int:challenge_id>/submit")
@login_required
def submit_final_work(challenge_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    note = str(data.get("note", "")).strip()[:1200]
    proof_url = str(data.get("proof_url", "")).strip()[:500]
    if proof_url:
        parsed = urlsplit(proof_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return api_error("Enter a complete proof link starting with https:// or http://.")
    if len(note) < 20 and not proof_url:
        return api_error("Add a short reflection (at least 20 characters) or a link to your finished work.")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        member = db.execute(
            """SELECT cm.*, c.title, c.duration_days FROM challenge_members cm
               JOIN challenges c ON c.id=cm.challenge_id
               WHERE cm.user_id=? AND cm.challenge_id=? AND c.status='approved'""",
            (user["id"], challenge_id),
        ).fetchone()
        if not member:
            return api_error("Join this quest before submitting your work.", 404)
        if member["status"] == "completed":
            return api_error("This quest is already completed.", 409)
        if member["status"] == "submission_rejected":
            return api_error("This submission was rejected. Contact a moderator if you believe this was a mistake.", 409)
        if member["progress"] < member["duration_days"]:
            return api_error(f"Complete all {member['duration_days']} daily check-ins before final submission.", 409)
        pending = db.execute(
            "SELECT id FROM submissions WHERE user_id=? AND challenge_id=? AND is_final=1 AND status='pending'",
            (user["id"], challenge_id),
        ).fetchone()
        if pending:
            return api_error("Your final work is already waiting for review.", 409)
        db.execute(
            "INSERT INTO submissions(user_id, challenge_id, note, proof_url, created_at, is_final, status) VALUES (?, ?, ?, ?, ?, 1, 'pending')",
            (user["id"], challenge_id, note, proof_url, now_iso()),
        )
        db.execute(
            "UPDATE challenge_members SET status='submitted' WHERE user_id=? AND challenge_id=?",
            (user["id"], challenge_id),
        )
        record_activity(db, user["id"], "submission", f"Submitted final work for {member['title']}")
    return jsonify({"ok": True, "message": "Your final work is in the review queue. Your completion badge arrives after approval."})


@app.post("/api/challenges/create")
@login_required
def create_challenge():
    user = current_user()
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()[:80]
    category = str(data.get("category", "Creative")).strip()
    activity_type = str(data.get("activity_type", "Creative jam")).strip()
    description = str(data.get("description", "")).strip()[:240]
    team_allowed = 1 if data.get("team_allowed", True) is True else 0
    duration = data.get("duration_days", 5)
    if len(title) < 5 or len(description) < 12:
        return api_error("Add a title and a little more detail so others know what they're joining.")
    if category not in CHALLENGE_CATEGORIES:
        return api_error("Choose one of the available categories.")
    if activity_type not in ACTIVITY_TYPES:
        return api_error("Choose one of the available activity types.")
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 5
    duration = max(1, min(duration, 14))
    with get_db() as db:
        recent_creations = db.execute(
            "SELECT COUNT(*) FROM challenges WHERE created_by=? AND created_at>=?",
            (user["id"], (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")),
        ).fetchone()[0]
        if recent_creations >= 3:
            return api_error("You can publish up to 3 community quests in 24 hours. Give each one room to shine.", 429)
        cur = db.execute(
            """INSERT INTO challenges(title, category, activity_type, difficulty, duration_days, description, details,
               badge_name, badge_emoji, accent, team_allowed, created_by, status, created_at)
               VALUES (?, ?, ?, 'Community-made', ?, ?, ?, 'Quest Creator', '✳', 'lilac', ?, ?, 'pending', ?)""",
            (title, category, activity_type, duration, description, description, team_allowed, user["id"], now_iso()),
        )
        challenge_id = cur.lastrowid
        record_activity(db, user["id"], "proposed", f"Submitted {title} for review")
    return jsonify({"ok": True, "challenge_id": challenge_id, "message": "Your quest has been submitted for a quick community review. It will appear on the board once approved."})


@app.get("/api/badges")
@login_required
def get_badges():
    user = current_user()
    with get_db() as db:
        rows = db.execute(
            """SELECT b.*, ub.earned_at FROM badges b LEFT JOIN user_badges ub
               ON ub.badge_id=b.id AND ub.user_id=? ORDER BY CASE WHEN ub.id IS NULL THEN 1 ELSE 0 END, ub.earned_at DESC, b.id""",
            (user["id"],),
        ).fetchall()
    return jsonify({"ok": True, "badges": [dict(r) | {"earned": bool(r["earned_at"])} for r in rows]})


@app.get("/api/activity")
@login_required
def get_activity():
    user = current_user()
    start = app_today() - timedelta(days=111)
    with get_db() as db:
        rows = db.execute(
            "SELECT activity_date, COUNT(*) AS count FROM activity WHERE user_id=? AND activity_date>=? GROUP BY activity_date",
            (user["id"], start.isoformat()),
        ).fetchall()
    counts = {r["activity_date"]: r["count"] for r in rows}
    days = []
    for offset in range(112):
        day = start + timedelta(days=offset)
        days.append({"date": day.isoformat(), "count": counts.get(day.isoformat(), 0)})
    return jsonify({"ok": True, "days": days, "active_days": sum(1 for d in days if d["count"] > 0)})


@app.get("/api/teams")
def get_teams():
    user = current_user()
    user_id = user["id"] if user else -1
    with get_db() as db:
        rows = db.execute(
            """SELECT t.*, c.title AS challenge_title,
               CASE WHEN u.profile_public=1 THEN u.name ELSE 'CampusQuest member' END AS creator_name,
               (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id=t.id) AS member_count,
               EXISTS(SELECT 1 FROM team_members tm WHERE tm.team_id=t.id AND tm.user_id=?) AS joined,
               (EXISTS(SELECT 1 FROM challenge_members cm WHERE cm.challenge_id=t.challenge_id AND cm.user_id=? AND cm.status='active')
                AND NOT EXISTS(SELECT 1 FROM team_members tm2 JOIN teams t2 ON t2.id=tm2.team_id WHERE t2.challenge_id=t.challenge_id AND tm2.user_id=?)) AS can_join,
               EXISTS(SELECT 1 FROM team_join_requests r WHERE r.team_id=t.id AND r.user_id=? AND r.status='pending') AS requested,
               CASE WHEN t.created_by=? THEN 1 ELSE 0 END AS is_owner
               FROM teams t JOIN challenges c ON c.id=t.challenge_id JOIN users u ON u.id=t.created_by
               WHERE c.status='approved' ORDER BY t.created_at DESC LIMIT 20""", (user_id, user_id, user_id, user_id, user_id)
        ).fetchall()
    return jsonify({"ok": True, "teams": [dict(r) for r in rows]})


@app.post("/api/teams")
@login_required
def create_team():
    user = current_user()
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:50]
    description = str(data.get("description", "")).strip()[:180]
    try:
        challenge_id = int(data.get("challenge_id"))
    except (TypeError, ValueError):
        return api_error("Choose a challenge for your team.")
    if len(name) < 3:
        return api_error("Give your team a name with at least 3 characters.")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        challenge = db.execute("SELECT team_allowed FROM challenges WHERE id=? AND status='approved'", (challenge_id,)).fetchone()
        if not challenge:
            return api_error("That quest could not be found.", 404)
        if not challenge["team_allowed"]:
            return api_error("This quest is designed for solo participation.", 400)
        joined = db.execute(
            "SELECT id FROM challenge_members WHERE user_id=? AND challenge_id=? AND status='active'", (user["id"], challenge_id)
        ).fetchone()
        if not joined:
            return api_error("Join an active challenge before creating a team for it.")
        existing_team = db.execute(
            "SELECT id FROM teams WHERE challenge_id=? AND created_by=?", (challenge_id, user["id"])
        ).fetchone()
        if existing_team:
            return api_error("You've already created a squad for this quest.", 409)
        existing_membership = db.execute(
            "SELECT 1 FROM team_members tm JOIN teams t ON t.id=tm.team_id WHERE t.challenge_id=? AND tm.user_id=?",
            (challenge_id, user["id"]),
        ).fetchone()
        if existing_membership:
            return api_error("You're already part of a squad for this quest.", 409)
        cur = db.execute(
            "INSERT INTO teams(challenge_id, name, description, capacity, created_by, created_at) VALUES (?, ?, ?, 4, ?, ?)",
            (challenge_id, name, description, user["id"], now_iso()),
        )
        team_id = cur.lastrowid
        db.execute("INSERT INTO team_members(team_id, user_id, role, joined_at) VALUES (?, ?, 'captain', ?)", (team_id, user["id"], now_iso()))
        record_activity(db, user["id"], "team", f"Created team {name}")
        new_badges = ["Squad Star"] if award_badge(db, user["id"], "squad-star") else []
    return jsonify({"ok": True, "team_id": team_id, "message": "Your squad is ready!", "new_badges": new_badges})


@app.post("/api/teams/<int:team_id>/request")
@login_required
def request_team_join(team_id):
    user = current_user()
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        team = db.execute(
            """SELECT t.*, c.team_allowed,
               (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id=t.id) AS member_count
               FROM teams t JOIN challenges c ON c.id=t.challenge_id
               WHERE t.id=? AND c.status='approved'""", (team_id,)
        ).fetchone()
        if not team:
            return api_error("This squad is no longer available.", 404)
        if team["created_by"] == user["id"]:
            return api_error("You're already the squad captain.", 409)
        if not team["team_allowed"]:
            return api_error("This quest is designed for solo participation.", 400)
        membership = db.execute(
            "SELECT id FROM challenge_members WHERE user_id=? AND challenge_id=? AND status='active'",
            (user["id"], team["challenge_id"]),
        ).fetchone()
        if not membership:
            return api_error("Join the related quest before requesting a squad spot.", 403)
        if team["member_count"] >= team["capacity"]:
            return api_error("This squad is full.", 409)
        existing_membership = db.execute(
            "SELECT 1 FROM team_members tm JOIN teams t ON t.id=tm.team_id WHERE t.challenge_id=? AND tm.user_id=?",
            (team["challenge_id"], user["id"]),
        ).fetchone()
        if existing_membership:
            return api_error("You're already in a squad for this quest.", 409)
        existing = db.execute("SELECT id, status FROM team_join_requests WHERE team_id=? AND user_id=?", (team_id, user["id"])).fetchone()
        if existing and existing["status"] == "pending":
            return api_error("Your request is already waiting for the squad captain.", 409)
        if existing:
            db.execute("UPDATE team_join_requests SET status='pending', requested_at=?, reviewed_by=NULL, reviewed_at=NULL WHERE id=?",
                       (now_iso(), existing["id"]))
        else:
            db.execute("INSERT INTO team_join_requests(team_id, user_id, status, requested_at) VALUES (?, ?, 'pending', ?)",
                       (team_id, user["id"], now_iso()))
        record_activity(db, user["id"], "team-request", f"Requested to join {team['name']}")
    return jsonify({"ok": True, "message": "Request sent. The squad captain can review it."})


@app.get("/api/teams/<int:team_id>")
@login_required
def team_detail(team_id):
    user = current_user()
    with get_db() as db:
        team = db.execute(
            """SELECT t.*, c.title AS challenge_title,
               (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id=t.id) AS member_count,
               EXISTS(SELECT 1 FROM team_members tm WHERE tm.team_id=t.id AND tm.user_id=?) AS is_member,
               EXISTS(SELECT 1 FROM team_join_requests r WHERE r.team_id=t.id AND r.user_id=? AND r.status='pending') AS requested,
               (EXISTS(SELECT 1 FROM challenge_members cm WHERE cm.challenge_id=t.challenge_id AND cm.user_id=? AND cm.status='active')
                AND NOT EXISTS(SELECT 1 FROM team_members tm2 JOIN teams t2 ON t2.id=tm2.team_id WHERE t2.challenge_id=t.challenge_id AND tm2.user_id=?)) AS can_join,
               CASE WHEN t.created_by=? THEN 1 ELSE 0 END AS is_owner
               FROM teams t JOIN challenges c ON c.id=t.challenge_id WHERE t.id=? AND c.status='approved'""",
            (user["id"], user["id"], user["id"], user["id"], user["id"], team_id),
        ).fetchone()
        if not team:
            return api_error("This squad could not be found.", 404)
        members = db.execute(
            """SELECT u.id, CASE WHEN u.profile_public=1 OR u.id=? THEN u.name ELSE 'CampusQuest member' END AS name,
               tm.role, u.department, u.study_year
               FROM team_members tm JOIN users u ON u.id=tm.user_id WHERE tm.team_id=? ORDER BY CASE tm.role WHEN 'captain' THEN 0 ELSE 1 END, tm.joined_at""",
            (user["id"], team_id),
        ).fetchall()
        requests = []
        if team["created_by"] == user["id"]:
            requests = [dict(row) for row in db.execute(
                """SELECT r.id, u.name, u.department, u.study_year, r.requested_at
                   FROM team_join_requests r JOIN users u ON u.id=r.user_id
                   WHERE r.team_id=? AND r.status='pending' ORDER BY r.requested_at""", (team_id,)
            ).fetchall()]
    team_payload = dict(team)
    team_payload["is_full"] = team_payload["member_count"] >= team_payload["capacity"]
    return jsonify({"ok": True, "team": team_payload, "members": [dict(row) for row in members], "requests": requests})


@app.post("/api/team-requests/<int:request_id>/review")
@login_required
def review_team_request(request_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower()
    if action not in {"accept", "decline"}:
        return api_error("Choose accept or decline.")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT r.*, t.created_by, t.capacity, t.challenge_id,
               (SELECT COUNT(*) FROM team_members tm WHERE tm.team_id=t.id) AS member_count
               FROM team_join_requests r JOIN teams t ON t.id=r.team_id
               JOIN challenges c ON c.id=t.challenge_id
               WHERE r.id=? AND r.status='pending' AND c.status='approved'""", (request_id,)
        ).fetchone()
        if not row:
            return api_error("This request has already been reviewed.", 404)
        if row["created_by"] != user["id"]:
            return api_error("Only the squad captain can review join requests.", 403)
        if action == "accept":
            already_member = db.execute("SELECT id FROM team_members WHERE team_id=? AND user_id=?",
                                        (row["team_id"], row["user_id"])).fetchone()
            active_challenge_member = db.execute(
                "SELECT id FROM challenge_members WHERE user_id=? AND challenge_id=? AND status='active'",
                (row["user_id"], row["challenge_id"]),
            ).fetchone()
            if not already_member and not active_challenge_member:
                return api_error("This student must still be active in the related quest before joining the squad.", 409)
            if not already_member:
                other_squad = db.execute(
                    "SELECT 1 FROM team_members tm JOIN teams t ON t.id=tm.team_id WHERE t.challenge_id=(SELECT challenge_id FROM teams WHERE id=?) AND tm.user_id=?",
                    (row["team_id"], row["user_id"]),
                ).fetchone()
                if other_squad:
                    return api_error("This student has already joined another squad for the quest.", 409)
                if row["member_count"] >= row["capacity"]:
                    return api_error("The squad is full. You cannot accept another member.", 409)
                db.execute("INSERT INTO team_members(team_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                           (row["team_id"], row["user_id"], now_iso()))
                record_activity(db, row["user_id"], "team", "A squad accepted your request")
                award_badge(db, row["user_id"], "squad-star")
        db.execute("UPDATE team_join_requests SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
                   ("accepted" if action == "accept" else "declined", user["id"], now_iso(), request_id))
    return jsonify({"ok": True, "message": "Student added to your squad." if action == "accept" else "Request declined."})


@app.post("/api/teams/<int:team_id>/kudos")
@login_required
def give_peer_kudos(team_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    try:
        recipient_id = int(data.get("to_user_id"))
    except (TypeError, ValueError):
        return api_error("Choose a squad member.")
    message = str(data.get("message", "")).strip()[:240]
    if len(message) < 8:
        return api_error("Write a short, specific note (at least 8 characters).")
    with get_db() as db:
        team = db.execute("SELECT challenge_id FROM teams WHERE id=?", (team_id,)).fetchone()
        if not team:
            return api_error("This squad could not be found.", 404)
        memberships = db.execute(
            "SELECT user_id FROM team_members WHERE team_id=? AND user_id IN (?, ?)",
            (team_id, user["id"], recipient_id),
        ).fetchall()
        if len(memberships) != 2 or recipient_id == user["id"]:
            return api_error("Peer kudos is for another member of your own squad.", 403)
        participated = db.execute(
            "SELECT COUNT(*) FROM challenge_members WHERE challenge_id=? AND user_id IN (?, ?) AND progress>0",
            (team["challenge_id"], user["id"], recipient_id),
        ).fetchone()[0]
        if participated != 2:
            return api_error("Both teammates need at least one recorded check-in before peer kudos.", 409)
        try:
            db.execute(
                "INSERT INTO peer_kudos(team_id, challenge_id, from_user_id, to_user_id, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (team_id, team["challenge_id"], user["id"], recipient_id, message, now_iso()),
            )
        except sqlite3.IntegrityError:
            return api_error("You've already given this teammate kudos for this quest.", 409)
        record_activity(db, recipient_id, "kudos", "Received peer recognition from a teammate")
        count = db.execute("SELECT COUNT(*) FROM peer_kudos WHERE to_user_id=?", (recipient_id,)).fetchone()[0]
        badge_awarded = count >= 3 and award_badge(db, recipient_id, "community-spark")
    return jsonify({"ok": True, "message": "Your kudos was added to their community profile.", "badge_awarded": bool(badge_awarded)})


@app.get("/api/kudos")
@login_required
def get_my_kudos():
    user = current_user()
    with get_db() as db:
        rows = db.execute(
            """SELECT k.message, k.created_at, c.title AS challenge_title,
               CASE WHEN u.profile_public=1 THEN u.name ELSE 'A teammate' END AS from_name
               FROM peer_kudos k JOIN users u ON u.id=k.from_user_id
               JOIN challenges c ON c.id=k.challenge_id
               WHERE k.to_user_id=? ORDER BY k.created_at DESC LIMIT 12""", (user["id"],)
        ).fetchall()
    return jsonify({"ok": True, "kudos": [dict(row) for row in rows]})


@app.post("/api/teams/<int:team_id>/join")
@login_required
def join_team(team_id):
    """Backward-compatible endpoint: a join now always requires captain approval."""
    return request_team_join(team_id)


@app.post("/api/challenges/<int:challenge_id>/report")
@login_required
def report_challenge(challenge_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    reason = str(data.get("reason", "")).strip()
    details = str(data.get("details", "")).strip()[:500]
    allowed = {"spam", "misleading", "inappropriate", "unsafe", "copyright", "other"}
    if reason not in allowed:
        return api_error("Choose a valid report reason.")
    with get_db() as db:
        exists = db.execute("SELECT id FROM challenges WHERE id=? AND status='approved'", (challenge_id,)).fetchone()
        if not exists:
            return api_error("This quest is not available to report.", 404)
        try:
            db.execute(
                "INSERT INTO challenge_reports(challenge_id, reported_by, reason, details, created_at) VALUES (?, ?, ?, ?, ?)",
                (challenge_id, user["id"], reason, details, now_iso()),
            )
        except sqlite3.IntegrityError:
            return api_error("You've already reported this quest. The community team can review it.", 409)
    return jsonify({"ok": True, "message": "Thanks. Your report has been sent to the moderation team."})


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return api_error("Please sign in first.", 401)
        if user.get("role") != "admin":
            return api_error("You do not have permission to review community quests.", 403)
        return fn(*args, **kwargs)
    return wrapped


@app.get("/api/admin/pending-challenges")
@admin_required
def pending_challenges():
    with get_db() as db:
        rows = db.execute(
            """SELECT c.*, u.name AS creator_name FROM challenges c
               LEFT JOIN users u ON u.id=c.created_by
               WHERE c.status='pending' ORDER BY c.created_at ASC"""
        ).fetchall()
    return jsonify({"ok": True, "challenges": [dict(row) for row in rows]})


@app.get("/api/admin/pending-submissions")
@admin_required
def pending_submissions():
    with get_db() as db:
        rows = db.execute(
            """SELECT s.*, u.name AS student_name, c.title AS challenge_title
               FROM submissions s JOIN users u ON u.id=s.user_id
               JOIN challenges c ON c.id=s.challenge_id
               WHERE s.is_final=1 AND s.status='pending'
               ORDER BY s.created_at ASC"""
        ).fetchall()
    return jsonify({"ok": True, "submissions": [dict(row) for row in rows]})


@app.post("/api/admin/submissions/<int:submission_id>/review")
@admin_required
def review_submission(submission_id):
    admin = current_user()
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower()
    feedback = str(data.get("feedback", "")).strip()[:500]
    if action not in {"approve", "needs_changes", "reject"}:
        return api_error("Choose approve, needs_changes or reject.")
    if action != "approve" and len(feedback) < 8:
        return api_error("Add at least 8 characters of feedback so the student knows what to do next.")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        submission = db.execute(
            """SELECT s.*, c.title FROM submissions s JOIN challenges c ON c.id=s.challenge_id
               WHERE s.id=? AND s.is_final=1 AND s.status='pending'""",
            (submission_id,),
        ).fetchone()
        if not submission:
            return api_error("This submission is no longer awaiting review.", 404)
        if submission["user_id"] == admin["id"]:
            return api_error("You cannot review your own submission.", 403)
        status = "approved" if action == "approve" else ("needs_changes" if action == "needs_changes" else "rejected")
        db.execute(
            "UPDATE submissions SET status=?, reviewed_by=?, reviewed_at=?, review_feedback=? WHERE id=?",
            (status, admin["id"], now_iso(), feedback, submission_id),
        )
        if action == "approve":
            db.execute(
                "UPDATE challenge_members SET status='completed', completed_at=? WHERE user_id=? AND challenge_id=?",
                (now_iso(), submission["user_id"], submission["challenge_id"]),
            )
            record_activity(db, submission["user_id"], "completed", f"Completed {submission['title']}")
            award_badge(db, submission["user_id"], "quest-finisher")
        elif action == "needs_changes":
            db.execute(
                "UPDATE challenge_members SET status='ready_to_submit', completed_at=NULL WHERE user_id=? AND challenge_id=?",
                (submission["user_id"], submission["challenge_id"]),
            )
            record_activity(db, submission["user_id"], "feedback", f"Received review feedback for {submission['title']}")
        else:
            db.execute(
                "UPDATE challenge_members SET status='submission_rejected', completed_at=NULL WHERE user_id=? AND challenge_id=?",
                (submission["user_id"], submission["challenge_id"]),
            )
            record_activity(db, submission["user_id"], "feedback", f"Final submission rejected for {submission['title']}")
    message = ("Work approved. The completion badge is now on the student's shelf." if action == "approve" else
               "Changes requested. The student can revise and submit again." if action == "needs_changes" else
               "Submission rejected. The student has been notified and can contact a moderator.")
    return jsonify({"ok": True, "status": status, "message": message})


@app.get("/api/admin/reports")
@admin_required
def admin_reports():
    with get_db() as db:
        rows = db.execute(
            """SELECT r.*, c.title AS challenge_title, u.name AS reporter_name
               FROM challenge_reports r JOIN challenges c ON c.id=r.challenge_id
               JOIN users u ON u.id=r.reported_by
               WHERE r.status='open' ORDER BY r.created_at ASC"""
        ).fetchall()
    return jsonify({"ok": True, "reports": [dict(row) for row in rows]})


@app.post("/api/admin/reports/<int:report_id>/review")
@admin_required
def review_report(report_id):
    admin = current_user()
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower()
    if action not in {"dismiss", "hide_challenge"}:
        return api_error("Choose dismiss or hide_challenge.")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        report = db.execute("SELECT * FROM challenge_reports WHERE id=? AND status='open'", (report_id,)).fetchone()
        if not report:
            return api_error("This report has already been reviewed.", 404)
        db.execute(
            "UPDATE challenge_reports SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            ("dismissed" if action == "dismiss" else "actioned", admin["id"], now_iso(), report_id),
        )
        if action == "hide_challenge":
            db.execute("UPDATE challenges SET status='rejected', reviewed_by=?, reviewed_at=?, review_note='Hidden after community report' WHERE id=?",
                       (admin["id"], now_iso(), report["challenge_id"]))
            db.execute(
                "UPDATE challenge_members SET status='challenge_closed' WHERE challenge_id=? AND status IN ('active','ready_to_submit')",
                (report["challenge_id"],),
            )
    return jsonify({"ok": True, "message": "Report reviewed."})


@app.post("/api/admin/challenges/<int:challenge_id>/review")
@admin_required
def review_challenge(challenge_id):
    admin = current_user()
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).lower()
    note = str(data.get("note", "")).strip()[:300]
    if action not in {"approve", "reject"}:
        return api_error("Choose approve or reject.")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        challenge = db.execute("SELECT * FROM challenges WHERE id=? AND status='pending'", (challenge_id,)).fetchone()
        if not challenge:
            return api_error("This community quest is no longer awaiting review.", 404)
        new_status = "approved" if action == "approve" else "rejected"
        db.execute(
            "UPDATE challenges SET status=?, reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
            (new_status, admin["id"], now_iso(), note, challenge_id),
        )
        if action == "approve" and challenge["created_by"]:
            record_activity(db, challenge["created_by"], "created", f"Community quest approved: {challenge['title']}")
            award_badge(db, challenge["created_by"], "quest-maker")
    message = "Quest approved and added to Explore." if action == "approve" else "Quest rejected and kept off the public board."
    return jsonify({"ok": True, "message": message, "status": new_status})


@app.post("/api/muse")
def quest_muse():
    data = request.get_json(silent=True) or {}
    mood = str(data.get("mood", "curious")).lower()
    time_available = str(data.get("time", "30")).lower()
    raw_interests = data.get("interests", [])
    if not isinstance(raw_interests, list):
        raw_interests = []
    interests = [str(x).lower()[:40] for x in raw_interests[:10] if isinstance(x, str)]
    category_map = {
        "creative": ["Creative", "Culture"],
        "social": ["Social", "Community", "Games"],
        "focused": ["Tech", "Learning", "Career"],
        "gentle": ["Wellbeing", "Sustainability", "Learning"],
        "adventurous": ["Sports", "Games", "Culture", "Community"],
        "curious": ["Learning", "Tech", "Culture", "Career"],
        "career": ["Career", "Tech", "Learning"],
        "playful": ["Games", "Sports", "Social", "Culture"],
    }
    preferred = category_map.get(mood, [])
    max_days = 3 if time_available in {"3", "quick"} else (5 if time_available in {"5", "30"} else 14)
    with get_db() as db:
        rows = db.execute("SELECT * FROM challenges WHERE status='approved' AND duration_days<=? ORDER BY id", (max_days,)).fetchall()
    def score(row):
        value = 0
        if row["category"] in preferred:
            value += 4
        if any(term in (row["title"] + " " + row["description"] + " " + row["category"]).lower() for term in interests):
            value += 5
        if row["duration_days"] <= 3:
            value += 2
        return value
    rows = sorted(rows, key=score, reverse=True)
    if not rows:
        return api_error("No matching quests found yet.", 404)
    chosen = rows[0]
    reason = {
        "focused": "A small focused win can make it easier to get into a flow.",
        "creative": "A creative quest gives you room to experiment without overthinking.",
        "social": "This one is better with a buddy — invite someone to make it more fun.",
        "gentle": "Keep it light. A tiny reset still counts as showing up.",
        "adventurous": "Try something a little different and see where it takes you.",
    }.get(mood, "This looks like a nice next step based on the time you have.")
    return jsonify({"ok": True, "suggestion": challenge_json(chosen), "reason": reason, "note": "Quest Muse uses simple matching rules in this starter build; it can be connected to an AI service later."})


@app.post("/api/privacy/leaderboard")
@login_required
def update_leaderboard_privacy():
    user = current_user()
    data = request.get_json(silent=True) or {}
    visible = data.get("show") is True
    with get_db() as db:
        db.execute("UPDATE users SET leaderboard_public=? WHERE id=?", (1 if visible else 0, user["id"]))
    return jsonify({"ok": True, "show": visible, "message": "Your name will appear on the community board." if visible else "Your name is hidden from the community board."})


@app.get("/api/leaderboard")
def leaderboard():
    with get_db() as db:
        rows = db.execute(
            """SELECT u.name,
               (SELECT COUNT(*) FROM challenge_members cm WHERE cm.user_id=u.id AND cm.status='completed') AS completed,
               (SELECT COUNT(*) FROM challenge_members cm WHERE cm.user_id=u.id) AS joined,
               (SELECT COUNT(*) FROM user_badges ub WHERE ub.user_id=u.id) AS badges
               FROM users u WHERE u.leaderboard_public=1
               ORDER BY completed DESC, joined DESC, badges DESC LIMIT 8"""
        ).fetchall()
    return jsonify({"ok": True, "leaders": [dict(r) for r in rows]})


@app.cli.command("create-admin")
@click.option("--name", prompt="Admin name", help="Name shown in the application.")
@click.option("--email", prompt="Admin email", help="Email address for the admin account.")
def create_admin(name, email):
    """Create or promote an admin account from the trusted server terminal."""
    clean_name = str(name).strip()[:60]
    clean_email = str(email).strip().lower()[:120]
    if len(clean_name) < 2 or not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", clean_email):
        raise click.ClickException("Enter a valid name and email address.")
    password = click.prompt("Admin password", hide_input=True, confirmation_prompt=True)
    if len(password) < 12 or len(password) > 128:
        raise click.ClickException("Use an admin password between 12 and 128 characters.")
    with get_db() as db:
        existing = db.execute("SELECT id FROM users WHERE email=?", (clean_email,)).fetchone()
        if existing:
            db.execute(
                "UPDATE users SET name=?, password_hash=?, role='admin' WHERE id=?",
                (clean_name, generate_password_hash(password), existing["id"]),
            )
            message = "Existing account promoted to admin and password updated."
        else:
            db.execute(
                "INSERT INTO users(name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
                (clean_name, clean_email, generate_password_hash(password), now_iso()),
            )
            message = "Admin account created. Sign in through CampusQuest."
    click.echo(message)


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "CampusQuest"})


@app.errorhandler(413)
def too_large(_error):
    return api_error("That request is too large. The starter build accepts requests up to 2 MB.", 413)


@app.errorhandler(500)
def internal_error(_error):
    # Avoid leaking exception details to visitors. Full traces belong in server logs.
    return api_error("Something went wrong on our side. Please try again.", 500)


if __name__ == "__main__":
    init_db()
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 5000)))
else:
    init_db()
