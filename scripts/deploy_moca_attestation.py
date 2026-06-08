"""Compile and deploy contracts/moca/EtornieAttestation.sol to Moca.

Usage (from services/api so the .env loads):
    cd services/api
    .venv/bin/python ../../scripts/deploy_moca_attestation.py

Reads the operator key + RPC from app.config (i.e. services/api/.env):
    MOCA_OPERATOR_PRIVATE_KEY, MOCA_RPC_URL, MOCA_CHAIN_ID

Prints the deployed contract address; put it in .env as
MOCA_ATTESTATION_CONTRACT and set MOCA_ENABLED=true.
"""
from __future__ import annotations

import sys
from pathlib import Path

import solcx
from web3 import Web3

from app.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT = _REPO_ROOT / "contracts" / "moca" / "EtornieAttestation.sol"
_SOLC_VERSION = "0.8.20"


def main() -> int:
    if not settings.moca_operator_private_key:
        print("ERROR: MOCA_OPERATOR_PRIVATE_KEY is not set in services/api/.env")
        return 1
    if not _CONTRACT.is_file():
        print(f"ERROR: contract not found at {_CONTRACT}")
        return 1

    print(f"Installing solc {_SOLC_VERSION} ...")
    solcx.install_solc(_SOLC_VERSION)
    compiled = solcx.compile_files(
        [str(_CONTRACT)],
        output_values=["abi", "bin"],
        solc_version=_SOLC_VERSION,
    )
    key = next(k for k in compiled if k.endswith(":EtornieAttestation"))
    abi = compiled[key]["abi"]
    bytecode = compiled[key]["bin"]

    w3 = Web3(Web3.HTTPProvider(settings.moca_rpc_url, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print(f"ERROR: cannot reach Moca RPC {settings.moca_rpc_url}")
        return 1

    account = w3.eth.account.from_key(settings.moca_operator_private_key)
    balance = w3.eth.get_balance(account.address)
    print(f"Deployer: {account.address}  balance: {w3.from_wei(balance, 'ether')} MOCA")
    if balance == 0:
        print("ERROR: deployer has no MOCA for gas")
        return 1

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor().build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": settings.moca_chain_id,
            "gas": 1_500_000,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Deploy tx: {tx_hash.hex()} — waiting for receipt ...")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        print("ERROR: deploy tx reverted")
        return 1

    print("\n=== DEPLOYED ===")
    print(f"Contract address: {receipt.contractAddress}")
    print(f"Explorer: {settings.moca_explorer_url}/address/{receipt.contractAddress}")
    print("\nNext: set in services/api/.env")
    print(f"  MOCA_ATTESTATION_CONTRACT={receipt.contractAddress}")
    print("  MOCA_ENABLED=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
