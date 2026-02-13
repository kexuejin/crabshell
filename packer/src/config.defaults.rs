// Fallback config used when generated config.rs is absent in clean CI checkout.
// pack.py overwrites src/config.rs with generated key material during packing.

#[inline(always)]
pub fn get_aes_key() -> [u8; 32] {
    [0u8; 32]
}
