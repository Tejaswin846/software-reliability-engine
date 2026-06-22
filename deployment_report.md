# Phase 13 Cloud Deployment Report

Generated: 2026-06-20T19:39:13.9540197+05:30

## Deployment Target

Selected target: Azure VM

- VM name: `Nexora`
- Public IP: `52.237.82.140`
- OS: Ubuntu 24.04 LTS
- Deployment path: `/home/azureuser/software-platform`
- Runtime: Python 3.12 virtual environment
- App service port on VM: `8300`

Docker and Render were not used for the live deployment because Docker, Azure CLI, and Render CLI are not installed on the local Windows machine. Docker deployment artifacts still exist in the project.

## Public URL

Current public URL:

```text
https://honey-supplies-dave-tony.trycloudflare.com
```

Dashboard:

```text
https://honey-supplies-dave-tony.trycloudflare.com/dashboard
```

Note: This is a Cloudflare quick tunnel URL. It can change if the tunnel process restarts. To retrieve the latest URL:

```bash
ssh 52.237.82.140 "journalctl -u software-platform-tunnel.service -n 120 --no-pager | grep -Eo 'https://[^ ]+trycloudflare.com' | tail -1"
```

## Services Deployed

### Software FastAPI Service

Systemd unit:

```text
software-platform.service
```

Status:

```text
active
enabled
```

Purpose:

- Runs the FastAPI API.
- Serves the reliability dashboard.
- Loads the SQLite databases.
- Automatically restarts on crash or reboot.

### Public Tunnel Service

Systemd unit:

```text
software-platform-tunnel.service
```

Status:

```text
active
enabled
```

Purpose:

- Exposes `http://127.0.0.1:8300` through a public HTTPS URL.
- Avoids changing the existing Nexora service on port `8000`.
- Avoids Azure NSG edits because Azure CLI/credentials were not available.

## Environment Configuration

Production environment:

```text
SOFTWARE_ENV=production
SOFTWARE_VERSION=0.2.0
SOFTWARE_API_DB_PATH=/home/azureuser/software-platform/Software/data/software_reliability.db
RELIABILITY_DB_PATH=/home/azureuser/software-platform/Software/data/reliability.db
HOST=0.0.0.0
PORT=8300
```

## Database Deployment

SQLite databases deployed:

- `/home/azureuser/software-platform/Software/data/software_reliability.db`
- `/home/azureuser/software-platform/Software/data/reliability.db`

The `/health` startup checks confirm:

- API database reachable
- Reliability database reachable
- Dashboard assets reachable

## Public Endpoint Verification

Verified from local Windows machine through the public URL:

| Endpoint | Result |
| --- | --- |
| `/health` | 200 |
| `/status` | 200 |
| `/metrics` | 200 |
| `/dashboard` | 200 |
| `/api/dashboard` | 200 |

Verified locally on the Azure VM:

| Endpoint | Result |
| --- | --- |
| `http://127.0.0.1:8300/health` | 200 |
| `http://127.0.0.1:8300/dashboard` | 200 |

## Existing Nexora Service

The existing Nexora app remains untouched:

- Existing service: `nexora.service`
- Existing public port: `8000`
- Existing app response: `/health` returns the Nexora Agent service

Software was deployed separately on port `8300`.

## Operational Commands

Check Software service:

```bash
ssh 52.237.82.140 "systemctl status software-platform.service --no-pager"
```

Restart Software service:

```bash
ssh 52.237.82.140 "sudo systemctl restart software-platform.service"
```

Check public tunnel:

```bash
ssh 52.237.82.140 "systemctl status software-platform-tunnel.service --no-pager"
```

Restart public tunnel:

```bash
ssh 52.237.82.140 "sudo systemctl restart software-platform-tunnel.service"
```

Get latest public URL:

```bash
ssh 52.237.82.140 "journalctl -u software-platform-tunnel.service -n 120 --no-pager | grep -Eo 'https://[^ ]+trycloudflare.com' | tail -1"
```

## Limitations

- Azure NSG blocks direct public access to port `8300`.
- The VM does not have a managed identity, so the NSG could not be updated automatically.
- The current public URL is a Cloudflare quick tunnel URL, not a permanent custom domain.

## Recommendation

For a permanent production URL, choose one of these:

1. Open Azure NSG inbound access for port `8300` and use `http://52.237.82.140:8300/dashboard`.
2. Put Nginx on port `80/443` and route `/software` to `127.0.0.1:8300`.
3. Replace the quick tunnel with a named Cloudflare Tunnel attached to a real domain.
4. Deploy the Docker image to Render, Azure Container Apps, or another container host.

## Conclusion

Phase 13 is deployed. The Software platform is running on the Azure VM, the dashboard and API are accessible through a public HTTPS URL, SQLite databases load successfully, health monitoring is active, and both the app service and tunnel service are configured for automatic restart.
