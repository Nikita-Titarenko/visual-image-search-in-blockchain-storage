from __future__ import annotations

import asyncio
import json
import time
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Boolean, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from config import MOCK_ALLOWED_ORIGINS
from database import Base, SessionLocal, engine


def now_unix() -> int:
    return int(time.time())


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, object]]] = set()
        self._next_event_id = 1

    def subscribe(self) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_name: str, payload: dict[str, object]) -> None:
        message = self._format_message(event_name, payload)
        for queue in list(self._subscribers):
            queue.put_nowait(message)

    def _format_message(self, event_name: str, payload: dict[str, object]) -> dict[str, object]:
        event_id = self._next_event_id
        self._next_event_id += 1
        return {
            "id": event_id,
            "event": event_name,
            "payload": payload,
        }


class CollectionModel(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    creator: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ImageModel(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    current_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    metadata_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    registered_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class LicenseOfferModel(Base):
    __tablename__ = "license_offers"

    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id"), primary_key=True)
    seller: Mapped[str] = mapped_column(String(255), nullable=False)
    price_wei: Mapped[int] = mapped_column(BigInteger, nullable=False)
    terms_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class LicensePurchaseModel(Base):
    __tablename__ = "license_purchases"
    __table_args__ = (UniqueConstraint("image_id", "buyer", name="uq_purchase_image_buyer"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    image_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("images.id"), nullable=False)
    buyer: Mapped[str] = mapped_column(String(255), nullable=False)
    seller: Mapped[str] = mapped_column(String(255), nullable=False)
    paid_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purchased_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AuditSnapshotModel(Base):
    __tablename__ = "audit_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_version: Mapped[str] = mapped_column(String(255), nullable=False)
    model_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    index_version: Mapped[str] = mapped_column(String(255), nullable=False)
    index_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_size: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RegisterCollectionRequest(BaseModel):
    creator: str
    metadataURI: str


class RegisterImageRequest(BaseModel):
    collectionId: int = Field(default=0, ge=0)
    currentOwner: str
    contentHash: str
    metadataURI: str


class ConfigureLicenseOfferRequest(BaseModel):
    imageId: int = Field(gt=0)
    seller: str
    priceWei: int = Field(ge=0)
    termsURI: str
    active: bool


class BuyLicenseRequest(BaseModel):
    imageId: int = Field(gt=0)
    buyer: str
    paidAmount: int = Field(ge=0)


class RecordAuditSnapshotRequest(BaseModel):
    modelVersion: str
    modelHash: str
    indexVersion: str
    indexHash: str
    metadataURI: str
    submittedBy: str
    datasetSize: int = Field(ge=0)


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def serialize_collection(model: CollectionModel) -> dict[str, object]:
    return {
        "id": int(model.id),
        "creator": model.creator,
        "metadataURI": model.metadata_uri,
        "createdAt": int(model.created_at),
    }


def serialize_image(model: ImageModel) -> dict[str, object]:
    return {
        "id": int(model.id),
        "collectionId": int(model.collection_id),
        "currentOwner": model.current_owner,
        "contentHash": model.content_hash,
        "metadataURI": model.metadata_uri,
        "registeredAt": int(model.registered_at),
    }


def serialize_offer(model: LicenseOfferModel) -> dict[str, object]:
    return {
        "imageId": int(model.image_id),
        "seller": model.seller,
        "priceWei": int(model.price_wei),
        "termsURI": model.terms_uri,
        "active": bool(model.active),
    }


def serialize_purchase(model: LicensePurchaseModel) -> dict[str, object]:
    return {
        "id": int(model.id),
        "imageId": int(model.image_id),
        "buyer": model.buyer,
        "seller": model.seller,
        "paidAmount": int(model.paid_amount),
        "purchasedAt": int(model.purchased_at),
    }


def serialize_snapshot(model: AuditSnapshotModel) -> dict[str, object]:
    return {
        "id": int(model.id),
        "modelVersion": model.model_version,
        "modelHash": model.model_hash,
        "indexVersion": model.index_version,
        "indexHash": model.index_hash,
        "metadataURI": model.metadata_uri,
        "submittedBy": model.submitted_by,
        "recordedAt": int(model.recorded_at),
        "datasetSize": int(model.dataset_size),
    }


app = FastAPI(title="Smart Contracts Mock", version="1.0.0")
event_broker = EventBroker()
app.add_middleware(
    CORSMiddleware,
    allow_origins=MOCK_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/api/mock/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/mock/admin/reset")
def reset_state(db: Session = Depends(get_db)) -> dict[str, bool]:
    db.query(LicensePurchaseModel).delete()
    db.query(LicenseOfferModel).delete()
    db.query(AuditSnapshotModel).delete()
    db.query(ImageModel).delete()
    db.query(CollectionModel).delete()
    db.commit()
    event_broker.publish("state_reset", {"resetAt": now_unix()})
    return {"ok": True}


@app.websocket("/api/mock/ws/events")
async def stream_events(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = event_broker.subscribe()
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=10)
                await websocket.send_text(json.dumps(message, separators=(",", ":")))
            except TimeoutError:
                await websocket.send_text(json.dumps({"event": "keepalive"}, separators=(",", ":")))
    except WebSocketDisconnect:
        return
    finally:
        event_broker.unsubscribe(queue)


@app.post("/api/mock/image-registry/collections")
def register_collection(request: RegisterCollectionRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    record = CollectionModel(creator=request.creator, metadata_uri=request.metadataURI, created_at=now_unix())
    db.add(record)
    db.commit()
    db.refresh(record)
    return serialize_collection(record)


@app.post("/api/mock/image-registry/images")
def register_image(request: RegisterImageRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    if request.collectionId != 0:
        collection = db.get(CollectionModel, request.collectionId)
        if collection is None:
            raise HTTPException(status_code=404, detail="Collection not found.")
        if collection.creator.lower() != request.currentOwner.lower():
            raise HTTPException(status_code=403, detail="Only the collection creator can add images.")
    existing = db.execute(select(ImageModel).where(ImageModel.content_hash == request.contentHash)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Image content hash already registered.")
    record = ImageModel(
        collection_id=request.collectionId,
        current_owner=request.currentOwner,
        content_hash=request.contentHash.lower(),
        metadata_uri=request.metadataURI,
        registered_at=now_unix(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    payload = serialize_image(record)
    event_broker.publish("image_registered", payload)
    return payload


@app.get("/api/mock/image-registry/images")
def list_images(afterId: int = Query(default=0, ge=0), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    records = db.execute(select(ImageModel).where(ImageModel.id > afterId).order_by(ImageModel.id.asc())).scalars().all()
    return [serialize_image(record) for record in records]


@app.get("/api/mock/image-registry/images/{image_id}")
def get_image(image_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    record = db.get(ImageModel, image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    return serialize_image(record)


@app.post("/api/mock/licensing/offers")
def configure_license_offer(request: ConfigureLicenseOfferRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    image = db.get(ImageModel, request.imageId)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    if image.current_owner.lower() != request.seller.lower():
        raise HTTPException(status_code=403, detail="Only the image owner can configure the license offer.")
    record = db.get(LicenseOfferModel, request.imageId)
    if record is None:
        record = LicenseOfferModel(
            image_id=request.imageId,
            seller=request.seller,
            price_wei=request.priceWei,
            terms_uri=request.termsURI,
            active=request.active,
        )
        db.add(record)
    else:
        record.seller = request.seller
        record.price_wei = request.priceWei
        record.terms_uri = request.termsURI
        record.active = request.active
    db.commit()
    db.refresh(record)
    return serialize_offer(record)


@app.get("/api/mock/licensing/offers/{image_id}")
def get_license_offer(image_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    record = db.get(LicenseOfferModel, image_id)
    if record is None:
        raise HTTPException(status_code=404, detail="License offer not found.")
    return serialize_offer(record)


@app.post("/api/mock/licensing/purchases")
def buy_license(request: BuyLicenseRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    image = db.get(ImageModel, request.imageId)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    offer = db.get(LicenseOfferModel, request.imageId)
    if offer is None or not offer.active:
        raise HTTPException(status_code=409, detail="License offer is not active.")
    if offer.seller.lower() != image.current_owner.lower():
        raise HTTPException(status_code=409, detail="License offer seller is outdated.")
    if request.buyer.lower() == offer.seller.lower():
        raise HTTPException(status_code=409, detail="Buyer cannot purchase their own image.")
    if request.paidAmount != offer.price_wei:
        raise HTTPException(status_code=409, detail="Incorrect payment amount.")
    existing = db.execute(
        select(LicensePurchaseModel).where(
            LicensePurchaseModel.image_id == request.imageId,
            LicensePurchaseModel.buyer == request.buyer,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="License already purchased for this buyer and image.")
    record = LicensePurchaseModel(
        image_id=request.imageId,
        buyer=request.buyer,
        seller=offer.seller,
        paid_amount=request.paidAmount,
        purchased_at=now_unix(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return serialize_purchase(record)


@app.get("/api/mock/licensing/purchases/{purchase_id}")
def get_purchase(purchase_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    record = db.get(LicensePurchaseModel, purchase_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Purchase not found.")
    return serialize_purchase(record)


@app.post("/api/mock/audit/snapshots")
def record_audit_snapshot(request: RecordAuditSnapshotRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    record = AuditSnapshotModel(
        model_version=request.modelVersion,
        model_hash=request.modelHash,
        index_version=request.indexVersion,
        index_hash=request.indexHash,
        metadata_uri=request.metadataURI,
        submitted_by=request.submittedBy,
        recorded_at=now_unix(),
        dataset_size=request.datasetSize,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return serialize_snapshot(record)


@app.get("/api/mock/audit/snapshots")
def list_audit_snapshots(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    records = db.execute(select(AuditSnapshotModel).order_by(AuditSnapshotModel.id.desc())).scalars().all()
    return [serialize_snapshot(record) for record in records]


@app.get("/api/mock/audit/verify/{snapshot_id}")
def verify_audit_snapshot(snapshot_id: int, modelHash: str, indexHash: str, db: Session = Depends(get_db)) -> dict[str, bool]:
    record = db.get(AuditSnapshotModel, snapshot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Snapshot not found.")
    return {"match": record.model_hash == modelHash and record.index_hash == indexHash}