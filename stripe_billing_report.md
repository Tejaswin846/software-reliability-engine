# Stripe Billing Report

## Phase 24 Goal

Enable real subscription payments for the Software reliability platform using Stripe.

## Implemented Billing Capabilities

- Free, Pro, and Enterprise plan metadata now includes Stripe price ID support.
- Authenticated users can create Stripe Checkout sessions with `POST /api/billing/checkout`.
- Authenticated users can open the Stripe Billing Portal with `POST /api/billing/portal`.
- Stripe can send subscription and invoice events to `POST /api/billing/webhook`.
- The dashboard now shows current plan, Stripe status, invoice count, invoices, usage, quota, upgrade, and manage/downgrade actions.

## Stripe Environment Variables

```text
SOFTWARE_PUBLIC_URL=https://your-software-domain.example
STRIPE_SECRET_KEY=sk_live_replace_me
STRIPE_WEBHOOK_SECRET=whsec_replace_me
STRIPE_PRO_PRICE_ID=price_replace_me
STRIPE_ENTERPRISE_PRICE_ID=price_replace_me
STRIPE_SUCCESS_URL=
STRIPE_CANCEL_URL=
STRIPE_PORTAL_RETURN_URL=
```

## API Endpoints

```text
POST /api/billing/checkout
POST /api/billing/portal
POST /api/billing/webhook
```

Existing local/dev billing remains available:

```text
GET  /api/billing/plans
GET  /api/billing/me
POST /api/billing/subscribe
```

## Database Updates

Users now store:

```text
stripe_customer_id
```

Subscriptions now store:

```text
stripe_subscription_id
stripe_price_id
stripe_status
```

New tables:

```text
stripe_invoices
stripe_events
```

## Webhook Handling

Handled events:

```text
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
invoice.payment_failed
invoice.payment_succeeded
```

Subscription events sync the local plan and Stripe subscription state.
Invoice events upsert invoice records and update payment status.
Duplicate webhook events are ignored using the Stripe event ID.

## Dashboard

The dashboard billing panel now includes:

- Current Plan
- Monthly Workflows
- Remaining Quota
- API Requests
- Stripe Status
- Invoices
- Upgrade to Pro
- Manage / Downgrade
- Recent invoice list

## Production Notes

- Paid checkout requires `STRIPE_SECRET_KEY` and the matching plan price ID.
- Webhook signature verification is required in production when `STRIPE_WEBHOOK_SECRET` is set.
- The local Free plan switch remains available without Stripe.
- Stripe secrets are read from environment variables and are not committed to source control.

## Result

Software now has the subscription payment foundation needed for a commercial SaaS platform.

## Verification

Completed checks:

- Python backend compile passed.
- Dashboard JavaScript syntax check passed.
- Local temp-database billing smoke test passed.
- Stripe webhook sync created a Pro subscription and stored an invoice in a temp database.
- Azure service restart succeeded.
- Production `/health` returned OK.
- Production `/status` shows `stripe_invoices` and `stripe_events`.
- Public dashboard serves the Billing, Invoices, Upgrade, and Manage / Downgrade controls.
- Public `/api/billing/plans` returns Free, Pro, and Enterprise plans.

Current public dashboard:

```text
https://martial-grad-relief-replacement.trycloudflare.com/dashboard
```

Stripe keys and price IDs are not configured on the deployed environment yet, so paid checkout and portal routes correctly return configuration errors until live Stripe settings are added.
