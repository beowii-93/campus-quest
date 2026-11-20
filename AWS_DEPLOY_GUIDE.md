# CampusQuest — AWS Elastic Beanstalk first deployment (Windows)

This package is prepared for a **first public preview** of CampusQuest on AWS Elastic Beanstalk. It includes `application.py` at the ZIP root, which exposes the Flask app as the WSGI callable AWS expects.

## Important cost and data warnings

- Elastic Beanstalk has no separate service fee, but the AWS resources it creates (especially EC2, storage, data transfer, and any load balancer/database) can be billed. Check the estimate and your AWS Free plan/credits before creating the environment. AWS budgets are alerts, not hard spending caps.
- This first preview still uses SQLite on the EC2 instance. Do not use it for important real student accounts or files. Instance replacement, redeployment or storage changes can lose this database. Before onboarding real users, migrate the app's SQLite data layer to PostgreSQL on Amazon RDS, configure backups, HTTPS, and restricted access.
- The initial Elastic Beanstalk URL may be HTTP. For a short smoke test only, set `COOKIE_SECURE=0` so login sessions work over that HTTP URL. Do not use real passwords or student personal information during this HTTP preview. Configure HTTPS first, then change `COOKIE_SECURE=1` and redeploy before any real users sign up.

## 1. Prepare

1. Extract the ZIP.
2. The ZIP root must directly contain `application.py`, `app.py`, `requirements.txt`, `templates/` and `static/`.
3. Do not upload `.env`, `.venv`, `.git`, local database files or private uploads.
4. Confirm the app runs locally before deploying.

## 2. Create the environment

1. Open https://console.aws.amazon.com/elasticbeanstalk/home?region=ap-south-1
2. Confirm region **Asia Pacific (Mumbai) — ap-south-1**.
3. Choose **Create application**.
4. Application name: `CampusQuest`.
5. Environment tier: **Web server environment**.
6. Environment name: `campusquest-preview`.
7. Platform: **Python**. Choose **Python 3.13** if available; otherwise choose a currently supported branch compatible with the app's dependencies. AWS's currently supported platform list may change, so use the options shown in your region.
8. Application code: **Upload your code** and upload this ZIP as-is.
9. Choose a **single-instance** preset if available. Avoid a load-balanced environment for this preview.
10. Review the cost estimate and instance type before creating. Create only if the expected charges are acceptable.

Elastic Beanstalk uses the `application.py` file and its `application` callable as the default WSGI entry point. `requirements.txt` is used to install dependencies. Gunicorn is included for Linux by the requirements marker.

## 3. Set environment properties

After the environment is created, open **Configuration** → **Updates, monitoring, and logging** (or **Software**, depending on the console layout) → **Edit** → **Runtime environment variables**.

Set:

- `APP_ENV` = `production`
- `FLASK_DEBUG` = `0`
- `SECRET_KEY` = a newly generated long random value
- `ENABLE_DEMO_LOGIN` = `0`
- `APP_TIMEZONE` = `Asia/Kolkata`
- `COOKIE_SECURE` = `0` **only for the temporary HTTP smoke test**

Generate a secret on Windows:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

Keep the generated secret private. Do not put it in the ZIP, source code, GitHub, screenshots, or frontend JavaScript.

## 4. Check the environment

Wait until the environment is healthy. Open its environment URL and check:

- `/healthz` returns JSON containing `"ok": true`.
- Homepage loads and CSS/JavaScript assets load.
- Test-only registration/login works during the temporary preview.
- Challenge discovery and filters load.

The temporary HTTP preview is not suitable for real accounts. Do not share it as a production service until HTTPS and durable database storage are configured.

## 5. HTTPS and real-user readiness

Before any real students sign up:

1. Configure a custom domain and HTTPS certificate (for example with ACM and a supported HTTPS front end/load balancer, or another appropriately maintained TLS setup).
2. Set `COOKIE_SECURE=1` and redeploy.
3. Migrate SQLite usage to PostgreSQL on Amazon RDS; the current code uses `sqlite3` directly, so changing only `DATABASE_PATH` to an RDS URL will not work.
4. Keep RDS private and allow database traffic only from the application security group.
5. Configure database backups and test restoring one.
6. Use S3 with private access and short-lived presigned URLs for proof uploads.
7. Add account verification/recovery, account deletion/data export, and moderation workflows.

## 6. Updating the site

Make changes locally, test them, create a new ZIP with the same root structure and use **Upload and deploy** in the Elastic Beanstalk environment. Wait for health to return to Green and retest `/healthz` plus key user journeys.

## Official AWS documentation

- Flask on Elastic Beanstalk: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create-deploy-python-flask.html
- Python platform / WSGI: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/create-deploy-python-container.html
- Environment variables: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/environments-cfg-softwaresettings.html
- Supported platforms: https://docs.aws.amazon.com/elasticbeanstalk/latest/platforms/platforms-supported.html
- Pricing: https://aws.amazon.com/elasticbeanstalk/pricing/
