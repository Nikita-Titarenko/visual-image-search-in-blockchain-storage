// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IImageRegistry {
    struct ImageAssetView {
        uint256 id;
        uint256 collectionId;
        address currentOwner;
        bytes32 contentHash;
        string metadataURI;
        uint64 registeredAt;
    }

    /// @notice Returns whether an image identifier has been registered.
    /// @param imageId The image identifier to query.
    /// @return exists True when the image exists in storage.
    function imageExists(uint256 imageId) external view returns (bool);

    /// @notice Returns the current owner of a registered image.
    /// @param imageId The image identifier to query.
    /// @return owner The current image owner.
    function ownerOfImage(uint256 imageId) external view returns (address);

    /// @notice Returns the full record of a registered image.
    /// @param imageId The image identifier to query.
    /// @return asset The stored image asset data.
    function getImage(uint256 imageId) external view returns (ImageAssetView memory asset);

    /// @notice Returns all registered images in id order.
    /// @return images The full image records stored in the registry.
    function getAllImages() external view returns (ImageAssetView[] memory images);
}