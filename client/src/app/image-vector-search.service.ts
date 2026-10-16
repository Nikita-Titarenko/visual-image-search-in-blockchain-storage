import { Injectable } from '@angular/core';

import { mapServiceFetchError, parseServiceError } from './api-error.utils';

export interface ImageSearchResult {
  rank: number;
  score: number;
  distance: number;
  imageId: number;
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
  async searchSimilarImages(file: File, topK: number): Promise<ImageSearchResponse> {
    const formData = new FormData();
    formData.append('file', file, file.name);

    try {
      const response = await fetch(
        `${VECTOR_SERVICE_BASE_URL}/api/vector/search?top_k=${encodeURIComponent(topK)}`,
        {
          method: 'POST',
          body: formData,
        },
      );

      if (!response.ok) {
        throw await parseServiceError(
          response,
          'ML service returned an error while processing the similarity search request.',
        );
      }

      return (await response.json()) as ImageSearchResponse;
    } catch (error) {
      throw mapServiceFetchError(
        error,
        'ML service is unavailable. Start image-vector-service and try the similarity search again.',
      );
    }
  }
}