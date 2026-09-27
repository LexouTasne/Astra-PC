package dev.lex.astra.localai

import android.content.Context
import java.io.Closeable
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class LocalQwenEngine(
    context: Context,
    modelFile: File,
    tokenizerFile: File
) : Closeable {
    private val tokenizer = BpeTokenizer(context, tokenizerFile)
    private val stopped = AtomicBoolean(false)

    private val roleTokens = RoleTokenIds(
        systemStart = listOf(
            tokenizer.getTokenId("<|im_start|>"),
            tokenizer.getTokenId("system"),
            tokenizer.getTokenId("Ċ")
        ),
        userStart = listOf(
            tokenizer.getTokenId("<|im_start|>"),
            tokenizer.getTokenId("user"),
            tokenizer.getTokenId("Ċ")
        ),
        assistantStart = listOf(
            tokenizer.getTokenId("<|im_start|>"),
            tokenizer.getTokenId("assistant"),
            tokenizer.getTokenId("Ċ")
        ),
        endToken = tokenizer.getTokenId("<|im_end|>")
    )

    private val config = ModelConfig(
        modelName = "Qwen3-0.6B",
        promptStyle = PromptStyle.QWEN3,
        modelPath = modelFile.absolutePath,
        eosTokenIds = setOf(151643, 151645),
        numLayers = 28,
        numKvHeads = 8,
        headDim = 128,
        batchSize = 1,
        defaultSystemPrompt = (
            "Você é Astra, uma assistente local rápida. " +
            "Responda no idioma do usuário de forma direta, útil e curta."
        ),
        roleTokenIds = roleTokens,
        scalarPosId = true,
        dtype = "float16",
        IsThinkingModeAvailable = true
    )

    private val promptBuilder = PromptBuilder(tokenizer, config)
    private val model = OnnxModel(context, config)

    fun generate(
        prompt: String,
        maxTokens: Int = 160,
        onPartial: ((String) -> Unit)? = null
    ): String {
        stopped.set(false)
        val input = promptBuilder.buildPromptTokens(
            prompt,
            PromptIntent.QA(config.defaultSystemPrompt + " /no_think")
        )
        val out = StringBuilder()
        model.runInferenceStreamingWithPastKV(
            inputIds = input,
            maxTokens = maxTokens,
            endTokenIds = config.eosTokenIds,
            shouldStop = { stopped.get() },
            onTokenGenerated = { tokenId ->
                val text = tokenizer.decodeSingleToken(tokenId)
                if (!text.startsWith("<|") && text != "<unk>") {
                    out.append(text)
                    onPartial?.invoke(clean(out.toString()))
                }
            }
        )
        return clean(out.toString())
    }

    fun stop() {
        stopped.set(true)
    }

    override fun close() {
        stop()
        model.close()
    }

    private fun clean(text: String): String =
        text
            .replace("<|im_end|>", "")
            .replace("<|endoftext|>", "")
            .trim()
}
