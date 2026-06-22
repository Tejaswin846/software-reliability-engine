# SSL Setup

## Goal

Serve Software over HTTPS with automatic certificate renewal.

Production domains:

```text
software.yourdomain.com
app.yourdomain.com
api.yourdomain.com
```

## Recommended Setup

Use:

```text
Cloudflare DNS + Caddy on Azure VM
```

Caddy automatically obtains and renews Let's Encrypt certificates.

## Azure VM Ports

Open:

```text
80/tcp
443/tcp
```

Caddy needs port `80` for HTTP challenge redirects and port `443` for HTTPS traffic.

## Caddyfile

Create:

```bash
sudo nano /etc/caddy/Caddyfile
```

Use:

```text
software.yourdomain.com, app.yourdomain.com, api.yourdomain.com {
    encode gzip
    reverse_proxy 127.0.0.1:8300
}

yourdomain.com, www.yourdomain.com, www.software.yourdomain.com, www.app.yourdomain.com, www.api.yourdomain.com {
    redir https://software.yourdomain.com{uri} permanent
}
```

Validate and reload:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

## Certificate Renewal

Caddy renews certificates automatically.

Check certificate state:

```bash
sudo journalctl -u caddy -n 100 --no-pager
sudo caddy list-certificates
```

## Cloudflare SSL Mode

Set:

```text
SSL/TLS encryption mode: Full (strict)
Always Use HTTPS: On
Automatic HTTPS Rewrites: On
Universal SSL: Enabled
```

With `Full (strict)`, Cloudflare validates the certificate served by Caddy on the Azure VM.

## Software HTTPS Redirects

Set:

```text
SOFTWARE_FORCE_HTTPS=true
SOFTWARE_REDIRECT_WWW=true
SOFTWARE_PRIMARY_HOST=software.yourdomain.com
```

This makes Software redirect non-HTTPS and `www` requests when they reach the app.

## Verification

Run:

```bash
curl -I http://software.yourdomain.com/health
curl -I https://software.yourdomain.com/health
curl -I https://app.yourdomain.com/login
curl -I https://api.yourdomain.com/status
curl -I http://www.yourdomain.com/dashboard
```

Expected:

```text
HTTP requests redirect to HTTPS.
HTTPS requests return 200.
www requests redirect to software.yourdomain.com.
```

## Troubleshooting

If certificate issuance fails:

1. Confirm DNS points to the Azure VM or Cloudflare proxy is forwarding correctly.
2. Confirm Azure allows inbound `80/tcp` and `443/tcp`.
3. Confirm no other service is using ports `80` or `443`.
4. Check Caddy logs:

```bash
sudo journalctl -u caddy -n 200 --no-pager
```

If Cloudflare shows certificate errors:

1. Confirm SSL mode is `Full (strict)`.
2. Confirm Caddy has a valid certificate for each hostname.
3. Temporarily set DNS proxy to DNS-only while issuing certificates, then re-enable proxy.
