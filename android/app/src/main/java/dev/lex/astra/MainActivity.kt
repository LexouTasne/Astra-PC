package dev.lex.astra

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognizerIntent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import java.util.Locale

class MainActivity : ComponentActivity() {
    private lateinit var repo: MeshRepository

    private val permissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { }

    private val qrLauncher = registerForActivityResult(ScanContract()) { result ->
        val raw = result.contents ?: return@registerForActivityResult
        repo.parsePairUri(raw)?.let { repo.pair(it) }
    }

    private val cameraLauncher =
        registerForActivityResult(ActivityResultContracts.TakePicturePreview()) { bitmap ->
            bitmap?.let { repo.uploadBitmap(it) }
        }

    private val speechLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode != Activity.RESULT_OK) return@registerForActivityResult
            val text = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
                ?: return@registerForActivityResult
            repo.sendAsk(text)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        repo = MeshRepository.get(this)
        requestNetworkPermissions()

        setContent {
            AstraAndroidApp(
                repository = repo,
                onScanQr = { scanQr() },
                onVoice = { startVoice() },
                onCamera = { cameraLauncher.launch(null) },
                onStartSensors = { startSensors() },
                onStopSensors = { stopService(Intent(this, SensorService::class.java)) },
                onSendClipboard = { sendClipboard() }
            )
        }
    }

    private fun requestNetworkPermissions() {
        val permissions = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 37) {
            permissions += "android.permission.ACCESS_LOCAL_NETWORK"
        } else if (Build.VERSION.SDK_INT >= 33) {
            permissions += Manifest.permission.NEARBY_WIFI_DEVICES
        }
        if (Build.VERSION.SDK_INT >= 33) {
            permissions += Manifest.permission.POST_NOTIFICATIONS
        }
        if (permissions.isNotEmpty()) {
            permissionLauncher.launch(permissions.toTypedArray())
        }
    }

    private fun scanQr() {
        qrLauncher.launch(
            ScanOptions()
                .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Aponte para o QR da Astra Mesh")
                .setBeepEnabled(false)
                .setOrientationLocked(false)
        )
    }

    private fun startVoice() {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM
            )
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "pt-BR")
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_PROMPT, "Fale com a Astra")
        }
        try {
            speechLauncher.launch(intent)
        } catch (_: Exception) {
            repo.sendAsk("O reconhecimento de voz do Android não está disponível neste aparelho.")
        }
    }

    private fun startSensors() {
        ContextCompat.startForegroundService(
            this,
            Intent(this, SensorService::class.java)
        )
    }

    private fun sendClipboard() {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val text = clipboard.primaryClip
            ?.getItemAt(0)
            ?.coerceToText(this)
            ?.toString()
            .orEmpty()
        if (text.isNotBlank()) {
            repo.pushClipboard(text)
        }
    }
}
