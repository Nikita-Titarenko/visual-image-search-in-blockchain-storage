import { Injectable } from '@angular/core';

import { mapServiceFetchError, parseServiceError } from './api-error.utils';

export interface PinataUploadResult {
  ipfsHash: string;
  ipfsUri: string;
  gatewayUrl: string;
  pinSize: number;
  timestamp: string;
}

@Injectable({ providedIn: 'root' })
export class PinataUploadService {
  async uploadImage(file: File): Promise<PinataUploadResult> {
    const formData = new FormData();
    formData.append('file', file, file.name);

    try {
      const response = await fetch('http://localhost:3001/api/pinata/upload', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw await parseServiceError(
          response,
          'Pinata proxy returned an error while uploading the preview image.',
        );
      }

      return (await response.json()) as PinataUploadResult;
    } catch (error) {
      throw mapServiceFetchError(
        error,
        'Pinata service is unavailable. Start pinata-proxy or restore Pinata connectivity and try again.',
      );
    }
  }

  async uploadJson(name: string, content: Record<string, unknown>): Promise<PinataUploadResult> {
    try {
      const response = await fetch('http://localhost:3001/api/pinata/pin-json', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ name, content }),
      });

      if (!response.ok) {
        throw await parseServiceError(
          response,
          'Pinata proxy returned an error while uploading JSON metadata.',
        );
      }

      return (await response.json()) as PinataUploadResult;
    } catch (error) {
      throw mapServiceFetchError(
        error,
        'Pinata service is unavailable. Start pinata-proxy or restore Pinata connectivity and try again.',
      );
    }
  }
}