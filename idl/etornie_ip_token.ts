/**
 * Program IDL in camelCase format in order to be used in JS/TS.
 *
 * Note that this is only a type helper and is not the actual IDL. The original
 * IDL can be found at `target/idl/etornie_ip_token.json`.
 */
export type EtornieIpToken = {
  "address": "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF",
  "metadata": {
    "name": "etornieIpToken",
    "version": "0.1.0",
    "spec": "0.1.0",
    "description": "Soul-bound Case NFT program for Etornie: Token-2022 + Light Protocol compression"
  },
  "instructions": [
    {
      "name": "burnCaseNft",
      "docs": [
        "Thaw the client's frozen ATA, burn the 1-unit supply, mark record burned.",
        "",
        "Only the operator needs to sign — the program PDA acts as freeze",
        "authority (thaw) and mint authority (burn). This is intended to be",
        "called when the case reaches a terminal closed state; the",
        "backend must enforce that precondition off-chain before invoking."
      ],
      "discriminator": [
        135,
        82,
        163,
        145,
        195,
        199,
        248,
        207
      ],
      "accounts": [
        {
          "name": "caseNftRecord",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  115,
                  101,
                  95,
                  110,
                  102,
                  116
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
          "name": "nftAuthority",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  115,
                  101,
                  95,
                  110,
                  102,
                  116,
                  95,
                  97,
                  117,
                  116,
                  104,
                  111,
                  114,
                  105,
                  116,
                  121
                ]
              }
            ]
          }
        },
        {
          "name": "mint",
          "writable": true,
          "relations": [
            "caseNftRecord"
          ]
        },
        {
          "name": "clientTokenAccount",
          "writable": true
        },
        {
          "name": "operator",
          "writable": true,
          "signer": true
        },
        {
          "name": "tokenProgram",
          "address": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
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
        }
      ]
    },
    {
      "name": "mintCaseNft",
      "docs": [
        "Mint a soul-bound case NFT into the client's frozen ATA.",
        "",
        "The mint must already be created client-side with:",
        "- decimals = 0",
        "- mint_authority = nft_authority PDA",
        "- freeze_authority = nft_authority PDA",
        "- DefaultAccountState = Frozen extension",
        "- MetadataPointer + TokenMetadata extensions",
        "",
        "The client's ATA starts frozen (DefaultAccountState), so the NFT",
        "cannot be transferred, delegated, or burned by the holder. Only",
        "`burn_case_nft` can thaw → burn via program PDA signing."
      ],
      "discriminator": [
        37,
        75,
        52,
        141,
        2,
        156,
        79,
        104
      ],
      "accounts": [
        {
          "name": "caseNftRecord",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  115,
                  101,
                  95,
                  110,
                  102,
                  116
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
          "name": "nftAuthority",
          "docs": [
            "Derived from [NFT_AUTHORITY_SEED]; signed via invoke_signed."
          ],
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  115,
                  101,
                  95,
                  110,
                  102,
                  116,
                  95,
                  97,
                  117,
                  116,
                  104,
                  111,
                  114,
                  105,
                  116,
                  121
                ]
              }
            ]
          }
        },
        {
          "name": "mint",
          "writable": true
        },
        {
          "name": "clientTokenAccount",
          "writable": true
        },
        {
          "name": "client",
          "signer": true
        },
        {
          "name": "operator",
          "writable": true,
          "signer": true
        },
        {
          "name": "tokenProgram",
          "address": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
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
          "name": "metadataUriHash",
          "type": {
            "array": [
              "u8",
              32
            ]
          }
        }
      ]
    }
  ],
  "accounts": [
    {
      "name": "caseNftRecord",
      "discriminator": [
        77,
        20,
        229,
        240,
        123,
        49,
        45,
        115
      ]
    }
  ],
  "events": [
    {
      "name": "caseNftBurned",
      "discriminator": [
        65,
        120,
        160,
        68,
        228,
        3,
        113,
        138
      ]
    },
    {
      "name": "caseNftMinted",
      "discriminator": [
        251,
        117,
        139,
        107,
        151,
        7,
        234,
        115
      ]
    }
  ],
  "errors": [
    {
      "code": 6000,
      "name": "alreadyBurned",
      "msg": "Case NFT has already been burned"
    }
  ],
  "types": [
    {
      "name": "caseNftBurned",
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
            "name": "mint",
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
    },
    {
      "name": "caseNftMinted",
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
            "name": "mint",
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
            "name": "metadataUriHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "timestamp",
            "type": "i64"
          }
        ]
      }
    },
    {
      "name": "caseNftRecord",
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
            "name": "mint",
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
            "name": "metadataUriHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "mintedAt",
            "type": "i64"
          },
          {
            "name": "burnedAt",
            "type": "i64"
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    }
  ]
};
