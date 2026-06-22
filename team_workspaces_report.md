# Team Workspaces Report

Generated: 2026-06-21

## Goal

Allow organizations and teams to collaborate inside Software.

## Database

Created:

```text
organizations
organization_members
invitations
```

Updated:

```text
projects.organization_id
```

This allows projects to remain personal or become organization-owned.

## Roles

```text
owner
admin
developer
viewer
```

Permissions:

- owner: full access
- admin: manage organization projects and team members below admin
- developer: use projects and API keys
- viewer: read-only access

## Features

Implemented:

- create organization
- invite member
- remove member
- transfer ownership
- organization project access
- organization API key access
- member and invitation dashboard data

## APIs

Created:

```text
POST /api/orgs
GET  /api/orgs
POST /api/orgs/invite
POST /api/orgs/remove
POST /api/orgs/transfer-ownership
GET  /api/orgs/members
```

## Dashboard

Added:

```text
Team Management
```

The dashboard shows:

- organization count
- member count
- pending invitations
- organization list
- member list
- invitation list

## Current Behavior

Invitations are stored locally. If the invited email already belongs to a registered user, Software immediately adds that user as a member and marks the invitation as accepted.

If the invited email does not belong to a registered user, the invitation stays pending.

The next production step is adding email delivery and invitation acceptance links.
