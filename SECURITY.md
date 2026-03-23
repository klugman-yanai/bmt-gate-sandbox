# Security policy

## Supported versions

Security fixes are applied to the **default branch** (`dev` or as configured for this repository). Use the latest commit for production deployments.

## Reporting a vulnerability

**Do not** open a public GitHub issue for undisclosed security vulnerabilities (including leaked credentials, bucket data exposure, or authentication bypasses).

Please report security issues **privately** to the repository maintainers using one of these channels:

- Use **[GitHub private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)** for this repository, if enabled; or
- Contact the owning team through your organization’s **internal security** or **engineering** channel.

Include:

- A description of the issue and its **impact**
- **Steps to reproduce** (or proof-of-concept) if safe to share
- **Affected components** (e.g. GitHub Actions, Cloud Run, GCS, secrets)
- Whether the issue is **already exploited** or **public**

## Scope

In scope for reports:

- This repository’s **CI workflows**, **BMT CLI** (`.github/bmt/`), **GCP integration** (WIF, Workflows, Cloud Run, GCS paths), and **secrets handling** as documented in [docs/configuration.md](docs/configuration.md).

Out of scope:

- **Third-party** issues (GitHub, Google Cloud platform) — report through their programs
- **Social engineering** or **physical** attacks

## What to expect

Maintainers will acknowledge receipt as soon as practical and coordinate **fix and disclosure** timelines. Please allow time for validation and patching before public discussion.
