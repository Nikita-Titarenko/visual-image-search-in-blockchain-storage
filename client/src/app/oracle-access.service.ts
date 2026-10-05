import { Injectable } from '@angular/core';

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
  purchaseId: number;
  imageId: number;
  buyerAddress: string;
  encryptedAssetUri: string;
  metadataUri: string;
  metadataName: string;
  accessToken: string;
  accessProof: string;
  expiresAt: string;
  downloadUrl: string;
  confirmationTransactionHash: string | null;
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

    const response = await fetch(`${ORACLE_BASE_URL}/api/oracle/encrypt-upload`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string; error?: string } | null;
      throw new Error(payload?.detail || payload?.error || 'Encrypted upload failed.');
    }

    return (await response.json()) as OracleEncryptedUploadResult;
  }

  async claimAccessToken(purchaseId: string, buyerAddress: string, signedMessage: string, issuedAt: string): Promise<OracleAccessClaimResult> {
    const response = await fetch(`${ORACLE_BASE_URL}/api/oracle/claim-access`, {
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
      const payload = (await response.json().catch(() => null)) as { detail?: string; error?: string } | null;
      throw new Error(payload?.detail || payload?.error || 'Oracle access claim failed.');
    }

    return (await response.json()) as OracleAccessClaimResult;
  }

  async downloadDecryptedFile(downloadUrl: string, accessToken: string): Promise<Blob> {
    const response = await fetch(`${ORACLE_BASE_URL}${downloadUrl}?token=${encodeURIComponent(accessToken)}`);
    if (!response.ok) {
      const payload = (await response.json().catch(() => null)) as { detail?: string; error?: string } | null;
      throw new Error(payload?.detail || payload?.error || 'Decrypted download failed.');
    }

    return response.blob();
  }
}