# Software Authentication

Phase 16 adds account-based authentication to Software.

## Auth Endpoints

```text
POST /auth/register
POST /auth/login
POST /auth/logout
GET  /auth/me
```

## Register

```bash
curl -X POST http://127.0.0.1:8300/auth/register \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"dev@example.com\",\"password\":\"change-this-password\"}"
```

Response includes a JWT access token:

```json
{
  "ok": true,
  "access_token": "...",
  "token_type": "bearer",
  "expires_at": "..."
}
```

## Login

```bash
curl -X POST http://127.0.0.1:8300/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"dev@example.com\",\"password\":\"change-this-password\"}"
```

## Authenticated Requests

Send the JWT with:

```text
Authorization: Bearer YOUR_JWT
```

Example:

```bash
curl http://127.0.0.1:8300/auth/me \
  -H "Authorization: Bearer YOUR_JWT"
```

## Security

- Passwords are hashed with bcrypt.
- JWTs use HS256 and expire according to `SOFTWARE_JWT_EXPIRE_MINUTES`.
- Set `SOFTWARE_JWT_SECRET` to a strong secret in production.
- Logout is stateless for now; clients remove the JWT locally.

## Environment Variables

```text
SOFTWARE_JWT_SECRET=replace-with-a-long-random-secret
SOFTWARE_JWT_EXPIRE_MINUTES=1440
SOFTWARE_ENABLE_BOOTSTRAP_DEV_KEY=false
```

The bootstrap dev key exists only for local migration compatibility. Disable it in production.
