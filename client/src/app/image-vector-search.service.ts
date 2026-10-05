import { Injectable } from '@angular/core';

export interface ImageSearchResult {
  rank: number;
  score: number;
  distance: number;
  className: string;
  fileName: string;
  ipfsUri: string;
  gatewayUrl: string;
  contentHash: string;
  relativePath: string;
}

export interface ImageSearchResponse {
  method: string;
  topK: number;
  modelVersion: string;
  indexVersion: string;
  queryHash: string;
  results: ImageSearchResult[];
}

const VECTOR_SERVICE_BASE_URL = 'http://localhost:8010';

@Injectable({ providedIn: 'root' })
export class ImageVectorSearchService {
  async searchSimilarImages(file: File, method: 'cnn' | 'histogram', topK: number): Promise<ImageSearchResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);

    const response = await fetch(
      `${VECTOR_SERVICE_BASE_URL}/api/vector/search?method=${encodeURIComponent(method)}&top_k=${encodeURIComponent(topK)}`,
      {
        method: 'POST',
        body: formData,
      },
    );

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string; error?: string } | null;
      throw new Error(payload?.detail || payload?.error || 'Image vector search failed.');
    }

    return (await response.json()) as ImageSearchResponse;
  }
}