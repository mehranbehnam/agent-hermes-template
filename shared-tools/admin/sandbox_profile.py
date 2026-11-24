#!/usr/bin/python3
"""Rule #1 hard isolation: run a USER profile's terminal / file / code tools inside its own Docker container
(image hermes-user-sandbox:1) where ONLY that user's folders exist. Another user's files, the server's secrets
(/root/.hermes/.env, rclone token, owner archive) and other profiles are simply not present in the container.

  sandbox_profile.py on <profile>      # switch the profile to its sealed container (backup of config.yaml first)
  sandbox_profile.py off <profile>     # back to the host (local) terminal
  sandbox_profile.py status            # which profiles are sealed
Owner / owner-work profiles (default, adsaccount, adsaccount2, hermesgroup, iranvpngroup, owner2) stay on the host.
"""
import os, re, shutil, sys, time

H = "/root/.hermes"
OWNER_WORK = {"adsaccount", "adsaccount2", "hermesgroup", "iranvpngroup", "owner2"}
IMAGE = "hermes-user-sandbox:1"
PY = "/root/.hermes/tools"
BEGIN, END = "  # >>> sandbox (sandbox_profile.py) >>>", "  # <<< sandbox <<<"


def block(p):
    d = f"{H}/profiles/{p}"
    # HOME is /home/user inside the container: Hermes' file tools refuse writes under /root/.hermes (its "sandbox mirror"
    # soft guard). The same folder stays mounted at its host path too, so MEDIA: can name the host path.
    vols = [f"{d}/home:/home/user", f"{d}/home:{d}/home", f"{d}/cache:{d}/cache", f"{d}/userbot:{d}/userbot",
            f"{d}/skills:{d}/skills:ro", f"{PY}:{PY}:ro", f"{H}/shared-tools/userbot:{H}/shared-tools/userbot:ro"]
    return "\n".join([BEGIN,
                      f'  backend: "docker"',
                      f'  docker_image: "{IMAGE}"',
                      "  docker_volumes:", *[f'    - "{v}"' for v in vols],
                      "  docker_env:", '    HOME: "/home/user"', '    TZ: "Asia/Tehran"',
                      "  docker_network: true",
                      "  docker_mount_cwd_to_workspace: false",
                      '  cwd: "/home/user"',
                      "  container_cpu: 1",
                      "  container_memory: 768",
                      "  container_disk: 5120",
                      "  container_persistent: true",
                      END])


def on(p):
    if p in OWNER_WORK or not re.fullmatch(r"[a-z][a-z0-9]{1,20}", p):
        sys.exit(f"refused: {p} is not a user profile")
    d = f"{H}/profiles/{p}"
    cfg = f"{d}/config.yaml"
    for sub in ("home", "cache", "userbot"):
        os.makedirs(f"{d}/{sub}", exist_ok=True)
    os.chmod(f"{d}/userbot", 0o700)
    s = open(cfg).read()
    shutil.copy2(cfg, f"/root/backups/{p}-config.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}-sandbox")
    s = re.sub(rf"\n{re.escape(BEGIN)}.*?{re.escape(END)}", "", s, flags=re.S)
    m = re.search(r"^terminal:\n", s, re.M)
    if not m:
        sys.exit("no terminal: section")
    # neutralise the profile's own backend/cwd lines inside terminal: (the sandbox block below wins anyway: last key wins in YAML)
    s = s[:m.end()] + block(p) + "\n" + s[m.end():]
    seg_end = re.search(r"^[a-z_]+:", s[m.end():], re.M)
    seg = s[m.end(): m.end() + (seg_end.start() if seg_end else len(s))]
    after = seg.split(END, 1)[1]
    after = re.sub(r'(?m)^  (backend|cwd|container_cpu|container_memory|container_disk|container_persistent|docker_mount_cwd_to_workspace):.*\n', "", after)
    s = s[:m.end()] + seg.split(END, 1)[0] + END + after + s[m.end() + len(seg):]
    # owner 2026-11-16: small in-scope actions run without asking the user; risky things are blocked by the admin-panel
    # no-build guard and the container itself, so the "needs your OK" prompts only stalled users (5-min waits).
    if not re.search(r"^approvals:", s, re.M):
        s = s.rstrip() + "\n\napprovals:  # sandbox_profile.py\n  mode: \"off\"\n"
    open(cfg, "w").write(s)
    print(f"{p}: sealed (docker {IMAGE})")


def off(p):
    cfg = f"{H}/profiles/{p}/config.yaml"
    s = open(cfg).read()
    shutil.copy2(cfg, f"/root/backups/{p}-config.yaml.bak-{time.strftime('%Y%m%d-%H%M%S')}-unsandbox")
    s = re.sub(rf"\n{re.escape(BEGIN)}.*?{re.escape(END)}", "", s, flags=re.S)
    s = re.sub(r"^terminal:\n", 'terminal:\n  backend: "local"\n  cwd: "."\n', s, count=1, flags=re.M)
    open(cfg, "w").write(s)
    print(f"{p}: back on host")


def status():
    for p in sorted(os.listdir(f"{H}/profiles")):
        cfg = f"{H}/profiles/{p}/config.yaml"
        if os.path.exists(cfg):
            print(f"{p:14s} {'SEALED' if BEGIN in open(cfg).read() else 'host'}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["on"] and len(a) == 2:
        on(a[1])
    elif a[:1] == ["off"] and len(a) == 2:
        off(a[1])
    elif a[:1] == ["status"]:
        status()
    else:
        sys.exit(__doc__)
