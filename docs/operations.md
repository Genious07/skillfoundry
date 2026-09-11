# Local operations

Run `make install` once, then `make dev`. The server listens on 127.0.0.1:8020
and serves the production web bundle. For frontend development, run the API and
`cd apps/web && npm run dev` in separate terminals; Vite proxies `/api` locally.

`GET /api/health` checks the SQLite connection. The default database is
`skillfoundry.db` in this checkout; `SKILLFOUNDRY_DB` overrides it. Keep the
checkout's fixtures available. Start with a fresh path to create another workspace.

For a backup, stop the server, copy the database and any SQLite sidecar files
together, then restart. Restore with the server stopped. Do not copy a live WAL
database using ordinary file copy. Unknown database schema versions fail closed;
this release creates version 1 and has no cross-version migration framework.

The service has local host/origin checks and a 128 KiB request limit, but no user
authentication. Do not bind it to a public interface or reverse-proxy it as a team
service. There are no secrets or model credentials to configure.

Evaluations use the bundled finite suite synchronously. Exported JSON includes
synthetic input rows and your correction reasons; inspect it before sharing.
Saved records are append-only through the API. Changing fixtures requires a
server restart and creates different fixture identities for subsequent runs.

Run `make test` for Python tests, frontend tests and a production build.
