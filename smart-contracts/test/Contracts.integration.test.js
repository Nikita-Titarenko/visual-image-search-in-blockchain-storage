const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture, time } = require("@nomicfoundation/hardhat-network-helpers");

function digest(label) {
  return ethers.keccak256(ethers.toUtf8Bytes(label));
}

describe("Contract integration flows", function () {
  async function deployFixture() {
    const [owner, seller, buyer, oracle, otherBuyer] = await ethers.getSigners();

    const registryFactory = await ethers.getContractFactory("ImageRegistry");
    const registry = await registryFactory.deploy();
    await registry.waitForDeployment();

    const licensingFactory = await ethers.getContractFactory("LicensingAndPayment");
    const licensing = await licensingFactory.deploy(await registry.getAddress(), owner.address, oracle.address);
    await licensing.waitForDeployment();

    const auditFactory = await ethers.getContractFactory("ModelAndIndexAudit");
    const audit = await auditFactory.deploy(owner.address);
    await audit.waitForDeployment();

    return { registry, licensing, audit, owner, seller, buyer, oracle, otherBuyer };
  }

  it("executes the end-to-end registry, licensing, and audit flow", async function () {
    const { registry, licensing, audit, seller, buyer, oracle } = await loadFixture(deployFixture);
    await registry.connect(seller).registerCollection("Premium", "ipfs://premium");
    await registry.connect(seller).registerImage(digest("asset-1"), "ipfs://asset-1", 1n);
    await licensing.connect(seller).configureLicenseOffer(1n, ethers.parseEther("1"), "ipfs://terms", true);

    await expect(licensing.connect(buyer).buyLicense(1n, { value: ethers.parseEther("1") }))
      .to.emit(licensing, "LicensePurchased");

    await expect(licensing.connect(oracle).confirmDownloadAccess(1n, digest("ticket-1")))
      .to.emit(licensing, "DownloadAccessConfirmed");

    await expect(audit.recordSnapshot("resnet18", digest("model-1"), "hist-v1", digest("index-1"), "ipfs://audit"))
      .to.emit(audit, "AuditSnapshotRecorded");

    expect(await audit.verifySnapshot(1n, digest("model-1"), digest("index-1"))).to.equal(true);
  });

  it("restores buying after pause and unpause", async function () {
    const { registry, licensing, seller, buyer, owner } = await loadFixture(deployFixture);
    await registry.connect(seller).registerImage(digest("asset-2"), "ipfs://asset-2", 0);
    await licensing.connect(seller).configureLicenseOffer(1n, ethers.parseEther("1.5"), "ipfs://terms-2", true);
    await licensing.connect(owner).pause();

    await expect(licensing.connect(buyer).buyLicense(1n, { value: ethers.parseEther("1.5") }))
      .to.be.revertedWithCustomError(licensing, "EnforcedPause");

    await licensing.connect(owner).unpause();
    await expect(licensing.connect(buyer).buyLicense(1n, { value: ethers.parseEther("1.5") }))
      .to.emit(licensing, "LicensePurchased");
  });

  it("tracks timestamps across collection, image, purchase, and snapshot records", async function () {
    const { registry, licensing, audit, seller, buyer, oracle } = await loadFixture(deployFixture);

    const collectionTimestamp = (await time.latest()) + 100;
    await time.setNextBlockTimestamp(collectionTimestamp);
    await registry.connect(seller).registerCollection("Timed", "ipfs://timed");

    const imageTimestamp = collectionTimestamp + 100;
    await time.setNextBlockTimestamp(imageTimestamp);
    await registry.connect(seller).registerImage(digest("asset-3"), "ipfs://asset-3", 1n);

    await licensing.connect(seller).configureLicenseOffer(1n, ethers.parseEther("0.75"), "ipfs://terms-3", true);

    const purchaseTimestamp = imageTimestamp + 100;
    await time.setNextBlockTimestamp(purchaseTimestamp);
    await licensing.connect(buyer).buyLicense(1n, { value: ethers.parseEther("0.75") });

    const snapshotTimestamp = purchaseTimestamp + 100;
    await time.setNextBlockTimestamp(snapshotTimestamp);
    await audit.recordSnapshot("resnet50", digest("model-2"), "cnn-v2", digest("index-2"), "ipfs://audit-2");

    const [collection] = await registry.getCollectionWithImages(1n);
    const image = await registry.getImage(1n);
    const purchase = await licensing.getPurchase(1n);
    const snapshot = await audit.getSnapshot(1n);

    expect(collection.createdAt).to.equal(BigInt(collectionTimestamp));
    expect(image.registeredAt).to.equal(BigInt(imageTimestamp));
    expect(purchase.purchasedAt).to.equal(BigInt(purchaseTimestamp));
    expect(snapshot.recordedAt).to.equal(BigInt(snapshotTimestamp));

    await licensing.connect(oracle).confirmDownloadAccess(1n, digest("ticket-2"));
  });

  it("keeps registry views consistent across collections and all-images listing", async function () {
    const { registry, seller, otherBuyer } = await loadFixture(deployFixture);
    await registry.connect(seller).registerCollection("Batch", "ipfs://batch");
    await registry.connect(seller).registerImage(digest("asset-4"), "ipfs://asset-4", 1n);
    await registry.connect(seller).registerImage(digest("asset-5"), "ipfs://asset-5", 1n);
    await registry.connect(otherBuyer).registerImage(digest("asset-6"), "ipfs://asset-6", 0);

    const [collection, collectionImages] = await registry.getCollectionWithImages(1n);
    const allImages = await registry.getAllImages();

    expect(collection.name).to.equal("Batch");
    expect(collectionImages.map((image) => image.id)).to.deep.equal([1n, 2n]);
    expect(allImages.map((image) => image.id)).to.deep.equal([1n, 2n, 3n]);
  });

  it("allows administrative oracle rotation during pause and uses the new oracle afterward", async function () {
    const { registry, licensing, seller, buyer, owner, oracle, otherBuyer } = await loadFixture(deployFixture);
    await registry.connect(seller).registerImage(digest("asset-7"), "ipfs://asset-7", 0);
    await licensing.connect(seller).configureLicenseOffer(1n, ethers.parseEther("2"), "ipfs://terms-7", true);
    await licensing.connect(owner).pause();
    await licensing.connect(owner).setOracle(otherBuyer.address);
    await licensing.connect(owner).unpause();
    await licensing.connect(buyer).buyLicense(1n, { value: ethers.parseEther("2") });

    await expect(licensing.connect(oracle).confirmDownloadAccess(1n, digest("old-oracle-proof")))
      .to.be.revertedWithCustomError(licensing, "CallerIsNotOracle")
      .withArgs(oracle.address);

    await expect(licensing.connect(otherBuyer).confirmDownloadAccess(1n, digest("new-oracle-proof")))
      .to.emit(licensing, "DownloadAccessConfirmed");
  });

  it("records multiple snapshots and verifies each independently", async function () {
    const { audit } = await loadFixture(deployFixture);
    await audit.recordSnapshot("m1", digest("m1"), "i1", digest("i1"), "ipfs://audit-1");
    await audit.recordSnapshot("m2", digest("m2"), "i2", digest("i2"), "ipfs://audit-2");

    expect(await audit.verifySnapshot(1n, digest("m1"), digest("i1"))).to.equal(true);
    expect(await audit.verifySnapshot(2n, digest("m2"), digest("i2"))).to.equal(true);
    expect(await audit.verifySnapshot(2n, digest("m2"), digest("wrong-index"))).to.equal(false);
  });
});