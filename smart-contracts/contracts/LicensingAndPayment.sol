// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import "./interfaces/IImageRegistry.sol";

contract LicensingAndPayment is Ownable, Pausable, ReentrancyGuard {
    error RegistryAddressIsZero();
    error ImageNotRegistered(uint256 imageId);
    error CallerIsNotImageOwner(uint256 imageId, address caller);
    error LicenseOfferNotActive(uint256 imageId);
    error LicenseAlreadyPurchased(uint256 imageId, address buyer);
    error CannotBuyOwnImage(uint256 imageId, address buyer);
    error IncorrectPaymentAmount(uint256 expected, uint256 actual);
    error OfferSellerIsOutdated(uint256 imageId, address expectedSeller, address actualSeller);
    error PurchaseDoesNotExist(uint256 purchaseId);
    error NoFundsAvailable(address account);
    error WithdrawalFailed(address payee, uint256 amount);

    struct LicenseOffer {
        address seller;
        uint256 priceWei;
        string termsURI;
        bool active;
    }

    struct LicensePurchase {
        uint256 imageId;
        address buyer;
        address seller;
        uint256 paidAmount;
        uint64 purchasedAt;
    }

    struct LicenseOfferView {
        uint256 imageId;
        address seller;
        uint256 priceWei;
        string termsURI;
        bool active;
    }

    struct LicensePurchaseView {
        uint256 id;
        uint256 imageId;
        address buyer;
        address seller;
        uint256 paidAmount;
        uint64 purchasedAt;
    }

    IImageRegistry public immutable imageRegistry;
    uint256 private _nextPurchaseId = 1;

    mapping(uint256 => LicenseOffer) private _offersByImage;
    mapping(uint256 => LicensePurchase) private _purchasesById;
    mapping(address => uint256[]) private _purchaseIdsByBuyer;
    mapping(address => uint256[]) private _purchaseIdsBySeller;
    mapping(uint256 => mapping(address => bool)) private _hasLicenseForImage;
    mapping(address => uint256) public pendingWithdrawals;

    event LicenseOfferConfigured(uint256 indexed imageId, address indexed seller, uint256 priceWei, string termsURI, bool active);
    event LicensePurchased(uint256 indexed purchaseId, uint256 indexed imageId, address indexed buyer, address seller, uint256 paidAmount);
    event Withdrawal(address indexed payee, uint256 amount);

    /// @notice Creates the licensing contract and binds it to an image registry.
    /// @param registryAddress The image registry contract used for ownership checks.
    /// @param initialOwner The address that receives the Ownable administrator role.
    constructor(address registryAddress, address initialOwner) Ownable(initialOwner) {
        if (registryAddress == address(0)) {
            revert RegistryAddressIsZero();
        }

        imageRegistry = IImageRegistry(registryAddress);
    }

    /// @notice Pauses user-facing licensing operations.
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Resumes user-facing licensing operations.
    function unpause() external onlyOwner {
        _unpause();
    }

    /// @notice Creates or updates a license offer for a registered image.
    /// @param imageId The registered image identifier.
    /// @param priceWei The price to purchase a license, denominated in wei.
    /// @param termsURI The URI pointing to the license terms.
    /// @param active Whether the license offer should be purchasable.
    function configureLicenseOffer(
        uint256 imageId,
        uint256 priceWei,
        string calldata termsURI,
        bool active
    ) external whenNotPaused {
        if (!imageRegistry.imageExists(imageId)) {
            revert ImageNotRegistered(imageId);
        }
        if (imageRegistry.ownerOfImage(imageId) != msg.sender) {
            revert CallerIsNotImageOwner(imageId, msg.sender);
        }

        _offersByImage[imageId] = LicenseOffer({
            seller: msg.sender,
            priceWei: priceWei,
            termsURI: termsURI,
            active: active
        });

        emit LicenseOfferConfigured(imageId, msg.sender, priceWei, termsURI, active);
    }

    /// @notice Purchases a license for an image using the active offer terms.
    /// @param imageId The registered image identifier.
    /// @return purchaseId The newly assigned purchase identifier.
    function buyLicense(uint256 imageId) external payable whenNotPaused nonReentrant returns (uint256 purchaseId) {
        LicenseOffer storage offer = _offersByImage[imageId];

        if (!offer.active) {
            revert LicenseOfferNotActive(imageId);
        }
        if (_hasLicenseForImage[imageId][msg.sender]) {
            revert LicenseAlreadyPurchased(imageId, msg.sender);
        }
        if (msg.value != offer.priceWei) {
            revert IncorrectPaymentAmount(offer.priceWei, msg.value);
        }

        address currentOwner = imageRegistry.ownerOfImage(imageId);
        if (offer.seller != currentOwner) {
            revert OfferSellerIsOutdated(imageId, currentOwner, offer.seller);
        }
        if (currentOwner == msg.sender) {
            revert CannotBuyOwnImage(imageId, msg.sender);
        }

        purchaseId = _nextPurchaseId++;
        _purchasesById[purchaseId] = LicensePurchase({
            imageId: imageId,
            buyer: msg.sender,
            seller: offer.seller,
            paidAmount: msg.value,
            purchasedAt: uint64(block.timestamp)
        });

        _purchaseIdsByBuyer[msg.sender].push(purchaseId);
        _purchaseIdsBySeller[offer.seller].push(purchaseId);
        _hasLicenseForImage[imageId][msg.sender] = true;
        pendingWithdrawals[offer.seller] += msg.value;

        emit LicensePurchased(purchaseId, imageId, msg.sender, offer.seller, msg.value);
    }

    /// @notice Withdraws pending license revenue for the caller.
    function withdrawPayments() external whenNotPaused nonReentrant {
        uint256 amount = pendingWithdrawals[msg.sender];
        if (amount == 0) {
            revert NoFundsAvailable(msg.sender);
        }

        pendingWithdrawals[msg.sender] = 0;
        (bool success, ) = payable(msg.sender).call{value: amount}("");
        if (!success) {
            revert WithdrawalFailed(msg.sender, amount);
        }

        emit Withdrawal(msg.sender, amount);
    }

    /// @notice Returns the current license offer for a given image.
    /// @param imageId The registered image identifier.
    /// @return offer The stored license offer.
    function getLicenseOffer(uint256 imageId) external view returns (LicenseOfferView memory offer) {
        LicenseOffer storage storedOffer = _offersByImage[imageId];
        return LicenseOfferView({
            imageId: imageId,
            seller: storedOffer.seller,
            priceWei: storedOffer.priceWei,
            termsURI: storedOffer.termsURI,
            active: storedOffer.active
        });
    }

    /// @notice Returns the details of a recorded license purchase.
    /// @param purchaseId The purchase identifier to query.
    /// @return purchase The stored purchase record.
    function getPurchase(uint256 purchaseId) external view returns (LicensePurchaseView memory purchase) {
        LicensePurchase storage storedPurchase = _purchasesById[purchaseId];
        if (storedPurchase.buyer == address(0)) {
            revert PurchaseDoesNotExist(purchaseId);
        }
        return _toPurchaseView(purchaseId, storedPurchase);
    }

    /// @notice Returns all license purchases made by the caller.
    /// @return purchases The caller purchase records in creation order.
    function getMyPurchases() external view returns (LicensePurchaseView[] memory purchases) {
        return _getPurchaseViews(_purchaseIdsByBuyer[msg.sender]);
    }

    /// @notice Returns all license sales received by the caller.
    /// @return sales The caller sales records in creation order.
    function getMySales() external view returns (LicensePurchaseView[] memory sales) {
        return _getPurchaseViews(_purchaseIdsBySeller[msg.sender]);
    }

    /// @notice Returns whether a buyer already owns a license for an image.
    /// @param imageId The registered image identifier.
    /// @param buyer The buyer address to query.
    /// @return hasLicense True when the buyer has purchased a license.
    function hasPurchasedLicense(uint256 imageId, address buyer) external view returns (bool) {
        return _hasLicenseForImage[imageId][buyer];
    }

    function _getPurchaseViews(
        uint256[] storage purchaseIds
    ) private view returns (LicensePurchaseView[] memory purchases) {
        purchases = new LicensePurchaseView[](purchaseIds.length);
        for (uint256 index = 0; index < purchaseIds.length; index++) {
            uint256 purchaseId = purchaseIds[index];
            purchases[index] = _toPurchaseView(purchaseId, _purchasesById[purchaseId]);
        }
    }

    function _toPurchaseView(
        uint256 purchaseId,
        LicensePurchase storage purchase
    ) private view returns (LicensePurchaseView memory) {
        return LicensePurchaseView({
            id: purchaseId,
            imageId: purchase.imageId,
            buyer: purchase.buyer,
            seller: purchase.seller,
            paidAmount: purchase.paidAmount,
            purchasedAt: purchase.purchasedAt
        });
    }
}