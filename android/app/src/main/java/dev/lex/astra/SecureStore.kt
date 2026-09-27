package dev.lex.astra

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureStore(context: Context) {
    private val prefs = context.getSharedPreferences("astra_mesh", Context.MODE_PRIVATE)
    private val alias = "astra_mesh_key"

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                alias,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        )
        return generator.generateKey()
    }

    fun putSecret(name: String, value: String) {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        prefs.edit()
            .putString(name + "_iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(name, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .apply()
    }

    fun getSecret(name: String): String? {
        val raw = prefs.getString(name, null) ?: return null
        val iv = prefs.getString(name + "_iv", null) ?: return null
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                key(),
                GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP))
            )
            String(
                cipher.doFinal(Base64.decode(raw, Base64.NO_WRAP)),
                Charsets.UTF_8
            )
        } catch (_: Exception) {
            null
        }
    }

    fun putString(name: String, value: String) {
        prefs.edit().putString(name, value).apply()
    }

    fun getString(name: String): String? = prefs.getString(name, null)

    fun clearPairing() {
        listOf("token", "token_iv", "host", "port", "fingerprint", "node_name").forEach {
            prefs.edit().remove(it).apply()
        }
    }
}
