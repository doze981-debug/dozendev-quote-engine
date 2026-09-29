# Real implementation checklist

## Mandatory before production

- Fill `DOZENDEV_LEGAL_DETAILS`, `DOZENDEV_PEC`, `DOZENDEV_FORUM`.
- Review the price list and replace demo values with the authoritative DozenDev price list.
- Choose the signature provider and implement two distinct signature actions: general signature and art. 1341/1342 approval.
- Attach the actual DPA / AI Addendum / SLA templates when contract flags require them.
- Choose payment provider and map `deposit_created` / `deposit_paid` callbacks.
- Put the application behind HTTPS and authentication for `/internal`.
- Replace SQLite with PostgreSQL before multi-user/high-availability use, or ensure single-instance operation and backups.
- Add SMTP/transactional-email provider for proposal and onboarding delivery.
- Configure retention/backups for signed documents and provider audit trails.
- Add secret management; never put provider credentials in workflow JSON committed to a repository.

## Recommended second pass

- CRM synchronization.
- Project creation in Notion/GitHub/other PM tool on `PROJECT_READY`.
- Invoice generation after signature/deposit event.
- Branded HTML/PDF templates.
- Role-based internal access and quote approval thresholds.
