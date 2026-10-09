from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path

from web3 import Web3
from web3._utils.events import event_abi_to_log_topic

from config import ARTIFACTS_DIR, MANIFEST_PATH, POLYGON_AMOY_WS_URL, STATE_DIR, VECTOR_BOOTSTRAP_LIMIT, require_env
from logger import get_logger
from models import DatasetImageRecord, IMAGE_SUFFIXES
from pinata import fetch_json
from utils import ensure_directory, read_json, write_json


logger = get_logger()
ALCHEMY_FREE_TIER_LOG_RANGE = 11
LOG_REQUEST_DELAY_SECONDS = 0.35
LOG_REQUEST_MAX_ATTEMPTS = 5
LOG_REQUEST_BACKOFF_BASE_SECONDS = 1.0
LAST_PROCESSED_BLOCK_PATH = STATE_DIR / "last_processed_block.json"


def _load_registry_artifact() -> dict[str, object]:
    artifact_path = ARTIFACTS_DIR / "ImageRegistry.sol" / "ImageRegistry.json"
    logger.info("Loading registry artifact from %s", artifact_path)
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def resolve_websocket_rpc_url() -> str:
    if POLYGON_AMOY_WS_URL:
        return POLYGON_AMOY_WS_URL

    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    if rpc_url.startswith("https://"):
        return "wss://" + rpc_url.removeprefix("https://")
    if rpc_url.startswith("http://"):
        return "ws://" + rpc_url.removeprefix("http://")
    if rpc_url.startswith("wss://") or rpc_url.startswith("ws://"):
        return rpc_url
    raise RuntimeError("POLYGON_AMOY_WS_URL is required when POLYGON_AMOY_RPC_URL cannot be converted to ws/wss.")


def _read_last_processed_block() -> int | None:
    payload = read_json(LAST_PROCESSED_BLOCK_PATH, None)
    if payload is None:
        return None
    if isinstance(payload, int):
        return payload
    if isinstance(payload, dict):
        value = payload.get("lastProcessedBlock")
        return int(value) if value is not None else None
    return None


def _write_last_processed_block(block_number: int) -> None:
    ensure_directory(STATE_DIR)
    write_json(LAST_PROCESSED_BLOCK_PATH, {"lastProcessedBlock": int(block_number)})
    logger.info("Saved last processed block %s to %s", block_number, LAST_PROCESSED_BLOCK_PATH)


def write_last_processed_block(block_number: int) -> None:
    _write_last_processed_block(block_number)


def _coerce_block_number(value: object) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    return int(value)


def _find_contract_deployment_block(w3: Web3, registry_address: str) -> int:
    latest_block = int(w3.eth.block_number)
    latest_code = w3.eth.get_code(registry_address, latest_block)
    if not latest_code:
        logger.warning("No contract code found for ImageRegistry at %s on latest block %s", registry_address, latest_block)
        return latest_block

    low = 0
    high = latest_block
    while low < high:
        middle = (low + high) // 2
        if w3.eth.get_code(registry_address, middle):
            high = middle
        else:
            low = middle + 1

    logger.info("Discovered ImageRegistry deployment block %s for contract %s", low, registry_address)
    return low


def get_image_registry_address() -> str:
    return Web3.to_checksum_address(require_env("IMAGE_REGISTRY_ADDRESS"))


def load_registry_contract(web3_client: Web3) -> object:
    artifact = _load_registry_artifact()
    return web3_client.eth.contract(address=get_image_registry_address(), abi=artifact["abi"])


def get_image_registered_topic() -> str:
    artifact = _load_registry_artifact()
    event_abi = next(item for item in artifact["abi"] if item.get("type") == "event" and item.get("name") == "ImageRegistered")
    return Web3.to_hex(event_abi_to_log_topic(event_abi))


def _resolve_scan_start_block(w3: Web3, registry_address: str) -> int | None:
    saved_block = _read_last_processed_block()
    if saved_block == -1:
        logger.info("last_processed_block.json contains -1, using ImageRegistry enumeration fallback")
        return None
    if saved_block is not None:
        logger.info("Resuming ImageRegistered scan from last_processed_block=%s", saved_block)
        return max(0, saved_block)

    deployment_block = _find_contract_deployment_block(w3, registry_address)
    _write_last_processed_block(deployment_block)
    logger.info("Initialized last_processed_block.json with deployment block %s", deployment_block)
    return deployment_block


