import { Injectable } from '@angular/core';

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

    const response = await fetch('http://localhost:3001/api/pinata/upload', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { error?: string; details?: string } | null;
      throw new Error(payload?.details || payload?.error || 'Pinata upload failed.');
    }

    return (await response.json()) as PinataUploadResult;
  }

  async uploadJson(name: string, content: Record<string, unknown>): Promise<PinataUploadResult> {
    const response = await fetch('http://localhost:3001/api/pinata/pin-json', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ name, content }),
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { error?: string; details?: string } | null;
      throw new Error(payload?.details || payload?.error || 'Pinata JSON upload failed.');
    }

    return (await response.json()) as PinataUploadResult;
  }
}