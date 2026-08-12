import json
import time
import urllib.request

HOST = "http://127.0.0.1:5123"
OK = 0


def get(path):
    global OK
    with urllib.request.urlopen(HOST + path, timeout=10) as r:
        data = json.load(r)
    OK += 1
    return data


def main():
    s = get("/api/summary")
    assert s["total_messages"] == 900, s
    assert s["mandatory_ids_found"] == 15, s

    cls = get("/api/classification?category=promotional")
    assert len(cls) == 110, len(cls)

    items = get("/api/items?type=event")
    assert len(items) == 170, len(items)

    sens = get("/api/sensitive?risk=high")
    assert sens and all(x["risk"] == "high" for x in sens)

    mand = get("/api/mandatory")
    assert len(mand) == 15, len(mand)

    all_rows = get("/api/classification")
    text = json.dumps(all_rows)
    for secret in ("BlueRiver", "482193", "006418220145", "tok_demo_A8K29Q",
                   "RC-88-KL", "ID-7842", "98765 43210", "4111 1111"):
        assert secret not in text, f"leak: {secret}"

    health = get("/healthz")
    assert health["status"] == "ok"

    print(f"API smoke test OK ({OK} requests, no secret leaks)")


if __name__ == "__main__":
    time.sleep(1)
    main()