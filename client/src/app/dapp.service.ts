import { Injectable, inject } from '@angular/core';
import { Contract, Interface, keccak256, parseEther, toUtf8Bytes, zeroPadValue } from 'ethers';

import { imageRegistryAbi, licensingAndPaymentAbi, modelAndIndexAuditAbi } from './contract-abis';
import { ContractAddresses } from './contracts.config';
import { WalletService } from './wallet.service';

@Injectable({ providedIn: 'root' })
export class DappService {
  private static readonly MIN_PRIORITY_FEE_PER_GAS = 35_000_000_000n;
  private static readonly imageRegistryInterface = new Interface(imageRegistryAbi);
  private static readonly licensingAndPaymentInterface = new Interface(licensingAndPaymentAbi);
  private static readonly modelAndIndexAuditInterface = new Interface(modelAndIndexAuditAbi);
  private static readonly builtinErrorInterface = new Interface([
    'error Error(string)',
    'error Panic(uint256)',
  ]);
  private readonly walletService = inject(WalletService);

  async hashFile(file: File): Promise<string> {
    const bytes = new Uint8Array(await file.arrayBuffer());
    return keccak256(bytes);
  }

  async registerCollection(addresses: ContractAddresses, metadataUri: string) {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.imageRegistry, imageRegistryAbi, signer);
    const tx = await contract['registerCollection'](metadataUri, await this.getWriteOverrides(signer));
    const receipt = await tx.wait();
    const collectionId = this.extractEventValue(receipt.logs, imageRegistryAbi, 'CollectionRegistered', 'collectionId');

