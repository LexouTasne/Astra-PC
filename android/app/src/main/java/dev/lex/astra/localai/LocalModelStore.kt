package dev.lex.astra.localai

import android.content.Context
import android.net.Uri
import java.io.File

class LocalModelStore(private val context: Context) {
    private val root = File(context.filesDir, "local-qwen").apply { mkdirs() }

    val modelFile: File get() = File(root, "model.onnx")
    val tokenizerFile: File get() = File(root, "tokenizer.json")

    fun ready(): Boolean =
        modelFile.isFile && modelFile.length() > 1_000_000L &&
            tokenizerFile.isFile && tokenizerFile.length() > 10_000L

    fun importModel(uri: Uri) = copy(uri, modelFile)
    fun importTokenizer(uri: Uri) = copy(uri, tokenizerFile)

    fun remove() {
        modelFile.delete()
        tokenizerFile.delete()
    }

    private fun copy(uri: Uri, target: File) {
        val tmp = File(root, target.name + ".part")
        context.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Não foi possível abrir o arquivo selecionado." }
            tmp.outputStream().buffered().use { output ->
                input.copyTo(output, bufferSize = 1024 * 1024)
            }
        }
        require(tmp.length() > 0L) { "Arquivo importado está vazio." }
        if (target.exists()) target.delete()
        require(tmp.renameTo(target)) { "Falha ao salvar ${target.name}." }
    }
}
