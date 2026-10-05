export const imageRegistryAbi = [
  'function registerCollection(string name, string metadataURI) returns (uint256)',
  'function registerImage(bytes32 contentHash, string metadataURI, uint256 collectionId) returns (uint256)',
  'function verifyImageHash(uint256 imageId, bytes32 candidateHash) view returns (bool)',
  'function getImage(uint256 imageId) view returns ((uint256 id, uint256 collectionId, address creator, address currentOwner, bytes32 contentHash, string metadataURI, uint64 registeredAt, bool exists))',
  'event CollectionRegistered(uint256 indexed collectionId, address indexed creator, string name)',
  'event ImageRegistered(uint256 indexed imageId, uint256 indexed collectionId, address indexed creator, bytes32 contentHash, string metadataURI)',
] as const;

export const licensingAndPaymentAbi = [
  'function configureLicenseOffer(uint256 imageId, uint256 priceWei, string termsURI, bool active)',
  'function buyLicense(uint256 imageId) payable returns (uint256)',
  'function confirmDownloadAccess(uint256 purchaseId, bytes32 accessProof)',
  'function getPurchase(uint256 purchaseId) view returns ((uint256 id, uint256 imageId, address buyer, address seller, uint256 paidAmount, bytes32 accessProof, uint64 purchasedAt, bool oracleConfirmed))',
  'event LicensePurchased(uint256 indexed purchaseId, uint256 indexed imageId, address indexed buyer, address seller, uint256 paidAmount)',
] as const;

export const modelAndIndexAuditAbi = [
  'function recordSnapshot(string modelVersion, bytes32 modelHash, string indexVersion, bytes32 indexHash, string metadataURI) returns (uint256)',
  'function getSnapshot(uint256 snapshotId) view returns ((uint256 id, string modelVersion, bytes32 modelHash, string indexVersion, bytes32 indexHash, string metadataURI, address submittedBy, uint64 recordedAt))',
  'function verifySnapshot(uint256 snapshotId, bytes32 expectedModelHash, bytes32 expectedIndexHash) view returns (bool)',
  'event AuditSnapshotRecorded(uint256 indexed snapshotId, string modelVersion, bytes32 indexed modelHash, string indexVersion, bytes32 indexed indexHash, string metadataURI, address submittedBy)',
] as const;