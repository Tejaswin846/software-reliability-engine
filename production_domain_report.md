# Production Domain Report

## Phase 25 Goal

Prepare Software to move from temporary `trycloudflare.com` URLs to a permanent production domain.

## Target Production Domains

```text
software.yourdomain.com
app.yourdomain.com
api.yourdomain.com
```

Recommended canonical dashboard:

```text
https://software.yourdomain.com/dashboard
```

Recommended SDK/API base URL:

```text
https://api.yourdomain.com
```

## Current Azure Origin

```text
52.237.82.140
```

## Application Changes

Added production-domain support in `Software/app.py`:

- HTTPS redirect support.
- `www` redirect support.
- Canonical host redirect support.
- Domain configuration exposed in `/status`.

New environment variables:

```text
SOFTWARE_PUBLIC_URL=https://software.yourdomain.com
SOFTWARE_PRIMARY_HOST=software.yourdomain.com
SOFTWARE_PRODUCTION_HOSTS=software.yourdomain.com,app.yourdomain.com,api.yourdomain.com
SOFTWARE_REDIRECT_HOSTS=yourdomain.com,www.yourdomain.com,www.software.yourdomain.com,www.app.yourdomain.com,www.api.yourdomain.com
SOFTWARE_FORCE_HTTPS=true
SOFTWARE_REDIRECT_WWW=true
SOFTWARE_ALLOWED_ORIGINS=https://software.yourdomain.com,https://app.yourdomain.com,https://api.yourdomain.com
```

## Documentation Created

```text
domain_setup.md
production_dns.md
ssl_setup.md
```

## DNS Records Required

Recommended Cloudflare records:

| Type | Name | Target | Proxy |
| --- | --- | --- | --- |
| A | software | 52.237.82.140 | Proxied |
| CNAME | app | software.yourdomain.com | Proxied |
| CNAME | api | software.yourdomain.com | Proxied |
| CNAME | www | software.yourdomain.com | Proxied |
| A | @ | 52.237.82.140 | Proxied |

## SSL Plan

Recommended production setup:

```text
Cloudflare Full (strict)
Caddy reverse proxy on Azure VM
Automatic Let's Encrypt renewal
```

Required Azure inbound ports:

```text
80/tcp
443/tcp
```

## Verification Completed

Local production-mode checks passed:

- HTTP to HTTPS redirect works.
- `www` redirect works.
- `software.yourdomain.com`, `app.yourdomain.com`, and `api.yourdomain.com` are accepted as production hosts.
- `/status` exposes domain configuration.
- Python backend compile passed.

Azure deployment checks passed:

- FastAPI service restarted successfully.
- `/health` returned OK.
- `/dashboard` returned 200.
- `/login` returned 200.
- `/api/billing/plans` returned 200.
- New domain setup docs are present on the server.

Temporary public URL checks passed:

```text
https://adopted-iso-ist-affects.trycloudflare.com/dashboard
https://adopted-iso-ist-affects.trycloudflare.com/login
https://adopted-iso-ist-affects.trycloudflare.com/api/billing/plans
```

SDK verification passed:

- Created a throwaway user.
- Created a throwaway project.
- Generated a project API key.
- Sent one SDK workflow into the platform.
- Workflow ID: `wf_2d05dae6357940ce97ecd69a68af8432`.

## Verification To Complete After Real DNS Is Added

```bash
curl -I https://software.yourdomain.com/health
curl -I https://software.yourdomain.com/dashboard
curl -I https://software.yourdomain.com/login
curl -I https://api.yourdomain.com/api/billing/plans
curl -I http://www.yourdomain.com/dashboard
```

Expected:

- Dashboard works.
- Login works.
- API works.
- SDK can post workflow data using `https://api.yourdomain.com`.
- HTTP and `www` requests redirect to the canonical HTTPS domain.

## Current Limitation

A permanent public URL cannot be activated until the real domain name and DNS provider access are available.

Until then, the temporary Cloudflare tunnel URL can still be used for testing.

## Conclusion

Software is now prepared for permanent custom-domain hosting. The remaining production step is to add DNS records for the real domain and place Caddy or an equivalent HTTPS reverse proxy in front of the FastAPI service.
