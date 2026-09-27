package dev.lex.astra.localai

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.Closeable

class LocalAiManager(context: Context) : Closeable {
    private val appContext = context.applicationContext
    private val store = LocalModelStore(appContext)

    @Volatile
    private var engine: LocalQwenEngine? = null

    @Volatile
    var status: String = if (store.ready()) "Modelo local disponível" else "Modelo local não instalado"
        private set

    fun filesReady(): Boolean = store.ready()

    suspend fun importModel(uri: Uri) = withContext(Dispatchers.IO) {
        closeEngine()
        store.importModel(uri)
        status = if (store.ready()) "Modelo local pronto" else "ONNX salvo; falta tokenizer.json"
    }

    suspend fun importTokenizer(uri: Uri) = withContext(Dispatchers.IO) {
        closeEngine()
        store.importTokenizer(uri)
        status = if (store.ready()) "Modelo local pronto" else "Tokenizer salvo; falta model.onnx"
    }

    suspend fun ask(
        text: String,
        onPartial: ((String) -> Unit)? = null
    ): String = withContext(Dispatchers.IO) {
        require(store.ready()) {
            "Qwen local não instalado. Importe model.onnx e tokenizer.json."
        }
        val local = engine ?: LocalQwenEngine(
            appContext,
            store.modelFile,
            store.tokenizerFile
        ).also {
            engine = it
            status = "Qwen3 0.6B local carregado"
        }
        local.generate(text, onPartial = onPartial)
    }

    fun stop() {
        engine?.stop()
    }

    fun removeModel() {
        closeEngine()
        store.remove()
        status = "Modelo local não instalado"
    }

    override fun close() {
        closeEngine()
    }

    private fun closeEngine() {
        engine?.close()
        engine = null
    }
}
