/**
 * Program IDL in camelCase format in order to be used in JS/TS.
 *
 * Note that this is only a type helper and is not the actual IDL. The original
 * IDL can be found at `target/idl/etornie_attestation.json`.
 */
export type EtornieAttestation = {
  "address": "CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X",
  "metadata": {
    "name": "etornieAttestation",
    "version": "0.1.0",
    "spec": "0.1.0",
    "description": "Case lifecycle compressed attestations for Etornie"
  },
  "instructions": [
    {
      "name": "createCaseAttestation",
      "discriminator": [
        165,
        86,
        244,
        190,
        152,
        112,
        150,
        122
      ],
      "accounts": [
        {
          "name": "attestation",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  115,
                  101
                ]
              },
              {
                "kind": "arg",
                "path": "caseId"
              }
            ]
          }
        },
        {
          "name": "operator",
          "docs": [
            "Backend operator — pays rent and acts as co-signer so users do",
            "not need SOL in their wallet."
          ],
          "writable": true,
          "signer": true
        },
        {
          "name": "creator",
          "docs": [
            "The case creator (user wallet). Signing this instruction is a",
            "cryptographic proof that the wallet owner authorized the case",
            "attestation; the pubkey is recorded as `creator` on the PDA."
          ],
          "signer": true
        },
        {
          "name": "systemProgram",
          "address": "11111111111111111111111111111111"
        }
      ],
      "args": [
        {
          "name": "caseId",
          "type": {
            "array": [
              "u8",
              16
            ]
          }
        },
        {
          "name": "metadataHash",
          "type": {
            "array": [
              "u8",
              32
            ]
          }
        },
        {
          "name": "clientWallet",
          "type": "pubkey"
        }
      ]
    },
    {
      "name": "updateCaseAttestation",
      "docs": [
        "Record a lifecycle event against an existing case attestation.",
        "",
        "The main PDA's ``metadata_hash`` is overwritten with the fresh",
        "hash (current case state at event time) and a typed ``emit!``",
        "event is written to the tx log so historical timelines can be",
        "reconstructed from Solana tx history."
      ],
      "discriminator": [
        184,
        212,
        255,
        56,
        65,
        123,
        77,
        54
      ],
      "accounts": [
        {
          "name": "attestation",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  115,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "attestation.case_id",
                "account": "caseAttestation"
              }
            ]
          }
        },
        {
          "name": "operator",
          "docs": [
            "Backend operator — pays fees so users do not need SOL."
          ],
          "writable": true,
          "signer": true
        },
        {
          "name": "actor",
          "docs": [
            "The actor triggering the event (case creator, lawyer, admin).",
            "Signing this instruction authorizes the on-chain update."
          ],
          "signer": true
        }
      ],
      "args": [
        {
          "name": "metadataHash",
          "type": {
            "array": [
              "u8",
              32
            ]
          }
        },
        {
          "name": "eventType",
          "type": "u8"
        }
      ]
    }
  ],
  "accounts": [
    {
      "name": "caseAttestation",
      "discriminator": [
        57,
        196,
        113,
        84,
        182,
        107,
        157,
        123
      ]
    }
  ],
  "events": [
    {
      "name": "caseAttestationUpdated",
      "discriminator": [
        242,
        135,
        167,
        44,
        46,
        36,
        234,
        172
      ]
    }
  ],
  "errors": [
    {
      "code": 6000,
      "name": "attestationAlreadyExists",
      "msg": "Attestation already exists for this case id"
    }
  ],
  "types": [
    {
      "name": "caseAttestation",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "caseId",
            "type": {
              "array": [
                "u8",
                16
              ]
            }
          },
          {
            "name": "metadataHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "clientWallet",
            "type": "pubkey"
          },
          {
            "name": "operator",
            "type": "pubkey"
          },
          {
            "name": "createdAt",
            "type": "i64"
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "caseAttestationUpdated",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "caseId",
            "type": {
              "array": [
                "u8",
                16
              ]
            }
          },
          {
            "name": "oldMetadataHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "newMetadataHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "eventType",
            "type": "u8"
          },
          {
            "name": "actor",
            "type": "pubkey"
          },
          {
            "name": "operator",
            "type": "pubkey"
          },
          {
            "name": "timestamp",
            "type": "i64"
          }
        ]
      }
    }
  ]
};
