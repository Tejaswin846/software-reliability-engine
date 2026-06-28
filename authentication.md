# Software Authentication

Software uses Clerk for sign-up, login, logout, password reset, email
verification, Google OAuth, GitHub OAuth, and JWT/session validation.

Supabase is not an auth provider in Software. It is used only for database and
storage records keyed by the Clerk user id.

## Public Routes

- `/`
- `/docs`
- `/install`
- `/sdk`
- `/pricing`
- `/health`
- `/status`

The SDK can be installed and used locally without signing in:

```bash
pip install software-sdk
npm install software-sdk
```

## Protected Routes

- `/dashboard`
- `/projects`
- `/workflows`
- `/memory`
- `/api-keys`
- `/apps`
- cloud workflow execution APIs

Protected API requests send:

```text
Authorization: Bearer CLERK_SESSION_JWT
```

SDK cloud ingestion can also use a project API key:

```text
SOFTWARE_API_KEY=sw_...
```

## Environment Variables

```text
CLERK_SECRET_KEY=replace-with-your-clerk-secret-key
CLERK_PUBLISHABLE_KEY=replace-with-your-clerk-publishable-key
CLERK_JWT_ISSUER=https://your-clerk-instance.clerk.accounts.dev
CLERK_WEBHOOK_SECRET=replace-with-your-clerk-webhook-secret
SOFTWARE_CLERK_AUTH_REQUIRED=true
```
