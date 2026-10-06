const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture, time } = require("@nomicfoundation/hardhat-network-helpers");

function digest(label) {
  return ethers.keccak256(ethers.toUtf8Bytes(label));
}

describe("ModelAndIndexAudit", function () {
  async function deployFixture() {
    const [owner, outsider] = await ethers.getSigners();
    const factory = await ethers.getContractFactory("ModelAndIndexAudit");
    const audit = await factory.deploy(owner.address);
    await audit.waitForDeployment();
    return { audit, owner, outsider };
  }

  it("sets the configured owner", async function () {
    const { audit, owner } = await loadFixture(deployFixture);
    expect(await audit.owner()).to.equal(owner.address);
  });

  it("records a snapshot, emits an event, and stores the timestamp", async function () {
    const { audit, owner } = await loadFixture(deployFixture);
    const modelHash = digest("model-v1");
    const indexHash = digest("index-v1");
    const nextTimestamp = (await time.latest()) + 300;
    await time.setNextBlockTimestamp(nextTimestamp);

    await expect(audit.connect(owner).recordSnapshot("model-v1", modelHash, "index-v1", indexHash, "ipfs://audit-1"))
      .to.emit(audit, "AuditSnapshotRecorded")
      .withArgs(1n, "model-v1", modelHash, "index-v1", indexHash, "ipfs://audit-1", owner.address);

    const snapshot = await audit.getSnapshot(1n);
    expect(snapshot.id).to.equal(1n);
    expect(snapshot.modelVersion).to.equal("model-v1");
    expect(snapshot.modelHash).to.equal(modelHash);
    expect(snapshot.indexVersion).to.equal("index-v1");
    expect(snapshot.indexHash).to.equal(indexHash);
    expect(snapshot.metadataURI).to.equal("ipfs://audit-1");
    expect(snapshot.submittedBy).to.equal(owner.address);
    expect(snapshot.recordedAt).to.equal(BigInt(nextTimestamp));
  });

  it("increments snapshot ids", async function () {
    const { audit, owner } = await loadFixture(deployFixture);
    await audit.connect(owner).recordSnapshot("m1", digest("m1"), "i1", digest("i1"), "ipfs://1");
    await audit.connect(owner).recordSnapshot("m2", digest("m2"), "i2", digest("i2"), "ipfs://2");

    expect((await audit.getSnapshot(1n)).id).to.equal(1n);
    expect((await audit.getSnapshot(2n)).id).to.equal(2n);
  });

  it("restricts recordSnapshot to the owner", async function () {
    const { audit, outsider } = await loadFixture(deployFixture);
    await expect(audit.connect(outsider).recordSnapshot("m1", digest("m1"), "i1", digest("i1"), "ipfs://x"))
      .to.be.revertedWithCustomError(audit, "OwnableUnauthorizedAccount")
      .withArgs(outsider.address);
  });

  it("rejects empty model versions", async function () {
    const { audit } = await loadFixture(deployFixture);
    await expect(audit.recordSnapshot("", digest("m1"), "i1", digest("i1"), "ipfs://x"))
      .to.be.revertedWithCustomError(audit, "EmptyModelVersion");
  });

  it("rejects empty index versions", async function () {
    const { audit } = await loadFixture(deployFixture);
    await expect(audit.recordSnapshot("m1", digest("m1"), "", digest("i1"), "ipfs://x"))
      .to.be.revertedWithCustomError(audit, "EmptyIndexVersion");
  });

  it("rejects empty model hashes", async function () {
    const { audit } = await loadFixture(deployFixture);
    await expect(audit.recordSnapshot("m1", ethers.ZeroHash, "i1", digest("i1"), "ipfs://x"))
      .to.be.revertedWithCustomError(audit, "EmptyModelHash");
  });

  it("rejects empty index hashes", async function () {
    const { audit } = await loadFixture(deployFixture);
    await expect(audit.recordSnapshot("m1", digest("m1"), "i1", ethers.ZeroHash, "ipfs://x"))
      .to.be.revertedWithCustomError(audit, "EmptyIndexHash");
  });

  it("reverts getSnapshot for missing ids", async function () {
    const { audit } = await loadFixture(deployFixture);
    await expect(audit.getSnapshot(12n))
      .to.be.revertedWithCustomError(audit, "SnapshotDoesNotExist")
      .withArgs(12n);
  });

  it("verifies exact snapshot hashes", async function () {
    const { audit } = await loadFixture(deployFixture);
    const modelHash = digest("model-a");
    const indexHash = digest("index-a");
    await audit.recordSnapshot("model-a", modelHash, "index-a", indexHash, "ipfs://a");

    expect(await audit.verifySnapshot(1n, modelHash, indexHash)).to.equal(true);
  });

  it("returns false when the model hash differs", async function () {
    const { audit } = await loadFixture(deployFixture);
    const indexHash = digest("index-a");
    await audit.recordSnapshot("model-a", digest("model-a"), "index-a", indexHash, "ipfs://a");

    expect(await audit.verifySnapshot(1n, digest("model-b"), indexHash)).to.equal(false);
  });

  it("returns false when the index hash differs", async function () {
    const { audit } = await loadFixture(deployFixture);
    const modelHash = digest("model-a");
    await audit.recordSnapshot("model-a", modelHash, "index-a", digest("index-a"), "ipfs://a");

    expect(await audit.verifySnapshot(1n, modelHash, digest("index-b"))).to.equal(false);
  });

  it("reverts verifySnapshot for missing ids", async function () {
    const { audit } = await loadFixture(deployFixture);
    await expect(audit.verifySnapshot(77n, digest("m"), digest("i")))
      .to.be.revertedWithCustomError(audit, "SnapshotDoesNotExist")
      .withArgs(77n);
  });
});