import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { DEFAULT_CONTRACT_ADDRESSES, POLYGON_AMOY_CONFIG } from './contracts.config';
import { DappService } from './dapp.service';
import { ImageSearchResult, ImageVectorSearchService } from './image-vector-search.service';
import { OracleAccessService } from './oracle-access.service';
import { PinataUploadService } from './pinata-upload.service';
import { WalletService } from './wallet.service';

@Component({
  imports: [CommonModule, FormsModule],
  selector: 'app-root',
  styleUrl: './app.css',
  templateUrl: './dashboard.html',
})
export class App {
  protected readonly formTabs = [
    { id: 'collection', label: '1. Collection' },
    { id: 'image', label: '2. Image' },
    { id: 'license', label: '3. License' },
    { id: 'buy', label: '4. Purchase' },
    { id: 'oracle', label: '5. Oracle' },
    { id: 'audit', label: '6. Audit' },
    { id: 'search', label: '7. Search' },
  ] as const;
  protected readonly walletService = inject(WalletService);
  private readonly dappService = inject(DappService);
  private readonly imageVectorSearchService = inject(ImageVectorSearchService);
  private readonly oracleAccessService = inject(OracleAccessService);
  private readonly pinataUploadService = inject(PinataUploadService);

  protected readonly appTitle = signal('Polygon Image Rights Console');
  protected readonly networkLabel = signal(`${POLYGON_AMOY_CONFIG.chainName} (${POLYGON_AMOY_CONFIG.chainId})`);
  protected readonly txStatus = signal('Connect a wallet to start the on-chain flow.');
  protected readonly activityLog = signal<string[]>([]);
  protected readonly inspectorOutput = signal('');
  protected readonly collectionPinataUri = signal('');
  protected readonly imagePinataUri = signal('');
  protected readonly licensePinataUri = signal('');
  protected readonly auditPinataUri = signal('');
  protected readonly encryptedAssetUri = signal('');
  protected readonly oracleAccessToken = signal('');
  protected readonly oracleDownloadUrl = signal('');
  protected readonly oracleTokenExpiry = signal('');
  protected readonly imageSearchResults = signal<ImageSearchResult[]>([]);
  protected readonly imageSearchMethod = signal<'cnn' | 'histogram'>('cnn');
  protected readonly imageSearchQueryHash = signal('');
  protected readonly activeFormTab = signal<(typeof this.formTabs)[number]['id']>('collection');

  protected contractAddresses = { ...DEFAULT_CONTRACT_ADDRESSES };

  protected collectionName = '';
  protected collectionDescription = '';
  protected collectionCategory = '';

  protected imageHashInput = '';
  protected imageCollectionId = '0';
  protected selectedImageFile: File | null = null;
  protected imageName = '';
  protected imageDescription = '';
  protected imageTags = '';

  protected licenseImageId = '';
  protected licensePriceMatic = '';
  protected licenseActive = true;
  protected licenseName = '';
  protected licenseDescription = '';
  protected licenseUsageTerms = '';

  protected buyImageId = '';
  protected buyPriceMatic = '';

  protected oraclePurchaseId = '';

  protected auditModelVersion = '';
  protected auditModelHash = '';
  protected auditIndexVersion = '';
  protected auditIndexHash = '';
  protected auditSummary = '';
  protected auditNotes = '';
  protected selectedSearchFile: File | null = null;
  protected searchFileName = '';

  protected inspectImageId = '';
  protected inspectCandidateHash = '';
  protected inspectPurchaseId = '';
  protected inspectSnapshotId = '';

  protected readonly shortAccount = computed(() => {
    const account = this.walletService.account();
    if (!account) {
      return 'Wallet not connected';
    }

    return `${account.slice(0, 6)}...${account.slice(-4)}`;
  });

  protected setActiveFormTab(tabId: (typeof this.formTabs)[number]['id']): void {
    this.activeFormTab.set(tabId);
  }

  protected async connectWallet(): Promise<void> {
    await this.runAction('Wallet connected', async () => {
      await this.walletService.connect();
      return `Connected ${this.walletService.account()} on chain ${this.walletService.chainId()}`;
    });
  }

  protected async switchToAmoy(): Promise<void> {
    await this.runAction('Switched network', async () => {
      await this.walletService.switchToPolygonAmoy();
      return `Wallet switched to ${POLYGON_AMOY_CONFIG.chainName}`;
    });
  }

  protected async hashSelectedFile(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      return;
    }

    this.selectedImageFile = file;

