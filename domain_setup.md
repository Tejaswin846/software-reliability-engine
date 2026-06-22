# Software Custom Domain Setup

## Goal

Replace temporary `trycloudflare.com` URLs with permanent production domains:

```text
software.yourdomain.com
app.yourdomain.com
api.yourdomain.com
```

Recommended canonical dashboard URL:

```text
https://software.yourdomain.com/dashboard
```

## Production Host Strategy

Use one Azure VM as the origin server and put Cloudflare in front of it.

```text
User
  -> Cloudflare DNS + HTTPS
  -> Azure VM public IP
  -> Caddy or Nginx reverse proxy
  -> FastAPI on 127.0.0.1:8300
```

Current Azure VM public IP:

```text
52.237.82.140
```

## Application Environment

Set these variables on the production VM:

```text
SOFTWARE_ENV=production
SOFTWARE_PUBLIC_URL=https://software.yourdomain.com
SOFTWARE_PRIMARY_HOST=software.yourdomain.com
SOFTWARE_PRODUCTION_HOSTS=software.yourdomain.com,app.yourdomain.com,api.yourdomain.com
SOFTWARE_REDIRECT_HOSTS=yourdomain.com,www.yourdomain.com,www.software.yourdomain.com,www.app.yourdomain.com,www.api.yourdomain.com
SOFTWARE_FORCE_HTTPS=true
SOFTWARE_REDIRECT_WWW=true
SOFTWARE_ALLOWED_ORIGINS=https://software.yourdomain.com,https://app.yourdomain.com,https://api.yourdomain.com
```

The app now performs production redirects when `SOFTWARE_ENV=production`:

- HTTP requests are redirected to HTTPS when `SOFTWARE_FORCE_HTTPS=true`.
- `www.*` hosts are redirected when `SOFTWARE_REDIRECT_WWW=true`.
- Hosts listed in `SOFTWARE_REDIRECT_HOSTS` are redirected to `SOFTWARE_PRIMARY_HOST`.

## Azure VM Reverse Proxy

Recommended: Caddy, because it automatically creates and renews HTTPS certificates.

Install Caddy:

```bash
sudo apt update
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

Create `/etc/caddy/Caddyfile`:

```text
software.yourdomain.com, app.yourdomain.com, api.yourdomain.com {
    encode gzip
    reverse_proxy 127.0.0.1:8300
}

yourdomain.com, www.yourdomain.com, www.software.yourdomain.com, www.app.yourdomain.com, www.api.yourdomain.com {
    redir https://software.yourdomain.com{uri} permanent
}
```

Reload Caddy:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Azure Network Rules

Open these inbound ports in the Azure Network Security Group:

```text
80/tcp
443/tcp
22/tcp
```

Keep FastAPI bound to localhost or protected by the VM firewall:

```text
127.0.0.1:8300
```

## Verification

After DNS propagates, verify:

```bash
curl -I https://software.yourdomain.com/health
curl -I https://software.yourdomain.com/dashboard
curl -I https://app.yourdomain.com/login
curl -I https://api.yourdomain.com/api/billing/plans
curl -I http://www.yourdomain.com/dashboard
```

Expected:

- `/health` returns `200`.
- `/dashboard` loads.
- `/login` loads.
- `/api/billing/plans` returns JSON.
- `www` and HTTP URLs redirect to HTTPS canonical URLs.

## SDK Configuration

External agents should use:

```python
from software_sdk import ReliabilityMonitor

monitor = ReliabilityMonitor(
    project_name="my-agent",
    api_url="https://api.yourdomain.com",
    api_key="sw_live_key"
)
```

If you prefer one domain for everything, use:

```text
https://software.yourdomain.com
```
