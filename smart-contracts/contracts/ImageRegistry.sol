// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";

contract ImageRegistry is Ownable {
    error EmptyContentHash();
    error InvalidNewOwner();
    error InputLengthMismatch();
    error ImageNotRegistered(uint256 imageId);
    error CollectionNotRegistered(uint256 collectionId);
    error ImageHashAlreadyRegistered(bytes32 contentHash);
    error CallerIsNotCurrentOwner(uint256 imageId, address caller);
    error OnlyCollectionCreatorCanAddImages(uint256 collectionId, address caller);

    struct ImageAsset {
        uint256 id;
        uint256 collectionId;
        address creator;
        address currentOwner;
        bytes32 contentHash;
        string metadataURI;
        uint64 registeredAt;
        bool exists;
    }

    struct Collection {
        uint256 id;
        address creator;
        string name;
        string metadataURI;
        uint64 createdAt;
        bool exists;
    }

    uint256 private _nextImageId = 1;
    uint256 private _nextCollectionId = 1;

    mapping(uint256 => ImageAsset) private _images;
    mapping(uint256 => Collection) private _collections;
    mapping(uint256 => uint256[]) private _collectionImages;
    mapping(bytes32 => uint256) private _imageIdByHash;

    event CollectionRegistered(uint256 indexed collectionId, address indexed creator, string name);
    event ImageRegistered(
        uint256 indexed imageId,
        uint256 indexed collectionId,
        address indexed creator,
        bytes32 contentHash,
        string metadataURI
    );
    event ImageOwnershipTransferred(uint256 indexed imageId, address indexed previousOwner, address indexed newOwner);

    /// @notice Creates the image registry contract.
    /// @param initialOwner The address that receives the Ownable administrator role.
    constructor(address initialOwner) Ownable(initialOwner) {}

    /// @notice Registers a new collection for the caller.
    /// @param name The human-readable collection name.
    /// @param metadataURI The metadata URI describing the collection.
    /// @return collectionId The newly assigned collection identifier.
    function registerCollection(string calldata name, string calldata metadataURI) external returns (uint256 collectionId) {
        collectionId = _nextCollectionId++;

        _collections[collectionId] = Collection({
            id: collectionId,
            creator: msg.sender,
            name: name,
            metadataURI: metadataURI,
            createdAt: uint64(block.timestamp),
            exists: true
        });

        emit CollectionRegistered(collectionId, msg.sender, name);
    }

    /// @notice Registers a single image and binds it to the caller.
    /// @param contentHash The hash of the original image content.
    /// @param metadataURI The metadata URI describing the image.
    /// @param collectionId The optional parent collection identifier, or zero for no collection.
    /// @return imageId The newly assigned image identifier.
    function registerImage(
        bytes32 contentHash,
        string calldata metadataURI,
        uint256 collectionId
    ) external returns (uint256 imageId) {
        imageId = _registerImage(msg.sender, contentHash, metadataURI, collectionId);
    }

    /// @notice Registers multiple images for the caller in a single transaction.
    /// @param contentHashes The hashes of the original image files.
    /// @param metadataURIs The metadata URIs describing the images.
    /// @param collectionId The optional parent collection identifier, or zero for no collection.
    /// @return imageIds The list of newly assigned image identifiers.
    function registerImageBatch(
        bytes32[] calldata contentHashes,
        string[] calldata metadataURIs,
        uint256 collectionId
    ) external returns (uint256[] memory imageIds) {
        if (contentHashes.length != metadataURIs.length) {
            revert InputLengthMismatch();
        }

        imageIds = new uint256[](contentHashes.length);
        for (uint256 index = 0; index < contentHashes.length; index++) {
            imageIds[index] = _registerImage(msg.sender, contentHashes[index], metadataURIs[index], collectionId);
        }
    }

    /// @notice Transfers ownership of a registered image to a new wallet.
    /// @param imageId The registered image identifier.
    /// @param newOwner The address of the new image owner.
    function transferImageOwnership(uint256 imageId, address newOwner) external {
        if (newOwner == address(0)) {
            revert InvalidNewOwner();
        }

        ImageAsset storage asset = _images[imageId];
        if (!asset.exists) {
            revert ImageNotRegistered(imageId);
        }
        if (asset.currentOwner != msg.sender) {
            revert CallerIsNotCurrentOwner(imageId, msg.sender);
        }

        address previousOwner = asset.currentOwner;
        asset.currentOwner = newOwner;

        emit ImageOwnershipTransferred(imageId, previousOwner, newOwner);
    }

    /// @notice Verifies whether a candidate hash matches the stored original hash.
    /// @param imageId The registered image identifier.
    /// @param candidateHash The hash to compare with the stored image hash.
    /// @return isMatch True when the candidate hash matches the stored hash.
    function verifyImageHash(uint256 imageId, bytes32 candidateHash) external view returns (bool) {
        ImageAsset storage asset = _images[imageId];
        if (!asset.exists) {
            revert ImageNotRegistered(imageId);
        }
        return asset.contentHash == candidateHash;
    }

    /// @notice Returns whether an image identifier has been registered.
    /// @param imageId The image identifier to query.
    /// @return exists True when the image exists in storage.
    function imageExists(uint256 imageId) external view returns (bool) {
        return _images[imageId].exists;
    }

    /// @notice Returns the current owner of a registered image.
    /// @param imageId The image identifier to query.
    /// @return owner The current image owner.
    function ownerOfImage(uint256 imageId) external view returns (address) {
        ImageAsset storage asset = _images[imageId];
        if (!asset.exists) {
            revert ImageNotRegistered(imageId);
        }
        return asset.currentOwner;
    }

    /// @notice Returns the full record of a registered image.
    /// @param imageId The image identifier to query.
    /// @return asset The stored image asset data.
    function getImage(uint256 imageId) external view returns (ImageAsset memory) {
        if (!_images[imageId].exists) {
            revert ImageNotRegistered(imageId);
        }
        return _images[imageId];
    }

    /// @notice Returns the full record of a registered collection.
    /// @param collectionId The collection identifier to query.
    /// @return collection The stored collection data.
    function getCollection(uint256 collectionId) external view returns (Collection memory) {
        if (!_collections[collectionId].exists) {
            revert CollectionNotRegistered(collectionId);
        }
        return _collections[collectionId];
    }

    /// @notice Returns the image identifiers assigned to a collection.
    /// @param collectionId The collection identifier to query.
    /// @return imageIds The list of image identifiers inside the collection.
    function getCollectionImageIds(uint256 collectionId) external view returns (uint256[] memory) {
        if (!_collections[collectionId].exists) {
            revert CollectionNotRegistered(collectionId);
        }
        return _collectionImages[collectionId];
    }

    /// @notice Returns the registered image identifier for a given content hash.
    /// @param contentHash The original file hash to look up.
    /// @return imageId The registered image identifier, or zero if it is not registered.
    function imageIdByHash(bytes32 contentHash) external view returns (uint256) {
        return _imageIdByHash[contentHash];
    }

    function _registerImage(
        address creator,
        bytes32 contentHash,
        string calldata metadataURI,
        uint256 collectionId
    ) private returns (uint256 imageId) {
        if (contentHash == bytes32(0)) {
            revert EmptyContentHash();
        }
        if (_imageIdByHash[contentHash] != 0) {
            revert ImageHashAlreadyRegistered(contentHash);
        }

        if (collectionId != 0) {
            Collection storage collection = _collections[collectionId];
            if (!collection.exists) {
                revert CollectionNotRegistered(collectionId);
            }
            if (collection.creator != creator) {
                revert OnlyCollectionCreatorCanAddImages(collectionId, creator);
            }
        }

        imageId = _nextImageId++;
        _images[imageId] = ImageAsset({
            id: imageId,
            collectionId: collectionId,
            creator: creator,
            currentOwner: creator,
            contentHash: contentHash,
            metadataURI: metadataURI,
            registeredAt: uint64(block.timestamp),
            exists: true
        });

        _imageIdByHash[contentHash] = imageId;
        if (collectionId != 0) {
            _collectionImages[collectionId].push(imageId);
        }

        emit ImageRegistered(imageId, collectionId, creator, contentHash, metadataURI);
    }
}