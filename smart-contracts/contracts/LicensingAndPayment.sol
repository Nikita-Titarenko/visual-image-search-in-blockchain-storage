// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import "./interfaces/IImageRegistry.sol";

contract LicensingAndPayment is Ownable, ReentrancyGuard {
    error RegistryAddressIsZero();
    error OracleAddressIsZero();
    error CallerIsNotOracle(address caller);
    error ImageNotRegistered(uint256 imageId);
    error CallerIsNotImageOwner(uint256 imageId, address caller);
    error LicenseOfferNotActive(uint256 imageId);
    error IncorrectPaymentAmount(uint256 expected, uint256 actual);
    error OfferSellerIsOutdated(uint256 imageId, address expectedSeller, address actualSeller);
    error PurchaseDoesNotExist(uint256 purchaseId);
    error AccessAlreadyConfirmed(uint256 purchaseId);
    error NoFundsAvailable(address account);
    error WithdrawalFailed(address payee, uint256 amount);

    struct LicenseOffer {
        uint256 imageId;
        address seller;
        uint256 priceWei;
        string termsURI;
        bool active;
    }

    struct LicensePurchase {
        uint256 id;
        uint256 imageId;
        address buyer;
        address seller;
        uint256 paidAmount;
        bytes32 accessProof;
        uint64 purchasedAt;
        bool oracleConfirmed;
    }

    IImageRegistry public immutable imageRegistry;
    address public oracle;
    uint256 private _nextPurchaseId = 1;

    mapping(uint256 => LicenseOffer) private _offersByImage;
    mapping(uint256 => LicensePurchase) private _purchasesById;
    mapping(uint256 => mapping(address => bool)) private _hasLicenseForImage;
    mapping(address => uint256) public pendingWithdrawals;

    event OracleUpdated(address indexed previousOracle, address indexed newOracle);
    event LicenseOfferConfigured(uint256 indexed imageId, address indexed seller, uint256 priceWei, string termsURI, bool active);
    event LicensePurchased(uint256 indexed purchaseId, uint256 indexed imageId, address indexed buyer, address seller, uint256 paidAmount);
    event DownloadAccessConfirmed(uint256 indexed purchaseId, address indexed oracle, bytes32 accessProof);
    event Withdrawal(address indexed payee, uint256 amount);

    /// @notice Creates the licensing contract and binds it to an image registry.
    /// @param registryAddress The image registry contract used for ownership checks.
    /// @param initialOwner The address that receives the Ownable administrator role.
    /// @param initialOracle The oracle address allowed to confirm download access.
    constructor(address registryAddress, address initialOwner, address initialOracle) Ownable(initialOwner) {
        if (registryAddress == address(0)) {
            revert RegistryAddressIsZero();
        }
        if (initialOracle == address(0)) {
            revert OracleAddressIsZero();
        }

        imageRegistry = IImageRegistry(registryAddress);
        oracle = initialOracle;
    }

    modifier onlyOracle() {
        if (msg.sender != oracle) {
            revert CallerIsNotOracle(msg.sender);
        }
        _;
    }

    /// @notice Updates the oracle account that can confirm download access.
    /// @param newOracle The new oracle address.
    function setOracle(address newOracle) external onlyOwner {
        if (newOracle == address(0)) {
            revert OracleAddressIsZero();
        }

        address previousOracle = oracle;
        oracle = newOracle;
        emit OracleUpdated(previousOracle, newOracle);
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
    ) external {
        if (!imageRegistry.imageExists(imageId)) {
            revert ImageNotRegistered(imageId);
        }
        if (imageRegistry.ownerOfImage(imageId) != msg.sender) {
            revert CallerIsNotImageOwner(imageId, msg.sender);
        }

        _offersByImage[imageId] = LicenseOffer({
            imageId: imageId,
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
    function buyLicense(uint256 imageId) external payable nonReentrant returns (uint256 purchaseId) {
        LicenseOffer storage offer = _offersByImage[imageId];

        if (!offer.active) {
            revert LicenseOfferNotActive(imageId);
        }
        if (msg.value != offer.priceWei) {
            revert IncorrectPaymentAmount(offer.priceWei, msg.value);
        }

        address currentOwner = imageRegistry.ownerOfImage(imageId);
        if (offer.seller != currentOwner) {
            revert OfferSellerIsOutdated(imageId, currentOwner, offer.seller);
        }

        purchaseId = _nextPurchaseId++;
        _purchasesById[purchaseId] = LicensePurchase({
            id: purchaseId,
            imageId: imageId,
            buyer: msg.sender,
            seller: offer.seller,
            paidAmount: msg.value,
            accessProof: bytes32(0),
            purchasedAt: uint64(block.timestamp),
            oracleConfirmed: false
        });

        _hasLicenseForImage[imageId][msg.sender] = true;
        pendingWithdrawals[offer.seller] += msg.value;

        emit LicensePurchased(purchaseId, imageId, msg.sender, offer.seller, msg.value);
    }

    /// @notice Stores oracle confirmation that a purchased file can be downloaded.
    /// @param purchaseId The purchase identifier to confirm.
    /// @param accessProof A proof or ticket hash associated with the download authorization.
    function confirmDownloadAccess(uint256 purchaseId, bytes32 accessProof) external onlyOracle {
        LicensePurchase storage purchase = _purchasesById[purchaseId];
        if (purchase.id == 0) {
            revert PurchaseDoesNotExist(purchaseId);
        }
        if (purchase.oracleConfirmed) {
            revert AccessAlreadyConfirmed(purchaseId);
        }

        purchase.oracleConfirmed = true;
        purchase.accessProof = accessProof;

        emit DownloadAccessConfirmed(purchaseId, msg.sender, accessProof);
    }

    /// @notice Withdraws pending license revenue for the caller.
    function withdrawPayments() external nonReentrant {
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
    function getLicenseOffer(uint256 imageId) external view returns (LicenseOffer memory) {
        return _offersByImage[imageId];
    }

    /// @notice Returns the details of a recorded license purchase.
    /// @param purchaseId The purchase identifier to query.
    /// @return purchase The stored purchase record.
    function getPurchase(uint256 purchaseId) external view returns (LicensePurchase memory) {
        if (_purchasesById[purchaseId].id == 0) {
            revert PurchaseDoesNotExist(purchaseId);
        }
        return _purchasesById[purchaseId];
    }

    /// @notice Returns whether a buyer already owns a license for an image.
    /// @param imageId The registered image identifier.
    /// @param buyer The buyer address to query.
    /// @return hasLicense True when the buyer has purchased a license.
    function hasPurchasedLicense(uint256 imageId, address buyer) external view returns (bool) {
        return _hasLicenseForImage[imageId][buyer];
    }
}