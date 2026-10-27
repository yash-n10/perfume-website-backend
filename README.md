# MOHERA FastAPI backend

Provides email OTP verification, signup, login, the current-user endpoint, and public enquiries backed by PostgreSQL.

## Setup

1. Create a virtual environment and install dependencies:

   ```powershell
   cd backend
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env`. Put the Vercel Postgres connection string in `DATABASE_URL`, generate a long random `JWT_SECRET`, and configure SMTP. Keep `.env` private.

3. Run the SQL in the workspace-root `schema.sql` against your Vercel Postgres database.

4. Start the API:

   ```powershell
   uvicorn app.main:app --reload --port 8000
   ```

Interactive API docs are available at `http://localhost:8000/docs`.

## Endpoints

- `POST /api/auth/send-otp` with `{ "email": "name@example.com" }` sends a four-digit email code. Codes expire and are rate-limited.
- `POST /api/auth/verify-otp` with `{ "email": "name@example.com", "code": "1234" }` verifies the latest code.
- `POST /api/auth/signup` with `{ "name": "Full Name", "email": "name@example.com", "phone": "+1 555 0100", "password": "...", "confirm_password": "..." }` creates the account after verification and returns a bearer token.
- `POST /api/auth/login` with `{ "email": "name@example.com", "password": "..." }` returns a bearer token.
- `GET /api/auth/me` returns the signed-in user. Send `Authorization: Bearer <access_token>`.
- `POST /api/enquiries` with `{ "name": "Full Name", "email": "name@example.com", "phone": "+1 555 0100", "enquiry": "Your message" }` saves an enquiry without requiring login.
- `GET /api/health` checks database connectivity.

Configure `CORS_ORIGINS` as a comma-separated list of the frontend origins, including the deployed frontend URL. The current React forms are still demo-only and need to call these endpoints to persist data.