from __future__ import annotations

import json
import mimetypes
import os
from base64 import b64decode
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT_DIR / "image-access-service" / "state.json"
REPLACEMENT_IMAGE_PATH = ROOT_DIR / "smart-contracts" / "scripts" / "test-images" / "test-image.jpg"
TARGET_PINATA_URL = "https://gateway.pinata.cloud/ipfs/QmU4FtfmHMRGLfuQhRB4TvTuciBwBH1HUQoDQnjrxr2Faz"


def load_env() -> tuple[str, str]:
    load_dotenv(ROOT_DIR / ".env")
    jwt = os.getenv("PINATA_JWT", "").strip()
    gateway = os.getenv("PINATA_GATEWAY_BASE_URL", "https://gateway.pinata.cloud/ipfs").rstrip("/")
    if not jwt:
        raise RuntimeError("PINATA_JWT is required in .env")
    return jwt, gateway


def extract_ipfs_hash(uri_or_url: str) -> str:
    if uri_or_url.startswith("ipfs://"):
        return uri_or_url.removeprefix("ipfs://")
    parsed = urlparse(uri_or_url)
    return parsed.path.rstrip("/").split("/")[-1]


def load_state() -> dict[str, object]:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(payload: dict[str, object]) -> None:
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def find_asset_by_url(state: dict[str, object], target_url: str) -> tuple[str, dict[str, object]]:
    assets = dict(state.get("assets", {}))
    normalized = target_url.rstrip("/")
    for content_hash, asset in assets.items():
        encrypted_gateway_url = str(asset.get("encryptedGatewayUrl", "")).rstrip("/")
        encrypted_asset_uri = str(asset.get("encryptedAssetUri", "")).rstrip("/")
        if encrypted_gateway_url == normalized or encrypted_asset_uri == normalized:
            return str(content_hash), dict(asset)
    raise RuntimeError(f"Target Pinata asset was not found in {STATE_PATH}")


def encrypt_replacement(asset: dict[str, object], replacement_bytes: bytes) -> bytes:
    key = b64decode(str(asset["decryptionKey"]))
    nonce = b64decode(str(asset["nonce"]))
    return AESGCM(key).encrypt(nonce, replacement_bytes, None)


def pin_file(jwt: str, encrypted_bytes: bytes, file_name: str, content_type: str, gateway_base_url: str) -> dict[str, str]:
    boundary = "----CopilotTamperImageBoundary7f3f6d3b"
    metadata_json = json.dumps({"name": file_name})
    parts = [
        f"--{boundary}\r\n".encode("utf-8"),
        (
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8"),
        encrypted_bytes,
        b"\r\n",
        f"--{boundary}\r\n".encode("utf-8"),
        b'Content-Disposition: form-data; name="pinataMetadata"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        metadata_json.encode("utf-8"),
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    body = b"".join(parts)
    request = Request(
        "https://api.pinata.cloud/pinning/pinFileToIPFS",
        data=body,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    ipfs_hash = str(payload["IpfsHash"])
    return {
        "ipfsHash": ipfs_hash,
        "ipfsUri": f"ipfs://{ipfs_hash}",
        "gatewayUrl": f"{gateway_base_url}/{ipfs_hash}",
    }


def unpin_old_hash(jwt: str, ipfs_hash: str) -> None:
    request = Request(
        f"https://api.pinata.cloud/pinning/unpin/{ipfs_hash}",
        headers={"Authorization": f"Bearer {jwt}"},
        method="DELETE",
    )
    with urlopen(request, timeout=120):
        return


def main() -> int:
    jwt, gateway_base_url = load_env()
    if not REPLACEMENT_IMAGE_PATH.exists():
        raise RuntimeError(f"Replacement image not found: {REPLACEMENT_IMAGE_PATH}")

    state = load_state()
    content_hash, asset = find_asset_by_url(state, TARGET_PINATA_URL)
    replacement_bytes = REPLACEMENT_IMAGE_PATH.read_bytes()
    encrypted_bytes = encrypt_replacement(asset, replacement_bytes)
    file_name = Path(str(asset.get("originalFileName") or REPLACEMENT_IMAGE_PATH.name)).with_suffix(".enc").name
    content_type = "application/octet-stream"
    upload_result = pin_file(jwt, encrypted_bytes, file_name, content_type, gateway_base_url)

    old_ipfs_hash = extract_ipfs_hash(TARGET_PINATA_URL)
    try:
        unpin_old_hash(jwt, old_ipfs_hash)
        unpinned = True
    except Exception:
        unpinned = False

    state_assets = state.setdefault("assets", {})
    state_assets[content_hash] = {
        **asset,
        "encryptedAssetUri": upload_result["ipfsUri"],
        "encryptedGatewayUrl": upload_result["gatewayUrl"],
        "originalFileName": REPLACEMENT_IMAGE_PATH.name,
        "contentType": mimetypes.guess_type(REPLACEMENT_IMAGE_PATH.name)[0] or "image/jpeg",
    }
    save_state(state)

    print(f"Target contentHash: {content_hash}")
    print(f"Old target URL: {TARGET_PINATA_URL}")
    print(f"Old CID unpinned: {unpinned}")
    print(f"New encrypted asset URI: {upload_result['ipfsUri']}")
    print(f"New encrypted gateway URL: {upload_result['gatewayUrl']}")
    print(f"Replacement source image: {REPLACEMENT_IMAGE_PATH}")
    print("State file updated. Future oracle downloads for this contentHash will decrypt to the replacement image bytes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())