    return { transactionHash: tx.hash, collectionId };
  }

  async registerImage(addresses: ContractAddresses, contentHash: string, metadataUri: string, collectionId: string) {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.imageRegistry, imageRegistryAbi, signer);
    const tx = await contract['registerImage'](
      this.normalizeHash(contentHash),
      metadataUri,
      BigInt(collectionId || '0'),
      await this.getWriteOverrides(signer),
    );
    const receipt = await tx.wait();
    const imageId = this.extractEventValue(receipt.logs, imageRegistryAbi, 'ImageRegistered', 'imageId');

    return { transactionHash: tx.hash, imageId };
  }

  async configureLicenseOffer(addresses: ContractAddresses, imageId: string, priceInMatic: string, termsUri: string, active: boolean): Promise<string> {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const tx = await contract['configureLicenseOffer'](
      BigInt(imageId),
      parseEther(priceInMatic || '0'),
      termsUri,
      active,
      await this.getWriteOverrides(signer),
    );
    await tx.wait();
    return tx.hash;
  }

  async buyLicense(addresses: ContractAddresses, imageId: string, priceInMatic: string) {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const tx = await contract['buyLicense'](BigInt(imageId), {
      ...(await this.getWriteOverrides(signer)),
      value: parseEther(priceInMatic || '0'),
    });
    const receipt = await tx.wait();
    const purchaseId = this.extractEventValue(receipt.logs, licensingAndPaymentAbi, 'LicensePurchased', 'purchaseId');

    return { transactionHash: tx.hash, purchaseId };
  }

  async hasPurchasedLicense(addresses: ContractAddresses, imageId: string, buyerAddress: string): Promise<boolean> {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, provider);
    return await contract['hasPurchasedLicense'](BigInt(imageId), buyerAddress.trim());
  }

  async pauseLicensing(addresses: ContractAddresses): Promise<string> {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const tx = await contract['pause'](await this.getWriteOverrides(signer));
    await tx.wait();
    return tx.hash;
  }

  async unpauseLicensing(addresses: ContractAddresses): Promise<string> {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const tx = await contract['unpause'](await this.getWriteOverrides(signer));
    await tx.wait();
    return tx.hash;
  }

  async withdrawPayments(addresses: ContractAddresses): Promise<string> {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const tx = await contract['withdrawPayments'](await this.getWriteOverrides(signer));
    await tx.wait();
    return tx.hash;
  }

  async getImageDetails(addresses: ContractAddresses, imageId: string) {
    const provider = this.walletService.getReadOnlyProvider();
    const registryContract = new Contract(addresses.imageRegistry, imageRegistryAbi, provider);
    const licensingContract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, provider);
    const normalizedImageId = BigInt(imageId);
    const [image, licenseOffer] = await Promise.all([
      registryContract['getImage'](normalizedImageId),
      licensingContract['getLicenseOffer'](normalizedImageId),
    ]);

    return { image, licenseOffer };
  }

  async getCollectionDetails(addresses: ContractAddresses, collectionId: string) {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.imageRegistry, imageRegistryAbi, provider);
    const [collection, images] = await contract['getCollectionWithImages'](BigInt(collectionId));
    return { collection, images };
  }

  async getPurchaseDetails(addresses: ContractAddresses, purchaseId: string) {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, provider);
    const purchase = await contract['getPurchase'](BigInt(purchaseId));
    return { purchase };
  }

  async getMyPurchases(addresses: ContractAddresses) {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const purchases = await contract['getMyPurchases']();
    return { purchases };
  }

  async getMySales(addresses: ContractAddresses) {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, signer);
    const sales = await contract['getMySales']();
    return { sales };
  }

  async getLicensingPauseStatus(addresses: ContractAddresses): Promise<boolean> {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.licensingAndPayment, licensingAndPaymentAbi, provider);
    return await contract['paused']();
  }

  async getSnapshotDetails(addresses: ContractAddresses) {
    const provider = this.walletService.getReadOnlyProvider();
    const contract = new Contract(addresses.modelAndIndexAudit, modelAndIndexAuditAbi, provider);
    const snapshots = await contract['getAllSnapshots']();
    return { snapshots };
  }

  async setAuditOwner(addresses: ContractAddresses, newOwner: string): Promise<string> {
    const signer = await this.walletService.getSigner();
    const contract = new Contract(addresses.modelAndIndexAudit, modelAndIndexAuditAbi, signer);
    const transaction = await contract['setOwner'](newOwner.trim());
    const receipt = await transaction.wait();
    return receipt.hash;
  }

  formatError(error: unknown): string {
    const mappedRpcError = this.tryMapRpcError(error);
    if (mappedRpcError) {
      return mappedRpcError;
    }

    const decodedContractError = this.tryDecodeContractError(error);
    if (decodedContractError) {
      return decodedContractError;
    }

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

  private tryMapRpcError(error: unknown): string | null {
    if (!error || typeof error !== 'object') {
      return null;
    }

    const errorRecord = error as Record<string, unknown>;
    if (errorRecord['code'] === 'ACTION_REJECTED' || this.readNestedValue(errorRecord, ['info', 'error', 'code']) === 4001) {
      return 'Transaction was rejected in the wallet.';
    }

    const message = this.readNestedValue(errorRecord, ['info', 'error', 'data', 'message']);
    if (typeof message === 'string' && message.toLowerCase().includes('gas required exceeds allowance')) {
      return 'Insufficient MATIC balance to cover transaction fees.';
    }

    return null;
  }

  private tryDecodeContractError(error: unknown): string | null {
    for (const data of this.collectErrorDataCandidates(error)) {
      const parsedError = this.tryParseErrorData(data);
      if (parsedError) {
        return parsedError;
      }
    }

    return null;
  }

  private collectErrorDataCandidates(error: unknown): string[] {
    if (!error || typeof error !== 'object') {
      return [];
    }

    const errorRecord = error as Record<string, unknown>;
    const candidates = [
      errorRecord['data'],
      this.readNestedValue(errorRecord, ['revert', 'data']),
      this.readNestedValue(errorRecord, ['info', 'error', 'data', 'data']),
      this.readNestedValue(errorRecord, ['info', 'error', 'data']),
      this.readNestedValue(errorRecord, ['error', 'data', 'data']),
      this.readNestedValue(errorRecord, ['error', 'data']),
      this.readNestedValue(errorRecord, ['cause', 'data']),
    ];

    return candidates.filter((value): value is string => typeof value === 'string' && /^0x[0-9a-fA-F]+$/.test(value));
  }

  private readNestedValue(value: unknown, path: string[]): unknown {
    let currentValue = value;
    for (const key of path) {
      if (!currentValue || typeof currentValue !== 'object' || !(key in (currentValue as Record<string, unknown>))) {
        return null;
      }
      currentValue = (currentValue as Record<string, unknown>)[key];
    }
    return currentValue;
  }

  private tryParseErrorData(data: string): string | null {
    const interfaces = [
      DappService.imageRegistryInterface,
      DappService.licensingAndPaymentInterface,
      DappService.modelAndIndexAuditInterface,
      DappService.builtinErrorInterface,
    ];

    for (const contractInterface of interfaces) {
      try {
        const parsed = contractInterface.parseError(data);
        if (parsed) {
          return this.mapContractError(parsed.name, parsed.args);
        }
      } catch {
        continue;
      }
    }

    return null;
  }

  private mapContractError(name: string, args: readonly unknown[]): string {
    switch (name) {
      case 'EmptyContentHash':
        return 'The image content hash is empty.';
      case 'ImageNotRegistered':
        return `Image ${this.stringifyErrorArg(args[0])} is not registered.`;
      case 'CollectionNotRegistered':
        return `Collection ${this.stringifyErrorArg(args[0])} is not registered.`;
      case 'ImageHashAlreadyRegistered':
        return `This image hash is already registered: ${this.stringifyErrorArg(args[0])}.`;
      case 'OnlyCollectionCreatorCanAddImages':
        return `Only the collection creator can add images to collection ${this.stringifyErrorArg(args[0])}. Caller: ${this.stringifyErrorArg(args[1])}.`;
      case 'RegistryAddressIsZero':
        return 'The licensing contract registry address is zero.';
      case 'CallerIsNotImageOwner':
        return `Only the current owner can manage image ${this.stringifyErrorArg(args[0])}. Caller: ${this.stringifyErrorArg(args[1])}.`;
      case 'LicenseOfferNotActive':
        return `The license offer for image ${this.stringifyErrorArg(args[0])} is not active.`;
      case 'LicenseAlreadyPurchased':
        return `Buyer ${this.stringifyErrorArg(args[1])} already owns a license for image ${this.stringifyErrorArg(args[0])}.`;
      case 'CannotBuyOwnImage':
        return `Buyer ${this.stringifyErrorArg(args[1])} cannot buy a license for owned image ${this.stringifyErrorArg(args[0])}.`;
      case 'IncorrectPaymentAmount':
        return `Incorrect payment amount. Expected ${this.stringifyErrorArg(args[0])} wei, received ${this.stringifyErrorArg(args[1])} wei.`;
      case 'OfferSellerIsOutdated':
        return `The stored seller for image ${this.stringifyErrorArg(args[0])} is outdated. Current owner: ${this.stringifyErrorArg(args[1])}, offer seller: ${this.stringifyErrorArg(args[2])}.`;
      case 'PurchaseDoesNotExist':
        return `Purchase ${this.stringifyErrorArg(args[0])} does not exist.`;
      case 'NoFundsAvailable':
        return `No funds are available for withdrawal by ${this.stringifyErrorArg(args[0])}.`;
      case 'WithdrawalFailed':
        return `Withdrawal failed for ${this.stringifyErrorArg(args[0])} with amount ${this.stringifyErrorArg(args[1])} wei.`;
      case 'EmptyModelVersion':
        return 'The model version cannot be empty.';
      case 'EmptyIndexVersion':
        return 'The index version cannot be empty.';
      case 'EmptyModelHash':
        return 'The model hash cannot be empty.';
      case 'EmptyIndexHash':
        return 'The index hash cannot be empty.';
      case 'SnapshotDoesNotExist':
        return `Snapshot ${this.stringifyErrorArg(args[0])} does not exist.`;
      case 'OwnableUnauthorizedAccount':
        return `Only the contract owner can call this method. Caller: ${this.stringifyErrorArg(args[0])}.`;
      case 'OwnableInvalidOwner':
        return `The owner address is invalid: ${this.stringifyErrorArg(args[0])}.`;
      case 'EnforcedPause':
        return 'This action is unavailable while the contract is paused.';
      case 'ExpectedPause':
        return 'This action requires the contract to be paused first.';
      case 'ReentrancyGuardReentrantCall':
        return 'This action was blocked by reentrancy protection.';
      case 'Error':
        return this.stringifyErrorArg(args[0]);
      case 'Panic':
        return `The EVM reverted with panic code ${this.stringifyErrorArg(args[0])}.`;
      default:
        return `Smart contract error: ${name}.`;
    }
  }

  private stringifyErrorArg(value: unknown): string {
    if (typeof value === 'bigint') {
      return value.toString();
    }
    if (typeof value === 'string') {
      return value;
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
    if (value && typeof value === 'object' && 'toString' in value) {
      return String(value);
    }
    return 'unknown';
  }

  private async getWriteOverrides(signer: Awaited<ReturnType<WalletService['getSigner']>>) {
    const provider = this.walletService.getReadOnlyProvider();
    const latestBlock = await provider.getBlock('latest');
    const feeData = await provider.getFeeData();
    const suggestedPriorityFeePerGas = feeData?.maxPriorityFeePerGas ?? feeData?.gasPrice ?? 0n;
    const priorityFeePerGas = suggestedPriorityFeePerGas > DappService.MIN_PRIORITY_FEE_PER_GAS
      ? suggestedPriorityFeePerGas
      : DappService.MIN_PRIORITY_FEE_PER_GAS;
    const baseFeePerGas = latestBlock?.baseFeePerGas ?? 0n;
    const maxFeePerGas = baseFeePerGas > 0n
      ? (baseFeePerGas * 2n) + priorityFeePerGas
      : priorityFeePerGas;

    return {
      maxPriorityFeePerGas: priorityFeePerGas,
      maxFeePerGas,
    };
  }
}