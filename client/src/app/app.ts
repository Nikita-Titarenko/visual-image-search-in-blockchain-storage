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
    { id: 'search', label: '6. Search' },
    { id: 'set-oracle', label: '7. Set Oracle' },
    { id: 'pause-licensing', label: '8. Pause Licensing' },
    { id: 'withdraw-payments', label: '9. Withdraw Payments' },
  ] as const;
  protected readonly inspectTabs = [
    { id: 'collection', label: 'Inspect Collection' },
    { id: 'image', label: 'Inspect Image' },
    { id: 'purchase', label: 'Inspect Purchase' },
    { id: 'snapshot', label: 'Inspect Snapshot' },
  ] as const;
  protected readonly walletService = inject(WalletService);
  private readonly dappService = inject(DappService);
  private readonly imageVectorSearchService = inject(ImageVectorSearchService);
  private readonly oracleAccessService = inject(OracleAccessService);
  private readonly pinataUploadService = inject(PinataUploadService);

  protected readonly appTitle = signal('Polygon Image Rights Console');
  protected readonly networkLabel = signal(`${POLYGON_AMOY_CONFIG.chainName} (${POLYGON_AMOY_CONFIG.chainId})`);
  protected readonly txStatus = signal('Connect a wallet to start the on-chain flow.');
  protected readonly lastActivity = signal<{ state: 'processing' | 'success' | 'error'; message: string } | null>(null);
  protected readonly activityLog = signal<string[]>([]);
  protected readonly inspectorOutput = signal('');
  protected readonly collectionPinataUri = signal('');
  protected readonly imagePinataUri = signal('');
  protected readonly licensePinataUri = signal('');
  protected readonly encryptedAssetUri = signal('');
  protected readonly oracleAccessToken = signal('');
  protected readonly oracleDownloadUrl = signal('');
  protected readonly oracleTokenExpiry = signal('');
  protected readonly imageSearchResults = signal<ImageSearchResult[]>([]);
  protected readonly imageSearchMethod = signal<'cnn' | 'histogram'>('cnn');
  protected readonly imageSearchQueryHash = signal('');
  protected readonly licensingPaused = signal<boolean | null>(null);
  protected readonly activeFormTab = signal<(typeof this.formTabs)[number]['id']>('collection');
  protected readonly activeInspectTab = signal<(typeof this.inspectTabs)[number]['id']>('collection');

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
  protected selectedSearchFile: File | null = null;
  protected searchFileName = '';
  protected licensingOracleAddress = '';

  protected inspectCollectionId = '';
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

  protected imageSearchResultSrc(result: ImageSearchResult): string {
    if (result.resultType === 'dataset') {
      return result.imageBytes ? `data:${result.imageMediaType || 'image/jpeg'};base64,${result.imageBytes}` : '';
    }

    return result.gatewayUrl || '';
  }

  protected setActiveFormTab(tabId: (typeof this.formTabs)[number]['id']): void {
    this.activeFormTab.set(tabId);
  }

  protected setActiveInspectTab(tabId: (typeof this.inspectTabs)[number]['id']): void {
    this.activeInspectTab.set(tabId);
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
      this.inspectCollectionId = result.collectionId;
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

      const compressedPreview = await this.buildCompressedPreviewFile(this.selectedImageFile);
      const previewUpload = await this.pinataUploadService.uploadImage(compressedPreview);
      this.pushLog(`Compressed preview uploaded to Pinata: ${previewUpload.ipfsUri}`);

      const metadataUpload = await this.pinataUploadService.uploadJson(`${this.imageName || this.selectedImageFile.name}-metadata`, {
        name: this.imageName,
        description: this.imageDescription,
        tags: this.imageTags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        collectionId: this.imageCollectionId,
        assetUri: assetUpload.ipfsUri,
        encryptedGatewayUrl: assetUpload.gatewayUrl,
        previewUri: previewUpload.ipfsUri,
        previewGatewayUrl: previewUpload.gatewayUrl,
        previewFileName: compressedPreview.name,
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

  private async buildCompressedPreviewFile(file: File): Promise<File> {
    const objectUrl = URL.createObjectURL(file);

    try {
      const imageElement = await this.loadImageElement(objectUrl);
      const maxDimension = 512;
      const scale = Math.min(1, maxDimension / Math.max(imageElement.width, imageElement.height));
      const width = Math.max(1, Math.round(imageElement.width * scale));
      const height = Math.max(1, Math.round(imageElement.height * scale));
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;

      const context = canvas.getContext('2d');
      if (!context) {
        throw new Error('Unable to prepare compressed preview canvas.');
      }

      context.drawImage(imageElement, 0, 0, width, height);
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((value) => {
          if (value) {
            resolve(value);
            return;
          }
          reject(new Error('Unable to generate compressed preview image.'));
        }, 'image/jpeg', 0.78);
      });

      return new File([blob], `${this.getFileStem(file.name)}-preview.jpg`, { type: 'image/jpeg' });
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  private loadImageElement(objectUrl: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const imageElement = new Image();
      imageElement.onload = () => resolve(imageElement);
      imageElement.onerror = () => reject(new Error('Unable to read the selected image file.'));
      imageElement.src = objectUrl;
    });
  }

  private getFileStem(fileName: string): string {
    const dotIndex = fileName.lastIndexOf('.');
    return dotIndex > 0 ? fileName.slice(0, dotIndex) : fileName;
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

  protected async updateLicensingOracle(): Promise<void> {
    await this.runAction('Oracle address updated', async () => {
      const transactionHash = await this.dappService.setOracle(this.contractAddresses, this.licensingOracleAddress);
      return `Oracle updated to ${this.licensingOracleAddress} tx ${transactionHash}`;
    });
  }

  protected async loadLicensingPauseStatus(): Promise<void> {
    await this.runAction('Licensing pause status loaded', async () => {
      const isPaused = await this.dappService.getLicensingPauseStatus(this.contractAddresses);
      this.licensingPaused.set(isPaused);
      return `LicensingAndPayment is currently ${isPaused ? 'paused' : 'active'}`;
    });
  }

  protected async pauseLicensing(): Promise<void> {
    await this.runAction('Licensing paused', async () => {
      const transactionHash = await this.dappService.pauseLicensing(this.contractAddresses);
      this.licensingPaused.set(true);
      return `LicensingAndPayment paused tx ${transactionHash}`;
    });
  }

  protected async unpauseLicensing(): Promise<void> {
    await this.runAction('Licensing unpaused', async () => {
      const transactionHash = await this.dappService.unpauseLicensing(this.contractAddresses);
      this.licensingPaused.set(false);
      return `LicensingAndPayment unpaused tx ${transactionHash}`;
    });
  }

  protected async withdrawSellerPayments(): Promise<void> {
    await this.runAction('Payments withdrawn', async () => {
      const transactionHash = await this.dappService.withdrawPayments(this.contractAddresses);
      return `Withdraw completed tx ${transactionHash}`;
    });
  }

  protected async inspectImage(): Promise<void> {
    await this.runAction('Image inspected', async () => {
      const payload = await this.dappService.getImageDetails(
        this.contractAddresses,
        this.inspectImageId,
        this.inspectCandidateHash,
      );
      this.inspectorOutput.set(this.stringifyInspectorOutput(payload));
      return `Loaded image ${this.inspectImageId}`;
    });
  }

  protected async inspectCollection(): Promise<void> {
    await this.runAction('Collection inspected', async () => {
      const payload = await this.dappService.getCollectionDetails(this.contractAddresses, this.inspectCollectionId);
      this.inspectorOutput.set(this.stringifyInspectorOutput(payload));
      return `Loaded collection ${this.inspectCollectionId}`;
    });
  }

  protected async inspectPurchase(): Promise<void> {
    await this.runAction('Purchase inspected', async () => {
      const payload = await this.dappService.getPurchaseDetails(this.contractAddresses, this.inspectPurchaseId);
      this.inspectorOutput.set(this.stringifyInspectorOutput(payload));
      return `Loaded purchase ${this.inspectPurchaseId}`;
    });
  }

  protected async inspectSnapshot(): Promise<void> {
    await this.runAction('Snapshot inspected', async () => {
      const payload = await this.dappService.getSnapshotDetails(this.contractAddresses, this.inspectSnapshotId, '', '');
      this.inspectorOutput.set(this.stringifyInspectorOutput(payload));
      return `Loaded snapshot ${this.inspectSnapshotId}`;
    });
  }

  private stringifyInspectorOutput(value: unknown): string {
    return JSON.stringify(value, (_key, candidate) => typeof candidate === 'bigint' ? candidate.toString() : candidate, 2);
  }

  private async runAction(successPrefix: string, action: () => Promise<string>): Promise<void> {
    this.txStatus.set('Waiting for wallet confirmation...');
    this.lastActivity.set({ state: 'processing', message: 'Waiting for wallet confirmation...' });

    try {
      const message = await action();
      this.txStatus.set(message);
      this.lastActivity.set({ state: 'success', message });
      this.pushLog(`${successPrefix}: ${message}`);
    } catch (error) {
      const message = this.dappService.formatError(error);
      this.txStatus.set(message);
      this.lastActivity.set({ state: 'error', message });
      this.pushLog(`Error: ${message}`);
    }
  }

  private pushLog(message: string): void {
    this.activityLog.update((entries) => [message, ...entries].slice(0, 12));
  }
}
