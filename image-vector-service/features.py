from __future__ import annotations

import hashlib
import io

import numpy as np
import torch
from PIL import Image
from torchvision.models import ResNet18_Weights, resnet18

from config import FINETUNED_MODEL_PATH, VECTOR_MODEL_VERSION
from logger import get_logger


def normalize_feature_vector(vector: np.ndarray) -> np.ndarray:
    normalized = vector.astype(np.float32, copy=False)
    norm = np.linalg.norm(normalized)
    if norm > 0:
        normalized = normalized / norm
    return normalized.astype(np.float32, copy=False)


def normalize_feature_matrix(matrix: np.ndarray) -> np.ndarray:
    normalized = matrix.astype(np.float32, copy=True)
    norms = np.linalg.norm(normalized, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (normalized / norms).astype(np.float32)


def build_resnet18_backbone(
    *,
    weights: ResNet18_Weights | None = None,
    load_fine_tuned_weights: bool = False,
    map_location: torch.device | str = "cpu",
) -> tuple[torch.nn.Sequential, bool]:
    logger = get_logger()
    selected_weights = weights or ResNet18_Weights.IMAGENET1K_V1
    backbone = resnet18(weights=selected_weights)
    model = torch.nn.Sequential(*list(backbone.children())[:-1]).eval()
    uses_fine_tuned_weights = False

    if load_fine_tuned_weights and FINETUNED_MODEL_PATH.exists():
        state_dict = torch.load(FINETUNED_MODEL_PATH, map_location=map_location)
        model.load_state_dict(state_dict)
        uses_fine_tuned_weights = True
        logger.info("Loaded fine-tuned ResNet-18 backbone weights from %s", FINETUNED_MODEL_PATH)
    elif load_fine_tuned_weights:
        logger.warning(
            "Fine-tuned ResNet-18 backbone weights were requested but %s does not exist; falling back to pretrained weights",
            FINETUNED_MODEL_PATH,
        )

    model = model.to(map_location)
    model.eval()
    return model, uses_fine_tuned_weights


class FeatureExtractor:
    def __init__(self, load_fine_tuned_weights: bool = False) -> None:
        self.logger = get_logger()
        self.weights = ResNet18_Weights.IMAGENET1K_V1
        self.model, self.uses_fine_tuned_weights = build_resnet18_backbone(
            weights=self.weights,
            load_fine_tuned_weights=load_fine_tuned_weights,
        )
        self.preprocess = self.weights.transforms()
        self.model_version = VECTOR_MODEL_VERSION
        if self.uses_fine_tuned_weights:
            self.model_version = f"{VECTOR_MODEL_VERSION}-finetuned-caltech101-top5000"

    def decode_image(self, image_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def extract_features(self, image_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
        image = self.decode_image(image_bytes)
        return self.extract_cnn_embedding(image), self.extract_color_histogram(image)

    def extract_structured_features(self, image: Image.Image) -> np.ndarray:
        array = np.asarray(image, dtype=np.float32)
        grayscale = array.mean(axis=2)
        width, height = image.size
        features = np.array(
            [
                float(width),
                float(height),
                float(width * height),
                float(width / height) if height else 0.0,
                float(grayscale.mean()),
                float(grayscale.std()),
                float(array[:, :, 0].mean()),
                float(array[:, :, 1].mean()),
                float(array[:, :, 2].mean()),
                float(array[:, :, 0].std()),
                float(array[:, :, 1].std()),
                float(array[:, :, 2].std()),
            ],
            dtype=np.float32,
        )
        return features

    def extract_cnn_embedding(self, image: Image.Image) -> np.ndarray:
        tensor = self.preprocess(image).unsqueeze(0)
        with torch.no_grad():
            embedding = self.model(tensor).squeeze().cpu().numpy().astype(np.float32)

        return normalize_feature_vector(embedding)

    def extract_color_histogram(self, image: Image.Image, bins: int = 8) -> np.ndarray:
        array = np.asarray(image, dtype=np.uint8)
        channels = []
        for channel_index in range(3):
            histogram, _ = np.histogram(array[:, :, channel_index], bins=bins, range=(0, 256), density=True)
            channels.append(histogram.astype(np.float32))

        features = np.concatenate(channels)
        return normalize_feature_vector(features)

    def compute_model_hash(self) -> str:
        digest = hashlib.sha256(VECTOR_MODEL_VERSION.encode("utf-8"))
        state_dict = self.model.state_dict()
        for key in sorted(state_dict.keys()):
            digest.update(key.encode("utf-8"))
            digest.update(state_dict[key].detach().cpu().numpy().tobytes())
        return f"0x{digest.hexdigest()}"