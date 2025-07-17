# import re
import re
from pathlib import Path
from typing import Any, List, Optional

import gnupg


def gpg_init(path: Path) -> gnupg.GPG:
    return gnupg.GPG(
        gnupghome=str(path),
        # binary="/opt/homebrew/bin/gpg"
    )


def import_pubkey(gpg: gnupg.GPG, key_data: str) -> Any:
    result = gpg.import_keys(key_data)
    # assert result.count
    return result.fingerprints


def decry(gpg: gnupg.GPG, encryed: str, passphrase: str = None) -> Optional[str]:
    decrypted = gpg.decrypt(message=encryed)
    return (
        str(decrypted.data.decode("utf-8", errors="ignore")).strip()
        if decrypted.ok
        else None
    )


def encry(gpg: gnupg.GPG, msg: str, recipient_fingerprint: str) -> Optional[str]:
    encrypted = gpg.encrypt(data=msg, recipients=recipient_fingerprint)
    return str(encrypted) if encrypted.ok else None


def encry_img(
    gpg: gnupg.GPG, img_path: Path, recipient_fingerprint: str
) -> Optional[str]:
    encrypted = gpg.encrypt_file(
        data=img_path, recipients=recipient_fingerprint, armor=True
    )
    return str(encrypted) if encrypted.ok else None


def get_own_fingp(gpg: gnupg.GPG, uid_filter: str) -> Optional[str]:
    private_keys = gpg.list_keys(secret=True)
    return (
        [
            key["fingerprint"]
            for key in private_keys
            for uid in key["uids"]
            if uid_filter is None or uid_filter in uid
        ][0]
        if private_keys
        else None
    )
    # for key in private_keys:
    #     if uid_filter is None or any(uid_filter in uid for uid in key["uids"]):
    #         return key["fingerprint"]


def export_pub(gpg: gnupg.GPG, fingerprint: str) -> str:
    return gpg.export_keys(
        keyids=fingerprint,
        # subkeys=True,
    )


# gpg = gpg_init(Path.home() / ".gnupg")
# print(get_own_fingp(gpg, "intro@j4cka.cc"))
# print(export_pub(gpg, "24EC64DBFE9D8527FA861270F701002DB94823E4"))

# def index(filename) -> Optional[str]:
#     # match = re.match(r"(\d+-)?(.*?)((-\d+)?(_\d+)?)\.(jpg|jpeg|png|gif|bmp)$", filename, re.IGNORECASE)
#     match = re.match(r"(.*?)(-\d+)?\.(jpg)$", filename, re.IGNORECASE)
#     return match.group(1) if match else None


def index(dir: Path) -> List[str]:
    # names = []
    # for filename in dir.iterdir():
    #     if filename.suffix.lower() in ['.py']:
    #         names.append(filename.stem)
    return [
        filename.stem
        for filename in dir.iterdir()
        if filename.suffix.lower() in [".jpg"]
    ]


def filter_zh_en(s: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fa5a-zA-Z\s]+", s))


# print(index(Path(__file__).parent))
# print(filter_zh_en("Hello, 世界! 123halo"))
