import { Injectable, inject } from '@angular/core';
import { Contract, Interface, keccak256, parseEther, toUtf8Bytes, zeroPadValue } from 'ethers';

import { imageRegistryAbi, licensingAndPaymentAbi, modelAndIndexAuditAbi } from './contract-abis';
import { ContractAddresses } from './contracts.config';
import { WalletService } from './wallet.service';

@Injectable({ providedIn: 'root' })
export class DappService {
  private readonly walletService = inject(WalletService);

  async hashFile(file: File): Promise<string> {
    const bytes = new Uint8Array(await file.arrayBuffer());
    return keccak256(bytes);
  }

  async registerCollection(addresses: ContractAddresses, name: string, metadataUri: string) {
    const contract = new Contract(addresses.imageRegistry, imageRegistryAbi, await this.walletService.getSigner());
    const tx = await contract['registerCollection'](name, metadataUri);
    const receipt = await tx.wait();
    const collectionId = this.extractEventValue(receipt.logs, imageRegistryAbi, 'CollectionRegistered', 'collectionId');

    return { transactionHash: tx.hash, collectionId };
  }

  async registerImage(addresses: ContractAddresses, contentHash: string, metadataUri: string, collectionId: string) {
    const contract = new Contract(addresses.imageRegistry, imageRegistryAbi, await this.walletService.getSigner());
    const tx = await contract['registerImage'](this.normalizeHash(contentHash), metadataUri, BigInt(collectionId || '0'));
    const receipt = await tx.wait();
    const imageId = this.extractEventValue(receipt.logs, imageRegistryAbi, 'ImageRegistered', 'imageId');

    return { transactionHash: tx.hash, imageId };
  }

  async configureLicenseOffer(addresses: ContractAddresses, imageId: string, priceInMatic: string, termsUri: string, active: boolean): Promise<string> {
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, await this.walletService.getSigner());
    const tx = await contract['configureLicenseOffer'](BigInt(imageId), parseEther(priceInMatic || '0'), termsUri, active);
    await tx.wait();
    return tx.hash;
  }

  async buyLicense(addresses: ContractAddresses, imageId: string, priceInMatic: string) {
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, await this.walletService.getSigner());
    const tx = await contract['buyLicense'](BigInt(imageId), { value: parseEther(priceInMatic || '0') });
    const receipt = await tx.wait();
    const purchaseId = this.extractEventValue(receipt.logs, licensingAndPaymentAbi, 'LicensePurchased', 'purchaseId');

    return { transactionHash: tx.hash, purchaseId };
  }

  async confirmDownloadAccess(addresses: ContractAddresses, purchaseId: string, accessProof: string): Promise<string> {
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, await this.walletService.getSigner());
    const tx = await contract['confirmDownloadAccess'](BigInt(purchaseId), this.normalizeHash(accessProof));
    await tx.wait();
    return tx.hash;
  }

  async recordAuditSnapshot(addresses: ContractAddresses, modelVersion: string, modelHash: string, indexVersion: string, indexHash: string, metadataUri: string) {
    const contract = new Contract(addresses.modelAndIndexAudit, modelAndIndexAuditAbi, await this.walletService.getSigner());
    const tx = await contract['recordSnapshot'](
      modelVersion,
      this.normalizeHash(modelHash),
      indexVersion,
      this.normalizeHash(indexHash),
      metadataUri,
    );
    const receipt = await tx.wait();
    const snapshotId = this.extractEventValue(receipt.logs, modelAndIndexAuditAbi, 'AuditSnapshotRecorded', 'snapshotId');

    return { transactionHash: tx.hash, snapshotId };
  }

  async getImageDetails(addresses: ContractAddresses, imageId: string, candidateHash: string) {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.imageRegistry, imageRegistryAbi, provider);
    const image = await contract['getImage'](BigInt(imageId));
    const hashMatches = candidateHash ? await contract['verifyImageHash'](BigInt(imageId), this.normalizeHash(candidateHash)) : null;

    return { image, hashMatches };
  }

  async getPurchaseDetails(addresses: ContractAddresses, purchaseId: string) {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, provider);
    const purchase = await contract['getPurchase'](BigInt(purchaseId));
    return { purchase };
  }

  async getSnapshotDetails(addresses: ContractAddresses, snapshotId: string, expectedModelHash: string, expectedIndexHash: string) {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.modelAndIndexAudit, modelAndIndexAuditAbi, provider);
    const snapshot = await contract['getSnapshot'](BigInt(snapshotId));
    const isVerified = expectedModelHash && expectedIndexHash
      ? await contract['verifySnapshot'](BigInt(snapshotId), this.normalizeHash(expectedModelHash), this.normalizeHash(expectedIndexHash))
      : null;

    return { snapshot, isVerified };
  }

  formatError(error: unknown): string {
    if (error instanceof Error) {
      return error.message;
    }

    return 'Unknown blockchain interaction error';
  }

  private extractEventValue(logs: readonly unknown[], abi: readonly string[], eventName: string, fieldName: string): string {
    const contractInterface = new Interface(abi);

    for (const log of logs) {
      try {
        const parsed = contractInterface.parseLog(log as { topics: readonly string[]; data: string });
        if (parsed?.name === eventName) {
          const value = parsed.args[fieldName];
          return value.toString();
        }
      } catch {
        continue;
      }
    }

    throw new Error(`Unable to parse ${eventName} from transaction logs.`);
  }

  private normalizeHash(value: string): string {
    const trimmed = value.trim();
    if (!trimmed) {
      throw new Error('Hash input is empty.');
    }

    if (/^0x[0-9a-fA-F]{64}$/.test(trimmed)) {
      return trimmed;
    }

    if (/^0x[0-9a-fA-F]+$/.test(trimmed)) {
      return zeroPadValue(trimmed, 32);
    }

    return keccak256(toUtf8Bytes(trimmed));
  }
}