package dev.lex.astra

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.UUID
import java.util.concurrent.TimeUnit

class MeshRepository private constructor(private val appContext: Context) {
    private val secure = SecureStore(appContext)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _state = MutableStateFlow(MeshUiState())
    val state: StateFlow<MeshUiState> = _state.asStateFlow()

    private var client: OkHttpClient? = null
    private var webSocket: WebSocket? = null
    private var discovery: NsdDiscovery? = null

    private val deviceId: String by lazy {
        secure.getString("device_id") ?: run {
            val id = UUID.randomUUID().toString()
            secure.putString("device_id", id)
            id
        }
    }

    init {
        startDiscovery()
        reconnectStored()
    }

    fun startDiscovery() {
        if (discovery != null) return
        discovery = NsdDiscovery(appContext) { node ->
            val old = _state.value.discovered
            val next = (
                old.filterNot { it.nodeId == node.nodeId && it.nodeId.isNotBlank() }
                    .filterNot { it.host == node.host && it.port == node.port } + node
                ).takeLast(12)
            _state.value = _state.value.copy(discovered = next)
        }.also { it.start() }
    }

    fun parsePairUri(raw: String): PairingInfo? {
        return try {
            val uri = Uri.parse(raw)
            if (uri.scheme != "astramesh" || uri.host != "pair") return null
            PairingInfo(
                host = uri.getQueryParameter("host") ?: return null,
                port = uri.getQueryParameter("port")?.toIntOrNull() ?: 8767,
                fingerprint = uri.getQueryParameter("fingerprint") ?: return null,
                code = uri.getQueryParameter("code") ?: return null,
                nodeId = uri.getQueryParameter("node") ?: ""
            )
        } catch (_: Exception) {
            null
        }
    }

