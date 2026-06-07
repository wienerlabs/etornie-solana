// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title EtornieAttestation
/// @notice Minimal on-chain attestation registry for Etornie IP cases on
/// the Moca chain. The Etornie operator (contract owner) records, per
/// case, a hash of the case's canonical data so the attestation is
/// verifiable and tamper-evident. This is the Moca-side counterpart of
/// the Solana attestation program.
contract EtornieAttestation {
    struct Attestation {
        bytes32 dataHash;
        address attester;
        uint64 timestamp;
        bool exists;
    }

    address public owner;

    /// caseId (keccak256 of the Etornie case UUID) => attestation
    mapping(bytes32 => Attestation) public attestations;

    event Attested(
        bytes32 indexed caseId,
        bytes32 dataHash,
        address indexed attester,
        uint64 timestamp
    );

    event OwnershipTransferred(
        address indexed previousOwner,
        address indexed newOwner
    );

    modifier onlyOwner() {
        require(msg.sender == owner, "EtornieAttestation: not owner");
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    /// @notice Record (or overwrite) the attestation for a case.
    /// @param caseId keccak256 of the case UUID.
    /// @param dataHash keccak256 of the case's canonical data.
    function attest(bytes32 caseId, bytes32 dataHash) external onlyOwner {
        attestations[caseId] = Attestation({
            dataHash: dataHash,
            attester: msg.sender,
            timestamp: uint64(block.timestamp),
            exists: true
        });
        emit Attested(caseId, dataHash, msg.sender, uint64(block.timestamp));
    }

    /// @notice Read an attestation back.
    function getAttestation(bytes32 caseId)
        external
        view
        returns (bytes32 dataHash, address attester, uint64 timestamp, bool exists)
    {
        Attestation memory a = attestations[caseId];
        return (a.dataHash, a.attester, a.timestamp, a.exists);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "EtornieAttestation: zero owner");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }
}
