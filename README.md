# 🔗 Linklytics — URL Shortening & Analytics Platform

## 📖 Overview

**Linklytics** is a web-based URL shortening and analytics platform developed using **Python, Flask, SQLite, HTML, CSS, and JavaScript**. The project provides a simple way to create, manage, and analyze shortened URLs through a modern dashboard.

The application allows users to register, sign in, create shortened links, customize URL aliases, manage existing links, and track click activity. It also includes analytics features such as daily click trends, referrer information, device categories, and top-performing links.

Linklytics was developed to strengthen my understanding of full-stack web development, REST APIs, database management, authentication, application security, automated testing, and deployment.

---

## 🚀 Live Demo

**Try Linklytics here:** [Linklytics — URL Shortening & Analytics Platform](https://linklytics-url-shortening-analytics.onrender.com)

Explore the live application to experience URL shortening, link management, user authentication, and analytics features.

> **Note:** The live application may take a little time to start after a period of inactivity, depending on the hosting service.

---

## ✨ Features

### Accounts and private workspaces
- Register, sign in, and sign out.
- Passwords stored with Werkzeug's password hashing (never plain text).
- Session cookies are HttpOnly and SameSite=Lax; secure cookies enable when `FLASK_ENV=production`.
- CSRF token validation for state-changing API routes.
- Every link, analytics query, custom domain, and deletion is scoped to the signed-in owner.
- Existing unowned links from a previous local MVP are assigned to the first account that registers, preserving local demo data.

### Links and abuse prevention
- Generated aliases and custom aliases, pause/resume, delete, copy, and CSV export.
- HTTP/HTTPS only; rejects localhost/private IP literals, local/internal hostnames, URL credentials, malformed hosts, and punycode domains by default.
- Redirect targets are read from the database and revalidated before redirecting; no request-supplied open-redirect parameter exists.
- Basic in-process per-IP rate limits for auth, API operations, link creation, and redirects.
- Bot-like user agents are recorded separately and excluded from dashboard analytics.
- Security headers and request body size limit.

### Analytics
- Select 7, 30, or 90-day ranges from the dashboard.
- Daily click trends, referrers, device category, top links, and an approximate unique-visitor count based on a keyed IP/User-Agent hash.
- The visitor count is an estimate, not a verified count of people. Update/rotate `SECRET_KEY` to invalidate old fingerprints.

---

## 🛠️ Technologies Used

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| Flask | Web framework and API development |
| SQLite | Database management |
| HTML5 | Web page structure |
| CSS3 | Styling and dashboard layout |
| JavaScript | Frontend interactions |
| Werkzeug | Password hashing and security utilities |
| Pytest | Automated testing |
| Gunicorn | Production WSGI server |
| Render | Web application deployment |
| Git & GitHub | Version control and source code hosting |

---

## 🧩 Core Components

### 1. User Authentication

Handles account creation and authentication.

**Responsibilities:**

- Register new users
- Authenticate existing users
- Securely hash passwords
- Manage user sessions
- Protect private user data
- Validate requests using CSRF tokens

### 2. URL Management

Manages the creation and maintenance of shortened links.

**Responsibilities:**

- Generate unique short URLs
- Support custom aliases
- Redirect users to original destinations
- Pause or resume links
- Copy and delete links
- Export link information

### 3. Analytics Dashboard

Collects and presents link engagement statistics.

**Responsibilities:**

- Track link clicks
- Display daily click trends
- Analyze referring sources
- Categorize devices
- Identify top-performing links
- Filter analytics by date range

The unique-visitor figure is an estimate based on a privacy-conscious combination of request information, not a verified count of individual people.

### 4. Database Management

Uses SQLite to store application data and maintain relationships between users, links, and analytics.

**Responsibilities:**

- Store user account information
- Maintain shortened URL records
- Associate links with their owners
- Store click and analytics information
- Apply supported schema upgrades

### 5. Security and Validation

Includes several safeguards for a public-facing URL-shortening application.

**Implemented safeguards include:**

- Password hashing
- Session cookie security settings
- CSRF validation for state-changing API requests
- Owner-based access restrictions
- Validation of destination URLs
- Basic request rate limiting
- Security response headers
- Request body size limits

These safeguards provide a foundation for the project; they do not replace a comprehensive production security review.

---

## 🔐 Application Security

Linklytics incorporates security practices intended to protect user accounts and prevent common URL-shortening abuses.

- Passwords are stored using secure password hashing rather than plain text.
- Users can access and manage only their own links.
- Destination URLs are validated before being accepted and redirected to.
- Localhost and private IP destinations are restricted by the application's validation rules.
- State-changing API requests require CSRF token validation.
- Basic rate limits help restrict excessive requests.
- Session cookies use appropriate security settings for the deployment environment.

---

## 🔌 API Overview

The application provides API endpoints for authentication, link management, analytics, custom domains, billing, and health checks.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Register a user |
| POST | `/api/auth/login` | Authenticate a user |
| POST | `/api/auth/logout` | Sign out |
| GET | `/api/auth/me` | Retrieve the current user's session information |
| GET / POST | `/api/links` | List or create shortened links |
| GET | `/api/links/<id>` | Retrieve a link |
| PATCH / DELETE | `/api/links/<id>` | Update or delete a link |
| GET | `/api/analytics?start=YYYY-MM-DD&end=YYYY-MM-DD` | Retrieve analytics for a date range |
| GET / POST | `/api/domains` | List or register custom domains |
| POST | `/api/domains/<id>/verify` | Verify a custom domain |
| DELETE | `/api/domains/<id>` | Remove a custom domain |
| GET | `/api/billing` | Retrieve billing information |
| POST | `/api/billing/checkout` | Initiate a billing checkout |
| GET | `/api/health` | Check application health |

**Note:** State-changing API requests require the appropriate session CSRF token in the `X-CSRF-Token` header.

---

## 💻 How to Run Locally

### Prerequisites

Install the following before running the project:

- Python 3.10 or newer
- Visual Studio Code or another code editor
- Git (optional, for cloning the repository)

### 1. Clone the Repository

```bash
git clone https://github.com/uzaam07/Linklytics-URL-Shortening-Analytics-Platform.git
```

### 2. Open the Project

```bash
cd Linklytics-URL-Shortening-Analytics-Platform
```

Open the folder in Visual Studio Code.

### 3. Create a Virtual Environment

**Windows — PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use Command Prompt:

```bat
.venv\Scripts\activate.bat
```

### 4. Install Dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure Environment Variables

For local development, configure a suitable `SECRET_KEY` using your environment or a local environment file if your application supports it.

Never upload secret keys, credentials, or `.env` files to GitHub.

### 6. Run the Application

```bash
python app.py
```

### 7. Open the Application

Visit the following address in your browser:

```text
http://127.0.0.1:5000
```

Create an account to begin using the application.

---

## 🧪 Running Automated Tests

Linklytics includes automated tests for important application functionality.

Run the test suite with:

```bash
python -m pytest -q
```

The tests cover areas such as:

- User registration and authentication
- User workspace isolation
- Short URL creation
- URL redirects
- Analytics date ranges
- CSRF protection
- Unsafe destination validation
- Custom-domain registration

Automated testing helps verify application behavior and catch regressions during development.

---

## ☁️ Deployment

Linklytics is deployed using Render.

**Live application:** [https://linklytics-url-shortening-analytics.onrender.com](https://linklytics-url-shortening-analytics.onrender.com)

Typical deployment configuration:

| Setting | Value |
|---|---|
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn wsgi:app` |
| Environment | Python |
| Application Framework | Flask |

Configure a strong `SECRET_KEY` in the hosting provider's environment settings. Review the project's deployment configuration before deploying, and ensure the application has persistent storage configured for its SQLite database.

**Database note:** SQLite data may not survive restarts or redeployments if it is stored on an ephemeral filesystem. Persistent storage or a migration to a managed database such as PostgreSQL is recommended for reliable long-term data retention.

---

## 📈 Future Improvements

Potential enhancements for future versions include:

- Email Verification and Password Recovery
- Two-Factor Authentication
- QR Code Generation for Shortened URLs
- Advanced Analytics and Interactive Charts
- Link Expiration and Scheduling
- Bulk URL Shortening
- Enhanced Search and Filtering
- PostgreSQL Database Integration
- Redis-Based Rate Limiting
- Improved Monitoring and Logging
- Custom Domain and HTTPS Automation
- Subscription and Billing Workflow Enhancements
- Automated Deployment and Continuous Integration
- Additional Security and Abuse-Prevention Integrations

---

## 🎯 Learning Outcomes

Through this project, I gained practical experience with:

- Python and Flask web development
- REST API design and implementation
- User authentication and session management
- Password hashing and CSRF protection
- Relational database design using SQLite
- Frontend development with HTML, CSS, and JavaScript
- URL validation and redirect handling
- Analytics data collection and presentation
- Automated testing with Pytest
- Environment configuration and deployment
- Version control using Git and GitHub
- Debugging and improving application reliability

---

## 👨‍💻 Author

- **Name:** Uzaam Shaad K
- **GitHub:** [uzaam07](https://github.com/uzaam07)
- **Portfolio:** [uzaam07.github.io](https://uzaam07.github.io/Portfolio/)
- **LinkedIn:** [linkedin.com/in/uzaamshaad](https://linkedin.com/in/uzaamshaad)

---