def _is_rate_limited(error: Exception) -> bool:
    message = str(error).lower()
    return "429" in message or "too many requests" in message


def _fetch_image_registered_logs(contract: object, range_start: int, range_end: int) -> list[dict[str, object]]:
    last_error: Exception | None = None

    for attempt in range(1, LOG_REQUEST_MAX_ATTEMPTS + 1):
        try:
            return contract.events.ImageRegistered().get_logs(from_block=range_start, to_block=range_end)
        except Exception as error:
            last_error = error
            if attempt >= LOG_REQUEST_MAX_ATTEMPTS or not _is_rate_limited(error):
                raise

            delay_seconds = LOG_REQUEST_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Alchemy rate limited ImageRegistered logs for block range [%s, %s] on attempt %s/%s. Retrying in %.2f seconds.",
                range_start,
                range_end,
                attempt,
                LOG_REQUEST_MAX_ATTEMPTS,
                delay_seconds,
            )
            time.sleep(delay_seconds)

    if last_error is not None:
        raise last_error
    return []


def _collect_registered_images_from_chain(
    w3: Web3,
    contract: object,
    registry_address: str,
    start_block: int | None,
) -> tuple[list[dict[str, object]], int]:
    if start_block is None:
        return [], int(w3.eth.block_number)

    latest_block = int(w3.eth.block_number)
    image_events: list[dict[str, object]] = []

    logger.info(
        "Scanning ImageRegistered events: contract=%s start_block=%s latest_block=%s block_step=%s bootstrap_limit=%s",
        registry_address,
        start_block,
        latest_block,
        ALCHEMY_FREE_TIER_LOG_RANGE,
        VECTOR_BOOTSTRAP_LIMIT,
    )

    if start_block > latest_block:
        logger.info("No new blocks to scan for contract %s because start_block=%s is ahead of latest_block=%s", registry_address, start_block, latest_block)
        return [], latest_block

    for range_start in range(start_block, latest_block + 1, ALCHEMY_FREE_TIER_LOG_RANGE):
        range_end = min(range_start + ALCHEMY_FREE_TIER_LOG_RANGE - 1, latest_block)
        logger.info("Fetching ImageRegistered logs for block range [%s, %s]", range_start, range_end)
        batch = _fetch_image_registered_logs(contract, range_start, range_end)
        if batch:
            logger.info(
                "Fetched %s ImageRegistered logs for block range [%s, %s]; total_collected=%s",
                len(batch),
                range_start,
                range_end,
                len(image_events) + len(batch),
            )
            image_events.extend(batch)
        else:
            logger.info("No ImageRegistered logs for block range [%s, %s]; total_collected=%s", range_start, range_end, len(image_events))
        time.sleep(LOG_REQUEST_DELAY_SECONDS)

    image_events.sort(key=lambda item: (int(item["blockNumber"]), int(item["logIndex"])))

    if VECTOR_BOOTSTRAP_LIMIT > 0:
        limited = image_events[:VECTOR_BOOTSTRAP_LIMIT]
        logger.info("Collected %s registered image events with bootstrap limit %s", len(limited), VECTOR_BOOTSTRAP_LIMIT)
        return limited, latest_block
    if not image_events:
        logger.warning("No ImageRegistered events found for contract %s up to block %s", registry_address, latest_block)
    logger.info("Collected %s registered image events", len(image_events))
    return image_events, latest_block


def collect_registered_images() -> tuple[list[dict[str, object]], int | None, int]:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    registry_address = get_image_registry_address()
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    contract = load_registry_contract(w3)
    start_block = _resolve_scan_start_block(w3, registry_address)
    image_events, latest_block = _collect_registered_images_from_chain(
        w3,
        contract,
        registry_address,
        start_block,
    )
    return image_events, start_block, latest_block


def _infer_file_name(metadata: dict[str, object], preview_location: str, image_id: int) -> str:
    name = str(metadata.get("name") or "").strip()
    if name:
        return name

    preview_path = Path(preview_location.split("?")[0])
    if preview_path.suffix.lower() in IMAGE_SUFFIXES:
        return preview_path.name
    return f"image-{image_id}"


def _infer_relative_path(preview_location: str, image_id: int) -> str:
    if preview_location.startswith("ipfs://"):
        return preview_location.removeprefix("ipfs://")

    preview_path = Path(preview_location.split("?")[0])
    return f"pinata/{preview_path.name or f'image-{image_id}'}"


