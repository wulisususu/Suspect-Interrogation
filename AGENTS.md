# Repository Execution Rules

These rules are mandatory for all development work on `linux-adaptation`.

## Production deployment is part of Definition of Done

A code change is **not complete** when it is only committed to GitHub or when CI/smoke tests pass.

Every change pushed to `linux-adaptation` must be carried through the production deployment chain and verified on the RK3588 target.

Required completion chain:

1. Commit the final source to `linux-adaptation`.
2. Run and pass the relevant CI gates.
3. Run `RK3588 Production Redeploy` for that exact final commit.
4. Build and install the frontend and backend on the RK3588 production host.
5. Restart the interrogation runtime as part of the atomic deployment.
6. Verify `https://192.168.2.109:18080` is serving the new frontend and backend with a certificate signed by the project LAN CA.
7. Verify `/health/live` and `/health/ready` over HTTPS with certificate verification enabled; do not use `-k` for ordinary production checks.
8. Verify browser audio endpoints derive `wss://` from the HTTPS origin.
9. Verify the deployed release SHA matches the final GitHub commit SHA.
10. Verify relevant user-visible behavior/API behavior on the deployed server.
11. Verify TCP/8000 remains untouched and available for the existing FunASR service.

Do not report a task as "completed", "fixed", or "deployed" until the production verification above succeeds.

If code is committed but production deployment fails, report the exact state as: **code committed, production deployment incomplete** and continue fixing the deployment problem.

## Mandatory production redeploy behavior

`linux-adaptation` is a continuously deployed development branch. Every push to this branch must trigger `.github/workflows/rk3588-production-redeploy.yml`.

Do not rely on meaningless edits to a YAML file solely to trigger deployment. The workflow itself must be configured so ordinary source commits trigger deployment automatically.

A GitHub Actions RK3588 smoke test is not a substitute for production deployment.

## Frontend and backend consistency

Runtime changes must never leave the browser frontend and Linux backend on different source revisions. Production redeploy must stage, build, and atomically switch both from the same Git commit.

The deployed frontend under `/opt/suspect-interrogation/current/webapp/dist` and backend under `/opt/suspect-interrogation/current/linux/backend` must come from the same release directory and commit.

## Trusted LAN TLS

The canonical production URL is `https://192.168.2.109:18080`.

Additional access points served by the same certificate (kept in
`SUSPECT_TLS_EXTRA_SAN`, see `deploy/lib/tls.sh`): the board's current LAN
addresses `https://192.168.0.26:18080` / `https://192.168.0.4:18080` and the
frp public entry `https://124.223.176.99:18080`. Any new access address must be
added to that list before clients can open WebSocket audio channels: browsers
do not extend a "proceed anyway" certificate exception to `new WebSocket`, so a
missing SAN fails silently on the client with no server-side trace.

The project LAN CA and server private keys live under `/etc/suspect-interrogation/tls/` on the RK3588 and must never be committed to GitHub. Production checks must trust the project CA explicitly or through the operating-system trust store. Browser ASR and voiceprint audio must use WSS under the HTTPS origin.

## Database migrations

When a change adds or modifies an Alembic migration, production deployment must apply the migration to the production database before the new runtime is considered ready. A schema created incidentally by ORM `create_all()` is not a substitute for running required migration/backfill logic.

## Port safety

TCP/8000 belongs to the existing FunASR service. Do not bind to it, stop it, restart it, or replace it.

The suspect-interrogation service uses TCP/18080 with HTTPS/TLS.

Production deployment verification must inspect both ports and prove TCP/8000 was preserved.
