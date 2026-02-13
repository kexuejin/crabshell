// Fallback config used when generated config.rs is absent in clean CI checkout.
// pack.py will overwrite src/config.rs with generated values during packaging.

pub const STRING_XOR_KEY: [u8; 32] = [0u8; 32];

#[inline(always)]
pub fn get_aes_key() -> [u8; 32] {
    [0u8; 32]
}

pub const PAYLOAD_HASH: [u8; 32] = [0u8; 32];
pub const EXPECTED_SIGNATURE_HASH: [u8; 32] = [0u8; 32];
