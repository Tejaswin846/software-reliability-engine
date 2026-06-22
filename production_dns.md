# Production DNS Setup

## DNS Target

Azure VM public IP:

```text
52.237.82.140
```

Replace `yourdomain.com` with the real domain.

## Required DNS Records

Recommended Cloudflare DNS records:

| Type | Name | Target | Proxy | Purpose |
| --- | --- | --- | --- | --- |
| A | `software` | `52.237.82.140` | Proxied | Main dashboard and canonical app |
| CNAME | `app` | `software.yourdomain.com` | Proxied | Browser app alias |
| CNAME | `api` | `software.yourdomain.com` | Proxied | API and SDK alias |
| CNAME | `www` | `software.yourdomain.com` | Proxied | Redirect to canonical host |
| A | `@` | `52.237.82.140` | Proxied | Apex redirect to canonical host |

Alternative: use A records for all subdomains:

| Type | Name | Target | Proxy |
| --- | --- | --- | --- |
| A | `software` | `52.237.82.140` | Proxied |
| A | `app` | `52.237.82.140` | Proxied |
| A | `api` | `52.237.82.140` | Proxied |
| A | `www` | `52.237.82.140` | Proxied |
| A | `@` | `52.237.82.140` | Proxied |

## Cloudflare SSL/TLS Settings

Use these settings:

```text
SSL/TLS encryption mode: Full (strict)
Always Use HTTPS: On
Automatic HTTPS Rewrites: On
Minimum TLS Version: TLS 1.2
Universal SSL: Enabled
HTTP/2: Enabled
HTTP/3: Enabled
Brotli: Enabled
```

## Cloudflare Redirect Handling

Application redirects are already supported by Software with:

```text
SOFTWARE_PRIMARY_HOST=software.yourdomain.com
SOFTWARE_REDIRECT_HOSTS=yourdomain.com,www.yourdomain.com,www.software.yourdomain.com,www.app.yourdomain.com,www.api.yourdomain.com
SOFTWARE_FORCE_HTTPS=true
SOFTWARE_REDIRECT_WWW=true
```

Optional Cloudflare redirect rules:

```text
http://*yourdomain.com/*
  -> https://software.yourdomain.com/$2

https://www.yourdomain.com/*
  -> https://software.yourdomain.com/$1
```

If using Caddy redirects on the VM, Cloudflare redirect rules are optional.

## DNS Propagation Checks

Run:

```bash
nslookup software.yourdomain.com
nslookup app.yourdomain.com
nslookup api.yourdomain.com
```

Expected target:

```text
52.237.82.140
```

If Cloudflare proxy is enabled, `nslookup` may show Cloudflare edge IPs instead. That is normal. Use Cloudflare DNS UI to confirm the origin target is `52.237.82.140`.

## API Endpoint Mapping

Recommended production routes:

```text
https://software.yourdomain.com/dashboard
https://software.yourdomain.com/login
https://software.yourdomain.com/register
https://api.yourdomain.com/health
https://api.yourdomain.com/status
https://api.yourdomain.com/metrics
https://api.yourdomain.com/api/billing/plans
```

## Stripe URLs

Update Stripe settings after the domain is live:

```text
STRIPE_SUCCESS_URL=https://software.yourdomain.com/dashboard?checkout=success
STRIPE_CANCEL_URL=https://software.yourdomain.com/pricing?checkout=cancelled
STRIPE_PORTAL_RETURN_URL=https://software.yourdomain.com/dashboard?billing=portal
```

Webhook endpoint:

```text
https://api.yourdomain.com/api/billing/webhook
```
