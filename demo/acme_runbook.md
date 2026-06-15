# Onboarding Runbook — Acme Robotics

_Generated from the provisioned workspace state (verified by reconcile)._

## What was built

### Pipelines
- **Sales Pipeline**: Lead, Qualified, Proposal, Negotiation, Closed Won
- **Onboarding Pipeline**: Kickoff, Configuration, Training, Live

### Custom Fields
- **Contract Value**: number — on **Sales Pipeline**
- **Health Score**: number — on **Onboarding Pipeline**
- **Account Tier**: dropdown — on **Sales Pipeline**

### User Roles
- **CSM**: read-write deals, read contacts
- **Account Exec**: read-write deals
- **Admin**: full access

### Automations
- **Notify CSM on stage change**: Notify CSM on stage change uses Health Score — on **Health Score**
- **Tier upsell alert**: Tier upsell alert uses Account Tier — on **Account Tier**

### Integrations
- **Slack**: Slack
- **Gmail**: Gmail

## Kickoff plan

1. Verify pipeline stages with the customer's RevOps lead.
2. Confirm field-level permissions for each role.
3. Dry-run each automation on a test record.
4. Connect integrations and validate the first sync.
5. Schedule the go-live review.
