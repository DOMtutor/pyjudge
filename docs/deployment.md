# Running Local Deployment

* Ensure that `docker` and `docker compose` is installed
* Create an empty folder and move the provided `docker-compose.yml` there
* Create a `.env` file and set the following variables:
  * `TZ=<timezone>` Your timezone, e.g. `Europe/Berlin`
  * `DOMJUDGE_DB_ROOT_PASSWORD=<random password>` Root password for the database
  * `DOMJUDGE_DB_DOMJUDGE_PASSWORD=<random password>` User password for the database (this goes into `db.yml` of `pyjudge`) 
  * `DOMJUDGE_JUDGE_PASSWORD=<random password>` The judgehost API password
* Then, in that folder, run `docker compose up -d`
* Check admin password of domjudge by `docker logs domjudge` (optional if you set it if you set it via `pyjudge`)
* Log in to the web interface at `localhost:12345`
* In the webinterface, change the password of the `judgehost` user to the one you picked above
* Check the log of the judgehost instance for errors with `docker compose logs judgehost`
* To stop the docker images, run `docker compose down` in this folder

## Judgehost Errors

The judgehost requires deep access to the host system to allow for secure sandboxing and profiling.
As such, they may need quite some configration flags added.

### Cgroups

The judgehosts heavily rely on [cgroups](https://en.wikipedia.org/wiki/Cgroups) for process isolation.
Modern systems are (still) migrating from version 1 to version 2, with many systems running restricted or hybrid configurations for compatibility.
The judgehosts require (exclusive) version 2 and all accounting enabled.
This requires modification of your cmdline (the arguments passed to the system upon boot).

If you use GRUB (widespread), you need to:
1. Open `/etc/default/grub`
2. Find the line that says `GRUB_CMDLINE_LINUX_DEFAULT="..."`
3. Add your changes there (e.g. `GRUB_CMDLINE_LINUX_DEFAULT="quiet nosplash cgroup_enable=memory swapaccount=1"`)
4. Run `sudo update-grub` and reboot
5. (optionall) verify the changes have been applied by `cat /proc/cmdline`

* To enable memory accounting (which is sometimes not enabeld by default), add `cgroup_enable=memory swapaccount=1` to your cmdline.
* If you get `missing cgroup hierarchy prefix`, you likely are running hybrid / unified cgroups, here you need to add `systemd.unified_cgroup_hierarchy=0` (or `cgroup_no_v1=all`) to your cmdline. 

### No new privileges

If you get `The "no new privileges" flag is set, which prevents sudo from running as root.`, add
```yaml
    security_opt:
      - no-new-privileges:false
```
to the docker-compose definition (even if `privileged: True` is already set).