async def _build_record_from_event(event: dict[str, object]) -> DatasetImageRecord | None:
    args = event["args"]
    image_id = int(args["imageId"])
    metadata_uri = str(args["metadataURI"])
    collection_id = str(args["collectionId"])
    content_hash = Web3.to_hex(args["contentHash"])
    creator_wallet = str(args.get("creator") or "Author upload")

    return await _build_record_from_metadata(
        image_id=image_id,
        metadata_uri=metadata_uri,
        collection_id=collection_id,
        content_hash=content_hash,
        creator_wallet=creator_wallet,
    )


async def _build_record_from_metadata(
    *,
    image_id: int,
    metadata_uri: str,
    collection_id: str,
    content_hash: str,
    creator_wallet: str,
) -> DatasetImageRecord | None:
    metadata = await fetch_json(metadata_uri)

    preview_uri = str(metadata.get("previewUri") or "").strip()
    preview_gateway_url = str(metadata.get("previewGatewayUrl") or "").strip()
    preview_location = preview_gateway_url or preview_uri
    if not preview_location:
        logger.warning("Skipping image %s because previewUri/previewGatewayUrl is missing in metadata %s", image_id, metadata_uri)
        return None

    creator_wallet = str(metadata.get("creatorWallet") or creator_wallet)
    collection_id = str(metadata.get("collectionId") or collection_id)
    preview_ipfs_hash = preview_uri.removeprefix("ipfs://") if preview_uri.startswith("ipfs://") else ""

    return DatasetImageRecord(
        image_id=image_id,
        relative_path=_infer_relative_path(preview_location, image_id),
        class_name=f"Collection {collection_id} | {creator_wallet}",
        file_name=_infer_file_name(metadata, preview_location, image_id),
        metadata_uri=metadata_uri,
        ipfs_hash=preview_ipfs_hash,
        ipfs_uri=preview_uri,
        gateway_url=preview_location,
        content_hash=content_hash,
        source="pinata",
    )


def _normalize_registry_asset(asset: object) -> Mapping[str, object]:
    if isinstance(asset, Mapping):
        return asset
    if isinstance(asset, tuple):
        if len(asset) != 6:
            raise TypeError(f"Unsupported registry image asset tuple length: {len(asset)}")
        return {
            "id": asset[0],
            "collectionId": asset[1],
            "currentOwner": asset[2],
            "contentHash": asset[3],
            "metadataURI": asset[4],
            "registeredAt": asset[5],
        }
    raise TypeError(f"Unsupported registry image asset type: {type(asset).__name__}")


def _fetch_all_registry_images(contract: object) -> list[Mapping[str, object]]:
    try:
        images = contract.functions.getAllImages().call()
        logger.info("Fetched %s images from ImageRegistry.getAllImages()", len(images))
        return [_normalize_registry_asset(asset) for asset in images]
    except Exception as error:
        logger.exception("ImageRegistry.getAllImages() failed")
        raise RuntimeError(
            "ImageRegistry does not support getAllImages(). Deploy the updated contract or stop using lastProcessedBlock = -1."
        ) from error


async def _sync_registered_images_from_registry(records_by_image_id: dict[int, DatasetImageRecord]) -> tuple[list[DatasetImageRecord], int]:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    contract = load_registry_contract(w3)
    registry_images = _fetch_all_registry_images(contract)
    added_records = 0

    for asset in registry_images:
        image_id = int(asset["id"])
        if image_id in records_by_image_id:
            continue

        record = await _build_record_from_metadata(
            image_id=image_id,
            metadata_uri=str(asset["metadataURI"]),
            collection_id=str(asset["collectionId"]),
            content_hash=Web3.to_hex(asset["contentHash"]),
            creator_wallet=str(asset["creator"]),
        )
        if record is None:
            continue

        records_by_image_id[record.image_id] = record
        added_records += 1

    records = list(sorted(records_by_image_id.values(), key=lambda record: record.image_id))
    save_manifest(records)
    logger.info("ImageRegistry enumeration completed with %s total records and %s newly added records", len(records), added_records)
    return records, added_records


def load_manifest() -> list[DatasetImageRecord]:
    payload = read_json(MANIFEST_PATH, [])
    records = [DatasetImageRecord.from_json(item) for item in payload]
    logger.info("Loaded manifest from %s with %s records", MANIFEST_PATH, len(records))
    return records


