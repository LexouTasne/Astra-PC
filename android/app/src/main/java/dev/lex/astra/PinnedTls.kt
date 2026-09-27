package dev.lex.astra

import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

class FingerprintTrustManager(private val expectedHex: String) : X509TrustManager {
    private val expected = expectedHex.lowercase().replace(":", "")

    override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) = Unit

    override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
        val cert = chain?.firstOrNull() ?: throw java.security.cert.CertificateException("No server certificate")
        val actual = MessageDigest.getInstance("SHA-256")
            .digest(cert.encoded)
            .joinToString("") { "%02x".format(it) }
        if (!MessageDigest.isEqual(
                actual.toByteArray(Charsets.US_ASCII),
                expected.toByteArray(Charsets.US_ASCII)
            )
        ) {
            throw java.security.cert.CertificateException("Astra Mesh certificate fingerprint mismatch")
        }
    }

    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    fun sslContext(): SSLContext = SSLContext.getInstance("TLS").apply {
        init(null, arrayOf<TrustManager>(this@FingerprintTrustManager), SecureRandom())
    }
}
