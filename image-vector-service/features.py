from __future__ import annotations

import hashlib
import io

import numpy as np
import torch
from PIL import Image
from torchvision.models import ResNet18_Weights, resnet18

from config import VECTOR_MODEL_VERSION


class FeatureExtractor:
    def __init__(self) -> None:
        self.weights = ResNet18_Weights.IMAGENET1K_V1
        backbone = resnet18(weights=self.weights)
        self.model = torch.nn.Sequential(*list(backbone.children())[:-1]).eval()
        self.preprocess = self.weights.transforms()

    def decode_image(self, image_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def extract_features(self, image_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
        image = self.decode_image(image_bytes)
        return self.extract_cnn_embedding(image), self.extract_color_histogram(image)

    def extract_cnn_embedding(self, image: Image.Image) -> np.ndarray:
        tensor = self.preprocess(image).unsqueeze(0)
        with torch.no_grad():
            embedding = self.model(tensor).squeeze().cpu().numpy().astype(np.float32)

        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def extract_color_histogram(self, image: Image.Image, bins: int = 8) -> np.ndarray:
        array = np.asarray(image, dtype=np.uint8)
        channels = []
        for channel_index in range(3):
            histogram, _ = np.histogram(array[:, :, channel_index], bins=bins, range=(0, 256), density=True)
            channels.append(histogram.astype(np.float32))

        features = np.concatenate(channels)
        norm = np.linalg.norm(features)
        if norm > 0:
            features = features / norm
        return features.astype(np.float32)

    def compute_model_hash(self) -> str:
        digest = hashlib.sha256(VECTOR_MODEL_VERSION.encode("utf-8"))
        state_dict = self.model.state_dict()
        for key in sorted(state_dict.keys()):
            digest.update(key.encode("utf-8"))
            digest.update(state_dict[key].detach().cpu().numpy().tobytes())
        return f"0x{digest.hexdigest()}"