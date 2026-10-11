const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

function hashLabel(label) {
  return ethers.keccak256(ethers.toUtf8Bytes(label));
}

describe("LicensingAndPayment", function () {
  async function deployFixture() {
    const [owner, seller, buyer, other] = await ethers.getSigners();
    const registryFactory = await ethers.getContractFactory("ImageRegistry");
    const registry = await registryFactory.deploy();
    await registry.waitForDeployment();

    const licensingFactory = await ethers.getContractFactory("LicensingAndPayment");
    const licensing = await licensingFactory.deploy(await registry.getAddress(), owner.address);
    await licensing.waitForDeployment();

    await registry.connect(seller).registerImage(hashLabel("lic-image"), "ipfs://lic-image", 0);

    return { registry, licensing, owner, seller, buyer, other };
  }

  async function createOffer(fixture, overrides = {}) {
    const { licensing, seller } = fixture;
    const priceWei = overrides.priceWei ?? ethers.parseEther("1");
    const termsURI = overrides.termsURI ?? "ipfs://terms-1";
    const active = overrides.active ?? true;
    await licensing.connect(seller).configureLicenseOffer(1n, priceWei, termsURI, active);
    return { priceWei, termsURI, active };
  }

  it("stores the registry address on deployment", async function () {
    const { registry, licensing } = await loadFixture(deployFixture);
    expect(await licensing.imageRegistry()).to.equal(await registry.getAddress());
  });

  it("rejects zero registry addresses", async function () {
    const [owner] = await ethers.getSigners();
    const licensingFactory = await ethers.getContractFactory("LicensingAndPayment");
    await expect(licensingFactory.deploy(ethers.ZeroAddress, owner.address))
      .to.be.revertedWithCustomError(licensingFactory, "RegistryAddressIsZero");
  });

  it("allows the owner to pause and unpause the contract", async function () {
    const { licensing, owner } = await loadFixture(deployFixture);
    await expect(licensing.connect(owner).pause())
      .to.emit(licensing, "Paused")
      .withArgs(owner.address);
    expect(await licensing.paused()).to.equal(true);

    await expect(licensing.connect(owner).unpause())
      .to.emit(licensing, "Unpaused")
      .withArgs(owner.address);
    expect(await licensing.paused()).to.equal(false);
  });

  it("restricts pause and unpause to the owner", async function () {
    const { licensing, other, owner } = await loadFixture(deployFixture);
    await expect(licensing.connect(other).pause())
      .to.be.revertedWithCustomError(licensing, "OwnableUnauthorizedAccount")
      .withArgs(other.address);

    await licensing.connect(owner).pause();
    await expect(licensing.connect(other).unpause())
      .to.be.revertedWithCustomError(licensing, "OwnableUnauthorizedAccount")
      .withArgs(other.address);
  });

  it("configures an active license offer and stores it", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, seller } = fixture;
    const { priceWei, termsURI } = await createOffer(fixture);

    const offer = await licensing.getLicenseOffer(1n);
    expect(offer.imageId).to.equal(1n);
    expect(offer.seller).to.equal(seller.address);
    expect(offer.priceWei).to.equal(priceWei);
    expect(offer.termsURI).to.equal(termsURI);
    expect(offer.active).to.equal(true);
  });

  it("emits LicenseOfferConfigured when configuring an offer", async function () {
    const { licensing, seller } = await loadFixture(deployFixture);
    const priceWei = ethers.parseEther("2");
    await expect(licensing.connect(seller).configureLicenseOffer(1n, priceWei, "ipfs://terms-2", true))
      .to.emit(licensing, "LicenseOfferConfigured")
      .withArgs(1n, seller.address, priceWei, "ipfs://terms-2", true);
  });

  it("blocks configureLicenseOffer while paused", async function () {
    const { licensing, owner, seller } = await loadFixture(deployFixture);
    await licensing.connect(owner).pause();
    await expect(licensing.connect(seller).configureLicenseOffer(1n, 1n, "ipfs://terms", true))
      .to.be.revertedWithCustomError(licensing, "EnforcedPause");
  });

  it("rejects offers for missing images", async function () {
    const { licensing, seller } = await loadFixture(deployFixture);
    await expect(licensing.connect(seller).configureLicenseOffer(9n, 1n, "ipfs://terms", true))
      .to.be.revertedWithCustomError(licensing, "ImageNotRegistered")
      .withArgs(9n);
  });

  it("rejects offers from non-owners", async function () {
    const { licensing, other } = await loadFixture(deployFixture);
    await expect(licensing.connect(other).configureLicenseOffer(1n, 1n, "ipfs://terms", true))
      .to.be.revertedWithCustomError(licensing, "CallerIsNotImageOwner")
      .withArgs(1n, other.address);
  });

  it("purchases an active license and stores the purchase", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, buyer, seller } = fixture;
    const { priceWei } = await createOffer(fixture);

    await expect(licensing.connect(buyer).buyLicense(1n, { value: priceWei }))
      .to.emit(licensing, "LicensePurchased")
      .withArgs(1n, 1n, buyer.address, seller.address, priceWei);

    const purchase = await licensing.getPurchase(1n);
    expect(purchase.id).to.equal(1n);
    expect(purchase.imageId).to.equal(1n);
    expect(purchase.buyer).to.equal(buyer.address);
    expect(purchase.seller).to.equal(seller.address);
    expect(purchase.paidAmount).to.equal(priceWei);
    expect(await licensing.hasPurchasedLicense(1n, buyer.address)).to.equal(true);
    expect(await licensing.pendingWithdrawals(seller.address)).to.equal(priceWei);
  });

  it("returns caller purchases and sales in purchase order", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, registry, seller, buyer, other } = fixture;
    const firstPrice = ethers.parseEther("1");
    await createOffer(fixture, { priceWei: firstPrice });

    await registry.connect(seller).registerImage(hashLabel("lic-image-2"), "ipfs://lic-image-2", 0);
    const secondPrice = ethers.parseEther("2");
    await licensing.connect(seller).configureLicenseOffer(2n, secondPrice, "ipfs://terms-2", true);

    await licensing.connect(buyer).buyLicense(1n, { value: firstPrice });
    await licensing.connect(other).buyLicense(2n, { value: secondPrice });

    const buyerPurchases = await licensing.connect(buyer).getMyPurchases();
    expect(buyerPurchases).to.have.lengthOf(1);
    expect(buyerPurchases[0].id).to.equal(1n);
    expect(buyerPurchases[0].buyer).to.equal(buyer.address);
    expect(buyerPurchases[0].seller).to.equal(seller.address);

    const otherPurchases = await licensing.connect(other).getMyPurchases();
    expect(otherPurchases).to.have.lengthOf(1);
    expect(otherPurchases[0].id).to.equal(2n);
    expect(otherPurchases[0].buyer).to.equal(other.address);

    const sellerSales = await licensing.connect(seller).getMySales();
    expect(sellerSales).to.have.lengthOf(2);
    expect(sellerSales.map((purchase) => purchase.id)).to.deep.equal([1n, 2n]);
    expect(sellerSales.map((purchase) => purchase.imageId)).to.deep.equal([1n, 2n]);
    expect(sellerSales.map((purchase) => purchase.paidAmount)).to.deep.equal([firstPrice, secondPrice]);

    expect(await licensing.connect(fixture.owner).getMyPurchases()).to.deep.equal([]);
    expect(await licensing.connect(fixture.owner).getMySales()).to.deep.equal([]);
  });

  it("blocks buyLicense while paused", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, owner, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(owner).pause();

    await expect(licensing.connect(buyer).buyLicense(1n, { value: priceWei }))
      .to.be.revertedWithCustomError(licensing, "EnforcedPause");
  });

  it("rejects buys when the offer is inactive", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, buyer } = fixture;
    const priceWei = ethers.parseEther("1");
    await createOffer(fixture, { priceWei, active: false });

    await expect(licensing.connect(buyer).buyLicense(1n, { value: priceWei }))
      .to.be.revertedWithCustomError(licensing, "LicenseOfferNotActive")
      .withArgs(1n);
  });

  it("rejects duplicate license purchases by the same buyer", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);

    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });

    await expect(licensing.connect(buyer).buyLicense(1n, { value: priceWei }))
      .to.be.revertedWithCustomError(licensing, "LicenseAlreadyPurchased")
      .withArgs(1n, buyer.address);
  });

  it("rejects buying a license for your own image", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, seller } = fixture;
    const { priceWei } = await createOffer(fixture);

    await expect(licensing.connect(seller).buyLicense(1n, { value: priceWei }))
      .to.be.revertedWithCustomError(licensing, "CannotBuyOwnImage")
      .withArgs(1n, seller.address);
  });

  it("rejects buys with incorrect payment amounts", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    const wrongValue = ethers.parseEther("0.5");

    await expect(licensing.connect(buyer).buyLicense(1n, { value: wrongValue }))
      .to.be.revertedWithCustomError(licensing, "IncorrectPaymentAmount")
      .withArgs(priceWei, wrongValue);
  });

  it("withdraws seller payments and clears the balance", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, seller, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });

    await expect(() => licensing.connect(seller).withdrawPayments())
      .to.changeEtherBalances([licensing, seller], [-priceWei, priceWei]);

    expect(await licensing.pendingWithdrawals(seller.address)).to.equal(0n);
  });

  it("blocks withdrawals while paused", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, owner, seller, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });
    await licensing.connect(owner).pause();

    await expect(licensing.connect(seller).withdrawPayments())
      .to.be.revertedWithCustomError(licensing, "EnforcedPause");
  });

  it("rejects withdrawals when no funds are available", async function () {
    const { licensing, seller } = await loadFixture(deployFixture);
    await expect(licensing.connect(seller).withdrawPayments())
      .to.be.revertedWithCustomError(licensing, "NoFundsAvailable")
      .withArgs(seller.address);
  });

  it("reverts getPurchase for missing ids", async function () {
    const { licensing } = await loadFixture(deployFixture);
    await expect(licensing.getPurchase(99n))
      .to.be.revertedWithCustomError(licensing, "PurchaseDoesNotExist")
      .withArgs(99n);
  });
});