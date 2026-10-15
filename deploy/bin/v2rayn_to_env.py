"""Turn a v2rayN binConfigs/config.json (VLESS + Reality) into the node.env that setup-xray.sh reads.

    python v2rayn_to_env.py "<path>/binConfigs/config.json" node.env

Nothing secret is printed; the output file is the only place the values go.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def convert(cfg: dict) -> dict[str, str]:
    out = next(o for o in cfg["outbounds"] if o.get("tag") == "proxy")
    if out["protocol"] != "vless":
        raise SystemExit(f"unsupported protocol {out['protocol']!r}, only vless is handled")
    node = out["settings"]["vnext"][0]
    user = node["users"][0]
    ss = out["streamSettings"]
    if ss.get("security") != "reality":
        raise SystemExit("only Reality nodes are handled")
    rs = ss["realitySettings"]
    return {
        "HOST": node["address"],
        "PORT": str(node["port"]),
        "UUID": user["id"],
        "FLOW": user.get("flow", ""),
        "SNI": rs["serverName"],
        "FP": rs.get("fingerprint", "chrome"),
        "PUBKEY": rs["publicKey"],
        "SHORTID": rs.get("shortId", ""),
        "SPIDERX": rs.get("spiderX", ""),
    }


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    values = convert(json.loads(Path(sys.argv[1]).read_text("utf-8-sig")))
    dest = Path(sys.argv[2])
    dest.write_text("".join(f"{k}={v}\n" for k, v in values.items()), "utf-8", newline="\n")
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    print(f"wrote {dest} ({len(values)} values for {values['HOST']})")


if __name__ == "__main__":
    main()
