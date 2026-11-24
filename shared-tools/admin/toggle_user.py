import sys, json, re, subprocess

ENV_PATH = "/root/.hermes/.env"
ROSTER_PATH = "/root/.hermes/shared-tools/admin/roster.json"

def main():
    name = sys.argv[1].strip().lower()
    action = sys.argv[2].strip().lower()  # "on" or "off"

    with open(ROSTER_PATH) as f:
        roster = json.load(f)
    user_id = roster.get(name)
    if not user_id:
        print(f"UNKNOWN_OR_NOT_CONNECTED_YET: {name}")
        return

    with open(ENV_PATH) as f:
        content = f.read()

    m = re.search(r"^TELEGRAM_ALLOWED_USERS=(.*)$", content, re.MULTILINE)
    ids = [i for i in m.group(1).split(",") if i.strip()] if m else []

    if action == "off":
        ids = [i for i in ids if i != user_id]
    elif action == "on":
        if user_id not in ids:
            ids.append(user_id)
    else:
        print("BAD_ACTION: use 'on' or 'off'")
        return

    new_line = "TELEGRAM_ALLOWED_USERS=" + ",".join(ids)
    content = re.sub(r"^TELEGRAM_ALLOWED_USERS=.*$", new_line, content, flags=re.MULTILINE)
    with open(ENV_PATH, "w") as f:
        f.write(content)

    subprocess.run(["/root/.local/bin/hermes", "gateway", "restart"], check=False)
    print(f"OK: {name} ({user_id}) is now {'CONNECTED' if action == 'on' else 'DISCONNECTED'}")

if __name__ == "__main__":
    main()
