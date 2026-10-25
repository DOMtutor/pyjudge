# Running DOMjudge with Docker

[docker-compose.yml](docker-compose.yml) starts a complete DOMjudge: MariaDB with periodic backups, the `domserver` web application and one `judgehost`.
It is suitable for local development and small courses.
It uses the DOMtutor builds of the DOMjudge images (`incaseoftrouble/domtutor_domserver` and `incaseoftrouble/domtutor_judgehost`, built from DOMtutor's domjudge-packaging with additional packages); the official `domjudge/domserver:9.0.1` and `domjudge/judgehost:9.0.1` work as well (change the `image:` lines).
`tests/integration/run.sh` checks this setup; it uses the official images by default and the DOMtutor ones with `DOMJUDGE_DOMSERVER_IMAGE` and `DOMJUDGE_JUDGEHOST_IMAGE`.

* Install `docker` and `docker compose`
* Create an empty folder and copy `docker-compose.yml` there
* Create a `.env` file in that folder:
  ```
  TZ=Europe/Berlin
  DOMJUDGE_DB_ROOT_PASSWORD=<random>      # database root password
  DOMJUDGE_DB_DOMJUDGE_PASSWORD=<random>  # database user password, goes into pydomjudge's db.yml
  DOMJUDGE_JUDGE_PASSWORD=<random>        # API password of the judgehost user
  DOMJUDGE_PORT=12345                     # optional, port of the web interface
  ```
* `docker compose up -d`
* `docker compose logs domserver` shows the initial admin password (unless you set one via `pydomjudge`)
* Log in at <http://localhost:12345>
* In the web interface, set the password of the `judgehost` user to `DOMJUDGE_JUDGE_PASSWORD` (or run `pyjudge upload password judgehost`)
* `docker compose logs judgehost` should show it connecting and idling
* `docker compose down` stops everything, `docker compose down -v` also deletes the database

The database is exposed on port 3306 for `pydomjudge`.
Do not expose it on a public host; bind it to `127.0.0.1:3306:3306` or run `pydomjudge` on the same machine.

More judgehosts: duplicate the `judgehost` service with a different `container_name`, `hostname` and `DAEMON_ID`.

The domserver image's nginx passes the host name without port to DOMjudge, so with a direct port mapping its redirects (for example to the login page) lose a port like 12345. The small start script in the compose file (`domserver-public-port`) adds `DOMJUDGE_PUBLIC_PORT`, which defaults to `DOMJUDGE_PORT`.
Behind a reverse proxy on the standard ports, the host name is right without it: set `DOMJUDGE_PUBLIC_PORT=` (empty) in `.env`, and the script changes nothing.

## Self-service

The profile `selfservice` adds the [self-service](tools.md#self-service) from the pyjudge image, which is built locally (set `PYJUDGE_IMAGE` in `.env` to use another one):

* In the pyjudge checkout: `docker build -t pyjudge .`
* Add to `.env`:
  ```
  SELFSERVICE_SECRET_KEY=<random>   # python -c 'import secrets; print(secrets.token_urlsafe(32))'
  SELFSERVICE_PORT=8001             # optional
  ```
* Upload the settings with `pyjudge upload settings` first: the self-service checks at startup that its team category (`participants`) exists, and restarts until it does
* `docker compose --profile selfservice up -d`

It listens on `127.0.0.1` only; put a reverse proxy with TLS in front of it (the compose configuration trusts one proxy, `server.trust_proxy: 1`).
The self-service configuration is the `selfservice-config` block in the compose file; edit its `services:` there.
The self-service reaches the database as `domjudge_mariadb` on the compose network, with `DOMJUDGE_DB_DOMJUDGE_PASSWORD`.

## Judgehost errors

The judgehost needs deep access to the host to sandbox and measure submissions, which may require kernel and container flags.

### cgroups

Judgehosts rely on [cgroups](https://en.wikipedia.org/wiki/Cgroups) version 2 with memory accounting enabled.
This is configured through the kernel command line.

With GRUB:
1. Open `/etc/default/grub`
2. Find `GRUB_CMDLINE_LINUX_DEFAULT="..."`
3. Add `cgroup_enable=memory swapaccount=1` (e.g. `GRUB_CMDLINE_LINUX_DEFAULT="quiet splash cgroup_enable=memory swapaccount=1"`)
4. `sudo update-grub` and reboot
5. Verify with `cat /proc/cmdline`

If you get `missing cgroup hierarchy prefix`, the system runs hybrid cgroups; add `cgroup_no_v1=all` (or, for old DOMjudge versions, `systemd.unified_cgroup_hierarchy=0`).
Check `cat /proc/self/cgroup`: any line besides the `0::` one makes the judgehost refuse to start; software that mounts a cgroup-v1 hierarchy at runtime (some VPN clients do, for split tunnelling) has to be stopped first.

### No new privileges

If you get `The "no new privileges" flag is set, which prevents sudo from running as root.`, add

```yaml
    security_opt:
      - no-new-privileges:false
```

to the judgehost service (even with `privileged: true`).
