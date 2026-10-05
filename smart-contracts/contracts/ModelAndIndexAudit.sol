// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract ModelAndIndexAudit is Ownable {
    error EmptyModelVersion();
    error EmptyIndexVersion();
    error EmptyModelHash();
    error EmptyIndexHash();
    error SnapshotDoesNotExist(uint256 snapshotId);

    struct AuditSnapshot {
        uint256 id;
        string modelVersion;
        bytes32 modelHash;
        string indexVersion;
        bytes32 indexHash;
        string metadataURI;
        address submittedBy;
        uint64 recordedAt;
    }

    uint256 private _nextSnapshotId = 1;
    mapping(uint256 => AuditSnapshot) private _snapshots;

    event AuditSnapshotRecorded(
        uint256 indexed snapshotId,
        string modelVersion,
        bytes32 indexed modelHash,
        string indexVersion,
        bytes32 indexed indexHash,
        string metadataURI,
        address submittedBy
    );

    /// @notice Creates the audit contract.
    /// @param initialOwner The address that receives the Ownable administrator role.
    constructor(address initialOwner) Ownable(initialOwner) {}

    /// @notice Records a new audit snapshot for a model and its search index.
    /// @param modelVersion The semantic version or label of the model.
    /// @param modelHash The immutable hash of the model artifact.
    /// @param indexVersion The semantic version or label of the search index.
    /// @param indexHash The immutable hash of the search index artifact.
    /// @param metadataURI The URI pointing to additional audit metadata.
    /// @return snapshotId The newly assigned audit snapshot identifier.
    function recordSnapshot(
        string calldata modelVersion,
        bytes32 modelHash,
        string calldata indexVersion,
        bytes32 indexHash,
        string calldata metadataURI
    ) external onlyOwner returns (uint256 snapshotId) {
        if (bytes(modelVersion).length == 0) {
            revert EmptyModelVersion();
        }
        if (bytes(indexVersion).length == 0) {
            revert EmptyIndexVersion();
        }
        if (modelHash == bytes32(0)) {
            revert EmptyModelHash();
        }
        if (indexHash == bytes32(0)) {
            revert EmptyIndexHash();
        }

        snapshotId = _nextSnapshotId++;
        _snapshots[snapshotId] = AuditSnapshot({
            id: snapshotId,
            modelVersion: modelVersion,
            modelHash: modelHash,
            indexVersion: indexVersion,
            indexHash: indexHash,
            metadataURI: metadataURI,
            submittedBy: msg.sender,
            recordedAt: uint64(block.timestamp)
        });

        emit AuditSnapshotRecorded(snapshotId, modelVersion, modelHash, indexVersion, indexHash, metadataURI, msg.sender);
    }

    /// @notice Returns a previously recorded audit snapshot.
    /// @param snapshotId The snapshot identifier to query.
    /// @return snapshot The stored audit snapshot.
    function getSnapshot(uint256 snapshotId) external view returns (AuditSnapshot memory) {
        if (_snapshots[snapshotId].id == 0) {
            revert SnapshotDoesNotExist(snapshotId);
        }
        return _snapshots[snapshotId];
    }

    /// @notice Verifies whether the supplied model and index hashes match a stored snapshot.
    /// @param snapshotId The snapshot identifier to verify.
    /// @param expectedModelHash The model hash to compare against storage.
    /// @param expectedIndexHash The index hash to compare against storage.
    /// @return isMatch True when both supplied hashes match the stored snapshot.
    function verifySnapshot(
        uint256 snapshotId,
        bytes32 expectedModelHash,
        bytes32 expectedIndexHash
    ) external view returns (bool) {
        AuditSnapshot storage snapshot = _snapshots[snapshotId];
        if (snapshot.id == 0) {
            revert SnapshotDoesNotExist(snapshotId);
        }
        return snapshot.modelHash == expectedModelHash && snapshot.indexHash == expectedIndexHash;
    }
}