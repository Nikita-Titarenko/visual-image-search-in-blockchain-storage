const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-network-helpers");

function hashLabel(label) {
  return ethers.keccak256(ethers.toUtf8Bytes(label));
}

describe("LicensingAndPayment", function () {
  async function deployFixture() {
    const [owner, seller, buyer, oracle, other] = await ethers.getSigners();
    const registryFactory = await ethers.getContractFactory("ImageRegistry");
    const registry = await registryFactory.deploy(owner.address);
    await registry.waitForDeployment();

    const licensingFactory = await ethers.getContractFactory("LicensingAndPayment");
    const licensing = await licensingFactory.deploy(await registry.getAddress(), owner.address, oracle.address);
    await licensing.waitForDeployment();

    await registry.connect(seller).registerImage(hashLabel("lic-image"), "ipfs://lic-image", 0);

    return { registry, licensing, owner, seller, buyer, oracle, other };
  }

  async function createOffer(fixture, overrides = {}) {
    const { licensing, seller } = fixture;
    const priceWei = overrides.priceWei ?? ethers.parseEther("1");
    const termsURI = overrides.termsURI ?? "ipfs://terms-1";
    const active = overrides.active ?? true;
    await licensing.connect(seller).configureLicenseOffer(1n, priceWei, termsURI, active);
    return { priceWei, termsURI, active };
  }

  it("stores the registry address and oracle on deployment", async function () {
    const { registry, licensing, oracle } = await loadFixture(deployFixture);
    expect(await licensing.imageRegistry()).to.equal(await registry.getAddress());
    expect(await licensing.oracle()).to.equal(oracle.address);
  });

  it("rejects zero registry addresses", async function () {
    const [owner, , , oracle] = await ethers.getSigners();
    const licensingFactory = await ethers.getContractFactory("LicensingAndPayment");
    await expect(licensingFactory.deploy(ethers.ZeroAddress, owner.address, oracle.address))
      .to.be.revertedWithCustomError(licensingFactory, "RegistryAddressIsZero");
  });

  it("rejects zero oracle addresses", async function () {
    const [owner] = await ethers.getSigners();
    const registryFactory = await ethers.getContractFactory("ImageRegistry");
    const registry = await registryFactory.deploy(owner.address);
    await registry.waitForDeployment();
    const licensingFactory = await ethers.getContractFactory("LicensingAndPayment");

    await expect(licensingFactory.deploy(await registry.getAddress(), owner.address, ethers.ZeroAddress))
      .to.be.revertedWithCustomError(licensingFactory, "OracleAddressIsZero");
  });

  it("allows the owner to update the oracle", async function () {
    const { licensing, owner, other, oracle } = await loadFixture(deployFixture);
    await expect(licensing.connect(owner).setOracle(other.address))
      .to.emit(licensing, "OracleUpdated")
      .withArgs(oracle.address, other.address);
    expect(await licensing.oracle()).to.equal(other.address);
  });

  it("rejects zero oracle updates", async function () {
    const { licensing, owner } = await loadFixture(deployFixture);
    await expect(licensing.connect(owner).setOracle(ethers.ZeroAddress))
      .to.be.revertedWithCustomError(licensing, "OracleAddressIsZero");
  });

  it("restricts setOracle to the owner", async function () {
    const { licensing, other } = await loadFixture(deployFixture);
    await expect(licensing.connect(other).setOracle(other.address))
      .to.be.revertedWithCustomError(licensing, "OwnableUnauthorizedAccount")
      .withArgs(other.address);
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

  it("keeps setOracle available while paused", async function () {
    const { licensing, owner, other } = await loadFixture(deployFixture);
    await licensing.connect(owner).pause();
    await licensing.connect(owner).setOracle(other.address);
    expect(await licensing.oracle()).to.equal(other.address);
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
    expect(purchase.imageId).to.equal(1n);
    expect(purchase.buyer).to.equal(buyer.address);
    expect(purchase.seller).to.equal(seller.address);
    expect(purchase.paidAmount).to.equal(priceWei);
    expect(purchase.oracleConfirmed).to.equal(false);
    expect(await licensing.hasPurchasedLicense(1n, buyer.address)).to.equal(true);
    expect(await licensing.pendingWithdrawals(seller.address)).to.equal(priceWei);
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

  it("rejects buys with incorrect payment amounts", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    const wrongValue = ethers.parseEther("0.5");

    await expect(licensing.connect(buyer).buyLicense(1n, { value: wrongValue }))
      .to.be.revertedWithCustomError(licensing, "IncorrectPaymentAmount")
      .withArgs(priceWei, wrongValue);
  });

  it("lets the oracle confirm download access", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, oracle, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });
    const proof = hashLabel("proof-1");

    await expect(licensing.connect(oracle).confirmDownloadAccess(1n, proof))
      .to.emit(licensing, "DownloadAccessConfirmed")
      .withArgs(1n, oracle.address, proof);

    const purchase = await licensing.getPurchase(1n);
    expect(purchase.oracleConfirmed).to.equal(true);
    expect(purchase.accessProof).to.equal(proof);
  });

  it("restricts confirmDownloadAccess to the oracle", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, buyer, other } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });

    await expect(licensing.connect(other).confirmDownloadAccess(1n, hashLabel("proof-2")))
      .to.be.revertedWithCustomError(licensing, "CallerIsNotOracle")
      .withArgs(other.address);
  });

  it("rejects confirmations for missing purchases", async function () {
    const { licensing, oracle } = await loadFixture(deployFixture);
    await expect(licensing.connect(oracle).confirmDownloadAccess(2n, hashLabel("proof")))
      .to.be.revertedWithCustomError(licensing, "PurchaseDoesNotExist")
      .withArgs(2n);
  });

  it("rejects duplicate confirmations", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, oracle, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });
    const proof = hashLabel("proof-3");
    await licensing.connect(oracle).confirmDownloadAccess(1n, proof);

    await expect(licensing.connect(oracle).confirmDownloadAccess(1n, proof))
      .to.be.revertedWithCustomError(licensing, "AccessAlreadyConfirmed")
      .withArgs(1n);
  });

  it("blocks confirmations while paused", async function () {
    const fixture = await loadFixture(deployFixture);
    const { licensing, oracle, owner, buyer } = fixture;
    const { priceWei } = await createOffer(fixture);
    await licensing.connect(buyer).buyLicense(1n, { value: priceWei });
    await licensing.connect(owner).pause();

    await expect(licensing.connect(oracle).confirmDownloadAccess(1n, hashLabel("proof-4")))
      .to.be.revertedWithCustomError(licensing, "EnforcedPause");
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