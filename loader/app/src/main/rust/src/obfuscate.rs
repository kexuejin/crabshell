use crate::config::STRING_XOR_KEY;

pub fn decrypt(obfuscated: &[u8]) -> String {
    let mut decrypted = Vec::with_capacity(obfuscated.len());
    for i in 0..obfuscated.len() {
        decrypted.push(obfuscated[i] ^ STRING_XOR_KEY[i % STRING_XOR_KEY.len()]);
    }
    String::from_utf8(decrypted).unwrap_or_else(|_| String::from("ERROR_DECRYPT"))
}

#[macro_export]
macro_rules! s {
    ($bytes:expr) => {
        $crate::obfuscate::decrypt($bytes)
    };
}