def save_manifest(records: list[DatasetImageRecord]) -> None:
    ensure_directory(STATE_DIR)
    write_json(MANIFEST_PATH, [record.to_json() for record in records])
    logger.info("Saved manifest to %s with %s records", MANIFEST_PATH, len(records))


async def _sync_registered_images_by_block(records_by_image_id: dict[int, DatasetImageRecord]) -> tuple[list[DatasetImageRecord], int]:
    rpc_url = require_env("POLYGON_AMOY_RPC_URL")
    registry_address = get_image_registry_address()
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    contract = load_registry_contract(w3)
    start_block = _resolve_scan_start_block(w3, registry_address)
    if start_block is None:
        return await _sync_registered_images_from_registry(records_by_image_id)

    latest_block = int(w3.eth.block_number)
    logger.info(
        "Synchronizing ImageRegistered events block-by-block: contract=%s start_block=%s latest_block=%s block_step=%s bootstrap_limit=%s",
        registry_address,
        start_block,
        latest_block,
        ALCHEMY_FREE_TIER_LOG_RANGE,
        VECTOR_BOOTSTRAP_LIMIT,
    )

    if start_block > latest_block:
        logger.info(
            "No new blocks to scan for contract %s because start_block=%s is ahead of latest_block=%s",
            registry_address,
            start_block,
            latest_block,
        )
        return list(sorted(records_by_image_id.values(), key=lambda record: record.image_id)), 0

    processed_events = 0
    added_records = 0
    for range_start in range(start_block, latest_block + 1, ALCHEMY_FREE_TIER_LOG_RANGE):
        range_end = min(range_start + ALCHEMY_FREE_TIER_LOG_RANGE - 1, latest_block)
        logger.info("Fetching ImageRegistered logs for block range [%s, %s]", range_start, range_end)
        batch = _fetch_image_registered_logs(contract, range_start, range_end)
        events_by_block: dict[int, list[dict[str, object]]] = {}
        for image_event in batch:
            block_number = _coerce_block_number(image_event["blockNumber"])
            events_by_block.setdefault(block_number, []).append(image_event)

        for block_number in range(range_start, range_end + 1):
            block_events = events_by_block.get(block_number, [])
            if block_events:
                logger.info(
                    "Processing %s ImageRegistered events from block %s",
                    len(block_events),
                    block_number,
                )

            for image_event in block_events:
                processed_events += 1
                logger.info(
                    "Resolving registered image event %s from block %s",
                    processed_events,
                    block_number,
                )
                record = await _build_record_from_event(image_event)
                if record is not None:
                    if record.image_id not in records_by_image_id:
                        added_records += 1
                    records_by_image_id[record.image_id] = record

                if VECTOR_BOOTSTRAP_LIMIT > 0 and processed_events >= VECTOR_BOOTSTRAP_LIMIT:
                    records = list(sorted(records_by_image_id.values(), key=lambda record: record.image_id))
                    save_manifest(records)
                    write_last_processed_block(block_number + 1)
                    logger.info("Reached bootstrap limit %s at block %s", VECTOR_BOOTSTRAP_LIMIT, block_number)
                    return records, added_records

            if block_events:
                records = list(sorted(records_by_image_id.values(), key=lambda record: record.image_id))
                save_manifest(records)

            write_last_processed_block(block_number + 1)

        time.sleep(LOG_REQUEST_DELAY_SECONDS)

    records = list(sorted(records_by_image_id.values(), key=lambda record: record.image_id))
    if not records:
        logger.warning("Registered image bootstrap produced 0 searchable records")
    save_manifest(records)
    logger.info("Completed block-by-block ImageRegistered synchronization with %s records", len(records))
    return records, added_records


async def ensure_pinata_dataset() -> tuple[list[DatasetImageRecord], int]:
    logger.info("Registered image bootstrap started from on-chain Pinata metadata")
    ensure_directory(STATE_DIR)
    records_by_image_id = {record.image_id: record for record in load_manifest()}
    logger.info("Preparing searchable records with %s existing manifest records", len(records_by_image_id))
    records, added_records = await _sync_registered_images_by_block(records_by_image_id)

    logger.info("Registered image bootstrap completed with %s searchable records", len(records))
    return records, added_records


async def build_record_from_image_registered_log(event_log: dict[str, object]) -> DatasetImageRecord | None:
    web3_client = Web3()
    contract = load_registry_contract(web3_client)
    decoded_event = contract.events.ImageRegistered().process_log(event_log)
    return await _build_record_from_event(decoded_event)