    const hash = await this.dappService.hashFile(file);
    this.imageHashInput = hash;
    this.inspectCandidateHash = hash;
    this.pushLog(`Calculated file hash for ${file.name}: ${hash}`);
  }

  protected async registerCollection(): Promise<void> {
    await this.runAction('Collection registered', async () => {
      const metadataUpload = await this.pinataUploadService.uploadJson(`${this.collectionName || 'collection'}-metadata`, {
        name: this.collectionName,
        description: this.collectionDescription,
        category: this.collectionCategory,
        creatorWallet: this.walletService.account(),
        createdAt: new Date().toISOString(),
      });

      this.collectionPinataUri.set(metadataUpload.ipfsUri);
      this.pushLog(`Pinned collection metadata to Pinata: ${metadataUpload.ipfsUri}`);

      const result = await this.dappService.registerCollection(this.contractAddresses, this.collectionName, metadataUpload.ipfsUri);
      return `Collection ID ${result.collectionId} tx ${result.transactionHash}`;
    });
  }

  protected async registerImage(): Promise<void> {
    await this.runAction('Image registered', async () => {
      if (!this.selectedImageFile) {
        throw new Error('Select an image file before registration.');
      }

      const assetUpload = await this.oracleAccessService.uploadEncryptedImage(this.selectedImageFile, this.imageHashInput);
      this.encryptedAssetUri.set(assetUpload.ipfsUri);
      this.pushLog(`Encrypted and uploaded ${this.selectedImageFile.name} to IPFS: ${assetUpload.ipfsUri}`);

      const metadataUpload = await this.pinataUploadService.uploadJson(`${this.imageName || this.selectedImageFile.name}-metadata`, {
        name: this.imageName,
        description: this.imageDescription,
        tags: this.imageTags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        collectionId: this.imageCollectionId,
        assetUri: assetUpload.ipfsUri,
        gatewayUrl: assetUpload.gatewayUrl,
        assetEncrypted: true,
        encryption: {
          algorithm: 'AES-256-GCM',
          accessMode: 'oracle-download-token',
          oracleBaseUrl: 'http://localhost:8000',
        },
        contentHash: this.imageHashInput,
        creatorWallet: this.walletService.account(),
        uploadedAt: new Date().toISOString(),
      });

      this.imagePinataUri.set(metadataUpload.ipfsUri);
      this.pushLog(`Pinned image metadata to Pinata: ${metadataUpload.ipfsUri}`);

      const result = await this.dappService.registerImage(
        this.contractAddresses,
        this.imageHashInput,
        metadataUpload.ipfsUri,
        this.imageCollectionId,
      );
      this.licenseImageId = result.imageId;
      this.buyImageId = result.imageId;
      this.inspectImageId = result.imageId;
      return `Image ID ${result.imageId} tx ${result.transactionHash}`;
    });
  }

  protected async configureLicense(): Promise<void> {
    await this.runAction('License configured', async () => {
      const metadataUpload = await this.pinataUploadService.uploadJson(`${this.licenseName || 'license'}-metadata`, {
        name: this.licenseName,
        description: this.licenseDescription,
        usageTerms: this.licenseUsageTerms,
        priceMatic: this.licensePriceMatic,
        imageId: this.licenseImageId,
        active: this.licenseActive,
        updatedAt: new Date().toISOString(),
      });

      this.licensePinataUri.set(metadataUpload.ipfsUri);
      this.pushLog(`Pinned license metadata to Pinata: ${metadataUpload.ipfsUri}`);

      const transactionHash = await this.dappService.configureLicenseOffer(
        this.contractAddresses,
        this.licenseImageId,
        this.licensePriceMatic,
        metadataUpload.ipfsUri,
        this.licenseActive,
      );
      return `Offer updated for image ${this.licenseImageId} tx ${transactionHash}`;
    });
  }

  protected async buyLicense(): Promise<void> {
    await this.runAction('License purchased', async () => {
      const result = await this.dappService.buyLicense(this.contractAddresses, this.buyImageId, this.buyPriceMatic);
      this.oraclePurchaseId = result.purchaseId;
      this.inspectPurchaseId = result.purchaseId;
      return `Purchase ID ${result.purchaseId} tx ${result.transactionHash}`;
    });
  }

  protected async claimEncryptedAccess(): Promise<void> {
    await this.runAction('Oracle access granted', async () => {
      const buyerAddress = this.walletService.account();
      if (!buyerAddress) {
        throw new Error('Connect the buyer wallet before requesting an access token.');
      }

      const issuedAt = new Date().toISOString();
      const signer = await this.walletService.getSigner();
      const claimMessage = this.oracleAccessService.buildClaimMessage(this.oraclePurchaseId, buyerAddress, issuedAt);
      const signedMessage = await signer.signMessage(claimMessage);
      const result = await this.oracleAccessService.claimAccessToken(
        this.oraclePurchaseId,
        buyerAddress,
        signedMessage,
        issuedAt,
      );

      this.oracleAccessToken.set(result.accessToken);
      this.oracleDownloadUrl.set(result.downloadUrl);
      this.oracleTokenExpiry.set(result.expiresAt);
      this.pushLog(`Oracle access token issued for purchase ${result.purchaseId}. Proof ${result.accessProof}`);
      if (result.confirmationTransactionHash) {
        this.pushLog(`Oracle confirmation tx: ${result.confirmationTransactionHash}`);
      }

      return `Encrypted asset access approved for purchase ${result.purchaseId}`;
    });
  }

  protected async downloadPurchasedImage(): Promise<void> {
    await this.runAction('Decrypted file downloaded', async () => {
      const accessToken = this.oracleAccessToken();
      const downloadUrl = this.oracleDownloadUrl();
      if (!accessToken || !downloadUrl) {
        throw new Error('Request an oracle access token before downloading the file.');
      }

      const blob = await this.oracleAccessService.downloadDecryptedFile(downloadUrl, accessToken);
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = this.imageName || `purchase-${this.oraclePurchaseId}`;
      anchor.click();
      URL.revokeObjectURL(objectUrl);

      return `Downloaded decrypted asset for purchase ${this.oraclePurchaseId}`;
    });
  }

  protected async recordAuditSnapshot(): Promise<void> {
    await this.runAction('Audit snapshot recorded', async () => {
      const metadataUpload = await this.pinataUploadService.uploadJson(`${this.auditModelVersion || 'audit'}-snapshot`, {
        summary: this.auditSummary,
        notes: this.auditNotes,
        modelVersion: this.auditModelVersion,
        modelHash: this.auditModelHash,
        indexVersion: this.auditIndexVersion,
        indexHash: this.auditIndexHash,
        recordedAt: new Date().toISOString(),
      });

      this.auditPinataUri.set(metadataUpload.ipfsUri);
      this.pushLog(`Pinned audit metadata to Pinata: ${metadataUpload.ipfsUri}`);

      const result = await this.dappService.recordAuditSnapshot(
        this.contractAddresses,
        this.auditModelVersion,
        this.auditModelHash,
        this.auditIndexVersion,
        this.auditIndexHash,
        metadataUpload.ipfsUri,
      );
      this.inspectSnapshotId = result.snapshotId;
      return `Snapshot ID ${result.snapshotId} tx ${result.transactionHash}`;
    });
  }

  protected handleSearchFileSelection(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    this.selectedSearchFile = file;
    this.searchFileName = file?.name ?? '';
  }

  protected async searchSimilarImages(): Promise<void> {
    await this.runAction('Image search completed', async () => {
      if (!this.selectedSearchFile) {
        throw new Error('Select an image file before running similarity search.');
      }

      const payload = await this.imageVectorSearchService.searchSimilarImages(
        this.selectedSearchFile,
        this.imageSearchMethod(),
        10,
      );

      this.imageSearchResults.set(payload.results);
      this.imageSearchQueryHash.set(payload.queryHash);
      this.pushLog(`Vector search returned ${payload.results.length} matches for ${this.selectedSearchFile.name}.`);

      return `Found ${payload.results.length} similar images using ${payload.method}`;
    });
  }

  protected async inspectImage(): Promise<void> {
    await this.runAction('Image inspected', async () => {
      const payload = await this.dappService.getImageDetails(
        this.contractAddresses,
        this.inspectImageId,
        this.inspectCandidateHash,
      );
      this.inspectorOutput.set(JSON.stringify(payload, null, 2));
      return `Loaded image ${this.inspectImageId}`;
    });
  }

  protected async inspectPurchase(): Promise<void> {
    await this.runAction('Purchase inspected', async () => {
      const payload = await this.dappService.getPurchaseDetails(this.contractAddresses, this.inspectPurchaseId);
      this.inspectorOutput.set(JSON.stringify(payload, null, 2));
      return `Loaded purchase ${this.inspectPurchaseId}`;
    });
  }

  protected async inspectSnapshot(): Promise<void> {
    await this.runAction('Snapshot inspected', async () => {
      const payload = await this.dappService.getSnapshotDetails(
        this.contractAddresses,
        this.inspectSnapshotId,
        this.auditModelHash,
        this.auditIndexHash,
      );
      this.inspectorOutput.set(JSON.stringify(payload, null, 2));
      return `Loaded snapshot ${this.inspectSnapshotId}`;
    });
  }

  private async runAction(successPrefix: string, action: () => Promise<string>): Promise<void> {
    this.txStatus.set('Waiting for wallet confirmation...');

    try {
      const message = await action();
      this.txStatus.set(message);
      this.pushLog(`${successPrefix}: ${message}`);
    } catch (error) {
      const message = this.dappService.formatError(error);
      this.txStatus.set(message);
      this.pushLog(`Error: ${message}`);
    }
  }

  private pushLog(message: string): void {
    this.activityLog.update((entries) => [message, ...entries].slice(0, 12));
  }
}
