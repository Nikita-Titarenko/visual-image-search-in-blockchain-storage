// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract ImageRegistry {
    error EmptyContentHash();
    error ImageNotRegistered(uint256 imageId);
    error CollectionNotRegistered(uint256 collectionId);
    error ImageHashAlreadyRegistered(bytes32 contentHash);
    error OnlyCollectionCreatorCanAddImages(uint256 collectionId, address caller);

    struct ImageAsset {
        uint256 collectionId;
        address currentOwner;
        bytes32 contentHash;
        string metadataURI;
        uint64 registeredAt;
    }

    struct Collection {
        address creator;
        string name;
        string metadataURI;
        uint64 createdAt;
    }

    struct ImageAssetView {
        uint256 id;
        uint256 collectionId;
        address currentOwner;
        bytes32 contentHash;
        string metadataURI;
        uint64 registeredAt;
    }

    struct CollectionView {
        uint256 id;
        address creator;
        string name;
        string metadataURI;
        uint64 createdAt;
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

    /// @notice Registers a new collection for the caller.
    /// @param name The human-readable collection name.
    /// @param metadataURI The metadata URI describing the collection.
    /// @return collectionId The newly assigned collection identifier.
    function registerCollection(string calldata name, string calldata metadataURI) external returns (uint256 collectionId) {
        collectionId = _nextCollectionId++;

        _collections[collectionId] = Collection({
            creator: msg.sender,
            name: name,
            metadataURI: metadataURI,
            createdAt: uint64(block.timestamp)
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
        if (contentHash == bytes32(0)) {
            revert EmptyContentHash();
        }
        if (_imageIdByHash[contentHash] != 0) {
            revert ImageHashAlreadyRegistered(contentHash);
        }

        if (collectionId != 0) {
            Collection storage collection = _collections[collectionId];
            if (collection.creator == address(0)) {
                revert CollectionNotRegistered(collectionId);
            }
            if (collection.creator != msg.sender) {
                revert OnlyCollectionCreatorCanAddImages(collectionId, msg.sender);
            }
        }

        imageId = _nextImageId++;
        _images[imageId] = ImageAsset({
            collectionId: collectionId,
            currentOwner: msg.sender,
            contentHash: contentHash,
            metadataURI: metadataURI,
            registeredAt: uint64(block.timestamp)
        });

        _imageIdByHash[contentHash] = imageId;
        if (collectionId != 0) {
            _collectionImages[collectionId].push(imageId);
        }

        emit ImageRegistered(imageId, collectionId, msg.sender, contentHash, metadataURI);
    }

    /// @notice Verifies whether a candidate hash matches the stored original hash.
    /// @param imageId The registered image identifier.
    /// @param candidateHash The hash to compare with the stored image hash.
    /// @return isMatch True when the candidate hash matches the stored hash.
    function verifyImageHash(uint256 imageId, bytes32 candidateHash) external view returns (bool) {
        ImageAsset storage asset = _images[imageId];
        if (asset.currentOwner == address(0)) {
            revert ImageNotRegistered(imageId);
        }
        return asset.contentHash == candidateHash;
    }

    /// @notice Returns whether an image identifier has been registered.
    /// @param imageId The image identifier to query.
    /// @return exists True when the image exists in storage.
    function imageExists(uint256 imageId) external view returns (bool) {
        return _images[imageId].currentOwner != address(0);
    }

    /// @notice Returns the current owner of a registered image.
    /// @param imageId The image identifier to query.
    /// @return owner The current image owner.
    function ownerOfImage(uint256 imageId) external view returns (address) {
        ImageAsset storage asset = _images[imageId];
        if (asset.currentOwner == address(0)) {
            revert ImageNotRegistered(imageId);
        }
        return asset.currentOwner;
    }

    /// @notice Returns the full record of a registered image.
    /// @param imageId The image identifier to query.
    /// @return asset The stored image asset data.
    function getImage(uint256 imageId) external view returns (ImageAssetView memory asset) {
        ImageAsset storage storedAsset = _images[imageId];
        if (storedAsset.currentOwner == address(0)) {
            revert ImageNotRegistered(imageId);
        }
        return _toImageAssetView(imageId, storedAsset);
    }

    /// @notice Returns all registered images in id order.
    /// @return images The full image records stored in the registry.
    function getAllImages() external view returns (ImageAssetView[] memory images) {
        uint256 totalImages = _nextImageId - 1;
        images = new ImageAssetView[](totalImages);
        for (uint256 imageId = 1; imageId <= totalImages; imageId++) {
            images[imageId - 1] = _toImageAssetView(imageId, _images[imageId]);
        }
    }

    /// @notice Returns a collection together with all registered images inside it.
    /// @param collectionId The collection identifier to query.
    /// @return collection The stored collection data.
    /// @return images The full image records assigned to the collection.
    function getCollectionWithImages(
        uint256 collectionId
    ) external view returns (CollectionView memory collection, ImageAssetView[] memory images) {
        Collection storage storedCollection = _collections[collectionId];
        if (storedCollection.creator == address(0)) {
            revert CollectionNotRegistered(collectionId);
        }
        collection = _toCollectionView(collectionId, storedCollection);

        uint256[] storage imageIds = _collectionImages[collectionId];
        images = new ImageAssetView[](imageIds.length);
        for (uint256 index = 0; index < imageIds.length; index++) {
            uint256 imageId = imageIds[index];
            images[index] = _toImageAssetView(imageId, _images[imageId]);
        }
    }

    function _toImageAssetView(uint256 imageId, ImageAsset storage asset) private view returns (ImageAssetView memory) {
        return ImageAssetView({
            id: imageId,
            collectionId: asset.collectionId,
            currentOwner: asset.currentOwner,
            contentHash: asset.contentHash,
            metadataURI: asset.metadataURI,
            registeredAt: asset.registeredAt
        });
    }

    function _toCollectionView(uint256 collectionId, Collection storage collection) private view returns (CollectionView memory) {
        return CollectionView({
            id: collectionId,
            creator: collection.creator,
            name: collection.name,
            metadataURI: collection.metadataURI,
            createdAt: collection.createdAt
        });
    }

}