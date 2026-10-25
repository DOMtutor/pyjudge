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

The domserver image passes the host name without port to DOMjudge, so its redirects (for example to the login page) would lose a port like 12345. The small start script in the compose file (`domserver-public-port`) adds `DOMJUDGE_PUBLIC_PORT`, which defaults to `DOMJUDGE_PORT`.
Behind a reverse proxy on the standard ports, set `DOMJUDGE_PUBLIC_PORT=` (empty) in `.env`.

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
Check `cat /proc/self/cgroup`: any line ending in `:/` besides the `0::` one makes the judgehost refuse to start.
Some software mounts a cgroup-v1 hierarchy at runtime even on a pure cgroup-v2 system, notably the Mullvad VPN app, which mounts `net_cls` at `/sys/fs/cgroup/net_cls` for split tunnelling; neither `cgroup: private` nor leaving out the `/sys/fs/cgroup` volume helps.
Stop such software (or `sudo umount /sys/fs/cgroup/net_cls`) before starting the judgehost.

### No new privileges

If you get `The "no new privileges" flag is set, which prevents sudo from running as root.`, add

```yaml
    security_opt:
      - no-new-privileges:false
```

to the judgehost service (even with `privileged: true`).
