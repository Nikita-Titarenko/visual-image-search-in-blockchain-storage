const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture, time } = require("@nomicfoundation/hardhat-network-helpers");

function hashLabel(label) {
  return ethers.keccak256(ethers.toUtf8Bytes(label));
}

describe("ImageRegistry", function () {
  async function deployFixture() {
    const [owner, creator, other] = await ethers.getSigners();
    const factory = await ethers.getContractFactory("ImageRegistry");
    const registry = await factory.deploy(owner.address);
    await registry.waitForDeployment();
    return { registry, owner, creator, other };
  }

  it("sets the deployer-provided owner", async function () {
    const { registry, owner } = await loadFixture(deployFixture);
    expect(await registry.owner()).to.equal(owner.address);
  });

  it("registers a collection, emits an event, and stores the timestamp", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    const nextTimestamp = (await time.latest()) + 60;
    await time.setNextBlockTimestamp(nextTimestamp);

    await expect(registry.connect(creator).registerCollection("Animals", "ipfs://collection-1"))
      .to.emit(registry, "CollectionRegistered")
      .withArgs(1n, creator.address, "Animals");

    const [collection, images] = await registry.getCollectionWithImages(1n);
    expect(collection.id).to.equal(1n);
    expect(collection.creator).to.equal(creator.address);
    expect(collection.name).to.equal("Animals");
    expect(collection.metadataURI).to.equal("ipfs://collection-1");
    expect(collection.createdAt).to.equal(BigInt(nextTimestamp));
    expect(images).to.have.lengthOf(0);
  });

  it("increments collection ids across registrations", async function () {
    const { registry, creator, other } = await loadFixture(deployFixture);

    await expect(registry.connect(creator).registerCollection("A", "ipfs://a"))
      .to.emit(registry, "CollectionRegistered")
      .withArgs(1n, creator.address, "A");
    await expect(registry.connect(other).registerCollection("B", "ipfs://b"))
      .to.emit(registry, "CollectionRegistered")
      .withArgs(2n, other.address, "B");
  });

  it("registers an image without a collection", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    const contentHash = hashLabel("image-1");
    const nextTimestamp = (await time.latest()) + 120;
    await time.setNextBlockTimestamp(nextTimestamp);

    await expect(registry.connect(creator).registerImage(contentHash, "ipfs://image-1", 0))
      .to.emit(registry, "ImageRegistered")
      .withArgs(1n, 0n, creator.address, contentHash, "ipfs://image-1");

    const image = await registry.getImage(1n);
    expect(image.id).to.equal(1n);
    expect(image.collectionId).to.equal(0n);
    expect(image.creator).to.equal(creator.address);
    expect(image.currentOwner).to.equal(creator.address);
    expect(image.contentHash).to.equal(contentHash);
    expect(image.metadataURI).to.equal("ipfs://image-1");
    expect(image.registeredAt).to.equal(BigInt(nextTimestamp));
  });

  it("adds collection images to the collection listing", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    await registry.connect(creator).registerCollection("Vehicles", "ipfs://vehicles");
    await registry.connect(creator).registerImage(hashLabel("car"), "ipfs://car", 1);
    await registry.connect(creator).registerImage(hashLabel("plane"), "ipfs://plane", 1);

    const [collection, images] = await registry.getCollectionWithImages(1n);
    expect(collection.name).to.equal("Vehicles");
    expect(images.map((image) => image.id)).to.deep.equal([1n, 2n]);
    expect(images.map((image) => image.metadataURI)).to.deep.equal(["ipfs://car", "ipfs://plane"]);
  });

  it("returns all images in id order", async function () {
    const { registry, creator, other } = await loadFixture(deployFixture);
    await registry.connect(creator).registerImage(hashLabel("a"), "ipfs://a", 0);
    await registry.connect(other).registerImage(hashLabel("b"), "ipfs://b", 0);
    await registry.connect(creator).registerImage(hashLabel("c"), "ipfs://c", 0);

    const images = await registry.getAllImages();
    expect(images.map((image) => image.id)).to.deep.equal([1n, 2n, 3n]);
    expect(images.map((image) => image.metadataURI)).to.deep.equal(["ipfs://a", "ipfs://b", "ipfs://c"]);
    expect(images.map((image) => image.creator)).to.deep.equal([creator.address, other.address, creator.address]);
  });

  it("returns an empty image list before any registrations", async function () {
    const { registry } = await loadFixture(deployFixture);
    expect(await registry.getAllImages()).to.deep.equal([]);
  });

  it("verifies a matching image hash", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    const contentHash = hashLabel("hash-match");
    await registry.connect(creator).registerImage(contentHash, "ipfs://match", 0);

    expect(await registry.verifyImageHash(1n, contentHash)).to.equal(true);
  });

  it("returns false for a mismatched image hash", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    await registry.connect(creator).registerImage(hashLabel("hash-a"), "ipfs://a", 0);

    expect(await registry.verifyImageHash(1n, hashLabel("hash-b"))).to.equal(false);
  });

  it("reports whether an image exists", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    expect(await registry.imageExists(99n)).to.equal(false);

    await registry.connect(creator).registerImage(hashLabel("exists"), "ipfs://exists", 0);
    expect(await registry.imageExists(1n)).to.equal(true);
  });

  it("reverts ownerOfImage for unknown images", async function () {
    const { registry } = await loadFixture(deployFixture);
    await expect(registry.ownerOfImage(77n))
      .to.be.revertedWithCustomError(registry, "ImageNotRegistered")
      .withArgs(77n);
  });

  it("reverts getImage for unknown images", async function () {
    const { registry } = await loadFixture(deployFixture);
    await expect(registry.getImage(55n))
      .to.be.revertedWithCustomError(registry, "ImageNotRegistered")
      .withArgs(55n);
  });

  it("reverts getCollectionWithImages for unknown collections", async function () {
    const { registry } = await loadFixture(deployFixture);
    await expect(registry.getCollectionWithImages(44n))
      .to.be.revertedWithCustomError(registry, "CollectionNotRegistered")
      .withArgs(44n);
  });

  it("rejects zero content hashes", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    await expect(registry.connect(creator).registerImage(ethers.ZeroHash, "ipfs://zero", 0))
      .to.be.revertedWithCustomError(registry, "EmptyContentHash");
  });

  it("rejects duplicate content hashes", async function () {
    const { registry, creator, other } = await loadFixture(deployFixture);
    const contentHash = hashLabel("dup");
    await registry.connect(creator).registerImage(contentHash, "ipfs://first", 0);

    await expect(registry.connect(other).registerImage(contentHash, "ipfs://second", 0))
      .to.be.revertedWithCustomError(registry, "ImageHashAlreadyRegistered")
      .withArgs(contentHash);
  });

  it("rejects images assigned to missing collections", async function () {
    const { registry, creator } = await loadFixture(deployFixture);
    await expect(registry.connect(creator).registerImage(hashLabel("orphan"), "ipfs://orphan", 3))
      .to.be.revertedWithCustomError(registry, "CollectionNotRegistered")
      .withArgs(3n);
  });

  it("rejects collection images from non-creators", async function () {
    const { registry, creator, other } = await loadFixture(deployFixture);
    await registry.connect(creator).registerCollection("Private", "ipfs://private");

    await expect(registry.connect(other).registerImage(hashLabel("intruder"), "ipfs://intruder", 1))
      .to.be.revertedWithCustomError(registry, "OnlyCollectionCreatorCanAddImages")
      .withArgs(1n, other.address);
  });
});