    fun pair(info: PairingInfo, deviceName: String = android.os.Build.MODEL) {
        _state.value = _state.value.copy(
            connecting = true,
            status = "Pareando com ${info.host}:${info.port}…"
        )
        scope.launch {
            try {
                val c = pinnedClient(info.fingerprint)
                val payload = JSONObject()
                    .put("code", info.code)
                    .put("device_id", deviceId)
                    .put("name", deviceName)
                    .put("platform", "android")
                    .toString()
                val request = Request.Builder()
                    .url("https://${info.host}:${info.port}/v1/pair")
                    .post(payload.toRequestBody("application/json".toMediaType()))
                    .build()

                c.newCall(request).execute().use { response ->
                    val body = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        throw IllegalStateException("Pairing recusado (${response.code}): $body")
                    }
                    val json = JSONObject(body)
                    val token = json.getString("token")
                    val node = json.optJSONObject("node")
                    val nodeName = node?.optString("name").orEmpty().ifBlank { info.host }

                    secure.putSecret("token", token)
                    secure.putString("host", info.host)
                    secure.putString("port", info.port.toString())
                    secure.putString("fingerprint", info.fingerprint)
                    secure.putString("node_name", nodeName)

                    client = c
                    _state.value = _state.value.copy(
                        paired = true,
                        connecting = false,
                        host = info.host,
                        nodeName = nodeName,
                        status = "Pareado"
                    )
                    connectWebSocket()
                }
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    connecting = false,
                    connected = false,
                    status = "Erro: ${e.message ?: "pairing"}"
                )
            }
        }
    }

    fun disconnectAndForget() {
        webSocket?.close(1000, "user")
        webSocket = null
        client = null
        secure.clearPairing()
        _state.value = MeshUiState(discovered = _state.value.discovered)
    }

    fun sendAsk(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        appendMessage(false, clean)
        val requestId = UUID.randomUUID().toString()
        val json = JSONObject()
            .put("v", 1)
            .put("type", "ask")
            .put("request_id", requestId)
            .put("text", clean)
        if (webSocket?.send(json.toString()) != true) {
            appendMessage(true, "Astra Mesh não está conectada.")
        }
    }

    fun requestContext() {
        webSocket?.send(
            JSONObject()
                .put("v", 1)
                .put("type", "context")
                .put("request_id", UUID.randomUUID().toString())
                .toString()
        )
    }

    fun sendSensor(sensor: String, values: FloatArray, timestampNs: Long) {
        val ws = webSocket ?: return
        val array = org.json.JSONArray()
        values.forEach { array.put(it.toDouble()) }
        ws.send(
            JSONObject()
                .put("v", 1)
                .put("type", "sensor")
                .put("sensor", sensor)
                .put("ts", timestampNs / 1_000_000_000.0)
                .put("data", array)
                .toString()
        )
    }

    fun pushClipboard(text: String) {
        if (text.isBlank()) return
        webSocket?.send(
            JSONObject()
                .put("v", 1)
                .put("type", "clipboard.push")
                .put("text", text.take(100_000))
                .toString()
        )
    }

    fun uploadBitmap(bitmap: Bitmap) {
        val host = secure.getString("host") ?: return
        val port = secure.getString("port")?.toIntOrNull() ?: 8767
        val token = secure.getSecret("token") ?: return
        val c = client ?: return

        scope.launch {
            try {
                val bytes = ByteArrayOutputStream().use {
                    bitmap.compress(Bitmap.CompressFormat.JPEG, 86, it)
                    it.toByteArray()
                }
                val request = Request.Builder()
                    .url("https://$host:$port/v1/snapshot")
                    .header("Authorization", "Bearer $token")
                    .post(bytes.toRequestBody("image/jpeg".toMediaType()))
                    .build()
                c.newCall(request).execute().use { response ->
                    appendMessage(
                        true,
                        if (response.isSuccessful) "Snapshot enviado para a Astra."
                        else "Falha ao enviar snapshot (${response.code})."
                    )
                }
            } catch (e: Exception) {
                appendMessage(true, "Snapshot falhou: ${e.message}")
            }
        }
    }

    private fun reconnectStored() {
        val host = secure.getString("host") ?: return
        val port = secure.getString("port")?.toIntOrNull() ?: return
        val fingerprint = secure.getString("fingerprint") ?: return
        val token = secure.getSecret("token") ?: return

        try {
            client = pinnedClient(fingerprint)
            _state.value = _state.value.copy(
                paired = true,
                host = host,
                nodeName = secure.getString("node_name").orEmpty(),
                status = "Reconectando…"
            )
            connectWebSocket(token, host, port)
        } catch (e: Exception) {
            _state.value = _state.value.copy(status = "Falha ao restaurar Mesh: ${e.message}")
        }
    }

    private fun connectWebSocket(
        tokenOverride: String? = null,
        hostOverride: String? = null,
        portOverride: Int? = null
    ) {
        val token = tokenOverride ?: secure.getSecret("token") ?: return
        val host = hostOverride ?: secure.getString("host") ?: return
        val port = portOverride ?: secure.getString("port")?.toIntOrNull() ?: 8767
        val c = client ?: return

        webSocket?.cancel()
        val request = Request.Builder()
            .url("wss://$host:$port/v1/ws")
            .header("Authorization", "Bearer $token")
            .build()

        webSocket = c.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                _state.value = _state.value.copy(
                    connected = true,
                    connecting = false,
                    host = host,
                    status = "Conectado"
                )
                webSocket.send(
                    JSONObject()
                        .put("v", 1)
                        .put("type", "hello")
                        .put("device_id", deviceId)
                        .toString()
                )
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    when (json.optString("type")) {
                        "reply" -> {
                            val result = json.optJSONObject("result")
                            val message = result?.optString("message").orEmpty()
                            if (message.isNotBlank()) appendMessage(true, message)
                        }
                        "context" -> {
                            val result = json.optJSONObject("result")
                            val context = result?.optJSONObject("context")
                            val active = context?.optString("active_window").orEmpty()
                            appendMessage(
                                true,
                                if (active.isBlank()) "Contexto recebido."
                                else "Janela ativa no PC: $active"
                            )
                        }
                        "notification" -> {
                            val title = json.optString("title", "Astra")
                            val message = json.optString("message")
                            appendMessage(true, "$title: $message")
                        }
                        "error" -> {
                            appendMessage(true, "Mesh: ${json.optString("error")}")
                        }
                    }
                } catch (_: Exception) {
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                _state.value = _state.value.copy(
                    connected = false,
                    status = "Desconectado"
                )
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                _state.value = _state.value.copy(
                    connected = false,
                    status = "Conexão falhou: ${t.message ?: "erro"}"
                )
            }
        })
    }

    private fun pinnedClient(fingerprint: String): OkHttpClient {
        val trust = FingerprintTrustManager(fingerprint)
        return OkHttpClient.Builder()
            .sslSocketFactory(trust.sslContext().socketFactory, trust)
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .pingInterval(20, TimeUnit.SECONDS)
            .build()
    }

    private fun appendMessage(fromAstra: Boolean, text: String) {
        val current = _state.value.messages
        _state.value = _state.value.copy(
            messages = (current + ChatMessage(fromAstra, text)).takeLast(100)
        )
    }

    companion object {
        @Volatile private var INSTANCE: MeshRepository? = null

        fun get(context: Context): MeshRepository =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: MeshRepository(context.applicationContext).also { INSTANCE = it }
            }
    }
}
