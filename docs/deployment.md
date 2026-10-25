# Running DOMjudge with Docker

[docker-compose.yml](docker-compose.yml) starts a complete DOMjudge: MariaDB with periodic backups, the `domserver` web application and one `judgehost`.
It is suitable for local development and small courses.
The images are the DOMtutor builds of the official DOMjudge containers.

* Install `docker` and `docker compose`
* Create an empty folder and copy `docker-compose.yml` there
* Create a `.env` file in that folder:
  ```
  TZ=Europe/Berlin
  DOMJUDGE_DB_ROOT_PASSWORD=<random>      # database root password
  DOMJUDGE_DB_DOMJUDGE_PASSWORD=<random>  # database user password, goes into pydomjudge's db.yml
  DOMJUDGE_JUDGE_PASSWORD=<random>        # API password of the judgehost user
  ```
* `docker compose up -d`
* `docker compose logs domserver` shows the initial admin password (unless you set one via `pydomjudge`)
* Log in at <http://localhost:12345>
* In the web interface, set the password of the `judgehost` user to `DOMJUDGE_JUDGE_PASSWORD`
* `docker compose logs judgehost` should show it connecting and idling
* `docker compose down` stops everything, `docker compose down -v` also deletes the database

The database is exposed on port 3306 for `pydomjudge`.
Do not expose it on a public host; bind it to `127.0.0.1:3306:3306` or run `pydomjudge` on the same machine.

More judgehosts: duplicate the `judgehost` service with a different `container_name`, `hostname` and `DAEMON_ID`.

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

### No new privileges

If you get `The "no new privileges" flag is set, which prevents sudo from running as root.`, add

```yaml
    security_opt:
      - no-new-privileges:false
```

to the judgehost service (even with `privileged: true`).
