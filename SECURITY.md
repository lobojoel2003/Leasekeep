# Security policy

Leasekeep holds personal and financial information about homeowners, so security reports are
taken seriously.

## Supported versions

| Version | Supported |
|---|---|
| 1.x (latest minor) | Yes |
| Older | No. Please upgrade. |

## Reporting a vulnerability

Please **do not** open a public issue. Report it privately through
[GitHub's private vulnerability reporting](https://github.com/lobojoel2003/Leasekeep/security/advisories/new).
Include what you found, how to reproduce it, and what it affects.

You'll get an acknowledgement within a few days. Once a fix is ready, it is released with a
security advisory that credits you unless you'd rather stay anonymous.

## Running Leasekeep safely

- Serve it only over HTTPS and keep `LEASEKEEP_ENV=production`.
- Use a long, random `DJANGO_SECRET_KEY`; never commit `.env`.
- Restrict access to the database and the `/data` media volume, and back both up.
- Give `is_staff` only to land trust staff. Homeowners get portal invitations.
- Keep the image current: each release is rebuilt with patched dependencies.
