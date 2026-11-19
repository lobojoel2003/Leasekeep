# Changelog

All notable changes to Leasekeep are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Leasekeep
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-19

The first release of Leasekeep: stewardship software for community land trusts.

### Added

- **Resale formula engine** for appraisal-based (shared appreciation, optionally scaled by
  purchase price ÷ initial appraisal), indexed (AMI or CPI) and fixed-rate (simple or compound)
  formulas, with capital improvement credits (full or straight-line depreciated), an optional
  cap at appraised value, an optional purchase-price floor and configurable rounding. Every
  price comes with a step-by-step worksheet. Tests reproduce published examples from HUD,
  Champlain Housing Trust, CPAH, Flagstaff, One Roof, Housing Land Trust of the North Bay,
  San Francisco MOHCD, Big River CLT, Homestead CLT, Houston CLT and the UT Austin CLT toolkit.
- **Home timeline** from land acquisition and purchase to resale: subsidies, appraisals, ground
  leases, yearly lease fee summaries, improvements, occupancy checks and refinances.
- **Formula price page** with the math visible, the sources of every input, a *What if…*
  calculator and a printable worksheet.
- **Resale workflow** that prices the sale, closes the seller's ownership and lease, and opens
  the buyer's with a new ground lease.
- **Lease fees**: idempotent monthly billing, oldest-first payment application, late fees,
  waivers, per-lease ledgers and 30/60/90-day aging.
- **Online payments** through Stripe Checkout (ACH bank transfer and card) with signed,
  idempotent webhooks, including delayed ACH settlement.
- **Owner-occupancy checks** scheduled each year, with owner self-certification in the portal
  and staff review.
- **Capital improvement credits** requested by owners with receipts and approved by staff.
- **Refinance approvals** checked against a loan-to-formula-price policy.
- **Homeowner portal**: balance and payments, resale value with the math, improvement and
  refinance requests, yearly certification, and the home's timeline.
- **Portal invitations** by email, and sign-in by email or username.
- **Dashboard** with portfolio tiles, a billed-vs-collected chart, a work queue, late accounts
  and affordability preserved.
- **Board report** for any fiscal year (HTML and CSV), **HUD HOME compliance export** using the
  2025 HOME rule thresholds for commitments from April 20, 2025 and the prior thresholds before
  that, plus portfolio valuation, aging and payments CSV exports.
- `seed_demo`, `generate_lease_charges` and `schedule_occupancy_checks` management commands.
- Production Docker image (non-root, health check, WhiteNoise static files, build metadata),
  `docker-compose.yml` with PostgreSQL 16, and `/healthz` reporting version and build.
- CI on Python 3.12 and 3.13 with PostgreSQL 16, and a release pipeline that publishes a
  multi-architecture image to GHCR and a GitHub Release with checksummed artifacts.

[Unreleased]: https://github.com/lobojoel2003/Leasekeep/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/lobojoel2003/Leasekeep/releases/tag/v1.0.0
