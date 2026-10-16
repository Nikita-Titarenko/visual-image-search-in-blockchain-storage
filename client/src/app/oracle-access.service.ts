import { Injectable } from '@angular/core';

import { mapServiceFetchError, parseServiceError } from './api-error.utils';

export interface OracleEncryptedUploadResult {
  ipfsHash: string;
  ipfsUri: string;
  gatewayUrl: string;
  pinSize: number;
  timestamp: string;
  encrypted: boolean;
  contentHash: string;
}

export interface OracleAccessClaimResult {
  blob: Blob;
}

const ORACLE_BASE_URL = 'http://localhost:8000';

@Injectable({ providedIn: 'root' })
export class OracleAccessService {
  buildClaimMessage(purchaseId: string, buyerAddress: string, issuedAt: string): string {
    return `Claim encrypted image access\nPurchase ID: ${purchaseId}\nBuyer: ${buyerAddress.toLowerCase()}\nIssued At: ${issuedAt}`;
  }

  async uploadEncryptedImage(file: File, contentHash: string): Promise<OracleEncryptedUploadResult> {
    const formData = new FormData();
    formData.append('file', file, file.name);
    formData.append('contentHash', contentHash);

    try {
      const response = await fetch(`${ORACLE_BASE_URL}/api/oracle/encrypt-upload`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw await parseServiceError(
          response,
          'Image-access service returned an error while encrypting and uploading the original image.',
        );
      }

      return (await response.json()) as OracleEncryptedUploadResult;
    } catch (error) {
      throw mapServiceFetchError(
        error,
        'Image-access service is unavailable. Start image-access-service and try the encrypted upload again.',
      );
    }
  }

  async downloadDecryptedFile(purchaseId: string, buyerAddress: string, signedMessage: string, issuedAt: string): Promise<Blob> {
    try {
      const response = await fetch(`${ORACLE_BASE_URL}/api/oracle/download`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          purchaseId: Number(purchaseId),
          buyerAddress,
          signedMessage,
          issuedAt,
        }),
      });

      if (!response.ok) {
        throw await parseServiceError(
          response,
          'Image-access service returned an error while downloading the decrypted original image.',
        );
      }

      return response.blob();
    } catch (error) {
      throw mapServiceFetchError(
        error,
        'Image-access service is unavailable. Start image-access-service and try the decrypted download again.',
      );
    }
  }
}