// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IImageRegistry {
    /// @notice Returns whether an image identifier has been registered.
    /// @param imageId The image identifier to query.
    /// @return exists True when the image exists in storage.
    function imageExists(uint256 imageId) external view returns (bool);

    /// @notice Returns the current owner of a registered image.
    /// @param imageId The image identifier to query.
    /// @return owner The current image owner.
    function ownerOfImage(uint256 imageId) external view returns (address);
}